"""Standalone Phase 6 pin-then-anchor composition."""

from __future__ import annotations

from web3.types import TxReceipt

from provenance_pipeline.records.fingerprint import compute_fingerprint
from .client import anchor_claim
from .ipfs import pin_json


def pin_and_anchor_claim(claim: dict) -> TxReceipt:
    """Pin a complete claim, fingerprint its stable body, and anchor its CID."""

    if not isinstance(claim, dict):
        raise TypeError("claim must be a dictionary")
    try:
        fingerprint_body = claim["fingerprint_body"]
        envelope = claim["envelope"]
    except KeyError as exc:
        raise ValueError("claim must contain fingerprint_body and envelope") from exc
    if not isinstance(fingerprint_body, dict) or not isinstance(envelope, dict):
        raise TypeError("claim sections must be dictionaries")

    fingerprint = compute_fingerprint(fingerprint_body)
    cid = pin_json(claim)
    return anchor_claim(fingerprint, cid)
