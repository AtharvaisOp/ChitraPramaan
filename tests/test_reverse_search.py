from pathlib import Path
import os

import pytest
import requests

from provenance_pipeline.search.domain_filter import filter_to_social
from provenance_pipeline.search.reverse_search import (
    RawResult,
    ReverseSearchError,
    SearchAuthError,
    SearchNotConfigured,
    SearchProviderUnavailable,
    SearchRateLimited,
    SearchResponseInvalid,
    reverse_image_search,
)


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self) -> dict:
        return self.payload


def test_reverse_search_uploads_crop_bytes_and_preserves_provider_order(
    monkeypatch,
) -> None:
    crop_bytes = b"\xff\xd8\xffphase-2-crop\xff\xd9"
    observed: dict[str, object] = {}

    def fake_post(url: str, **kwargs):
        observed["post_url"] = url
        observed["post"] = kwargs
        return FakeResponse({"image_id": "temporary-image-id"})

    def fake_get(url: str, **kwargs):
        observed["get_url"] = url
        observed["get"] = kwargs
        return FakeResponse(
            {
                "visual_matches": [
                    {
                        "link": "https://instagram.com/p/first",
                        "title": "First",
                        "thumbnail": "https://images.example/first.jpg",
                        "source": "Instagram",
                    },
                    {
                        "link": "https://x.com/example/status/second",
                        "title": "Second",
                        "thumbnail": "https://images.example/second.jpg",
                        "source": "X",
                    },
                ]
            }
        )

    monkeypatch.setenv("SERPAPI_KEY", "fixture-key")
    monkeypatch.setattr(
        "provenance_pipeline.search.reverse_search.requests.post", fake_post
    )
    monkeypatch.setattr(
        "provenance_pipeline.search.reverse_search.requests.get", fake_get
    )

    results = reverse_image_search(crop_bytes)

    post = observed["post"]
    get = observed["get"]
    assert post["files"]["image"] == (
        "face-crop.jpg",
        crop_bytes,
        "image/jpeg",
    )
    assert get["params"] == {
        "api_key": "fixture-key",
        "engine": "google_lens",
        "image_id": "temporary-image-id",
        "type": "visual_matches",
    }
    assert crop_bytes not in get["params"].values()
    assert results == [
        RawResult(
            url="https://instagram.com/p/first",
            title="First",
            thumbnail_url="https://images.example/first.jpg",
            source="Instagram",
        ),
        RawResult(
            url="https://x.com/example/status/second",
            title="Second",
            thumbnail_url="https://images.example/second.jpg",
            source="X",
        ),
    ]


def test_reverse_search_returns_empty_on_no_results(monkeypatch, caplog) -> None:
    """Google Lens 'no results' error should return [] instead of raising."""

    crop_bytes = b"\xff\xd8\xff\xff\xd9"

    def fake_post(url: str, **kwargs):
        return FakeResponse({"image_id": "temp-id"})

    def fake_get(url: str, **kwargs):
        return FakeResponse(
            {"error": "Google Lens hasn't returned any results for this query."}
        )

    monkeypatch.setenv("SERPAPI_KEY", "fixture-key")
    monkeypatch.setattr(
        "provenance_pipeline.search.reverse_search.requests.post", fake_post
    )
    monkeypatch.setattr(
        "provenance_pipeline.search.reverse_search.requests.get", fake_get
    )

    caplog.set_level(
        20,
        logger="provenance_pipeline.search.reverse_search",
    )
    results = reverse_image_search(crop_bytes)
    assert results == []
    assert "Search provider returned no visual matches" in caplog.messages


def test_similar_provider_error_is_not_treated_as_no_results(monkeypatch) -> None:
    """Only the known Lens empty-result message may become an empty list."""

    crop_bytes = b"\xff\xd8\xff\xff\xd9"

    monkeypatch.setenv("SERPAPI_KEY", "fixture-key")
    monkeypatch.setattr(
        "provenance_pipeline.search.reverse_search.requests.post",
        lambda *_args, **_kwargs: FakeResponse({"image_id": "temp-id"}),
    )
    monkeypatch.setattr(
        "provenance_pipeline.search.reverse_search.requests.get",
        lambda *_args, **_kwargs: FakeResponse(
            {"error": "Google Lens hasn't returned any results because the request failed."}
        ),
    )

    with pytest.raises(SearchResponseInvalid):
        reverse_image_search(crop_bytes)


