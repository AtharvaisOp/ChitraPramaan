"""FastAPI service for the two-step face-match provenance workflow."""

from __future__ import annotations

from pathlib import Path as _Path

from dotenv import load_dotenv as _load_dotenv

# Load .env from the repository root regardless of the working directory used
# to start uvicorn.  This makes SERPAPI_KEY, PINATA_JWT, PRIVATE_KEY, etc.
# available through os.getenv() during local development.
_load_dotenv(_Path(__file__).resolve().parent.parent / ".env")

from dataclasses import dataclass, field
from contextlib import asynccontextmanager
import asyncio
from io import BytesIO
import json
import logging
import time
from datetime import datetime, timezone
import math
import os
from threading import RLock
from typing import Literal
from uuid import uuid4

import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from PIL import Image, UnidentifiedImageError

from provenance_pipeline.chain.client import (
    AlreadyAnchoredError,
    ChainClientError,
    AnchorOutcomeUnknown,
    InsufficientFundsError,
    PrivateKeyError,
    anchor_claim,
    transaction_hash_hex,
)
from provenance_pipeline.chain.ipfs import IPFSPinningError, pin_json
from provenance_pipeline.claim_builder import (
    build_match_claim,
    embedding_sha256,
    oracle_response_sha256,
)
from provenance_pipeline.face.detector import (
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
    RerankMetrics,
    rerank,
    select_match,
)
from provenance_pipeline.search.reverse_search import (
    ReverseSearchError,
    SearchAuthError,
    SearchNotConfigured,
    SearchProviderUnavailable,
    SearchRateLimited,
    SearchResponseInvalid,
    reverse_image_search,
)
from provenance_pipeline.verification import (
    IPFSClaimInvalid,
    IPFSGatewayConfigurationError,
    IPFSGatewayUnavailable,
    VerificationError,
    verify_anchored_fingerprint,
)
from backend.rate_limit import limiter


MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
SESSION_TTL_SECONDS = 30 * 60
MAX_SESSIONS = 100
# The rerank pool is deliberately larger than the review set: three review
# sets lets later provider results survive filtering/invalid thumbnails while
# bounding expensive face inference. Final similarity ranking happens before
# the response is truncated.
MAX_RETURNED_CANDIDATES = 7
MAX_RERANK_CANDIDATES = MAX_RETURNED_CANDIDATES * 3
ALLOWED_IMAGE_TYPES = frozenset(
    {"image/jpeg", "image/jpg", "image/png", "image/webp"}
)
EXPLORER_TRANSACTION_URL = "https://sepolia.etherscan.io/tx/{tx_hash}"

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AnalysisPerf:
    """Safe request-local timings for one analysis summary log."""

    started_at: float = field(default_factory=time.perf_counter)
    outcome: str = "exception"
    total_ms: float = 0.0
    upload_validation_ms: float = 0.0
    image_decode_ms: float = 0.0
    query_face_detection_ms: float = 0.0
    crop_generation_ms: float = 0.0
    query_embedding_ms: float = 0.0
    reverse_search_ms: float = 0.0
    domain_filter_ms: float = 0.0
    session_storage_ms: float = 0.0
    candidate_count_raw: int = 0
    candidate_count_supported: int = 0
    candidate_count_returned: int = 0
    rerank: RerankMetrics = field(default_factory=RerankMetrics)


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


