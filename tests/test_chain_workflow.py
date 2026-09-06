from provenance_pipeline.records.canonical import build_claim
from provenance_pipeline.records.fingerprint import compute_fingerprint
from tests.test_canonical import BASE_VALUES


def test_pin_and_anchor_flows_claim_cid_and_fingerprint(monkeypatch) -> None:
    claim = build_claim(**BASE_VALUES)
    receipt = {"status": 1, "transactionHash": b"fixture"}
    observed: dict[str, object] = {}

    def fake_pin_json(data: dict) -> str:
        observed["pinned"] = data
        return "bafyworkflowcid"

    def fake_anchor_claim(fingerprint_hex: str, cid: str):
        observed["fingerprint"] = fingerprint_hex
        observed["cid"] = cid
        return receipt

    monkeypatch.setattr(
        "provenance_pipeline.chain.workflow.pin_json", fake_pin_json
    )
    monkeypatch.setattr(
        "provenance_pipeline.chain.workflow.anchor_claim", fake_anchor_claim
    )

    from provenance_pipeline.chain.workflow import pin_and_anchor_claim

    result = pin_and_anchor_claim(claim)

    assert result is receipt
    assert observed["pinned"] is claim
    assert observed["cid"] == "bafyworkflowcid"
    assert observed["fingerprint"] == compute_fingerprint(
        claim["fingerprint_body"]
    )
