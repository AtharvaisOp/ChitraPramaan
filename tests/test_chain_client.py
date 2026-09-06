from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from provenance_pipeline.chain import client as chain_client
from provenance_pipeline.chain.client import (
    AlreadyAnchoredError,
    AnchorOutcomeUnknown,
    AnchorPreparationError,
    ChainClientError,
    InsufficientFundsError,
    PrivateKeyError,
    RPCConnectionError,
    WrongChainError,
    anchor_claim,
    transaction_hash_hex,
    verify_claim,
)


FINGERPRINT = "ab" * 32
CID = "bafyfixturecid"


def _mock_chain(monkeypatch):
    receipt = {"status": 1, "transactionHash": b"fixture-transaction"}
    account = SimpleNamespace(
        address="0x1111111111111111111111111111111111111111",
        sign_transaction=lambda transaction: SimpleNamespace(
            raw_transaction=b"signed-transaction"
        ),
    )
    web3 = MagicMock()
    web3.eth.account.from_key.return_value = account
    web3.eth.get_transaction_count.return_value = 7
    web3.eth.send_raw_transaction.return_value = b"transaction-hash"
    web3.eth.wait_for_transaction_receipt.return_value = receipt
    contract = MagicMock()
    contract.functions.verify.return_value.call.return_value = (
        False,
        "0x0000000000000000000000000000000000000000",
        0,
        "",
    )
    monkeypatch.setenv("PRIVATE_KEY", "fixture-private-key")
    monkeypatch.setattr(
        "provenance_pipeline.chain.client._web3_and_contract",
        lambda: (web3, contract),
    )
    return web3, contract, receipt


def test_anchor_claim_passes_fingerprint_and_cid_and_returns_receipt(
    monkeypatch,
) -> None:
    web3, contract, receipt = _mock_chain(monkeypatch)
    anchor_function = contract.functions.anchor.return_value
    anchor_function.build_transaction.return_value = {"fixture": "transaction"}

    result = anchor_claim(FINGERPRINT, CID)

    assert result is receipt
    contract.functions.anchor.assert_called_once_with(bytes.fromhex(FINGERPRINT), CID)
    anchor_function.build_transaction.assert_called_once_with(
        {
            "from": "0x1111111111111111111111111111111111111111",
            "nonce": 7,
            "chainId": 11_155_111,
        }
    )
    web3.eth.send_raw_transaction.assert_called_once_with(b"signed-transaction")


def test_verify_claim_returns_named_record_fields(monkeypatch) -> None:
    _, contract, _ = _mock_chain(monkeypatch)
    contract.functions.verify.return_value.call.return_value = (
        True,
        "0x2222222222222222222222222222222222222222",
        1_788_000_000,
        CID,
    )

    assert verify_claim(FINGERPRINT) == {
        "exists": True,
        "submitter": "0x2222222222222222222222222222222222222222",
        "timestamp": 1_788_000_000,
        "uri": CID,
    }


def test_verify_claim_classifies_malformed_record_as_chain_error(monkeypatch) -> None:
    _, contract, _ = _mock_chain(monkeypatch)
    contract.functions.verify.return_value.call.return_value = (
        True,
        "0x2222222222222222222222222222222222222222",
        "not-a-timestamp",
        CID,
    )

    with pytest.raises(ChainClientError, match="Registry verify call failed"):
        verify_claim(FINGERPRINT)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (bytes.fromhex("ab" * 32), "0x" + "ab" * 32),
        ("0x" + "AB" * 32, "0x" + "ab" * 32),
    ],
)
def test_transaction_hash_hex_normalizes_confirmed_hash(value, expected) -> None:
    assert transaction_hash_hex({"transactionHash": value}) == expected


@pytest.mark.parametrize(
    "receipt",
    [
        {},
        {"transactionHash": "not-a-hash"},
        {"transactionHash": b"too-short"},
        {"transactionHash": "0x" + "ab" * 31},
    ],
)
def test_transaction_hash_hex_rejects_malformed_hash(receipt) -> None:
    with pytest.raises(AnchorOutcomeUnknown, match="transaction hash is invalid"):
        transaction_hash_hex(receipt)


@pytest.mark.parametrize("operation", ["send_raw_transaction", "wait_for_transaction_receipt"])
def test_broadcast_or_receipt_error_is_an_unknown_outcome(monkeypatch, operation):
    web3, _, _ = _mock_chain(monkeypatch)
    getattr(web3.eth, operation).side_effect = TimeoutError("provider credential fixture")
    with pytest.raises(AnchorOutcomeUnknown) as error:
        anchor_claim(FINGERPRINT, CID)
    assert "credential" not in str(error.value)


def test_insufficient_funds_during_build_is_typed_and_safe_to_retry(
    monkeypatch, caplog
):
    web3, contract, _ = _mock_chain(monkeypatch)
    monkeypatch.setenv("RPC_URL", "https://credential@rpc.example.test")
    contract.functions.anchor.return_value.build_transaction.side_effect = RuntimeError(
        "insufficient funds via https://credential@rpc.example.test"
    )
    caplog.set_level("WARNING", logger="provenance_pipeline.chain.client")

    with pytest.raises(InsufficientFundsError) as error:
        anchor_claim(FINGERPRINT, CID)

    assert not isinstance(error.value, AnchorOutcomeUnknown)
    web3.eth.send_raw_transaction.assert_not_called()
    assert "stage=build_transaction" in caplog.text
    assert "credential" not in caplog.text