def _log_analysis_perf(perf: AnalysisPerf) -> None:
    """Emit no image data, URLs, embeddings, provider secrets, or credentials."""

    slowest = sorted(
        perf.rerank.candidates,
        key=lambda item: item.total_ms,
        reverse=True,
    )[:5]
    payload = {
        "outcome": perf.outcome,
        # InsightFace FaceAnalysis.get produces detections and recognition
        # embeddings in one call; the face-detection timings include both.
        "face_inference_combined": True,
        "total_ms": round(perf.total_ms, 2),
        "upload_validation_ms": round(perf.upload_validation_ms, 2),
        "image_decode_ms": round(perf.image_decode_ms, 2),
        "query_face_detection_ms": round(perf.query_face_detection_ms, 2),
        "crop_generation_ms": round(perf.crop_generation_ms, 2),
        "query_embedding_ms": round(perf.query_embedding_ms, 2),
        "reverse_search_ms": round(perf.reverse_search_ms, 2),
        "domain_filter_ms": round(perf.domain_filter_ms, 2),
        "candidate_rerank_total_ms": round(perf.rerank.total_ms, 2),
        "thumbnail_download_total_ms": round(
            perf.rerank.thumbnail_download_total_ms, 2
        ),
        "thumbnail_download_wall_ms": round(
            perf.rerank.thumbnail_download_wall_ms, 2
        ),
        "candidate_image_decode_total_ms": round(
            perf.rerank.candidate_image_decode_total_ms, 2
        ),
        "candidate_face_detection_total_ms": round(
            perf.rerank.candidate_face_detection_total_ms, 2
        ),
        "candidate_embedding_total_ms": round(
            perf.rerank.candidate_embedding_total_ms, 2
        ),
        "ranking_ms": round(perf.rerank.ranking_ms, 2),
        "session_storage_ms": round(perf.session_storage_ms, 2),
        "candidate_count_raw": perf.candidate_count_raw,
        "candidate_count_supported": perf.candidate_count_supported,
        "candidate_count_processed": perf.rerank.candidate_count_processed,
        "candidate_count_face_valid": perf.rerank.candidate_count_face_valid,
        "candidate_count_returned": perf.candidate_count_returned,
        "slowest_candidates": [
            {
                "position": item.position,
                "outcome": item.outcome,
                "total_ms": round(item.total_ms, 2),
                "thumbnail_download_ms": round(item.thumbnail_download_ms, 2),
                "face_detection_ms": round(item.face_detection_ms, 2),
            }
            for item in slowest
        ],
    }
    logger.info("[analysis_perf] %s", json.dumps(payload, separators=(",", ":")))


class CandidateResponse(BaseModel):
    index: int
    url: str
    title: str
    thumbnail_url: str
    source: str
    score: float


class SessionResponse(BaseModel):
    session_id: str
    status: Literal["auto_selected", "review_required"]
    selection_method: Literal["auto"] | None = None
    selected_candidate: CandidateResponse | None = None
    candidates: list[CandidateResponse] = Field(default_factory=list)


class ConfirmRequest(BaseModel):
    candidate_index: int | None = Field(default=None, ge=0, strict=True)


class ConfirmResponse(BaseModel):
    session_id: str
    fingerprint: str
    selection_method: Literal["auto", "human"]
    score: float
    cid: str
    tx_hash: str
    explorer_link: str


class ChainRecordResponse(BaseModel):
    exists: bool
    submitter: str
    timestamp: int
    uri: str


class VerifyResponse(BaseModel):
    passed: bool
    fingerprint: str
    fetched_fingerprint: str | None
    on_chain_record: ChainRecordResponse
    message: str


@dataclass(slots=True)
class SessionState:
    session_id: str
    uploaded_photo: bytes | None
    query_embedding: np.ndarray | None
    ranked: list[RankedResult]
    crop_sha256: str
    embedding_digest: str
    image_sha256: str
    queried_at: str
    oracle_response_digest: str
    auto_selected_index: int | None
    lifecycle: Literal["ready", "anchoring", "anchored", "uncertain"] = "ready"
    result: ConfirmResponse | None = None
    created_at: float = field(default_factory=time.monotonic)
    pinned_cid: str | None = None
    confirmed_index: int | None = None
    fingerprint: str | None = None


# Demo-only state. It is intentionally process-local: sessions disappear on a
# restart and are not shared between multiple worker processes.
_sessions: dict[str, SessionState] = {}
_sessions_lock = RLock()


def _expire_sessions() -> None:
    with _sessions_lock:
        for key, session in list(_sessions.items()):
            if session.lifecycle != "anchoring" and time.monotonic() - session.created_at > SESSION_TTL_SECONDS:
                session.uploaded_photo = None
                session.query_embedding = None
                del _sessions[key]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async def cleanup():
        while True:
            await asyncio.sleep(60)
            _expire_sessions()
    task = asyncio.create_task(cleanup())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

app = FastAPI(
    lifespan=lifespan,
    title="Face-match provenance API",
    version="0.1.0",
    description=(
        "Search and anchor evidence that an image resembling a selected face "
        "appears at a URL. This API does not confirm identity."
    ),
)

