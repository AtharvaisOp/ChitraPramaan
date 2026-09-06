"""Python client for the deployed Sepolia Registry contract."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
from threading import Lock
from typing import Any, NoReturn

from web3 import Web3
from web3.contract import Contract
from web3.types import TxReceipt


SEPOLIA_CHAIN_ID = 11_155_111
DEFAULT_SEPOLIA_RPC_URL = "https://ethereum-sepolia-rpc.publicnode.com"
RECEIPT_TIMEOUT_SECONDS = 180
CHAIN_DIRECTORY = Path(__file__).resolve().parent
ADDRESS_PATH = CHAIN_DIRECTORY / "deployed_address.txt"
ABI_PATH = CHAIN_DIRECTORY / "registry_abi.json"
# In an editable checkout, prefer the address most recently written by the
# independent contract deploy script. Installed wheels retain the packaged
# public Sepolia deployment as a fallback.
REPOSITORY_ADDRESS_PATH = (
    CHAIN_DIRECTORY.parents[3] / "contracts" / "deployed_address.txt"
)
FINGERPRINT_PATTERN = re.compile(r"(?:0x)?([0-9a-fA-F]{64})\Z")
_anchor_lock = Lock()
logger = logging.getLogger(__name__)

_URL_PATTERN = re.compile(r"https?://[^\s'\"]+", re.IGNORECASE)
_LONG_HEX_PATTERN = re.compile(r"(?:0x)?[0-9a-fA-F]{64,}")
_SENSITIVE_ENV_NAMES = (
    "PRIVATE_KEY",
    "RPC_URL",
    "PINATA_JWT",
    "IPFS_API_KEY",
    "SERPAPI_KEY",
    "SEARCH_API_KEY",
)


class ChainClientError(RuntimeError):
    """Raised for invalid configuration or failed Registry interactions."""


class AnchorOutcomeUnknown(ChainClientError):
    """Broadcast may have succeeded; a caller must not submit another anchor."""


class RPCConnectionError(ChainClientError):
    """The configured Sepolia RPC endpoint could not be used."""


class WrongChainError(ChainClientError):
    """The configured RPC endpoint is connected to a non-Sepolia chain."""


class PrivateKeyError(ChainClientError):
    """The configured signing key is absent or invalid."""


class InsufficientFundsError(ChainClientError):
    """The configured signer cannot cover the transaction's maximum fee."""


class AnchorPreparationError(ChainClientError):
    """A known-prebroadcast Registry preparation stage failed."""


class AlreadyAnchoredError(ChainClientError):
    """The Registry already contains a first-seen record for a fingerprint."""

    def __init__(self, stored_cid: str, requested_cid: str) -> None:
        super().__init__("Registry fingerprint is already anchored")
        self.stored_cid = stored_cid
        self.same_cid = stored_cid == requested_cid


def _sanitized_exception_message(error: Exception) -> str:
    """Return useful diagnostics without credentials or transaction material."""

    message = " ".join(str(error).split())
    for name in _SENSITIVE_ENV_NAMES:
        value = os.getenv(name)
        if value:
            message = message.replace(value, f"<{name}>")
    message = _URL_PATTERN.sub("<URL>", message)
    message = _LONG_HEX_PATTERN.sub("<HEX>", message)
    return (message or "<no message>")[:500]


def _log_stage_failure(stage: str, error: Exception) -> None:
    logger.warning(
        "Sepolia anchor failed stage=%s exception=%s message=%s",
        stage,
        type(error).__name__,
        _sanitized_exception_message(error),
    )


def _is_insufficient_funds(error: Exception) -> bool:
    return "insufficient funds" in str(error).casefold()


def _raise_preparation_error(stage: str, error: Exception) -> NoReturn:
    _log_stage_failure(stage, error)
    if isinstance(error, ChainClientError):
        raise error
    if _is_insufficient_funds(error):
        raise InsufficientFundsError(
            "Sepolia wallet has insufficient ETH for transaction fees"
        ) from error
    raise AnchorPreparationError(
        f"Registry anchor preparation failed at {stage}"
    ) from error


