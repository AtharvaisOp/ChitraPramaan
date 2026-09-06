"""Upload a deterministic face crop and request Google Lens visual matches.

Provider contract verified against SerpApi's Image API and Google Lens API on
2026-09-05. The crop is uploaded as multipart form data; it is never embedded
in a URL or degraded to satisfy a query-string limit.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import time
from typing import Any

import requests


logger = logging.getLogger(__name__)

SERPAPI_IMAGE_ENDPOINT = "https://serpapi.com/image"
SERPAPI_SEARCH_ENDPOINT = "https://serpapi.com/search.json"
SERPAPI_MAX_UPLOAD_BYTES = 500 * 1024
REQUEST_TIMEOUT = (10, 60)

# Bounded retry for transient provider failures only.
MAX_RETRIES = 2
RETRY_BASE_SECONDS = 1.0

_SERPAPI_NO_RESULTS_MESSAGES = frozenset(
    {
        "google lens hasn't returned any results for this query",
        "google lens hasn't returned any results for this query.",
    }
)


@dataclass(frozen=True, slots=True)
class RawResult:
    """Provider result fields needed by later filtering and ranking phases."""

    url: str
    title: str
    thumbnail_url: str
    source: str


# ---------------------------------------------------------------------------
# Typed exception hierarchy
# ---------------------------------------------------------------------------

class ReverseSearchError(RuntimeError):
    """Raised when the reverse-search provider rejects or cannot serve a query."""


class SearchNotConfigured(ReverseSearchError):
    """The API key / credentials are missing from the server environment."""


class SearchAuthError(ReverseSearchError):
    """The provider rejected the server credentials (401/403)."""


class SearchRateLimited(ReverseSearchError):
    """The provider returned 429 or a quota-exhaustion error."""


class SearchProviderUnavailable(ReverseSearchError):
    """Transient provider failure (5xx, network error, timeout)."""


class SearchResponseInvalid(ReverseSearchError):
    """The provider returned an unexpected or malformed response."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _api_key() -> str:
    key = os.getenv("SERPAPI_KEY") or os.getenv("SEARCH_API_KEY")
    if not key:
        raise SearchNotConfigured(
            "Set SERPAPI_KEY (or SEARCH_API_KEY) before running reverse search"
        )
    return key


def _classify_http_error(
    response: requests.Response, operation: str,
) -> ReverseSearchError:
    """Return the correctly-typed exception for a non-2xx provider response."""
    status = response.status_code
    if status in (401, 403):
        return SearchAuthError(
            f"SerpApi {operation}: provider rejected credentials (HTTP {status})"
        )
    if status == 429:
        return SearchRateLimited(
            f"SerpApi {operation}: rate limited (HTTP 429)"
        )
    if status >= 500:
        return SearchProviderUnavailable(
            f"SerpApi {operation}: provider error (HTTP {status})"
        )
    return SearchResponseInvalid(
        f"SerpApi {operation}: unexpected HTTP {status}"
    )


def _is_transient(exc: Exception) -> bool:
    """True when a retry is justified."""
    return isinstance(exc, SearchProviderUnavailable)


def _is_no_results_error(value: object) -> bool:
    """Recognize only SerpApi's documented Google Lens no-results message."""

    return (
        isinstance(value, str)
        and value.strip().casefold() in _SERPAPI_NO_RESULTS_MESSAGES
    )


def _json_object(
    response: requests.Response,
    operation: str,
    *,
    allow_no_results: bool = False,
) -> dict[str, Any]:
    try:
        response.raise_for_status()
    except requests.HTTPError:
        raise _classify_http_error(response, operation)
    except requests.RequestException as exc:
        raise SearchProviderUnavailable(
            f"SerpApi {operation} request failed"
        ) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise SearchResponseInvalid(
            f"SerpApi {operation} returned invalid JSON"
        ) from exc

    if not isinstance(payload, dict):
        raise SearchResponseInvalid(
            f"SerpApi {operation} returned an invalid payload"
        )

    error_value = payload.get("error")
    if error_value:
        if allow_no_results and _is_no_results_error(error_value):
            return payload
        error_str = str(error_value).lower() if error_value else ""
        if "invalid api key" in error_str or "wrong api key" in error_str:
            raise SearchAuthError(f"SerpApi {operation}: invalid API key")
        if "rate limit" in error_str or "quota" in error_str:
            raise SearchRateLimited(
                f"SerpApi {operation}: quota/rate limit reached"
            )
        raise SearchResponseInvalid(f"SerpApi {operation} failed: application error")

    return payload


