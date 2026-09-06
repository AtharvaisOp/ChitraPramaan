"""Build the canonical data structures that make up a claim."""

from __future__ import annotations

import json


def _clean_string(value: str, *, lowercase: bool = False) -> str:
    """Remove insignificant surrounding whitespace from a string value."""

    cleaned = value.strip()
    return cleaned.lower() if lowercase else cleaned


def build_claim(
    platform: str,
    post_url: str,
    crop_sha256: str,
    embedding_sha256: str,
    detector_model_version: str,
    title_snippet: str,
    thumbnail_url: str,
    match_confidence: float,
    selection_method: str,
    queried_at: str,
    oracle_response_sha256: str,
) -> dict:
    """Build a claim whose stable identity is isolated from mutable metadata.

    The ``fingerprint_body`` contains only values that bind the claim to its
    source post and detected face. The ``envelope`` contains descriptive and
    query-time metadata and must never affect the claim fingerprint.
    """

    normalized_selection_method = _clean_string(selection_method, lowercase=True)
    if normalized_selection_method not in {"auto", "human"}:
        raise ValueError("selection_method must be 'auto' or 'human'")

    return {
        "fingerprint_body": {
            "platform": _clean_string(platform, lowercase=True),
            "normalized_post_url": _clean_string(post_url),
            "crop_sha256": _clean_string(crop_sha256, lowercase=True),
            "embedding_sha256": _clean_string(embedding_sha256, lowercase=True),
            "detector_model_version": _clean_string(detector_model_version),
        },
        "envelope": {
            "title_snippet": _clean_string(title_snippet),
            "thumbnail_url": _clean_string(thumbnail_url),
            "match_confidence": match_confidence,
            "selection_method": normalized_selection_method,
            "queried_at": _clean_string(queried_at),
            "oracle_response_sha256": _clean_string(
                oracle_response_sha256, lowercase=True
            ),
        },
    }


def canonical_json(d: dict) -> str:
    """Serialize a dictionary deterministically for hashing."""

    return json.dumps(d, sort_keys=True, separators=(",", ":"))
