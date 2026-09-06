"""Read-only verification of an on-chain fingerprint against public IPFS."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
import re
import time
from urllib.parse import urlsplit, urlunsplit

import requests

from provenance_pipeline.chain.client import verify_claim
from provenance_pipeline.records.fingerprint import compute_fingerprint


DEFAULT_IPFS_GATEWAY = "https://ipfs.io/ipfs"
DEFAULT_IPFS_FALLBACK_GATEWAY = "https://gateway.pinata.cloud/ipfs"
FETCH_TIMEOUT = (4, 8)
MAX_GATEWAY_ATTEMPTS = 2
MAX_CLAIM_BYTES = 1 * 1024 * 1024
RETRYABLE_GATEWAY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
CID_PATTERN = re.compile(r"[A-Za-z0-9]+\Z")
FINGERPRINT_PATTERN = re.compile(r"(?:0x)?([0-9a-fA-F]{64})\Z")
FINGERPRINT_BODY_FIELDS = frozenset(
    {
        "platform",
        "normalized_post_url",
        "crop_sha256",
        "embedding_sha256",
        "detector_model_version",
    }
)
logger = logging.getLogger(__name__)


class VerificationError(RuntimeError):
    """Raised when chain or IPFS data cannot be checked."""


class IPFSGatewayUnavailable(VerificationError):
    """All eligible IPFS gateway retrieval attempts were unavailable."""


class IPFSClaimInvalid(VerificationError):
    """The anchored URI or retrieved claim content is invalid."""


class IPFSGatewayConfigurationError(VerificationError):
    """A configured IPFS gateway base URL is unsafe or malformed."""


@dataclass(frozen=True, slots=True)
class AnchoredVerification:
    lookup_fingerprint: str
    fetched_fingerprint: str | None
    record: dict

    @property
    def passed(self) -> bool:
        return bool(
            self.record.get("exists")
            and self.fetched_fingerprint == self.lookup_fingerprint
        )


def normalize_fingerprint(fingerprint: str) -> str:
    """Return a lowercase 64-character fingerprint without a prefix."""

    if not isinstance(fingerprint, str):
        raise TypeError("fingerprint must be a string")
    match = FINGERPRINT_PATTERN.fullmatch(fingerprint.strip())
    if match is None:
        raise ValueError("fingerprint must contain exactly 32 bytes of hex")
    return match.group(1).lower()


def cid_from_uri(uri: str) -> str:
    """Extract a CID from a raw CID, ipfs:// URI, or path-gateway URL."""

    if not isinstance(uri, str):
        raise TypeError("IPFS URI must be a string")
    value = uri.strip()
    if value.startswith("ipfs://"):
        value = value.removeprefix("ipfs://").removeprefix("ipfs/")
    elif "/ipfs/" in value:
        value = value.split("/ipfs/", 1)[1]
    cid = value.split("/", 1)[0]
    if not cid or CID_PATTERN.fullmatch(cid) is None:
        raise IPFSClaimInvalid("on-chain URI does not contain a valid CID")
    return cid


