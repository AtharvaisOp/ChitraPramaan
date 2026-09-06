"""Compute fingerprints for the stable body of a claim."""

from __future__ import annotations

import hashlib

from .canonical import canonical_json


def compute_fingerprint(fingerprint_body: dict) -> str:
    """Return the SHA-256 hex digest of a canonical fingerprint body."""

    canonical_body = canonical_json(fingerprint_body)
    return hashlib.sha256(canonical_body.encode("utf-8")).hexdigest()