# ---- New error classification tests ----

def test_missing_api_key_raises_search_not_configured(monkeypatch) -> None:
    """Missing SERPAPI_KEY must raise SearchNotConfigured, not generic error."""
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    monkeypatch.delenv("SEARCH_API_KEY", raising=False)
    crop_bytes = b"\xff\xd8\xff\xff\xd9"
    with pytest.raises(SearchNotConfigured, match="Set SERPAPI_KEY"):
        reverse_image_search(crop_bytes)


def test_provider_401_raises_search_auth_error(monkeypatch) -> None:
    """Provider 401 must raise SearchAuthError."""
    crop_bytes = b"\xff\xd8\xff\xff\xd9"
    monkeypatch.setenv("SERPAPI_KEY", "fixture-key")

    def fake_post(url: str, **kwargs):
        resp = FakeResponse({}, status_code=401)
        return resp

    monkeypatch.setattr(
        "provenance_pipeline.search.reverse_search.requests.post", fake_post
    )
    with pytest.raises(SearchAuthError):
        reverse_image_search(crop_bytes)


def test_provider_403_raises_search_auth_error(monkeypatch) -> None:
    """Provider 403 must raise SearchAuthError."""
    crop_bytes = b"\xff\xd8\xff\xff\xd9"
    monkeypatch.setenv("SERPAPI_KEY", "fixture-key")

    def fake_post(url: str, **kwargs):
        return FakeResponse({}, status_code=403)

    monkeypatch.setattr(
        "provenance_pipeline.search.reverse_search.requests.post", fake_post
    )
    with pytest.raises(SearchAuthError):
        reverse_image_search(crop_bytes)


def test_provider_429_raises_search_rate_limited(monkeypatch) -> None:
    """Provider 429 must raise SearchRateLimited."""
    crop_bytes = b"\xff\xd8\xff\xff\xd9"
    monkeypatch.setenv("SERPAPI_KEY", "fixture-key")

    def fake_post(url: str, **kwargs):
        return FakeResponse({}, status_code=429)

    monkeypatch.setattr(
        "provenance_pipeline.search.reverse_search.requests.post", fake_post
    )
    # Disable retries for a faster test
    monkeypatch.setattr(
        "provenance_pipeline.search.reverse_search.MAX_RETRIES", 0
    )
    with pytest.raises(SearchRateLimited):
        reverse_image_search(crop_bytes)


def test_provider_502_raises_search_provider_unavailable(monkeypatch) -> None:
    """Provider 502 must raise SearchProviderUnavailable."""
    crop_bytes = b"\xff\xd8\xff\xff\xd9"
    monkeypatch.setenv("SERPAPI_KEY", "fixture-key")

    def fake_post(url: str, **kwargs):
        return FakeResponse({}, status_code=502)

    monkeypatch.setattr(
        "provenance_pipeline.search.reverse_search.requests.post", fake_post
    )
    monkeypatch.setattr(
        "provenance_pipeline.search.reverse_search.MAX_RETRIES", 0
    )
    with pytest.raises(SearchProviderUnavailable):
        reverse_image_search(crop_bytes)


def test_network_timeout_raises_provider_unavailable(monkeypatch) -> None:
    """Connection timeout must raise SearchProviderUnavailable."""
    crop_bytes = b"\xff\xd8\xff\xff\xd9"
    monkeypatch.setenv("SERPAPI_KEY", "fixture-key")

    def fake_post(url: str, **kwargs):
        raise requests.ConnectionError("timed out")

    monkeypatch.setattr(
        "provenance_pipeline.search.reverse_search.requests.post", fake_post
    )
    monkeypatch.setattr(
        "provenance_pipeline.search.reverse_search.MAX_RETRIES", 0
    )
    with pytest.raises(SearchProviderUnavailable):
        reverse_image_search(crop_bytes)