@pytest.mark.parametrize(
    ("stored_cid", "same_cid"),
    [(CID, True), ("bafydifferentcid", False)],
)
def test_duplicate_precheck_never_builds_or_broadcasts(
    monkeypatch, stored_cid, same_cid
):
    web3, contract, _ = _mock_chain(monkeypatch)
    contract.functions.verify.return_value.call.return_value = (
        True,
        "0x2222222222222222222222222222222222222222",
        1_788_000_000,
        stored_cid,
    )

    with pytest.raises(AlreadyAnchoredError) as error:
        anchor_claim(FINGERPRINT, CID)

    assert error.value.same_cid is same_cid
    assert error.value.stored_cid == stored_cid
    contract.functions.anchor.assert_not_called()
    web3.eth.get_transaction_count.assert_not_called()
    web3.eth.send_raw_transaction.assert_not_called()


def test_build_revert_is_a_staged_preparation_error(monkeypatch, caplog):
    web3, contract, _ = _mock_chain(monkeypatch)
    contract.functions.anchor.return_value.build_transaction.side_effect = RuntimeError(
        "execution reverted: authorization denied"
    )
    caplog.set_level("WARNING", logger="provenance_pipeline.chain.client")

    with pytest.raises(AnchorPreparationError, match="build_transaction"):
        anchor_claim(FINGERPRINT, CID)

    assert "stage=build_transaction" in caplog.text
    web3.eth.send_raw_transaction.assert_not_called()


def test_invalid_private_key_is_typed_and_logged_safely(monkeypatch, caplog):
    web3, _, _ = _mock_chain(monkeypatch)
    secret = "fixture-private-key"
    web3.eth.account.from_key.side_effect = ValueError(
        f"invalid key {secret} from https://credential@rpc.example.test"
    )
    monkeypatch.setenv("RPC_URL", "https://credential@rpc.example.test")
    caplog.set_level("WARNING", logger="provenance_pipeline.chain.client")

    with pytest.raises(PrivateKeyError):
        anchor_claim(FINGERPRINT, CID)

    assert "stage=private_key_parse" in caplog.text
    assert secret not in caplog.text
    assert "credential" not in caplog.text
    web3.eth.get_transaction_count.assert_not_called()
    web3.eth.send_raw_transaction.assert_not_called()


def test_pending_nonce_failure_reports_its_stage(monkeypatch, caplog):
    web3, contract, _ = _mock_chain(monkeypatch)
    web3.eth.get_transaction_count.side_effect = TimeoutError("nonce unavailable")
    caplog.set_level("WARNING", logger="provenance_pipeline.chain.client")

    with pytest.raises(AnchorPreparationError, match="pending_nonce"):
        anchor_claim(FINGERPRINT, CID)

    assert "stage=pending_nonce" in caplog.text
    contract.functions.anchor.assert_not_called()
    web3.eth.send_raw_transaction.assert_not_called()


def test_incomplete_receipt_does_not_allow_resubmission(monkeypatch):
    web3, _, _ = _mock_chain(monkeypatch)
    web3.eth.wait_for_transaction_receipt.return_value = {}
    with pytest.raises(AnchorOutcomeUnknown):
        anchor_claim(FINGERPRINT, CID)


def test_receipt_status_zero_is_a_confirmed_revert(monkeypatch):
    web3, _, _ = _mock_chain(monkeypatch)
    web3.eth.wait_for_transaction_receipt.return_value = {
        "status": 0,
        "transactionHash": b"reverted-transaction",
    }

    with pytest.raises(ChainClientError, match="reverted") as error:
        anchor_claim(FINGERPRINT, CID)

    assert not isinstance(error.value, AnchorOutcomeUnknown)
    web3.eth.send_raw_transaction.assert_called_once()


def test_rpc_unavailable_is_typed_and_does_not_fall_back(monkeypatch, caplog):
    web3 = MagicMock()
    web3.is_connected.return_value = False
    web3_factory = MagicMock(return_value=web3)
    web3_factory.HTTPProvider.return_value = object()
    monkeypatch.setattr(chain_client, "Web3", web3_factory)
    monkeypatch.setenv("RPC_URL", "https://credential@rpc.example.test")
    caplog.set_level("WARNING", logger="provenance_pipeline.chain.client")

    with pytest.raises(RPCConnectionError):
        chain_client._web3_and_contract()

    assert "stage=rpc_connection" in caplog.text
    assert "credential" not in caplog.text
    web3_factory.HTTPProvider.assert_called_once_with(
        "https://credential@rpc.example.test",
        request_kwargs={"timeout": 30},
    )


def test_wrong_chain_is_rejected(monkeypatch, caplog):
    web3 = MagicMock()
    web3.is_connected.return_value = True
    web3.eth.chain_id = 1
    web3_factory = MagicMock(return_value=web3)
    web3_factory.HTTPProvider.return_value = object()
    monkeypatch.setattr(chain_client, "Web3", web3_factory)
    caplog.set_level("WARNING", logger="provenance_pipeline.chain.client")

    with pytest.raises(WrongChainError, match="11155111"):
        chain_client._web3_and_contract()

    assert "stage=chain_id" in caplog.text


@pytest.mark.parametrize("fingerprint", ["", "ab", "zz" * 32, "ab" * 33])
def test_anchor_claim_rejects_invalid_fingerprint(
    monkeypatch, fingerprint: str
) -> None:
    monkeypatch.setenv("PRIVATE_KEY", "unused")

    with pytest.raises(ValueError, match="32 bytes"):
        anchor_claim(fingerprint, CID)