def _normalize_gateway_url(gateway_url: str) -> str:
    if not isinstance(gateway_url, str) or not gateway_url.strip():
        raise IPFSGatewayConfigurationError(
            "IPFS gateway URL must be a non-empty path-gateway base"
        )
    try:
        parsed = urlsplit(gateway_url.strip())
        hostname = parsed.hostname
    except ValueError as exc:
        raise IPFSGatewayConfigurationError(
            "IPFS gateway URL is malformed"
        ) from exc
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise IPFSGatewayConfigurationError(
            "IPFS gateway URL must use HTTP or HTTPS and include a hostname"
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise IPFSGatewayConfigurationError(
            "IPFS gateway URL must not contain credentials, a query, or a fragment"
        )
    if parsed.scheme == "http" and hostname.casefold() not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise IPFSGatewayConfigurationError(
            "non-local IPFS gateways must use HTTPS"
        )
    path = parsed.path.rstrip("/")
    if not path.endswith("/ipfs"):
        raise IPFSGatewayConfigurationError(
            "IPFS gateway URL must end with /ipfs and must not include a CID"
        )
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _gateway_operator(gateway_url: str) -> str:
    hostname = (urlsplit(gateway_url).hostname or "").casefold().rstrip(".")
    if hostname in {"ipfs.io", "dweb.link", "trustless-gateway.link"}:
        return "ipfs-foundation-public"
    if hostname == "gateway.pinata.cloud" or hostname.endswith(
        ".mypinata.cloud"
    ):
        return "pinata"
    return hostname


def resolve_ipfs_gateways(
    gateway_url: str | None = None,
    fallback_gateway_url: str | None = None,
) -> tuple[str, ...]:
    """Resolve at most two sequential gateways using one shared policy."""

    primary = (
        gateway_url
        or os.getenv("IPFS_GATEWAY_URL")
        or DEFAULT_IPFS_GATEWAY
    )
    fallback = (
        fallback_gateway_url
        or os.getenv("IPFS_FALLBACK_GATEWAY_URL")
        or DEFAULT_IPFS_FALLBACK_GATEWAY
    )
    candidates = [primary, fallback]
    # If both configured values share infrastructure, add the other built-in
    # operator instead of pretending the aliases provide independent fallback.
    candidates.extend((DEFAULT_IPFS_FALLBACK_GATEWAY, DEFAULT_IPFS_GATEWAY))

    resolved: list[str] = []
    operators: set[str] = set()
    for candidate in candidates:
        normalized = _normalize_gateway_url(candidate)
        operator = _gateway_operator(normalized)
        if operator in operators:
            continue
        resolved.append(normalized)
        operators.add(operator)
        if len(resolved) == MAX_GATEWAY_ATTEMPTS:
            break
    return tuple(resolved)


def _gateway_host(gateway_url: str) -> str:
    return urlsplit(gateway_url).hostname or "unknown"


def _unavailable_error(
    *,
    attempt: int,
    gateway_url: str,
    category: str,
    elapsed: float,
    status_code: int | None = None,
) -> IPFSGatewayUnavailable:
    logger.warning(
        "IPFS verification gateway failed attempt=%d host=%s status=%s "
        "category=%s elapsed=%.2fs",
        attempt,
        _gateway_host(gateway_url),
        status_code if status_code is not None else "none",
        category,
        elapsed,
    )
    return IPFSGatewayUnavailable("IPFS gateway is temporarily unavailable")


def _fetch_gateway_json(cid: str, gateway_url: str, attempt: int) -> dict:
    started = time.monotonic()
    try:
        response = requests.get(
            f"{gateway_url}/{cid}",
            headers={"Accept": "application/json"},
            timeout=FETCH_TIMEOUT,
            stream=True,
        )
    except requests.Timeout as exc:
        raise _unavailable_error(
            attempt=attempt,
            gateway_url=gateway_url,
            category="timeout",
            elapsed=time.monotonic() - started,
        ) from exc
    except requests.ConnectionError as exc:
        raise _unavailable_error(
            attempt=attempt,
            gateway_url=gateway_url,
            category="connection_error",
            elapsed=time.monotonic() - started,
        ) from exc
    except requests.RequestException as exc:
        raise _unavailable_error(
            attempt=attempt,
            gateway_url=gateway_url,
            category="network_error",
            elapsed=time.monotonic() - started,
        ) from exc

    try:
        status_code = response.status_code
        if status_code in RETRYABLE_GATEWAY_STATUSES:
            category = "rate_limited" if status_code == 429 else "upstream_error"
            raise _unavailable_error(
                attempt=attempt,
                gateway_url=gateway_url,
                status_code=status_code,
                category=category,
                elapsed=time.monotonic() - started,
            )
        if not 200 <= status_code < 300:
            logger.warning(
                "IPFS verification gateway rejected claim attempt=%d host=%s "
                "status=%d category=non_retryable_http",
                attempt,
                _gateway_host(gateway_url),
                status_code,
            )
            raise IPFSClaimInvalid(
                "IPFS gateway returned a non-retryable response"
            )
        content_length = getattr(response, "headers", {}).get("Content-Length")
        if content_length is not None:
            try:
                if int(content_length) > MAX_CLAIM_BYTES:
                    raise IPFSClaimInvalid("IPFS claim exceeds the response size limit")
            except ValueError:
                # An invalid length is not trusted; the streamed byte bound below
                # remains authoritative.
                pass
        try:
            chunks: list[bytes] = []
            total = 0
            iterator = response.iter_content(chunk_size=64 * 1024)
            for chunk in iterator:
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_CLAIM_BYTES:
                    raise IPFSClaimInvalid("IPFS claim exceeds the response size limit")
                chunks.append(chunk)
            value = json.loads(b"".join(chunks))
        except IPFSClaimInvalid:
            raise
        except requests.Timeout as exc:
            raise _unavailable_error(
                attempt=attempt,
                gateway_url=gateway_url,
                category="timeout",
                elapsed=time.monotonic() - started,
            ) from exc
        except requests.ConnectionError as exc:
            raise _unavailable_error(
                attempt=attempt,
                gateway_url=gateway_url,
                category="connection_error",
                elapsed=time.monotonic() - started,
            ) from exc
        except requests.RequestException as exc:
            raise _unavailable_error(
                attempt=attempt,
                gateway_url=gateway_url,
                category="network_error",
                elapsed=time.monotonic() - started,
            ) from exc
        except (TypeError, ValueError) as exc:
            logger.warning(
                "IPFS verification claim rejected attempt=%d host=%s "
                "category=invalid_json",
                attempt,
                _gateway_host(gateway_url),
            )
            raise IPFSClaimInvalid("IPFS claim is not valid JSON") from exc
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()

    if not isinstance(value, dict):
        logger.warning(
            "IPFS verification claim rejected attempt=%d host=%s "
            "category=non_object_json",
            attempt,
            _gateway_host(gateway_url),
        )
        raise IPFSClaimInvalid("IPFS claim JSON must be an object")
    return value


def fetch_ipfs_json(
    uri: str,
    gateway_url: str | None = None,
    fallback_gateway_url: str | None = None,
) -> dict:
    """Fetch claim JSON sequentially without forwarding pinning credentials."""

    cid = cid_from_uri(uri)
    gateways = resolve_ipfs_gateways(gateway_url, fallback_gateway_url)
    last_error: IPFSGatewayUnavailable | None = None
    for attempt, gateway in enumerate(gateways, start=1):
        try:
            return _fetch_gateway_json(cid, gateway, attempt)
        except IPFSGatewayUnavailable as exc:
            last_error = exc
            if attempt < len(gateways):
                logger.info(
                    "IPFS verification retrying with independent fallback "
                    "next_attempt=%d",
                    attempt + 1,
                )
    raise IPFSGatewayUnavailable(
        "all configured IPFS gateways are temporarily unavailable"
    ) from last_error


def validated_claim_fingerprint_body(document: dict) -> dict:
    """Return a structurally valid fingerprint body from a complete claim."""

    if set(document) != {"fingerprint_body", "envelope"}:
        raise IPFSClaimInvalid(
            "IPFS claim must contain exactly fingerprint_body and envelope"
        )
    body = document["fingerprint_body"]
    envelope = document["envelope"]
    if not isinstance(body, dict) or not isinstance(envelope, dict):
        raise IPFSClaimInvalid("IPFS claim sections must be objects")
    if set(body) != FINGERPRINT_BODY_FIELDS or not all(
        isinstance(value, str) and value
        for value in body.values()
    ):
        raise IPFSClaimInvalid("IPFS fingerprint_body has an invalid structure")
    if FINGERPRINT_PATTERN.fullmatch(body["crop_sha256"]) is None or (
        FINGERPRINT_PATTERN.fullmatch(body["embedding_sha256"]) is None
    ):
        raise IPFSClaimInvalid("IPFS fingerprint_body contains an invalid digest")
    return body


def verify_anchored_fingerprint(
    fingerprint: str,
    *,
    gateway_url: str | None = None,
    fallback_gateway_url: str | None = None,
) -> AnchoredVerification:
    """Compare the requested chain key with the claim fetched from its CID."""

    lookup_fingerprint = normalize_fingerprint(fingerprint)
    record = verify_claim(lookup_fingerprint)
    if not record.get("exists"):
        return AnchoredVerification(lookup_fingerprint, None, record)

    uri = record.get("uri")
    if not isinstance(uri, str) or not uri.strip():
        raise IPFSClaimInvalid("on-chain record contains no IPFS URI")
    document = fetch_ipfs_json(uri, gateway_url, fallback_gateway_url)
    body = validated_claim_fingerprint_body(document)
    try:
        fetched_fingerprint = compute_fingerprint(body)
    except (TypeError, ValueError) as exc:
        raise IPFSClaimInvalid(
            "IPFS fingerprint_body could not be canonicalized"
        ) from exc
    return AnchoredVerification(lookup_fingerprint, fetched_fingerprint, record)