# The browser is a separate localhost origin during development. Keep this
# allowlist explicit and credential-free; provider and wallet secrets remain
# server-side. Production deployments should set FRONTEND_ORIGIN to their
# exact frontend origin.
def _frontend_origins() -> list[str]:
    """Parse exact browser origins and reject wildcard/path configurations."""

    from urllib.parse import urlsplit, urlunsplit

    configured = os.getenv(
        "FRONTEND_ORIGIN", "http://localhost:3000,http://127.0.0.1:3000"
    )
    origins: list[str] = []
    for raw in configured.split(","):
        origin = raw.strip()
        if not origin or origin == "*":
            raise RuntimeError("FRONTEND_ORIGIN must contain exact HTTP(S) origins")
        try:
            parsed = urlsplit(origin)
            _ = parsed.port
        except ValueError as exc:
            raise RuntimeError("FRONTEND_ORIGIN must contain exact HTTP(S) origins") from exc
        hostname = (parsed.hostname or "").casefold()
        if (
            parsed.scheme not in {"http", "https"}
            or not hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or (parsed.scheme == "http" and hostname not in {"localhost", "127.0.0.1", "::1"})
        ):
            raise RuntimeError(
                "FRONTEND_ORIGIN must contain exact HTTPS origins (HTTP is allowed only for local development)"
            )
        normalized = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
        if normalized not in origins:
            origins.append(normalized)
    if not origins:
        raise RuntimeError("FRONTEND_ORIGIN must contain at least one exact origin")
    return origins


frontend_origins = _frontend_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def _analysis_perf_middleware(request: Request, call_next):
    """Log exactly one safe performance summary for each session creation."""

    if request.method != "POST" or request.url.path != "/api/sessions":
        return await call_next(request)

    perf = AnalysisPerf()
    request.state.analysis_perf = perf
    try:
        response = await call_next(request)
        perf.outcome = f"http_{response.status_code}"
        return response
    finally:
        perf.total_ms = _elapsed_ms(perf.started_at)
        _log_analysis_perf(perf)


def _candidate_response(index: int, result: RankedResult) -> CandidateResponse:
    candidate = result.candidate
    return CandidateResponse(
        index=index,
        url=candidate.url,
        title=candidate.title,
        thumbnail_url=candidate.thumbnail_url,
        source=candidate.source,
        score=result.score,
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _process_upload(
    uploaded_photo: bytes,
    auto_threshold: float,
    perf: AnalysisPerf | None = None,
) -> SessionState:
    perf = perf or AnalysisPerf()
    # Inspect encoded format/dimensions before allocating the OpenCV pixel array.
    validation_started = time.perf_counter()
    try:
        with Image.open(BytesIO(uploaded_photo)) as probe:
            if probe.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("photo must be JPEG, PNG, or WebP")
            if probe.width * probe.height > MAX_IMAGE_PIXELS:
                raise ValueError("photo exceeds the 25 megapixel limit")
            probe.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("photo is not a decodable image") from exc
    finally:
        perf.upload_validation_ms += _elapsed_ms(validation_started)
    image_sha256 = sha256_bytes(uploaded_photo)
    decode_started = time.perf_counter()
    image = decode_image_bytes(uploaded_photo)
    perf.image_decode_ms = _elapsed_ms(decode_started)
    detection_started = time.perf_counter()
    faces = detect_faces(image)
    perf.query_face_detection_ms = _elapsed_ms(detection_started)
    # HTTP creation has no blocking prompt. Multi-face images use Phase 2's
    # deterministic area-times-score fallback until a future face-review API
    # explicitly exposes subject selection.
    embedding_started = time.perf_counter()
    subject = select_subject(faces)
    embedding_digest = embedding_sha256(subject.embedding)
    perf.query_embedding_ms = _elapsed_ms(embedding_started)
    crop_started = time.perf_counter()
    crop_bytes = crop_face(image, subject.bbox)
    crop_sha256 = sha256_bytes(crop_bytes)
    perf.crop_generation_ms = _elapsed_ms(crop_started)

    queried_at = _utc_now()
    reverse_search_started = time.perf_counter()
    raw_results = reverse_image_search(crop_bytes)
    perf.reverse_search_ms = _elapsed_ms(reverse_search_started)
    perf.candidate_count_raw = len(raw_results)
    oracle_response_digest = oracle_response_sha256(raw_results)
    if not raw_results:
        raise ValueError(
            "No matching images were found for this photo. Try another photo."
        )
    domain_filter_started = time.perf_counter()
    social_candidates = filter_to_social(raw_results)
    perf.domain_filter_ms = _elapsed_ms(domain_filter_started)
    perf.candidate_count_supported = len(social_candidates)
    if not social_candidates:
        raise ValueError(
            "No supported source results were found. Try another photo."
        )
    rerank_candidates = social_candidates[:MAX_RERANK_CANDIDATES]
    ranked = rerank(rerank_candidates, subject.embedding, metrics=perf.rerank)
    if not ranked:
        raise ValueError(
            "No candidate thumbnails had a usable face. Try another photo."
        )
    ranked = ranked[:MAX_RETURNED_CANDIDATES]

    auto_selected_index: int | None = None
    try:
        selected, _ = select_match(ranked, auto_threshold=auto_threshold)
        auto_selected_index = ranked.index(selected)
    except HumanSelectionRequired:
        pass

    return SessionState(
        session_id=uuid4().hex,
        uploaded_photo=uploaded_photo,
        query_embedding=subject.embedding.copy(),
        ranked=ranked,
        crop_sha256=crop_sha256,
        embedding_digest=embedding_digest,
        image_sha256=image_sha256,
        queried_at=queried_at,
        oracle_response_digest=oracle_response_digest,
        auto_selected_index=auto_selected_index,
    )


def _session_response(session: SessionState) -> SessionResponse:
    candidates = [
        _candidate_response(index, result)
        for index, result in enumerate(session.ranked)
    ]
    if session.auto_selected_index is not None:
        return SessionResponse(
            session_id=session.session_id,
            status="auto_selected",
            selection_method="auto",
            selected_candidate=candidates[session.auto_selected_index],
            candidates=candidates,
        )
    return SessionResponse(
        session_id=session.session_id,
        status="review_required",
        candidates=candidates,
    )


def _enforce_rate_limit(request: Request, scope: str) -> None:
    """Apply a bounded per-client and global limit without trusting proxy headers."""

    client_host = request.client.host if request.client else "unknown"
    # Loopback is deliberately unrestricted for local development and tests;
    # public deployments should enforce limits at their edge as documented.
    if client_host in {"127.0.0.1", "::1", "localhost"}:
        return
    retry_after = limiter.check(scope, client_host)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )


