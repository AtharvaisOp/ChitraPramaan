"""Shared validation for IPFS content identifiers used by the pipeline."""

from __future__ import annotations

import re


CIDV0_PATTERN = re.compile(r"Qm[1-9A-HJ-NP-Za-km-z]{44}\Z")
CIDV1_BASE32_PATTERN = re.compile(r"b[a-z2-7]{9,199}\Z")


def normalize_ipfs_cid(value: str) -> str:
    """Return a supported CIDv0 or base32 CIDv1 without surrounding whitespace."""

    if not isinstance(value, str):
        raise TypeError("IPFS CID must be a string")
    cid = value.strip()
    if not (
        CIDV0_PATTERN.fullmatch(cid) or CIDV1_BASE32_PATTERN.fullmatch(cid)
    ):
        raise ValueError("IPFS CID must be CIDv0 or base32 CIDv1")
    return cid
