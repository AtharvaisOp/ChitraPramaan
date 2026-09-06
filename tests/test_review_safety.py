from concurrent.futures import ThreadPoolExecutor
from threading import Event
from io import BytesIO
from unittest.mock import Mock

from PIL import Image
import pytest
import requests

from backend import main as api
from provenance_pipeline.chain.client import (
    AlreadyAnchoredError,
    AnchorOutcomeUnknown,
    ChainClientError,
    InsufficientFundsError,
    PrivateKeyError,
)
from provenance_pipeline import public_http
from tests.test_backend import client, clear_sessions, _fixtures, _mock_search_pipeline, _photo_bytes


def session(client, monkeypatch):
    _mock_search_pipeline(monkeypatch, *_fixtures())
    return client.post('/api/sessions', data={'consent': 'true', 'auto_threshold': '0.99'},
                       files={'photo': ('fixture.jpg', _photo_bytes(), 'image/jpeg')}).json()['session_id']


def test_uncertain_anchor_cannot_resubmit(client, monkeypatch):
    sid = session(client, monkeypatch)
    pin = Mock(return_value='bafkfixture')
    anchor = Mock(side_effect=AnchorOutcomeUnknown('sensitive upstream detail'))
    monkeypatch.setattr(api, 'pin_json', pin)
    monkeypatch.setattr(api, 'anchor_claim', anchor)
    for _ in range(2):
        response = client.post(f'/api/sessions/{sid}/confirm', json={'candidate_index': 0})
        assert response.status_code == 409
        assert 'sensitive' not in response.text
        assert api._sessions[sid].fingerprint in response.text
    assert pin.call_count == anchor.call_count == 1
    assert api._sessions[sid].uploaded_photo is None


def test_malformed_success_receipt_cannot_resubmit(client, monkeypatch):
    sid = session(client, monkeypatch)
    pin = Mock(return_value='bafkfixture')
    anchor = Mock(return_value={'status': 1, 'transactionHash': 'not-a-hash'})
    monkeypatch.setattr(api, 'pin_json', pin)
    monkeypatch.setattr(api, 'anchor_claim', anchor)

    for _ in range(2):
        response = client.post(
            f'/api/sessions/{sid}/confirm', json={'candidate_index': 0}
        )
        assert response.status_code == 409
        assert 'outcome is unknown' in response.text

    assert pin.call_count == anchor.call_count == 1
    assert api._sessions[sid].lifecycle == 'uncertain'
    assert api._sessions[sid].uploaded_photo is None


def test_prebroadcast_retry_reuses_exact_pinned_cid(client, monkeypatch):
    sid = session(client, monkeypatch)
    pin = Mock(return_value='bafkfixture')
    anchor = Mock(side_effect=[ChainClientError('failed preparation'), {'status': 1, 'transactionHash': b'\xab' * 32}])
    monkeypatch.setattr(api, 'pin_json', pin)
    monkeypatch.setattr(api, 'anchor_claim', anchor)
    url = f'/api/sessions/{sid}/confirm'
    assert client.post(url, json={'candidate_index': 0}).status_code == 502
    assert client.post(url, json={'candidate_index': 1}).status_code == 409
    response = client.post(url, json={'candidate_index': 0})
    assert response.status_code == 200
    assert response.json()['cid'] == 'bafkfixture'
    assert pin.call_count == 1
    assert [call.args[1] for call in anchor.call_args_list] == ['bafkfixture', 'bafkfixture']


@pytest.mark.parametrize(
    ("error", "expected_message"),
    [
        (
            AlreadyAnchoredError("bafkfixture", "bafkfixture"),
            "already anchored to the same CID",
        ),
        (
            AlreadyAnchoredError("bafkexisting", "bafkfixture"),
            "already anchored to a different CID",
        ),
    ],
)
def test_duplicate_anchor_returns_safe_conflict(
    client, monkeypatch, error, expected_message
):
    sid = session(client, monkeypatch)
    pin = Mock(return_value='bafkfixture')
    anchor = Mock(side_effect=error)
    monkeypatch.setattr(api, 'pin_json', pin)
    monkeypatch.setattr(api, 'anchor_claim', anchor)

    response = client.post(
        f'/api/sessions/{sid}/confirm',
        json={'candidate_index': 0},
    )

    assert response.status_code == 409
    assert expected_message in response.json()['detail']
    assert 'bafkexisting' not in response.text
    assert pin.call_count == anchor.call_count == 1
    assert api._sessions[sid].lifecycle == 'ready'


def test_invalid_private_key_returns_sanitized_configuration_error(
    client, monkeypatch
):
    sid = session(client, monkeypatch)
    monkeypatch.setattr(api, 'pin_json', Mock(return_value='bafkfixture'))
    monkeypatch.setattr(
        api,
        'anchor_claim',
        Mock(side_effect=PrivateKeyError('fixture-private-key')),
    )

    response = client.post(
        f'/api/sessions/{sid}/confirm',
        json={'candidate_index': 0},
    )

    assert response.status_code == 503
    assert response.json()['detail'] == (
        'Blockchain signing is not configured correctly on this server.'
    )
    assert 'fixture-private-key' not in response.text


