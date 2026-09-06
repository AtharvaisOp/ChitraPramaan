from copy import deepcopy

import pytest
import requests

from provenance_pipeline.records.canonical import build_claim
from provenance_pipeline.records.fingerprint import compute_fingerprint
from provenance_pipeline.verification import (
    IPFSClaimInvalid,
    IPFSGatewayConfigurationError,
    IPFSGatewayUnavailable,
    fetch_ipfs_json,
    resolve_ipfs_gateways,
    verify_anchored_fingerprint,
)
from provenance_pipeline.verification import MAX_CLAIM_BYTES
from tests.test_canonical import BASE_VALUES


CID = "bafyfixtureclaim"
PRIMARY = "https://primary.example/ipfs"
FALLBACK = "https://fallback.example/ipfs"


class FakeResponse:
    def __init__(self, status_code=200, payload=None, json_error=None) -> None:
        self.status_code = status_code
        self.payload = payload
        self.json_error = json_error
        self.closed = False
        self.headers = {}

    def json(self):
        if self.json_error is not None:
            raise self.json_error
        return self.payload

    def iter_content(self, chunk_size=65536):
        import json

        if self.json_error is not None:
            raise self.json_error
        yield json.dumps(self.payload).encode("utf-8")

    def close(self) -> None:
        self.closed = True


def _claim() -> dict:
    return build_claim(**BASE_VALUES)


def test_primary_gateway_success_does_not_call_fallback(monkeypatch) -> None:
    claim = _claim()
    calls: list[tuple[str, dict]] = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(payload=claim)

    monkeypatch.setattr(
        "provenance_pipeline.verification.requests.get",
        get,
    )

    assert fetch_ipfs_json(CID, PRIMARY, FALLBACK) == claim
    assert [url for url, _ in calls] == [f"{PRIMARY}/{CID}"]


def test_rate_limit_uses_independent_fallback_without_credentials(
    monkeypatch, caplog
) -> None:
    claim = _claim()
    calls: list[tuple[str, dict]] = []
    responses = iter(
        [FakeResponse(status_code=429), FakeResponse(payload=claim)]
    )

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return next(responses)

    monkeypatch.setenv("PINATA_JWT", "must-not-be-forwarded")
    monkeypatch.setattr(
        "provenance_pipeline.verification.requests.get",
        get,
    )
    caplog.set_level("INFO", logger="provenance_pipeline.verification")

    assert fetch_ipfs_json(CID, PRIMARY, FALLBACK) == claim
    assert [url for url, _ in calls] == [
        f"{PRIMARY}/{CID}",
        f"{FALLBACK}/{CID}",
    ]
    assert all(kwargs["headers"] == {"Accept": "application/json"} for _, kwargs in calls)
    assert "must-not-be-forwarded" not in caplog.text
    assert "status=429" in caplog.text
    assert "category=rate_limited" in caplog.text


def test_timeout_uses_fallback(monkeypatch) -> None:
    claim = _claim()
    calls: list[str] = []

    def get(url, **_kwargs):
        calls.append(url)
        if len(calls) == 1:
            raise requests.ReadTimeout("fixture timeout")
        return FakeResponse(payload=claim)

    monkeypatch.setattr(
        "provenance_pipeline.verification.requests.get",
        get,
    )

    assert fetch_ipfs_json(CID, PRIMARY, FALLBACK) == claim
    assert calls == [f"{PRIMARY}/{CID}", f"{FALLBACK}/{CID}"]


def test_stream_timeout_uses_fallback(monkeypatch) -> None:
    class StreamingTimeout(FakeResponse):
        def iter_content(self, chunk_size=65536):
            raise requests.ReadTimeout("stream timeout")
            yield b""  # pragma: no cover

    responses = iter([StreamingTimeout(), FakeResponse(payload=_claim())])
    monkeypatch.setattr(
        "provenance_pipeline.verification.requests.get",
        lambda *_args, **_kwargs: next(responses),
    )
    assert fetch_ipfs_json(CID, PRIMARY, FALLBACK) == _claim()


