"""Shared claim inputs and construction used by every interface."""

from __future__ import annotations

from dataclasses import asdict
from urllib.parse import urlsplit

import numpy as np

from provenance_pipeline.face.detector import DETECTOR_MODEL_VERSION, sha256_bytes
from provenance_pipeline.records.canonical import build_claim, canonical_json
from provenance_pipeline.search.reverse_search import RawResult


PLATFORM_DOMAINS = {
    "x.com": "x",
    "twitter.com": "x",
    "instagram.com": "instagram",
    "facebook.com": "facebook",
    "linkedin.com": "linkedin",
    "reddit.com": "reddit",
    "tiktok.com": "tiktok",
}


def embedding_sha256(embedding: np.ndarray) -> str:
    """Hash an embedding's stable little-endian float32 representation."""

    stable_embedding = np.asarray(embedding, dtype="<f4").reshape(-1)
    return sha256_bytes(stable_embedding.tobytes(order="C"))


def oracle_response_sha256(results: list[RawResult]) -> str:
    """Hash the provider response fields retained by the pipeline."""

    serializable = {"results": [asdict(result) for result in results]}
    return sha256_bytes(canonical_json(serializable).encode("utf-8"))


def platform_from_url(url: str) -> str:
    """Map an allowlisted social URL to its canonical platform name."""

    hostname = (urlsplit(url).hostname or "").lower().rstrip(".")
    for domain, platform in PLATFORM_DOMAINS.items():
        if hostname == domain or hostname.endswith(f".{domain}"):
            return platform
    raise ValueError(f"selected result is not on a supported platform: {url}")


def build_match_claim(
    *,
    candidate: RawResult,
    score: float,
    selection_method: str,
    crop_sha256: str,
    embedding_digest: str,
    image_sha256: str,
    queried_at: str,
    oracle_response_digest: str,
    detector_model_version: str = DETECTOR_MODEL_VERSION,
) -> dict:
    """Build the complete persisted claim for one selected ranked result."""

    claim = build_claim(
        platform=platform_from_url(candidate.url),
        post_url=candidate.url,
        crop_sha256=crop_sha256,
        embedding_sha256=embedding_digest,
        detector_model_version=detector_model_version,
        title_snippet=candidate.title,
        thumbnail_url=candidate.thumbnail_url,
        match_confidence=score,
        selection_method=selection_method,
        queried_at=queried_at,
        oracle_response_sha256=oracle_response_digest,
    )
    # This audit value intentionally stays outside fingerprint_body.
    claim["envelope"]["image_sha256"] = image_sha256
    return claim