def test_insufficient_funds_returns_specific_sanitized_error(client, monkeypatch):
    sid = session(client, monkeypatch)
    monkeypatch.setattr(api, 'pin_json', Mock(return_value='bafkfixture'))
    monkeypatch.setattr(
        api,
        'anchor_claim',
        Mock(side_effect=InsufficientFundsError('balance=secret-detail')),
    )

    response = client.post(
        f'/api/sessions/{sid}/confirm',
        json={'candidate_index': 0},
    )

    assert response.status_code == 502
    assert response.json()['detail'] == (
        'The configured Sepolia wallet has insufficient ETH for transaction fees.'
    )
    assert 'secret-detail' not in response.text


def test_concurrent_confirmation_calls_anchor_once(client, monkeypatch):
    sid = session(client, monkeypatch)
    started, release = Event(), Event()
    monkeypatch.setattr(api, 'pin_json', lambda _: 'bafkfixture')
    def anchor(*_):
        started.set()
        assert release.wait(5)
        return {'status': 1, 'transactionHash': b'\xcd' * 32}
    monkeypatch.setattr(api, 'anchor_claim', anchor)
    with ThreadPoolExecutor() as pool:
        first = pool.submit(api._confirm_session, sid, 0)
        assert started.wait(5)
        try:
            response = client.post(f'/api/sessions/{sid}/confirm', json={'candidate_index': 0})
            assert response.status_code == 409
        finally:
            release.set()
        assert first.result().cid == 'bafkfixture'


def test_omitted_index_cannot_switch_a_pinned_selection(client, monkeypatch):
    sid = session(client, monkeypatch)
    state = api._sessions[sid]
    state.auto_selected_index = 0
    monkeypatch.setattr(api, 'pin_json', lambda _: 'bafkfixture')
    anchor = Mock(side_effect=ChainClientError('preparation failed'))
    monkeypatch.setattr(api, 'anchor_claim', anchor)
    url = f'/api/sessions/{sid}/confirm'
    assert client.post(url, json={'candidate_index': 1}).status_code == 502
    assert client.post(url, json={}).status_code == 409
    assert anchor.call_count == 1


@pytest.mark.parametrize('index', [-1, True, '0', 0.5])
def test_candidate_index_is_strict(client, index):
    assert client.post('/api/sessions/missing/confirm', json={'candidate_index': index}).status_code == 422


def test_disguised_format_rejected_before_detection(client, monkeypatch):
    buffer = BytesIO()
    Image.new('RGB', (20, 20)).save(buffer, format='BMP')
    detect = Mock(side_effect=AssertionError('must not detect'))
    monkeypatch.setattr(api, 'detect_faces', detect)
    response = client.post('/api/sessions', data={'consent': 'true'}, files={'photo': ('a.jpg', buffer.getvalue(), 'image/jpeg')})
    assert response.status_code == 422
    detect.assert_not_called()


def test_expiry_clears_raw_data(client, monkeypatch):
    sid = session(client, monkeypatch)
    state = api._sessions[sid]
    state.created_at -= api.SESSION_TTL_SECONDS + 1
    api._expire_sessions()
    assert sid not in api._sessions
    assert state.uploaded_photo is None and state.query_embedding is None


def test_provider_error_never_reaches_response_or_logs(client, monkeypatch, caplog):
    caplog.set_level("ERROR", logger="backend.main")
    monkeypatch.setattr(api, '_process_upload', Mock(side_effect=api.ReverseSearchError('credential fixture-secret')))
    response = client.post('/api/sessions', data={'consent': 'true'}, files={'photo': ('a.jpg', _photo_bytes(), 'image/jpeg')})
    assert response.status_code == 502
    assert 'fixture-secret' not in response.text
    assert 'fixture-secret' not in caplog.text
    assert 'category=unclassified' in caplog.text
    assert 'exception=ReverseSearchError' in caplog.text


@pytest.mark.parametrize('address', ['127.0.0.1', '10.0.0.1', '169.254.169.254', '::1'])
def test_private_dns_destinations_rejected(monkeypatch, address):
    monkeypatch.setattr(public_http.socket, 'getaddrinfo', lambda *_args, **_kwargs: [(2, 1, 6, '', (address, 80))])
    with pytest.raises(requests.RequestException):
        public_http.validate_public_url('https://source.example/image')


def test_redirect_target_is_checked_and_responses_closed(monkeypatch):
    checked = []
    def validate(url):
        checked.append(url)
        if '127.0.0.1' in url:
            raise requests.RequestException('blocked')
    monkeypatch.setattr(public_http, 'validate_public_url', validate)
    response = Mock(status_code=302, headers={'Location': 'http://127.0.0.1/secret'})
    get = Mock(return_value=response)
    monkeypatch.setattr(public_http.requests, 'get', get)
    with pytest.raises(requests.RequestException):
        public_http.public_request('https://public.example/image', method='GET', timeout=(1, 1), max_bytes=10)
    assert len(checked) == 2 and get.call_count == 1
    response.close.assert_called_once()


def test_download_stops_at_limit(monkeypatch):
    monkeypatch.setattr(public_http, 'validate_public_url', lambda _: None)
    response = Mock(status_code=200)
    response.iter_content.return_value = iter([b'123456', b'123456'])
    monkeypatch.setattr(public_http.requests, 'get', Mock(return_value=response))
    with pytest.raises(requests.RequestException, match='byte limit'):
        public_http.public_request('https://public.example/image', method='GET', timeout=(1, 1), max_bytes=10)
    response.close.assert_called_once()
