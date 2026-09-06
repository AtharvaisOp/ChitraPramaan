"""Normalize result URLs and enforce an explicit social-domain allowlist."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from provenance_pipeline.public_http import public_request

from .reverse_search import RawResult


logger = logging.getLogger(__name__)

# This is deliberately explicit. Add a domain only after reviewing it; do not
# replace this list with keyword, fuzzy, or provider-source matching.
ALLOWED_SOCIAL_DOMAINS = frozenset(
    {
        "x.com",
        "twitter.com",
        "instagram.com",
        "facebook.com",
        "linkedin.com",
        "reddit.com",
        "tiktok.com",
    }
)

TRACKING_QUERY_PARAMS = frozenset(
    {
        "_hsenc",
        "_hsmi",
        "dclid",
        "fbclid",
        "gclid",
        "igshid",
        "li_fat_id",
        "mc_cid",
        "mc_eid",
        "mkt_tok",
        "msclkid",
        "ref",
        "ref_src",
        "ttclid",
        "twclid",
    }
)
REDIRECT_TIMEOUT = (3, 5)
MAX_REDIRECT_WORKERS = 6


def _without_tracking(url: str) -> str:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("URL must be an absolute HTTP(S) URL")

    hostname = parts.hostname.lower().rstrip(".")
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("URL contains an invalid port") from exc

    if port is None or (scheme == "http" and port == 80) or (
        scheme == "https" and port == 443
    ):
        netloc = hostname
    else:
        netloc = f"{hostname}:{port}"

    clean_query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered_key = key.lower()
        if lowered_key.startswith("utm_") or lowered_key in TRACKING_QUERY_PARAMS:
            continue
        clean_query.append((key, value))

    return urlunsplit(
        (scheme, netloc, parts.path, urlencode(clean_query, doseq=True), "")
    )


def normalize_url(url: str) -> str:
    """Resolve redirects with HEAD, then remove tracking parameters/fragments."""

    if not isinstance(url, str):
        raise TypeError("url must be a string")

    initial_url = _without_tracking(url)
    try:
        resolved_url = public_request(
            initial_url,
            method="HEAD",
            timeout=REDIRECT_TIMEOUT,
        )
    except requests.RequestException:
        logger.warning("Could not resolve source redirects; retaining normalized input")
        resolved_url = initial_url

    return _without_tracking(resolved_url)


def _is_allowed_domain(url: str) -> bool:
    hostname = urlsplit(url).hostname
    if hostname is None:
        return False
    hostname = hostname.lower().rstrip(".")
    return any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in ALLOWED_SOCIAL_DOMAINS
    )


def filter_to_social(results: list[RawResult]) -> list[RawResult]:
    """Return allowlisted results with normalized URLs in provider order."""

    if not results:
        return []

    # Redirect checks are network-bound and independent. executor.map keeps
    # provider order while bounding concurrent SSRF-validated requests.
    worker_count = min(MAX_REDIRECT_WORKERS, len(results))
    with ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="source-redirect",
    ) as executor:
        normalized_results = executor.map(_normalize_result, results)

    filtered: list[RawResult] = []
    for normalized in normalized_results:
        if normalized is not None and _is_allowed_domain(normalized.url):
            filtered.append(normalized)
    return filtered


def _normalize_result(result: RawResult) -> RawResult | None:
    try:
        normalized_url = normalize_url(result.url)
    except (TypeError, ValueError):
        logger.warning("Skipping invalid result URL")
        return None
    return replace(result, url=normalized_url)
