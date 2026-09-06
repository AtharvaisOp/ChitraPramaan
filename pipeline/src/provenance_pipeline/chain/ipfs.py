"""Pin complete claim JSON to public IPFS through Pinata."""

from __future__ import annotations

import os
import re
from typing import Any

import requests


PINATA_JSON_ENDPOINT = "https://api.pinata.cloud/pinning/pinJSONToIPFS"
PIN_TIMEOUT = (10, 60)
CID_PATTERN = re.compile(r"[A-Za-z0-9]{10,200}\Z")


class IPFSPinningError(RuntimeError):
    """Raised when claim validation or remote pinning fails."""


def _pinata_jwt() -> str:
    token = os.getenv("PINATA_JWT") or os.getenv("IPFS_API_KEY")
    if not token:
        raise IPFSPinningError(
            "Set PINATA_JWT (or IPFS_API_KEY) before pinning claim JSON"
        )
    return token


def _validate_claim(data: dict) -> None:
    if set(data) != {"fingerprint_body", "envelope"}:
        raise ValueError(
            "claim must contain exactly fingerprint_body and envelope"
        )
    if not isinstance(data["fingerprint_body"], dict):
        raise TypeError("claim fingerprint_body must be a dictionary")
    if not isinstance(data["envelope"], dict):
        raise TypeError("claim envelope must be a dictionary")


def pin_json(data: dict) -> str:
    """Pin a full ``{fingerprint_body, envelope}`` claim and return its CID."""

    if not isinstance(data, dict):
        raise TypeError("data must be a claim dictionary")
    _validate_claim(data)

    payload = {
        "pinataContent": data,
        "pinataMetadata": {"name": "claim.json"},
        "pinataOptions": {"cidVersion": 1},
    }
    try:
        response = requests.post(
            PINATA_JSON_ENDPOINT,
            headers={
                "Authorization": f"Bearer {_pinata_jwt()}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=PIN_TIMEOUT,
        )
        response.raise_for_status()
        result: Any = response.json()
    except requests.RequestException as exc:
        raise IPFSPinningError("Pinata claim pin failed") from exc
    except ValueError as exc:
        raise IPFSPinningError("Pinata returned invalid JSON") from exc

    if not isinstance(result, dict):
        raise IPFSPinningError("Pinata returned an invalid payload")
    cid = result.get("IpfsHash")
    if not isinstance(cid, str) or CID_PATTERN.fullmatch(cid.strip()) is None:
        raise IPFSPinningError("Pinata returned an invalid IPFS CID")
    return cid.strip()