@app.post(
    "/api/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    request: Request,
    photo: UploadFile = File(...),
    consent: bool = Form(False),
    auto_threshold: float = Form(DEFAULT_AUTO_THRESHOLD),
) -> SessionResponse:
    """Validate a consented upload and run detection, search, and ranking."""

    perf = getattr(request.state, "analysis_perf", AnalysisPerf())
    upload_validation_started = time.perf_counter()
    _enforce_rate_limit(request, "analyze")

    if not consent:
        await photo.close()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="consent=true is required before searching this photo",
        )
    if not math.isfinite(auto_threshold) or not -1.0 <= auto_threshold <= 1.0:
        await photo.close()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="auto_threshold must be a finite value from -1 to 1",
        )
    content_type = (photo.content_type or "").lower()
    if content_type not in ALLOWED_IMAGE_TYPES:
        await photo.close()
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="photo must be JPEG, PNG, or WebP",
        )

    try:
        uploaded_photo = await photo.read(MAX_UPLOAD_BYTES + 1)
    finally:
        await photo.close()
    if not uploaded_photo:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="photo must not be empty",
        )
    if len(uploaded_photo) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"photo exceeds the {MAX_UPLOAD_BYTES} byte limit",
        )
    perf.upload_validation_ms += _elapsed_ms(upload_validation_started)

    try:
        session = await run_in_threadpool(
            _process_upload, uploaded_photo, auto_threshold, perf
        )
    except SearchNotConfigured as exc:
        logger.warning("Search provider not configured: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Source search is not configured on this server.",
        ) from exc
    except SearchAuthError as exc:
        logger.error("Search provider auth failure: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The source-search service rejected the server credentials.",
        ) from exc
    except SearchRateLimited as exc:
        logger.warning("Search provider rate limited: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="The source-search service is temporarily rate-limited or has reached its quota.",
        ) from exc
    except SearchProviderUnavailable as exc:
        logger.error("Search provider unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The source-search service is temporarily unavailable.",
        ) from exc
    except SearchResponseInvalid as exc:
        logger.error("Search provider invalid response: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The source-search service returned an unexpected response.",
        ) from exc
    except ReverseSearchError as exc:
        logger.error("Search provider error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Source search is unavailable. Check the backend search-provider configuration or try again later.",
        ) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=_upload_error(exc)
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Image analysis is unavailable. Check the backend face-model installation."
        ) from exc

    storage_started = time.perf_counter()
    with _sessions_lock:
        _expire_sessions()
        if len(_sessions) >= MAX_SESSIONS:
            raise HTTPException(503, "Review capacity is full. Try again later.")
        _sessions[session.session_id] = session
    perf.session_storage_ms = _elapsed_ms(storage_started)
    response = _session_response(session)
    perf.candidate_count_returned = len(response.candidates)
    return response


