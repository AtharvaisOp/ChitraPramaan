import json
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend import main as api
from cli import run as cli_run
from provenance_pipeline.face.detector import (
    DETECTOR_MODEL_VERSION,
    FaceDetection,
    crop_face,
    sha256_bytes,
)
from provenance_pipeline.images import decode_image_bytes
from provenance_pipeline.records.fingerprint import compute_fingerprint
from provenance_pipeline.search.rerank import RankedResult
from provenance_pipeline.search.reverse_search import (
    RawResult,
    SearchAuthError,
    SearchNotConfigured,
    SearchProviderUnavailable,
    SearchRateLimited,
    SearchResponseInvalid,
)


@pytest.fixture(autouse=True)
def clear_sessions() -> None:
    with api._sessions_lock:
        api._sessions.clear()
    api.limiter.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(api.app)


def _photo_bytes() -> bytes:
    y, x = np.indices((96, 112), dtype=np.uint16)
    image = np.stack(
        (
            (x * 3 + y * 5) % 256,
            (x * x + y * 7) % 256,
            (x * 11 + y * y) % 256,
        ),
        axis=2,
    ).astype(np.uint8)
    success, encoded = cv2.imencode(".jpg", image)
    assert success
    return encoded.tobytes()


def _fixtures():
    subject = FaceDetection(
        bbox=(20, 15, 75, 75),
        det_score=0.98,
        embedding=np.linspace(0.1, 1.0, 512, dtype=np.float32),
    )
    candidates = [
        RawResult(
            url="https://instagram.com/p/first",
            title="First fixture",
            thumbnail_url="https://images.example.test/first.jpg",
            source="Instagram",
        ),
        RawResult(
            url="https://instagram.com/p/second",
            title="Second fixture",
            thumbnail_url="https://images.example.test/second.jpg",
            source="Instagram",
        ),
    ]
    ranked = [
        RankedResult(candidate=candidates[0], score=0.79),
        RankedResult(candidate=candidates[1], score=0.72),
    ]
    return subject, candidates, ranked


def _mock_search_pipeline(monkeypatch, subject, candidates, ranked) -> None:
    for module in (api, cli_run):
        monkeypatch.setattr(module, "detect_faces", lambda _image: [subject])
        monkeypatch.setattr(
            module, "reverse_image_search", lambda _crop: candidates
        )
        monkeypatch.setattr(module, "filter_to_social", lambda results: results)
        monkeypatch.setattr(
            module,
            "rerank",
            lambda _candidates, _embedding, **_kwargs: ranked,
        )


