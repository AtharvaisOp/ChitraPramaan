import pytest

from provenance_pipeline.chain.ipfs import (
    IPFSPinningError,
    PINATA_JSON_ENDPOINT,
    pin_json,
)
from tests.test_canonical import BASE_VALUES
from provenance_pipeline.records.canonical import build_claim


def test_pin_json_sends_complete_claim_to_pinata(monkeypatch) -> None:
    claim = build_claim(**BASE_VALUES)
    observed: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"IpfsHash": "bafyfixturecid"}

    def fake_post(url: str, **kwargs):
        observed["url"] = url
        observed.update(kwargs)
        return FakeResponse()

    monkeypatch.setenv("PINATA_JWT", "fixture-jwt")
    monkeypatch.setattr("provenance_pipeline.chain.ipfs.requests.post", fake_post)

    cid = pin_json(claim)

    assert cid == "bafyfixturecid"
    assert observed["url"] == PINATA_JSON_ENDPOINT
    assert observed["headers"]["Authorization"] == "Bearer fixture-jwt"
    assert observed["json"] == {
        "pinataContent": claim,
        "pinataMetadata": {"name": "claim.json"},
        "pinataOptions": {"cidVersion": 1},
    }


def test_pin_json_rejects_non_claim_payload(monkeypatch) -> None:
    monkeypatch.setenv("PINATA_JWT", "fixture-jwt")

    with pytest.raises(ValueError, match="exactly"):
        pin_json({"fingerprint_body": {}})
