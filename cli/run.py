"""Command-line orchestration for the photo provenance pipeline."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys
from typing import Sequence

# Permit direct execution from a source checkout while keeping the package
# independently installable via ``pip install -e ./pipeline``.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_SOURCE = PROJECT_ROOT / "pipeline" / "src"
if str(PIPELINE_SOURCE) not in sys.path:
    sys.path.insert(0, str(PIPELINE_SOURCE))

from provenance_pipeline.chain.client import anchor_claim, transaction_hash_hex
from provenance_pipeline.chain.ipfs import pin_json
from provenance_pipeline.claim_builder import (
    build_match_claim,
    embedding_sha256,
    oracle_response_sha256,
)
from provenance_pipeline.face.detector import (
    FaceDetection,
    crop_face,
    detect_faces,
    select_subject,
    sha256_bytes,
)
from provenance_pipeline.images import decode_image_bytes
from provenance_pipeline.records.fingerprint import compute_fingerprint
from provenance_pipeline.search.domain_filter import filter_to_social
from provenance_pipeline.search.rerank import (
    DEFAULT_AUTO_THRESHOLD,
    HumanSelectionRequired,
    RankedResult,
    rerank,
    select_match,
)
from provenance_pipeline.search.reverse_search import reverse_image_search


NETWORKS = {
    "sepolia": {
        "explorer_transaction_url": "https://sepolia.etherscan.io/tx/{tx_hash}",
    }
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search for a consented face and anchor a provenance claim."
    )
    parser.add_argument("--photo", required=True, type=Path, help="input photo path")
    parser.add_argument(
        "--auto-threshold",
        type=float,
        default=DEFAULT_AUTO_THRESHOLD,
        help=f"automatic match threshold (default: {DEFAULT_AUTO_THRESHOLD})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="build and save the claim without pinning or spending testnet gas",
    )
    parser.add_argument(
        "--network",
        choices=sorted(NETWORKS),
        default="sepolia",
        help="deployed contract network (default: sepolia)",
    )
    return parser


def _confirm_consent() -> bool:
    response = input(
        "This will search the web for the person in this photo. "
        "Confirm you have the right to do this for this photo [y/N]: "
    )
    return response.strip().lower() in {"y", "yes"}


def _choose_subject(faces: list[FaceDetection]) -> FaceDetection:
    """Collect an optional face choice while keeping UI out of the pipeline."""

    if len(faces) <= 1:
        return select_subject(faces)

    print("Multiple faces detected. Choose the subject:")
    for index, face in enumerate(faces, start=1):
        print(f"  {index}. bbox={face.bbox}, det_score={face.det_score:.4f}")
    try:
        response = input("Face number (Enter for automatic selection): ").strip()
    except EOFError:
        response = ""

    if response:
        try:
            selected_index = int(response) - 1
            return select_subject(faces, selected_index=selected_index)
        except (TypeError, ValueError):
            logging.getLogger(__name__).warning(
                "Invalid face selection %r; falling back to method=auto", response
            )
    return select_subject(faces)


def _choose_match(
    ranked: list[RankedResult], auto_threshold: float
) -> tuple[RankedResult, str]:
    """Collect a human result index only when the pure selector requires it."""

    try:
        return select_match(ranked, auto_threshold=auto_threshold)
    except HumanSelectionRequired:
        top_result = ranked[0]

    print(
        f"Top similarity {top_result.score:.4f} is below the automatic "
        f"threshold {auto_threshold:.4f}. Choose a match:"
    )
    for index, result in enumerate(ranked, start=1):
        title = result.candidate.title or "Untitled result"
        print(
            f"  {index}. score={result.score:.4f} | "
            f"{title} | {result.candidate.url}"
        )
    try:
        response = input("Result number: ").strip()
    except EOFError as exc:
        raise ValueError("human selection is required below the auto threshold") from exc
    try:
        selected_index = int(response) - 1
    except ValueError as exc:
        raise ValueError("human selection must be a result number") from exc
    return select_match(
        ranked,
        auto_threshold=auto_threshold,
        human_index=selected_index,
    )


def _write_claim(photo_path: Path, claim: dict) -> Path:
    output_path = photo_path.with_suffix(".claim.json")
    output_path.write_text(
        json.dumps(claim, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    photo_path = args.photo.expanduser().resolve()
    if not photo_path.is_file():
        raise FileNotFoundError(f"photo does not exist: {photo_path}")

    uploaded_bytes = photo_path.read_bytes()
    image_sha256 = sha256_bytes(uploaded_bytes)
    if not _confirm_consent():
        print("Aborted: consent was not confirmed. No search was performed.")
        return 2

    image = decode_image_bytes(uploaded_bytes)
    faces = detect_faces(image)
    subject = _choose_subject(faces)
    crop_bytes = crop_face(image, subject.bbox)
    crop_sha256 = sha256_bytes(crop_bytes)
    embedding_digest = embedding_sha256(subject.embedding)

    queried_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    raw_results = reverse_image_search(crop_bytes)
    oracle_response_digest = oracle_response_sha256(raw_results)
    if not raw_results:
        print(
            "No matching images were found for this photo. Try another photo.",
            file=sys.stderr,
        )
        return 1

    candidates = filter_to_social(raw_results)
    if not candidates:
        print(
            "No supported source results were found. Try another photo.",
            file=sys.stderr,
        )
        return 1

    ranked_results = rerank(candidates, subject.embedding)
    if not ranked_results:
        print(
            "No candidate thumbnails had a usable face. Try another photo.",
            file=sys.stderr,
        )
        return 1

    selected, selection_method = _choose_match(ranked_results, args.auto_threshold)

    candidate = selected.candidate
    claim = build_match_claim(
        candidate=candidate,
        score=selected.score,
        selection_method=selection_method,
        crop_sha256=crop_sha256,
        embedding_digest=embedding_digest,
        image_sha256=image_sha256,
        queried_at=queried_at,
        oracle_response_digest=oracle_response_digest,
    )
    fingerprint = compute_fingerprint(claim["fingerprint_body"])
    claim_path = _write_claim(photo_path, claim)

    cid: str | None = None
    transaction_hash: str | None = None
    explorer_url: str | None = None
    if not args.dry_run:
        cid = pin_json(claim)
        receipt = anchor_claim(fingerprint, cid)
        transaction_hash = transaction_hash_hex(receipt)
        explorer_url = NETWORKS[args.network]["explorer_transaction_url"].format(
            tx_hash=transaction_hash
        )

    print("\nClaim summary")
    print(f"Claim file: {claim_path}")
    print(f"Fingerprint: {fingerprint}")
    print(f"Selection: {selection_method} (score={selected.score:.6f})")
    print(f"Network: {args.network}")
    print(f"IPFS CID: {cid or 'not pinned (--dry-run)'}")
    print(f"Transaction hash: {transaction_hash or 'not sent (--dry-run)'}")
    print(f"Explorer: {explorer_url or 'not available (--dry-run)'}")
    if args.dry_run:
        print(f"Would anchor fingerprint {fingerprint} after pinning {claim_path.name}.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
