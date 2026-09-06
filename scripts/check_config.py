"""Validate production configuration formats without printing secret values."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

from provenance_pipeline.verification import resolve_ipfs_gateways


HEX_32 = re.compile(r"(?:0x)?[0-9a-fA-F]{64}\Z")
ADDRESS = re.compile(r"(?:0x)?[0-9a-fA-F]{40}\Z")


def _origin_valid(value: str) -> bool:
    parsed = urlsplit(value)
    host = (parsed.hostname or "").casefold()
    return bool(
        parsed.scheme in {"https", "http"}
        and host
        and not parsed.username
        and not parsed.password
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
        and (parsed.scheme == "https" or host in {"localhost", "127.0.0.1", "::1"})
    )


def main() -> int:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    problems: list[str] = []
    if not (os.getenv("SERPAPI_KEY") or os.getenv("SEARCH_API_KEY")):
        problems.append("SERPAPI_KEY (or SEARCH_API_KEY) is missing")
    if not (os.getenv("PINATA_JWT") or os.getenv("IPFS_API_KEY")):
        problems.append("PINATA_JWT (or IPFS_API_KEY) is missing")
    if not os.getenv("RPC_URL"):
        problems.append("RPC_URL is missing")
    elif not urlsplit(os.environ["RPC_URL"]).scheme in {"https", "http"}:
        problems.append("RPC_URL must be an HTTP(S) URL")
    if not HEX_32.fullmatch((os.getenv("PRIVATE_KEY") or "").strip()):
        problems.append("PRIVATE_KEY must be 32 bytes of hexadecimal")
    if not ADDRESS.fullmatch((os.getenv("CONTRACT_ADDRESS") or "").strip()):
        problems.append("CONTRACT_ADDRESS must be a 20-byte hexadecimal address")
    origins = [item.strip() for item in (os.getenv("FRONTEND_ORIGIN") or "").split(",") if item.strip()]
    if not origins or any(item == "*" or not _origin_valid(item) for item in origins):
        problems.append("FRONTEND_ORIGIN must contain exact HTTPS origins (or local HTTP origins)")
    try:
        resolve_ipfs_gateways()
    except Exception:
        problems.append("IPFS gateway configuration is invalid")
    if problems:
        for problem in problems:
            print(f"configuration error: {problem}")
        return 1
    print("Configuration format checks passed (no secret values printed).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

