from copy import deepcopy
import json
from types import SimpleNamespace

from provenance_pipeline.records.canonical import build_claim
from provenance_pipeline.records.fingerprint import compute_fingerprint
from tests.test_canonical import BASE_VALUES


CONTRACT_ADDRESS = "0x1111111111111111111111111111111111111111"
CID = "bafyfixtureclaim"


def test_full_independent_reverification_passes(
    tmp_path, monkeypatch, capsys
) -> None:
    from scripts import reverify
    from provenance_pipeline.verification import resolve_ipfs_gateways

    claim = build_claim(**BASE_VALUES)
    claim_path = tmp_path / "claim.json"
    claim_path.write_text(json.dumps(claim), encoding="utf-8")
    expected_fingerprint = compute_fingerprint(claim["fingerprint_body"])
    observed: dict[str, str] = {}

    def fake_verify(fingerprint: str) -> dict:
        observed["fingerprint"] = fingerprint
        observed["contract"] = reverify.os.environ["CONTRACT_ADDRESS"]
        return {
            "exists": True,
            "submitter": "0x2222222222222222222222222222222222222222",
            "timestamp": 1_788_000_000,
            "uri": CID,
        }

    def fake_fetch(uri: str, gateway_url: str | None, fallback_url: str | None):
        preferred = resolve_ipfs_gateways(gateway_url, fallback_url)[0]
        observed["gateway_url"] = f"{preferred}/{uri}"
        return claim

    monkeypatch.setattr(reverify, "verify_claim", fake_verify)
    monkeypatch.setattr(reverify, "fetch_ipfs_json", fake_fetch)

    exit_code = reverify.main(
        ["--claim", str(claim_path), "--contract", CONTRACT_ADDRESS]
    )

    assert exit_code == 0
    assert observed == {
        "fingerprint": expected_fingerprint,
        "contract": CONTRACT_ADDRESS,
        "gateway_url": f"https://ipfs.io/ipfs/{CID}",
    }
    output = capsys.readouterr().out
    assert "Local vs on-chain:      MATCH" in output
    assert "IPFS vs on-chain:       MATCH" in output
    assert "Local vs IPFS:           MATCH" in output
    assert "PASS: local, on-chain lookup, and IPFS fingerprints all match." in output


def test_corrupt_ipfs_fingerprint_fails_clearly(
    tmp_path, monkeypatch, capsys
) -> None:
    from scripts import reverify

    local_claim = build_claim(**BASE_VALUES)
    corrupted_ipfs_claim = deepcopy(local_claim)
    corrupted_ipfs_claim["fingerprint_body"]["crop_sha256"] = "f" * 64
    claim_path = tmp_path / "claim.json"
    claim_path.write_text(json.dumps(local_claim), encoding="utf-8")

    monkeypatch.setattr(
        reverify,
        "verify_claim",
        lambda _fingerprint: {
            "exists": True,
            "submitter": "0x2222222222222222222222222222222222222222",
            "timestamp": 1_788_000_000,
            "uri": f"ipfs://{CID}",
        },
    )
    monkeypatch.setattr(
        reverify,
        "fetch_ipfs_json",
        lambda *_args, **_kwargs: corrupted_ipfs_claim,
    )

    exit_code = reverify.main(
        ["--claim", str(claim_path), "--contract", CONTRACT_ADDRESS]
    )

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "IPFS vs on-chain:       MISMATCH" in output
    assert "Local vs IPFS:           MISMATCH" in output
    assert "FAIL: the three fingerprint checks do not all match." in output


def test_corrupt_local_fingerprint_reports_missing_chain_record(
    tmp_path, monkeypatch, capsys
) -> None:
    from scripts import reverify

    claim = build_claim(**BASE_VALUES)
    claim["fingerprint_body"]["embedding_sha256"] = "0" * 64
    claim_path = tmp_path / "corrupt-local.json"
    claim_path.write_text(json.dumps(claim), encoding="utf-8")
    monkeypatch.setattr(
        reverify,
        "verify_claim",
        lambda _fingerprint: {
            "exists": False,
            "submitter": "0x0000000000000000000000000000000000000000",
            "timestamp": 0,
            "uri": "",
        },
    )
    monkeypatch.setattr(
        reverify,
        "fetch_ipfs_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("IPFS must not be fetched for an unanchored key")
        ),
    )

    exit_code = reverify.main(
        ["--claim", str(claim_path), "--contract", CONTRACT_ADDRESS]
    )

    assert exit_code == 1
    assert "FAIL: no on-chain record exists for local fingerprint" in (
        capsys.readouterr().out
    )