def _reserve_confirmation(
    session_id: str, candidate_index: int | None
) -> tuple[SessionState, RankedResult, Literal["auto", "human"]] | ConfirmResponse:
    with _sessions_lock:
        _expire_sessions()
        session = _sessions.get(session_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="session not found"
            )
        if session.lifecycle == "anchored" and session.result is not None:
            return session.result
        if session.lifecycle == "anchoring":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="session confirmation is already in progress",
            )
        if session.lifecycle == "uncertain":
            raise HTTPException(409, f"Transaction outcome is unknown. This session cannot submit again. Re-verify fingerprint {session.fingerprint} and check Sepolia before starting another analysis.")

        if candidate_index is None:
            if session.auto_selected_index is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="candidate_index is required for a review session",
                )
            selected_index = session.auto_selected_index
            selection_method: Literal["auto", "human"] = "auto"
        else:
            if not 0 <= candidate_index < len(session.ranked):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="candidate_index is outside the ranked candidate range",
                )
            selected_index = candidate_index
            selection_method = (
                "auto"
                if candidate_index == session.auto_selected_index
                else "human"
            )

        if session.pinned_cid is not None and selected_index != session.confirmed_index:
            raise HTTPException(409, "This session already pinned a different candidate. Retry the original selection.")
        session.lifecycle = "anchoring"
        session.confirmed_index = selected_index
        return session, session.ranked[selected_index], selection_method


def _release_failed_confirmation(session: SessionState) -> None:
    with _sessions_lock:
        if session.lifecycle == "anchoring":
            session.lifecycle = "ready"


def _confirm_session(
    session_id: str, candidate_index: int | None
) -> ConfirmResponse:
    reservation = _reserve_confirmation(session_id, candidate_index)
    if isinstance(reservation, ConfirmResponse):
        return reservation
    session, selected, selection_method = reservation

    try:
        claim = build_match_claim(
            candidate=selected.candidate,
            score=selected.score,
            selection_method=selection_method,
            crop_sha256=session.crop_sha256,
            embedding_digest=session.embedding_digest,
            image_sha256=session.image_sha256,
            queried_at=session.queried_at,
            oracle_response_digest=session.oracle_response_digest,
        )
        fingerprint = compute_fingerprint(claim["fingerprint_body"])
        session.fingerprint = fingerprint
        cid = session.pinned_cid or pin_json(claim)
        session.pinned_cid = cid
        receipt = anchor_claim(fingerprint, cid)
        # Any subsequent failure must not release a successfully broadcast anchor.
        session.lifecycle = "uncertain"
        tx_hash = transaction_hash_hex(receipt)
        result = ConfirmResponse(
            session_id=session_id,
            fingerprint=fingerprint,
            selection_method=selection_method,
            score=selected.score,
            cid=cid,
            tx_hash=tx_hash,
            explorer_link=EXPLORER_TRANSACTION_URL.format(tx_hash=tx_hash),
        )
    except AnchorOutcomeUnknown:
        with _sessions_lock:
            session.lifecycle = "uncertain"
            session.query_embedding = None
            session.uploaded_photo = None
        raise
    except Exception:
        _release_failed_confirmation(session)
        raise

    with _sessions_lock:
        session.lifecycle = "anchored"
        session.result = result
        # Raw biometric and upload data are required only between requests.
        session.query_embedding = None
        session.uploaded_photo = None
    return result