def test_malformed_json_raises_search_response_invalid(monkeypatch) -> None:
    """Non-JSON body on 200 must raise SearchResponseInvalid."""
    crop_bytes = b"\xff\xd8\xff\xff\xd9"
    monkeypatch.setenv("SERPAPI_KEY", "fixture-key")

    class BadJsonResponse:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            raise ValueError("bad json")

    monkeypatch.setattr(
        "provenance_pipeline.search.reverse_search.requests.post",
        lambda *a, **kw: BadJsonResponse(),
    )
    with pytest.raises(SearchResponseInvalid, match="invalid JSON"):
        reverse_image_search(crop_bytes)


def test_provider_error_inside_200_raises_appropriate(monkeypatch) -> None:
    """Provider-level 'invalid api key' error in 200 body must raise SearchAuthError."""
    crop_bytes = b"\xff\xd8\xff\xff\xd9"
    monkeypatch.setenv("SERPAPI_KEY", "fixture-key")

    def fake_post(url: str, **kwargs):
        return FakeResponse({"error": "Invalid API key. Your API key should be here: ..."})

    monkeypatch.setattr(
        "provenance_pipeline.search.reverse_search.requests.post", fake_post
    )
    with pytest.raises(SearchAuthError, match="invalid API key"):
        reverse_image_search(crop_bytes)


def test_provider_rate_limit_error_inside_200(monkeypatch) -> None:
    """Provider-level quota error in 200 body must raise SearchRateLimited."""
    crop_bytes = b"\xff\xd8\xff\xff\xd9"
    monkeypatch.setenv("SERPAPI_KEY", "fixture-key")

    def fake_post(url: str, **kwargs):
        return FakeResponse({"error": "You have exceeded your rate limit for this month."})

    monkeypatch.setattr(
        "provenance_pipeline.search.reverse_search.requests.post", fake_post
    )
    with pytest.raises(SearchRateLimited):
        reverse_image_search(crop_bytes)


def test_empty_valid_result_returns_empty_list(monkeypatch) -> None:
    """An empty visual_matches array should return [] without raising."""
    crop_bytes = b"\xff\xd8\xff\xff\xd9"
    monkeypatch.setenv("SERPAPI_KEY", "fixture-key")

    def fake_post(url: str, **kwargs):
        return FakeResponse({"image_id": "temp"})

    def fake_get(url: str, **kwargs):
        return FakeResponse({"visual_matches": []})

    monkeypatch.setattr(
        "provenance_pipeline.search.reverse_search.requests.post", fake_post
    )
    monkeypatch.setattr(
        "provenance_pipeline.search.reverse_search.requests.get", fake_get
    )
    results = reverse_image_search(crop_bytes)
    assert results == []


@pytest.mark.integration
def test_live_reverse_search_returns_allowlisted_candidate() -> None:
    """Opt-in paid test using a real Phase 2 crop and live SerpApi key."""

    if os.getenv("RUN_REVERSE_SEARCH_INTEGRATION") != "1":
        pytest.skip("set RUN_REVERSE_SEARCH_INTEGRATION=1 to allow a paid request")
    if not (os.getenv("SERPAPI_KEY") or os.getenv("SEARCH_API_KEY")):
        pytest.skip("set SERPAPI_KEY or SEARCH_API_KEY")

    crop_path_value = os.getenv("REVERSE_SEARCH_TEST_CROP")
    if not crop_path_value:
        pytest.skip("set REVERSE_SEARCH_TEST_CROP to a real Phase 2 JPEG crop")
    crop_path = Path(crop_path_value)
    if not crop_path.is_file():
        pytest.fail(f"REVERSE_SEARCH_TEST_CROP does not exist: {crop_path}")

    results = filter_to_social(reverse_image_search(crop_path.read_bytes()))

    assert results, "live search returned no candidates on an allowlisted domain"