def _fingerprint_bytes(fingerprint_hex: str) -> bytes:
    if not isinstance(fingerprint_hex, str):
        raise TypeError("fingerprint_hex must be a string")
    match = FINGERPRINT_PATTERN.fullmatch(fingerprint_hex.strip())
    if match is None:
        raise ValueError("fingerprint_hex must contain exactly 32 bytes of hex")
    return bytes.fromhex(match.group(1))


def _contract_address() -> str:
    configured = os.getenv("CONTRACT_ADDRESS")
    if configured:
        return configured.strip()
    for address_path in (REPOSITORY_ADDRESS_PATH, ADDRESS_PATH):
        try:
            address = address_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            continue
        if address:
            return address
    raise ChainClientError(
        "No contract address found; set CONTRACT_ADDRESS or deploy Registry first"
    )


def _contract_abi() -> list[dict[str, Any]]:
    try:
        artifact = json.loads(ABI_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ChainClientError(
            "Packaged Registry ABI is missing; reinstall provenance-pipeline"
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ChainClientError("Registry artifact could not be read") from exc

    abi = artifact.get("abi") if isinstance(artifact, dict) else None
    if not isinstance(abi, list):
        raise ChainClientError("Registry artifact contains no ABI")
    return abi


def _web3_and_contract() -> tuple[Web3, Contract]:
    # The public default keeps read-only third-party verification keyless.
    # Writers should set RPC_URL to a dedicated provider for reliability.
    rpc_url = os.getenv("RPC_URL") or DEFAULT_SEPOLIA_RPC_URL

    try:
        web3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
        connected = web3.is_connected()
    except Exception as exc:
        error = RPCConnectionError("Could not connect to configured Sepolia RPC")
        _log_stage_failure("rpc_connection", exc)
        raise error from exc
    if not connected:
        error = RPCConnectionError("Could not connect to configured Sepolia RPC")
        _log_stage_failure("rpc_connection", error)
        raise error

    try:
        chain_id = web3.eth.chain_id
    except Exception as exc:
        error = RPCConnectionError("Could not read chain ID from configured RPC")
        _log_stage_failure("chain_id", exc)
        raise error from exc
    if chain_id != SEPOLIA_CHAIN_ID:
        error = WrongChainError(
            f"Refusing chain ID {chain_id}; expected Sepolia {SEPOLIA_CHAIN_ID}"
        )
        _log_stage_failure("chain_id", error)
        raise error

    try:
        address = Web3.to_checksum_address(_contract_address())
    except Exception as exc:
        error = ChainClientError("Registry contract address is invalid")
        _log_stage_failure("contract_address", exc)
        raise error from exc
    try:
        abi = _contract_abi()
        contract = web3.eth.contract(address=address, abi=abi)
    except Exception as exc:
        error = ChainClientError("Registry ABI or contract construction is invalid")
        _log_stage_failure("contract_construction", exc)
        raise error from exc
    return web3, contract


def anchor_claim(fingerprint_hex: str, cid: str) -> TxReceipt:
    """Anchor a fingerprint/CID pair and return its confirmed receipt."""

    # One backend wallet must not prepare concurrent transactions with the same
    # pending nonce. Process-local, matching the demo's single-worker sessions.
    with _anchor_lock:
        return _anchor_claim(fingerprint_hex, cid)


def _anchor_claim(fingerprint_hex: str, cid: str) -> TxReceipt:

    fingerprint = _fingerprint_bytes(fingerprint_hex)
    if not isinstance(cid, str) or not cid.strip():
        raise ValueError("cid must be a non-empty string")
    private_key = os.getenv("PRIVATE_KEY")
    if not private_key:
        error = PrivateKeyError("PRIVATE_KEY is not configured")
        _log_stage_failure("private_key_configuration", error)
        raise error

    try:
        web3, contract = _web3_and_contract()
    except Exception as exc:
        if isinstance(exc, ChainClientError):
            raise
        _raise_preparation_error("rpc_contract_setup", exc)

    try:
        exists, _, _, stored_cid = contract.functions.verify(fingerprint).call()
    except Exception as exc:
        _raise_preparation_error("duplicate_precheck", exc)
    if exists:
        duplicate = AlreadyAnchoredError(str(stored_cid), cid.strip())
        logger.info(
            "Sepolia anchor skipped: fingerprint already anchored cid_match=%s",
            duplicate.same_cid,
        )
        raise duplicate

    try:
        account = web3.eth.account.from_key(private_key)
    except Exception as exc:
        _log_stage_failure("private_key_parse", exc)
        raise PrivateKeyError("Configured PRIVATE_KEY is invalid") from exc

    try:
        nonce = web3.eth.get_transaction_count(account.address, "pending")
    except Exception as exc:
        _raise_preparation_error("pending_nonce", exc)

    try:
        anchor_function = contract.functions.anchor(fingerprint, cid.strip())
    except Exception as exc:
        _raise_preparation_error("anchor_function", exc)

    try:
        transaction = anchor_function.build_transaction(
            {
                "from": account.address,
                "nonce": nonce,
                "chainId": SEPOLIA_CHAIN_ID,
            }
        )
    except Exception as exc:
        # A concurrent writer may have anchored after the first pre-check but
        # before gas estimation. Confirm that state before classifying a revert.
        try:
            exists, _, _, stored_cid = contract.functions.verify(fingerprint).call()
        except Exception:
            exists = False
            stored_cid = ""
        if exists:
            duplicate = AlreadyAnchoredError(str(stored_cid), cid.strip())
            logger.info(
                "Sepolia anchor skipped after build failure: "
                "fingerprint already anchored cid_match=%s",
                duplicate.same_cid,
            )
            raise duplicate from exc
        _raise_preparation_error("build_transaction", exc)

    try:
        signed = account.sign_transaction(transaction)
    except Exception as exc:
        _raise_preparation_error("sign_transaction", exc)

    try:
        transaction_hash = web3.eth.send_raw_transaction(signed.raw_transaction)
    except Exception as exc:
        _log_stage_failure("send_raw_transaction", exc)
        if _is_insufficient_funds(exc):
            raise InsufficientFundsError(
                "Sepolia wallet has insufficient ETH for transaction fees"
            ) from exc
        raise AnchorOutcomeUnknown(
            "Transaction outcome is unknown. Do not submit again; check the "
            "fingerprint on Sepolia before continuing."
        ) from exc

    try:
        receipt = web3.eth.wait_for_transaction_receipt(
            transaction_hash, timeout=RECEIPT_TIMEOUT_SECONDS
        )
    except Exception as exc:
        _log_stage_failure("receipt_wait", exc)
        raise AnchorOutcomeUnknown(
            "Transaction outcome is unknown. Do not submit again; check the "
            "fingerprint on Sepolia before continuing."
        ) from exc

    if receipt.get("status") not in (0, 1):
        error = AnchorOutcomeUnknown(
            "The transaction receipt is incomplete. Check Sepolia before "
            "submitting again."
        )
        _log_stage_failure("receipt_status", error)
        raise error
    if receipt["status"] != 1:
        error = ChainClientError("Registry anchor transaction reverted")
        _log_stage_failure("receipt_status", error)
        raise error
    return receipt


def verify_claim(fingerprint_hex: str) -> dict:
    """Read the Registry record for a fingerprint without sending a transaction."""

    fingerprint = _fingerprint_bytes(fingerprint_hex)
    try:
        _, contract = _web3_and_contract()
        exists, submitter, timestamp, uri = contract.functions.verify(
            fingerprint
        ).call()
        return {
            "exists": bool(exists),
            "submitter": str(submitter),
            "timestamp": int(timestamp),
            "uri": str(uri),
        }
    except Exception as exc:
        raise ChainClientError("Registry verify call failed") from exc


def transaction_hash_hex(receipt: TxReceipt | dict) -> str:
    """Normalize a Web3 transaction receipt hash to a 0x-prefixed string."""

    value = receipt["transactionHash"]
    if isinstance(value, str):
        return value if value.startswith("0x") else f"0x{value}"
    if hasattr(value, "hex"):
        encoded = value.hex()
    else:
        encoded = bytes(value).hex()
    return encoded if encoded.startswith("0x") else f"0x{encoded}"