def _log_attempt(
    operation: str, *, attempt: int, elapsed: float,
    status: int | None = None, error_category: str | None = None,
) -> None:
    """Emit a safe diagnostic log line (never contains credentials)."""
    parts = [f"provider=serpapi op={operation}"]
    if attempt > 0:
        parts.append(f"retry={attempt}")
    if status is not None:
        parts.append(f"status={status}")
    if error_category:
        parts.append(f"category={error_category}")
    parts.append(f"elapsed={elapsed:.2f}s")
    logger.info("Search provider request: %s", " ".join(parts))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def reverse_image_search(crop_bytes: bytes) -> list[RawResult]:
    """Upload Phase 2 JPEG crop bytes and return provider-ordered matches.

    This function deliberately accepts bytes rather than a full-frame image or
    an image URL. SerpApi's temporary ``image_id`` expires after ten minutes,
    and the follow-up request contains that ID rather than image data.
    """

    if not isinstance(crop_bytes, bytes):
        raise TypeError("crop_bytes must be bytes returned by crop_face")
    if not crop_bytes:
        raise ValueError("crop_bytes must not be empty")
    if len(crop_bytes) > SERPAPI_MAX_UPLOAD_BYTES:
        raise ValueError("crop_bytes exceeds SerpApi's 500 KB upload limit")
    if not crop_bytes.startswith(b"\xff\xd8\xff"):
        raise ValueError("crop_bytes must contain a JPEG produced by crop_face")

    key = _api_key()

    # --- Step 1: Upload crop ---
    image_id = _upload_crop(key, crop_bytes)

    # --- Step 2: Google Lens search ---
    return _lens_search(key, image_id)


def _upload_crop(key: str, crop_bytes: bytes) -> str:
    """Upload the crop and return the temporary image_id."""
    last_exc: Exception | None = None
    for attempt in range(1 + MAX_RETRIES):
        if attempt > 0:
            time.sleep(RETRY_BASE_SECONDS * (2 ** (attempt - 1)))
        t0 = time.monotonic()
        try:
            response = requests.post(
                SERPAPI_IMAGE_ENDPOINT,
                data={"api_key": key},
                files={"image": ("face-crop.jpg", crop_bytes, "image/jpeg")},
                timeout=REQUEST_TIMEOUT,
            )
            elapsed = time.monotonic() - t0
            _log_attempt(
                "image_upload", attempt=attempt, elapsed=elapsed,
                status=response.status_code,
            )
            payload = _json_object(response, "image upload")
            image_id = payload.get("image_id")
            if not isinstance(image_id, str) or not image_id:
                raise SearchResponseInvalid(
                    "SerpApi image upload returned no image_id"
                )
            return image_id
        except requests.RequestException as exc:
            elapsed = time.monotonic() - t0
            wrapped = SearchProviderUnavailable(
                "SerpApi image upload request failed"
            )
            wrapped.__cause__ = exc
            _log_attempt(
                "image_upload", attempt=attempt, elapsed=elapsed,
                error_category="network_error",
            )
            last_exc = wrapped
            if attempt < MAX_RETRIES:
                continue
            raise last_exc from exc
        except ReverseSearchError as exc:
            if _is_transient(exc) and attempt < MAX_RETRIES:
                last_exc = exc
                continue
            raise

    # Unreachable, but keeps the type checker happy.
    assert last_exc is not None  # pragma: no cover
    raise last_exc  # pragma: no cover


def _lens_search(key: str, image_id: str) -> list[RawResult]:
    """Run the Google Lens visual-match query."""
    last_exc: Exception | None = None
    for attempt in range(1 + MAX_RETRIES):
        if attempt > 0:
            time.sleep(RETRY_BASE_SECONDS * (2 ** (attempt - 1)))
        t0 = time.monotonic()
        try:
            response = requests.get(
                SERPAPI_SEARCH_ENDPOINT,
                params={
                    "api_key": key,
                    "engine": "google_lens",
                    "image_id": image_id,
                    "type": "visual_matches",
                },
                timeout=REQUEST_TIMEOUT,
            )
            elapsed = time.monotonic() - t0
            _log_attempt(
                "google_lens", attempt=attempt, elapsed=elapsed,
                status=response.status_code,
            )
        except requests.RequestException as exc:
            elapsed = time.monotonic() - t0
            wrapped = SearchProviderUnavailable(
                "SerpApi Google Lens request failed"
            )
            wrapped.__cause__ = exc
            _log_attempt(
                "google_lens", attempt=attempt, elapsed=elapsed,
                error_category="network_error",
            )
            last_exc = wrapped
            if attempt < MAX_RETRIES:
                continue
            raise last_exc from exc

        try:
            search_payload = _json_object(
                response,
                "Google Lens",
                allow_no_results=True,
            )
        except ReverseSearchError as exc:
            if _is_transient(exc) and attempt < MAX_RETRIES:
                last_exc = exc
                continue
            raise

        if _is_no_results_error(search_payload.get("error")):
            logger.info("Search provider returned no visual matches")
            return []

        matches = search_payload.get("visual_matches", [])
        if not isinstance(matches, list):
            raise SearchResponseInvalid("SerpApi visual_matches must be a list")

        results: list[RawResult] = []
        for match in matches:
            if not isinstance(match, dict):
                continue
            url = match.get("link")
            if not isinstance(url, str) or not url:
                continue
            results.append(
                RawResult(
                    url=url,
                    title=_string_value(match.get("title")),
                    thumbnail_url=_string_value(match.get("thumbnail")),
                    source=_string_value(match.get("source")),
                )
            )
        return results

    assert last_exc is not None  # pragma: no cover
    raise last_exc  # pragma: no cover


def _string_value(value: object) -> str:
    return value if isinstance(value, str) else ""