@pytest.mark.parametrize("status_code", [502, 503, 504])
def test_temporary_upstream_status_uses_fallback(
    monkeypatch, status_code
) -> None:
    responses = iter(
        [FakeResponse(status_code=status_code), FakeResponse(payload=_claim())]
    )
    get = lambda *_args, **_kwargs: next(responses)
    monkeypatch.setattr(
        "provenance_pipeline.verification.requests.get",
        get,
    )

    assert fetch_ipfs_json(CID, PRIMARY, FALLBACK) == _claim()


def test_all_gateways_unavailable_is_an_availability_error(monkeypatch) -> None:
    get = lambda *_args, **_kwargs: FakeResponse(status_code=503)
    monkeypatch.setattr(
        "provenance_pipeline.verification.requests.get",
        get,
    )

    with pytest.raises(IPFSGatewayUnavailable, match="temporarily unavailable"):
        fetch_ipfs_json(CID, PRIMARY, FALLBACK)


def test_invalid_json_is_hard_failure_without_fallback(monkeypatch) -> None:
    calls: list[str] = []

    def get(url, **_kwargs):
        calls.append(url)
        return FakeResponse(json_error=ValueError("not JSON"))

    monkeypatch.setattr(
        "provenance_pipeline.verification.requests.get",
        get,
    )

    with pytest.raises(IPFSClaimInvalid, match="not valid JSON"):
        fetch_ipfs_json(CID, PRIMARY, FALLBACK)
    assert calls == [f"{PRIMARY}/{CID}"]


def test_non_object_json_is_hard_failure_without_fallback(monkeypatch) -> None:
    calls: list[str] = []

    def get(url, **_kwargs):
        calls.append(url)
        return FakeResponse(payload=["not", "an", "object"])

    monkeypatch.setattr(
        "provenance_pipeline.verification.requests.get",
        get,
    )

    with pytest.raises(IPFSClaimInvalid, match="must be an object"):
        fetch_ipfs_json(CID, PRIMARY, FALLBACK)
    assert calls == [f"{PRIMARY}/{CID}"]


def test_non_retryable_http_error_does_not_use_fallback(monkeypatch) -> None:
    calls: list[str] = []

    def get(url, **_kwargs):
        calls.append(url)
        return FakeResponse(status_code=400)

    monkeypatch.setattr(
        "provenance_pipeline.verification.requests.get",
        get,
    )

    with pytest.raises(IPFSClaimInvalid, match="non-retryable"):
        fetch_ipfs_json(CID, PRIMARY, FALLBACK)
    assert calls == [f"{PRIMARY}/{CID}"]


def test_oversized_claim_is_integrity_failure_without_fallback(monkeypatch) -> None:
    class OversizedResponse(FakeResponse):
        def iter_content(self, chunk_size=65536):
            yield b"x" * (MAX_CLAIM_BYTES + 1)

    calls: list[str] = []

    def get(url, **_kwargs):
        calls.append(url)
        return OversizedResponse()

    monkeypatch.setattr("provenance_pipeline.verification.requests.get", get)
    with pytest.raises(IPFSClaimInvalid, match="size limit"):
        fetch_ipfs_json(CID, PRIMARY, FALLBACK)
    assert calls == [f"{PRIMARY}/{CID}"]


@pytest.mark.parametrize(
    "uri",
    ["ipfs://not-a-valid-cid", "definitelynotacid", "BAFYUPPERCASECID"],
)
def test_invalid_cid_is_rejected_before_gateway_request(monkeypatch, uri) -> None:
    monkeypatch.setattr(
        "provenance_pipeline.verification.requests.get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("invalid CID must not reach a gateway")
        ),
    )

    with pytest.raises(IPFSClaimInvalid, match="valid CID"):
        fetch_ipfs_json(uri, PRIMARY, FALLBACK)


def test_malformed_claim_is_hard_failure_without_gateway_shopping(
    monkeypatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "provenance_pipeline.verification.verify_claim",
        lambda _fingerprint: {
            "exists": True,
            "submitter": "0x2222222222222222222222222222222222222222",
            "timestamp": 1,
            "uri": CID,
        },
    )

    def get(url, **_kwargs):
        calls.append(url)
        return FakeResponse(payload={"unexpected": "document"})

    monkeypatch.setattr(
        "provenance_pipeline.verification.requests.get",
        get,
    )

    with pytest.raises(IPFSClaimInvalid, match="fingerprint_body and envelope"):
        verify_anchored_fingerprint(
            "a" * 64,
            gateway_url=PRIMARY,
            fallback_gateway_url=FALLBACK,
        )
    assert calls == [f"{PRIMARY}/{CID}"]


