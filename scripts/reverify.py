"""Independently re-verify a saved claim against Registry and public IPFS.

This read-only script needs no search, face-model, wallet, or pinning API key.
From the project root, run:

    python scripts/reverify.py --claim path/to/claim.json --contract 0x...

``RPC_URL``, ``IPFS_GATEWAY_URL``, and ``IPFS_FALLBACK_GATEWAY_URL`` may be set
to override the public defaults, but none is required.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from typing import Sequence


# Direct execution sets sys.path[0] to /scripts. Add the project root so this
# standalone command can import only the two small verification dependencies.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_SOURCE = PROJECT_ROOT / "pipeline" / "src"
if str(PIPELINE_SOURCE) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SOURCE))

from provenance_pipeline.chain.client import (  # noqa: E402
    ChainClientError,
    DEFAULT_SEPOLIA_RPC_URL,
    verify_claim,
)
from provenance_pipeline.records.fingerprint import compute_fingerprint  # noqa: E402
from provenance_pipeline.verification import (  # noqa: E402
    VerificationError,
    fetch_ipfs_json,
    validated_claim_fingerprint_body,
)


class ReverificationError(RuntimeError):
    """Raised when independent verification cannot be completed."""


@dataclass(frozen=True, slots=True)
class VerificationReport:
    local_fingerprint: str
    onchain_lookup_key: str
    ipfs_fingerprint: str
    submitter: str
    timestamp: int
    uri: str

    @property
    def local_matches_onchain(self) -> bool:
        return self.local_fingerprint == self.onchain_lookup_key

    @property
    def ipfs_matches_onchain(self) -> bool:
        return self.ipfs_fingerprint == self.onchain_lookup_key

    @property
    def local_matches_ipfs(self) -> bool:
        return self.local_fingerprint == self.ipfs_fingerprint

    @property
    def passed(self) -> bool:
        return (
            self.local_matches_onchain
            and self.ipfs_matches_onchain
            and self.local_matches_ipfs
        )


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReverificationError(f"claim file does not exist: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ReverificationError(f"claim file is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ReverificationError("claim JSON must be an object")
    return value


def _fingerprint_body(document: dict, source: str) -> dict:
    body = document.get("fingerprint_body", document)
    if not isinstance(body, dict):
        raise ReverificationError(f"{source} fingerprint_body must be an object")
    return body


def _verify_record(
    fingerprint: str, contract_address: str, rpc_url: str | None
) -> dict:
    previous_address = os.environ.get("CONTRACT_ADDRESS")
    previous_rpc = os.environ.get("RPC_URL")
    os.environ["CONTRACT_ADDRESS"] = contract_address
    if rpc_url:
        os.environ["RPC_URL"] = rpc_url
    elif previous_rpc is None:
        os.environ["RPC_URL"] = DEFAULT_SEPOLIA_RPC_URL

    try:
        try:
            return verify_claim(fingerprint)
        except ChainClientError as exc:
            raise ReverificationError(
                f"on-chain verification failed: {exc}"
            ) from exc
    finally:
        if previous_address is None:
            os.environ.pop("CONTRACT_ADDRESS", None)
        else:
            os.environ["CONTRACT_ADDRESS"] = previous_address
        if previous_rpc is None:
            os.environ.pop("RPC_URL", None)
        else:
            os.environ["RPC_URL"] = previous_rpc


def reverify(
    claim_path: Path,
    contract_address: str,
    *,
    rpc_url: str | None = None,
    gateway_url: str | None = None,
    fallback_gateway_url: str | None = None,
) -> VerificationReport:
    """Perform all local, on-chain, and IPFS fingerprint checks."""

    local_document = _load_json(claim_path)
    local_fingerprint = compute_fingerprint(
        _fingerprint_body(local_document, "local claim")
    )

    record = _verify_record(local_fingerprint, contract_address, rpc_url)
    if not record.get("exists"):
        raise ReverificationError(
            "no on-chain record exists for local fingerprint " + local_fingerprint
        )
    uri = record.get("uri")
    if not isinstance(uri, str) or not uri.strip():
        raise ReverificationError("on-chain record contains no IPFS URI")

    try:
        ipfs_document = fetch_ipfs_json(
            uri,
            gateway_url,
            fallback_gateway_url,
        )
    except VerificationError as exc:
        raise ReverificationError(str(exc)) from exc
    try:
        ipfs_body = validated_claim_fingerprint_body(ipfs_document)
    except VerificationError as exc:
        raise ReverificationError(str(exc)) from exc
    ipfs_fingerprint = compute_fingerprint(ipfs_body)
    return VerificationReport(
        local_fingerprint=local_fingerprint,
        onchain_lookup_key=local_fingerprint,
        ipfs_fingerprint=ipfs_fingerprint,
        submitter=str(record.get("submitter", "")),
        timestamp=int(record.get("timestamp", 0)),
        uri=uri,
    )


def _status(matches: bool) -> str:
    return "MATCH" if matches else "MISMATCH"


def _print_report(report: VerificationReport) -> None:
    print(f"Local fingerprint:       {report.local_fingerprint}")
    print(f"On-chain lookup key:     {report.onchain_lookup_key}")
    print(f"Fetched IPFS fingerprint:{report.ipfs_fingerprint}")
    print(
        "Local vs on-chain:      "
        + _status(report.local_matches_onchain)
    )
    print(
        "IPFS vs on-chain:       "
        + _status(report.ipfs_matches_onchain)
    )
    print("Local vs IPFS:           " + _status(report.local_matches_ipfs))
    print(f"On-chain URI:            {report.uri}")
    print(f"Submitter:               {report.submitter}")
    print(f"Timestamp:               {report.timestamp}")
    if report.passed:
        print("PASS: local, on-chain lookup, and IPFS fingerprints all match.")
    else:
        print("FAIL: the three fingerprint checks do not all match.")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Independently verify a saved claim against Registry and IPFS."
    )
    parser.add_argument("--claim", required=True, type=Path)
    parser.add_argument("--contract", required=True)
    parser.add_argument(
        "--rpc-url",
        help="optional Sepolia RPC override (defaults to a no-key public RPC)",
    )
    parser.add_argument(
        "--gateway",
        help="preferred IPFS path gateway base (or IPFS_GATEWAY_URL)",
    )
    parser.add_argument(
        "--fallback-gateway",
        help=(
            "independent fallback path gateway base "
            "(or IPFS_FALLBACK_GATEWAY_URL)"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = reverify(
            args.claim.expanduser().resolve(),
            args.contract,
            rpc_url=args.rpc_url,
            gateway_url=args.gateway,
            fallback_gateway_url=args.fallback_gateway,
        )
    except (ReverificationError, ValueError, TypeError) as exc:
        print(f"FAIL: {exc}")
        return 1

    _print_report(report)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
