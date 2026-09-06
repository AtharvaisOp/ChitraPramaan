import os
from pathlib import Path
import secrets

import pytest

from provenance_pipeline.chain.client import verify_claim
from provenance_pipeline.chain.workflow import pin_and_anchor_claim
from provenance_pipeline.records.canonical import build_claim
from provenance_pipeline.records.fingerprint import compute_fingerprint


@pytest.mark.integration
def test_live_pin_and_sepolia_anchor() -> None:
    """Opt-in test that creates a real Pinata pin and spends Sepolia gas."""

    if os.getenv("RUN_PIN_ANCHOR_INTEGRATION") != "1":
        pytest.skip("set RUN_PIN_ANCHOR_INTEGRATION=1 to permit external writes")
    required = ["RPC_URL", "PRIVATE_KEY"]
    if not (os.getenv("PINATA_JWT") or os.getenv("IPFS_API_KEY")):
        required.append("PINATA_JWT")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        pytest.skip(f"missing integration configuration: {', '.join(missing)}")
    saved_address = (
        Path(__file__).resolve().parents[1]
        / "contracts"
        / "deployed_address.txt"
    )
    if not os.getenv("CONTRACT_ADDRESS") and not saved_address.is_file():
        pytest.skip("set CONTRACT_ADDRESS or deploy Registry before pinning")

    nonce = secrets.token_hex(32)
    claim = build_claim(
        platform="instagram",
        post_url=f"https://instagram.com/p/integration-{nonce[:8]}",
        crop_sha256=nonce,
        embedding_sha256=secrets.token_hex(32),
        detector_model_version="buffalo_l-integration",
        title_snippet="Phase 6 integration fixture",
        thumbnail_url="https://example.test/integration.jpg",
        match_confidence=1.0,
        selection_method="human",
        queried_at="2026-09-05T00:00:00Z",
        oracle_response_sha256=secrets.token_hex(32),
    )
    fingerprint = compute_fingerprint(claim["fingerprint_body"])

    receipt = pin_and_anchor_claim(claim)
    record = verify_claim(fingerprint)

    assert receipt["status"] == 1
    assert record["exists"] is True
    assert record["uri"].startswith(("bafy", "bafk", "Qm"))