def test_malformed_fingerprint_body_is_not_reported_as_a_mismatch(
    monkeypatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "provenance_pipeline.verification.verify_claim",
        lambda _fingerprint: {
            "exists": True,
            "submitter": "0x2222222222222222222222222222222222222222",
            "timestamp": 1,
            "uri": CID,
        },
    )

    def get(url, **_kwargs):
        calls.append(url)
        return FakeResponse(payload={"fingerprint_body": {}, "envelope": {}})

    monkeypatch.setattr(
        "provenance_pipeline.verification.requests.get",
        get,
    )

    with pytest.raises(IPFSClaimInvalid, match="invalid structure"):
        verify_anchored_fingerprint(
            "a" * 64,
            gateway_url=PRIMARY,
            fallback_gateway_url=FALLBACK,
        )
    assert calls == [f"{PRIMARY}/{CID}"]


def test_fingerprint_mismatch_is_result_without_gateway_shopping(
    monkeypatch
) -> None:
    claim = deepcopy(_claim())
    fetched_fingerprint = compute_fingerprint(claim["fingerprint_body"])
    lookup_fingerprint = "0" * 64
    assert fetched_fingerprint != lookup_fingerprint
    calls: list[str] = []
    monkeypatch.setattr(
        "provenance_pipeline.verification.verify_claim",
        lambda _fingerprint: {
            "exists": True,
            "submitter": "0x2222222222222222222222222222222222222222",
            "timestamp": 1,
            "uri": CID,
        },
    )

    def get(url, **_kwargs):
        calls.append(url)
        return FakeResponse(payload=claim)

    monkeypatch.setattr(
        "provenance_pipeline.verification.requests.get",
        get,
    )

    report = verify_anchored_fingerprint(
        lookup_fingerprint,
        gateway_url=PRIMARY,
        fallback_gateway_url=FALLBACK,
    )

    assert report.passed is False
    assert report.fetched_fingerprint == fetched_fingerprint
    assert calls == [f"{PRIMARY}/{CID}"]


def test_unanchored_fingerprint_does_not_fetch_ipfs(monkeypatch) -> None:
    monkeypatch.setattr(
        "provenance_pipeline.verification.verify_claim",
        lambda _fingerprint: {
            "exists": False,
            "submitter": "0x0000000000000000000000000000000000000000",
            "timestamp": 0,
            "uri": "",
        },
    )
    monkeypatch.setattr(
        "provenance_pipeline.verification.requests.get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unanchored fingerprints must not fetch IPFS")
        ),
    )

    report = verify_anchored_fingerprint("a" * 64)

    assert report.passed is False
    assert report.fetched_fingerprint is None


def test_environment_gateway_is_preferred(monkeypatch) -> None:
    monkeypatch.setenv("IPFS_GATEWAY_URL", PRIMARY)
    monkeypatch.setenv("IPFS_FALLBACK_GATEWAY_URL", FALLBACK)

    assert resolve_ipfs_gateways() == (PRIMARY, FALLBACK)


def test_ipfs_foundation_aliases_are_not_fake_redundancy() -> None:
    assert resolve_ipfs_gateways(
        "https://ipfs.io/ipfs",
        "https://dweb.link/ipfs",
    ) == (
        "https://ipfs.io/ipfs",
        "https://gateway.pinata.cloud/ipfs",
    )


def test_gateway_url_with_credentials_is_rejected_before_request(
    monkeypatch
) -> None:
    monkeypatch.setattr(
        "provenance_pipeline.verification.requests.get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("invalid gateway configuration must not be requested")
        ),
    )

    with pytest.raises(IPFSGatewayConfigurationError, match="credentials"):
        fetch_ipfs_json(
            CID,
            "https://user:secret@primary.example/ipfs",
            FALLBACK,
        )