@app.post(
    "/api/sessions/{session_id}/confirm",
    response_model=ConfirmResponse,
)
async def confirm_session(
    request: Request,
    session_id: str,
    payload: ConfirmRequest | None = None,
) -> ConfirmResponse:
    """Build, pin, and anchor the confirmed match exactly once per session."""

    _enforce_rate_limit(request, "confirm")
    try:
        return await run_in_threadpool(
            _confirm_session,
            session_id,
            payload.candidate_index if payload is not None else None,
        )
    except HTTPException:
        raise
    except AnchorOutcomeUnknown as exc:
        with _sessions_lock:
            fingerprint = _sessions[session_id].fingerprint
        raise HTTPException(409, f"Transaction outcome is unknown. This session cannot submit again. Re-verify fingerprint {fingerprint} and check Sepolia before starting another analysis.") from exc
    except IPFSPinningError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="The claim could not be pinned to IPFS. No transaction was submitted. Check the backend pinning service and retry."
        ) from exc
    except AlreadyAnchoredError as exc:
        detail = (
            "This fingerprint is already anchored to the same CID. "
            "No transaction was submitted."
            if exc.same_cid
            else "This fingerprint is already anchored to a different CID. "
            "The existing first-seen record was preserved."
        )
        raise HTTPException(status.HTTP_409_CONFLICT, detail) from exc
    except PrivateKeyError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Blockchain signing is not configured correctly on this server.",
        ) from exc
    except InsufficientFundsError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "The configured Sepolia wallet has insufficient ETH for transaction fees.",
        ) from exc
    except ChainClientError as exc:
        raise HTTPException(502, "Sepolia rejected or could not prepare the transaction. Check backend RPC configuration, wallet funds, and whether this fingerprint is already anchored.") from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The selected claim could not be constructed. Start a new review."
        ) from exc


@app.get("/api/verify/{fingerprint}", response_model=VerifyResponse)
async def verify_fingerprint(request: Request, fingerprint: str) -> VerifyResponse:
    """Compare an on-chain lookup key with the claim fetched from its CID."""

    _enforce_rate_limit(request, "verify")
    try:
        report = await run_in_threadpool(
            verify_anchored_fingerprint, fingerprint
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except ChainClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The Registry could not be read. Verification is temporarily unavailable.",
        ) from exc
    except IPFSGatewayUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The anchored claim could not be retrieved from IPFS. Verification is temporarily unavailable.",
        ) from exc
    except IPFSGatewayConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="IPFS verification is not configured correctly on this server.",
        ) from exc
    except IPFSClaimInvalid as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The anchored claim could not be validated.",
        ) from exc
    except VerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Verification could not be completed.",
        ) from exc

    record = ChainRecordResponse.model_validate(report.record)
    if report.passed:
        message = "On-chain lookup and fetched IPFS fingerprint match."
    elif not record.exists:
        message = "No on-chain record exists for this fingerprint."
    else:
        message = "Fetched IPFS fingerprint does not match the on-chain lookup key."
    return VerifyResponse(
        passed=report.passed,
        fingerprint=report.lookup_fingerprint,
        fetched_fingerprint=report.fetched_fingerprint,
        on_chain_record=record,
        message=message,
    )


def _upload_error(error: Exception) -> str:
    # Only our fixed validation messages may cross the API boundary.
    allowed = {
        "photo must be JPEG, PNG, or WebP", "photo exceeds the 25 megapixel limit",
        "photo is not a decodable image",
        "No matching images were found for this photo. Try another photo.",
        "No supported source results were found. Try another photo.",
        "No candidate thumbnails had a usable face. Try another photo.",
    }
    message = str(error)
    if message in allowed:
        return message
    if message == "cannot select a subject when no faces were detected":
        return "No face was detected. Try a clear photo with one visible face."
    return "The image could not be analyzed. Try a clear JPEG, PNG, or WebP photo with one visible face."


class HealthResponse(BaseModel):
    status: Literal["ok"]
    services: dict[str, Literal["configured", "not_configured"]]


@app.get("/api/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Lightweight configuration check — no external calls, no secrets."""
    return HealthResponse(
        status="ok",
        services={
            "search": "configured" if (os.getenv("SERPAPI_KEY") or os.getenv("SEARCH_API_KEY")) else "not_configured",
            "ipfs": "configured" if (os.getenv("PINATA_JWT") or os.getenv("IPFS_API_KEY")) else "not_configured",
            "blockchain": "configured" if os.getenv("PRIVATE_KEY") else "not_configured",
        },
    )