def test_create_confirm_verify_flow_matches_cli_fingerprint(
    client, tmp_path, monkeypatch
) -> None:
    photo_bytes = _photo_bytes()
    subject, candidates, ranked = _fixtures()
    _mock_search_pipeline(monkeypatch, subject, candidates, ranked)
    external_calls: list[tuple] = []
    pinned: dict[str, dict] = {}

    def fake_pin(claim: dict) -> str:
        external_calls.append(("pin", claim))
        pinned["claim"] = claim
        return "bafybackendfixture"

    def fake_anchor(fingerprint: str, cid: str) -> dict:
        external_calls.append(("anchor", fingerprint, cid))
        return {"status": 1, "transactionHash": bytes.fromhex("12" * 32)}

    monkeypatch.setattr(api, "pin_json", fake_pin)
    monkeypatch.setattr(api, "anchor_claim", fake_anchor)

    create = client.post(
        "/api/sessions",
        data={"consent": "true", "auto_threshold": "0.80"},
        files={"photo": ("sample.jpg", photo_bytes, "image/jpeg")},
    )

    assert create.status_code == 201
    created = create.json()
    assert created["status"] == "review_required"
    assert created["selection_method"] is None
    assert [item["index"] for item in created["candidates"]] == [0, 1]
    assert [item["score"] for item in created["candidates"]] == [0.79, 0.72]
    assert external_calls == []

    session_id = created["session_id"]
    state = api._sessions[session_id]
    assert state.uploaded_photo == photo_bytes
    assert np.array_equal(state.query_embedding, subject.embedding)
    assert state.ranked == ranked

    confirm = client.post(
        f"/api/sessions/{session_id}/confirm",
        json={"candidate_index": 1},
    )

    assert confirm.status_code == 200
    confirmed = confirm.json()
    assert confirmed["selection_method"] == "human"
    assert confirmed["score"] == 0.72
    assert confirmed["cid"] == "bafybackendfixture"
    assert confirmed["tx_hash"] == "0x" + "12" * 32
    assert confirmed["explorer_link"].endswith(confirmed["tx_hash"])
    assert [call[0] for call in external_calls] == ["pin", "anchor"]

    expected_crop_hash = sha256_bytes(
        crop_face(decode_image_bytes(photo_bytes), subject.bbox)
    )
    expected_body = {
        "platform": "instagram",
        "normalized_post_url": candidates[1].url,
        "crop_sha256": expected_crop_hash,
        "embedding_sha256": state.embedding_digest,
        "detector_model_version": DETECTOR_MODEL_VERSION,
    }
    assert confirmed["fingerprint"] == compute_fingerprint(expected_body)
    assert pinned["claim"]["fingerprint_body"] == expected_body
    assert state.uploaded_photo is None
    assert state.query_embedding is None

    # Confirmation is idempotent at the API layer and cannot double-anchor.
    repeat = client.post(
        f"/api/sessions/{session_id}/confirm",
        json={"candidate_index": 1},
    )
    assert repeat.status_code == 200
    assert repeat.json() == confirmed
    assert [call[0] for call in external_calls] == ["pin", "anchor"]

    monkeypatch.setattr(
        "provenance_pipeline.verification.verify_claim",
        lambda fingerprint: {
            "exists": True,
            "submitter": "0x2222222222222222222222222222222222222222",
            "timestamp": 1_788_000_000,
            "uri": "bafybackendfixture",
        },
    )
    monkeypatch.setattr(
        "provenance_pipeline.verification.fetch_ipfs_json",
        lambda *_args, **_kwargs: pinned["claim"],
    )

    verify = client.get(f"/api/verify/{confirmed['fingerprint']}")
    assert verify.status_code == 200
    verification = verify.json()
    assert verification["passed"] is True
    assert verification["fingerprint"] == confirmed["fingerprint"]
    assert verification["fetched_fingerprint"] == confirmed["fingerprint"]
    assert verification["on_chain_record"]["uri"] == "bafybackendfixture"

    # The CLI consumes the same shared construction path and therefore emits
    # the same body fingerprint for the same bytes and chosen ranked result.
    photo_path = tmp_path / "same-photo.jpg"
    photo_path.write_bytes(photo_bytes)
    responses = iter(["y", "2"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(responses))
    assert cli_run.main(
        [
            "--photo",
            str(photo_path),
            "--auto-threshold",
            "0.80",
            "--dry-run",
        ]
    ) == 0
    cli_claim = json.loads(
        photo_path.with_suffix(".claim.json").read_text(encoding="utf-8")
    )
    assert compute_fingerprint(cli_claim["fingerprint_body"]) == confirmed[
        "fingerprint"
    ]


def test_auto_selected_session_confirms_without_index(client, monkeypatch) -> None:
    subject, candidates, ranked = _fixtures()
    _mock_search_pipeline(monkeypatch, subject, candidates, ranked)
    calls: list[str] = []
    monkeypatch.setattr(
        api,
        "pin_json",
        lambda _claim: calls.append("pin") or "bafyautofixture",
    )
    monkeypatch.setattr(
        api,
        "anchor_claim",
        lambda *_args: calls.append("anchor")
        or {"status": 1, "transactionHash": bytes.fromhex("34" * 32)},
    )

    create = client.post(
        "/api/sessions",
        data={"consent": "true", "auto_threshold": "0.75"},
        files={"photo": ("sample.jpg", _photo_bytes(), "image/jpeg")},
    )
    assert create.status_code == 201
    body = create.json()
    assert body["status"] == "auto_selected"
    assert body["selection_method"] == "auto"
    assert body["selected_candidate"]["index"] == 0
    assert [candidate["index"] for candidate in body["candidates"]] == [0, 1]
    assert body["candidates"][0] == body["selected_candidate"]
    assert calls == []

    confirm = client.post(f"/api/sessions/{body['session_id']}/confirm")
    assert confirm.status_code == 200
    assert confirm.json()["selection_method"] == "auto"
    assert calls == ["pin", "anchor"]


def test_analysis_budgets_rerank_pool_and_returns_top_seven_without_anchoring(
    client, monkeypatch
) -> None:
    subject, _, _ = _fixtures()
    raw = [
        RawResult(
            url=f"https://instagram.com/p/{index}",
            title=f"candidate-{index}",
            thumbnail_url=f"https://images.example.test/{index}.jpg",
            source="fixture",
        )
        for index in range(30)
    ]
    search_calls = 0
    rerank_inputs: list[list[RawResult]] = []

    def fake_search(_crop: bytes) -> list[RawResult]:
        nonlocal search_calls
        search_calls += 1
        return raw

    def fake_rerank(candidates, _embedding, *, metrics):
        rerank_inputs.append(candidates)
        metrics.candidate_count_processed = len(candidates)
        metrics.candidate_count_face_valid = len(candidates)
        ranked = [
            RankedResult(
                candidate=candidate,
                score=1.0 if candidate.title == "candidate-20" else 0.8 - index / 100,
            )
            for index, candidate in enumerate(candidates)
        ]
        return sorted(ranked, key=lambda result: result.score, reverse=True)

    monkeypatch.setattr(api, "detect_faces", lambda _image: [subject])
    monkeypatch.setattr(api, "reverse_image_search", fake_search)
    monkeypatch.setattr(api, "filter_to_social", lambda results: results[:25])
    monkeypatch.setattr(api, "rerank", fake_rerank)
    monkeypatch.setattr(
        api,
        "pin_json",
        lambda _claim: (_ for _ in ()).throw(AssertionError("analysis must not pin")),
    )
    monkeypatch.setattr(
        api,
        "anchor_claim",
        lambda *_args: (_ for _ in ()).throw(AssertionError("analysis must not anchor")),
    )

    response = client.post(
        "/api/sessions",
        data={"consent": "true"},
        files={"photo": ("sample.jpg", _photo_bytes(), "image/jpeg")},
    )

    assert response.status_code == 201
    body = response.json()
    assert search_calls == 1
    assert len(rerank_inputs) == 1
    assert len(rerank_inputs[0]) == api.MAX_RERANK_CANDIDATES
    assert rerank_inputs[0][-1].title == "candidate-20"
    assert len(body["candidates"]) == api.MAX_RETURNED_CANDIDATES == 7
    assert body["candidates"][0]["title"] == "candidate-20"
    assert [candidate["index"] for candidate in body["candidates"]] == list(range(7))
    assert [candidate["score"] for candidate in body["candidates"]] == sorted(
        [candidate["score"] for candidate in body["candidates"]], reverse=True
    )


def test_consent_and_upload_validation_happen_before_pipeline(
    client, monkeypatch
) -> None:
    monkeypatch.setattr(
        api,
        "detect_faces",
        lambda _image: (_ for _ in ()).throw(
            AssertionError("invalid uploads must not reach detection")
        ),
    )
    photo = _photo_bytes()

    no_consent = client.post(
        "/api/sessions",
        data={"consent": "false"},
        files={"photo": ("sample.jpg", photo, "image/jpeg")},
    )
    assert no_consent.status_code == 403

    wrong_type = client.post(
        "/api/sessions",
        data={"consent": "true"},
        files={"photo": ("sample.txt", photo, "text/plain")},
    )
    assert wrong_type.status_code == 415

    oversized = client.post(
        "/api/sessions",
        data={"consent": "true"},
        files={
            "photo": (
                "large.jpg",
                b"x" * (api.MAX_UPLOAD_BYTES + 1),
                "image/jpeg",
            )
        },
    )
    assert oversized.status_code == 413


def test_review_confirmation_requires_valid_index(client, monkeypatch) -> None:
    subject, candidates, ranked = _fixtures()
    _mock_search_pipeline(monkeypatch, subject, candidates, ranked)
    create = client.post(
        "/api/sessions",
        data={"consent": "true", "auto_threshold": "0.80"},
        files={"photo": ("sample.jpg", _photo_bytes(), "image/jpeg")},
    ).json()

    missing = client.post(
        f"/api/sessions/{create['session_id']}/confirm", json={}
    )
    assert missing.status_code == 422
    out_of_range = client.post(
        f"/api/sessions/{create['session_id']}/confirm",
        json={"candidate_index": 99},
    )
    assert out_of_range.status_code == 422
    unknown = client.post(
        "/api/sessions/does-not-exist/confirm", json={"candidate_index": 0}
    )
    assert unknown.status_code == 404


# ---- New error mapping and health tests ----


def test_search_not_configured_returns_503(client, monkeypatch) -> None:
    """SearchNotConfigured must map to 503 with the correct user message."""
    monkeypatch.setattr(
        api,
        "reverse_image_search",
        lambda _crop: (_ for _ in ()).throw(
            SearchNotConfigured("no key")
        ),
    )
    subject, candidates, ranked = _fixtures()
    monkeypatch.setattr(api, "detect_faces", lambda _image: [subject])
    monkeypatch.setattr(api, "filter_to_social", lambda r: r)
    monkeypatch.setattr(api, "rerank", lambda c, e, **_kwargs: ranked)

    resp = client.post(
        "/api/sessions",
        data={"consent": "true"},
        files={"photo": ("s.jpg", _photo_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"]
    # Must not contain secrets
    assert "key" not in resp.json()["detail"].lower() or "api key" not in resp.json()["detail"].lower()


def test_search_auth_error_returns_502(client, monkeypatch) -> None:
    """SearchAuthError must map to 502 with credentials-rejected message."""
    monkeypatch.setattr(
        api,
        "reverse_image_search",
        lambda _crop: (_ for _ in ()).throw(
            SearchAuthError("bad key")
        ),
    )
    subject, candidates, ranked = _fixtures()
    monkeypatch.setattr(api, "detect_faces", lambda _image: [subject])
    monkeypatch.setattr(api, "filter_to_social", lambda r: r)
    monkeypatch.setattr(api, "rerank", lambda c, e, **_kwargs: ranked)

    resp = client.post(
        "/api/sessions",
        data={"consent": "true"},
        files={"photo": ("s.jpg", _photo_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 502
    assert "rejected" in resp.json()["detail"]


def test_search_rate_limited_returns_429(client, monkeypatch) -> None:
    """SearchRateLimited must map to 429."""
    monkeypatch.setattr(
        api,
        "reverse_image_search",
        lambda _crop: (_ for _ in ()).throw(
            SearchRateLimited("quota")
        ),
    )
    subject, candidates, ranked = _fixtures()
    monkeypatch.setattr(api, "detect_faces", lambda _image: [subject])
    monkeypatch.setattr(api, "filter_to_social", lambda r: r)
    monkeypatch.setattr(api, "rerank", lambda c, e, **_kwargs: ranked)

    resp = client.post(
        "/api/sessions",
        data={"consent": "true"},
        files={"photo": ("s.jpg", _photo_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 429
    assert "rate-limited" in resp.json()["detail"].lower() or "quota" in resp.json()["detail"].lower()


def test_search_provider_unavailable_returns_502(client, monkeypatch) -> None:
    """SearchProviderUnavailable must map to 502 with 'unavailable' message."""
    monkeypatch.setattr(
        api,
        "reverse_image_search",
        lambda _crop: (_ for _ in ()).throw(
            SearchProviderUnavailable("down")
        ),
    )
    subject, candidates, ranked = _fixtures()
    monkeypatch.setattr(api, "detect_faces", lambda _image: [subject])
    monkeypatch.setattr(api, "filter_to_social", lambda r: r)
    monkeypatch.setattr(api, "rerank", lambda c, e, **_kwargs: ranked)

    resp = client.post(
        "/api/sessions",
        data={"consent": "true"},
        files={"photo": ("s.jpg", _photo_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 502
    assert "unavailable" in resp.json()["detail"].lower()


def test_search_response_invalid_returns_502(client, monkeypatch) -> None:
    """SearchResponseInvalid must map to 502 with 'unexpected' message."""
    monkeypatch.setattr(
        api,
        "reverse_image_search",
        lambda _crop: (_ for _ in ()).throw(
            SearchResponseInvalid("bad json")
        ),
    )
    subject, candidates, ranked = _fixtures()
    monkeypatch.setattr(api, "detect_faces", lambda _image: [subject])
    monkeypatch.setattr(api, "filter_to_social", lambda r: r)
    monkeypatch.setattr(api, "rerank", lambda c, e, **_kwargs: ranked)

    resp = client.post(
        "/api/sessions",
        data={"consent": "true"},
        files={"photo": ("s.jpg", _photo_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 502
    assert "unexpected" in resp.json()["detail"].lower()


def test_zero_raw_results_returns_422_accurate_message(client, monkeypatch) -> None:
    """CASE A: provider returns zero matches -> accurate 422 message."""
    subject, _, ranked = _fixtures()
    monkeypatch.setattr(api, "detect_faces", lambda _image: [subject])
    monkeypatch.setattr(api, "reverse_image_search", lambda _crop: [])
    filter_calls: list = []
    monkeypatch.setattr(
        api,
        "filter_to_social",
        lambda results: filter_calls.append(results) or results,
    )
    rerank_calls: list = []
    monkeypatch.setattr(
        api,
        "rerank",
        lambda candidates, _embedding, **_kwargs: rerank_calls.append(candidates)
        or ranked,
    )

    resp = client.post(
        "/api/sessions",
        data={"consent": "true"},
        files={"photo": ("s.jpg", _photo_bytes(), "image/jpeg")},
    )

    assert resp.status_code == 422
    assert (
        resp.json()["detail"]
        == "No matching images were found for this photo. Try another photo."
    )
    # rerank must not run when there is nothing to rank.
    assert filter_calls == []
    assert rerank_calls == []


def test_all_raw_results_filtered_out_returns_422_supported_message(
    client, monkeypatch
) -> None:
    """CASE B: matches exist but none on allowed domains -> existing 422 message."""
    subject, _, ranked = _fixtures()
    non_social = [
        RawResult(
            url="https://news.example.com/article",
            title="News fixture",
            thumbnail_url="https://images.example.test/article.jpg",
            source="News site",
        )
    ]
    monkeypatch.setattr(api, "detect_faces", lambda _image: [subject])
    monkeypatch.setattr(api, "reverse_image_search", lambda _crop: non_social)
    monkeypatch.setattr(api, "filter_to_social", lambda _results: [])
    rerank_calls: list = []
    monkeypatch.setattr(
        api,
        "rerank",
        lambda candidates, _embedding, **_kwargs: rerank_calls.append(candidates)
        or ranked,
    )

    resp = client.post(
        "/api/sessions",
        data={"consent": "true"},
        files={"photo": ("s.jpg", _photo_bytes(), "image/jpeg")},
    )

    assert resp.status_code == 422
    assert (
        resp.json()["detail"]
        == "No supported source results were found. Try another photo."
    )
    assert rerank_calls == []


def test_no_usable_ranked_faces_returns_422_thumbnail_message(
    client, monkeypatch
) -> None:
    """CASE C: supported matches exist but no thumbnail has a usable face."""
    subject, candidates, _ = _fixtures()
    monkeypatch.setattr(api, "detect_faces", lambda _image: [subject])
    monkeypatch.setattr(api, "reverse_image_search", lambda _crop: candidates)
    monkeypatch.setattr(api, "filter_to_social", lambda results: results)
    monkeypatch.setattr(api, "rerank", lambda _candidates, _embedding, **_kwargs: [])
    select_calls: list = []
    monkeypatch.setattr(
        api,
        "select_match",
        lambda ranked, **_kwargs: select_calls.append(ranked),
    )

    resp = client.post(
        "/api/sessions",
        data={"consent": "true"},
        files={"photo": ("s.jpg", _photo_bytes(), "image/jpeg")},
    )

    assert resp.status_code == 422
    assert (
        resp.json()["detail"]
        == "No candidate thumbnails had a usable face. Try another photo."
    )
    assert select_calls == []


def test_no_secrets_in_error_responses(client, monkeypatch) -> None:
    """Error responses must never contain API keys or auth headers."""
    monkeypatch.setattr(
        api,
        "reverse_image_search",
        lambda _crop: (_ for _ in ()).throw(
            SearchAuthError("api_key=secret123 bad key")
        ),
    )
    subject, candidates, ranked = _fixtures()
    monkeypatch.setattr(api, "detect_faces", lambda _image: [subject])
    monkeypatch.setattr(api, "filter_to_social", lambda r: r)
    monkeypatch.setattr(api, "rerank", lambda c, e, **_kwargs: ranked)

    resp = client.post(
        "/api/sessions",
        data={"consent": "true"},
        files={"photo": ("s.jpg", _photo_bytes(), "image/jpeg")},
    )
    body = json.dumps(resp.json())
    assert "secret123" not in body
    assert "api_key" not in body.lower()


def test_health_endpoint(client) -> None:
    """Health endpoint must return service configuration status without secrets."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert set(body["services"].keys()) == {"search", "ipfs", "blockchain"}
    for value in body["services"].values():
        assert value in ("configured", "not_configured")
    # Must not contain actual key values
    body_str = json.dumps(body)
    assert "SERPAPI" not in body_str
    assert "PINATA" not in body_str
    assert "PRIVATE_KEY" not in body_str


def test_frontend_origin_rejects_wildcards_and_paths(monkeypatch) -> None:
    monkeypatch.setenv("FRONTEND_ORIGIN", "*")
    with pytest.raises(RuntimeError, match="exact"):
        api._frontend_origins()
    monkeypatch.setenv("FRONTEND_ORIGIN", "https://app.example/path")
    with pytest.raises(RuntimeError, match="exact"):
        api._frontend_origins()


def test_public_analysis_rate_limit_returns_retryable_http_error() -> None:
    api.limiter.clear()
    request = SimpleNamespace(client=SimpleNamespace(host="198.51.100.10"))
    for _ in range(5):
        api._enforce_rate_limit(request, "analyze")
    with pytest.raises(api.HTTPException) as error:
        api._enforce_rate_limit(request, "analyze")
    assert error.value.status_code == 429
    assert "Retry-After" in (error.value.headers or {})


def test_verify_honors_configured_ipfs_gateway(client, monkeypatch) -> None:
    body = {
        "platform": "instagram",
        "normalized_post_url": "https://instagram.com/p/fixture",
        "crop_sha256": "a" * 64,
        "embedding_sha256": "b" * 64,
        "detector_model_version": "fixture-detector",
    }
    document = {"fingerprint_body": body, "envelope": {}}
    fingerprint = compute_fingerprint(body)
    calls: list[tuple[str, dict]] = []
    monkeypatch.setenv("IPFS_GATEWAY_URL", "https://configured.example/ipfs")
    monkeypatch.setenv(
        "IPFS_FALLBACK_GATEWAY_URL",
        "https://fallback.example/ipfs",
    )
    monkeypatch.setattr(
        "provenance_pipeline.verification.verify_claim",
        lambda _fingerprint: {
            "exists": True,
            "submitter": "0x2222222222222222222222222222222222222222",
            "timestamp": 1_788_000_000,
            "uri": "bafybackendverifyfixture",
        },
    )

    class Response:
        status_code = 200
        headers = {}

        def json(self):
            return document

        def iter_content(self, chunk_size=65536):
            yield json.dumps(document).encode("utf-8")

        def close(self):
            pass

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(
        "provenance_pipeline.verification.requests.get",
        get,
    )

    response = client.get(f"/api/verify/{fingerprint}")

    assert response.status_code == 200
    assert response.json()["passed"] is True
    assert [url for url, _ in calls] == [
        "https://configured.example/ipfs/bafybackendverifyfixture"
    ]


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_detail"),
    [
        (
            api.ChainClientError("RPC credential detail"),
            502,
            "The Registry could not be read. Verification is temporarily unavailable.",
        ),
        (
            api.IPFSGatewayUnavailable("gateway detail"),
            502,
            "The anchored claim could not be retrieved from IPFS. Verification is temporarily unavailable.",
        ),
        (
            api.IPFSClaimInvalid("claim detail"),
            502,
            "The anchored claim could not be validated.",
        ),
    ],
)
def test_verify_errors_are_classified_without_internal_details(
    client, monkeypatch, error, expected_status, expected_detail
) -> None:
    monkeypatch.setattr(
        api,
        "verify_anchored_fingerprint",
        lambda _fingerprint: (_ for _ in ()).throw(error),
    )

    response = client.get(f"/api/verify/{'a' * 64}")

    assert response.status_code == expected_status
    assert response.json()["detail"] == expected_detail
    assert str(error) not in response.text

