"""Re-rank reverse-image results with the Phase 2 face embedding pipeline."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import logging
import math
import time
from urllib.parse import urlsplit

import cv2
import numpy as np
import requests

from provenance_pipeline.face.detector import detect_faces, select_subject
from provenance_pipeline.public_http import public_request
from .reverse_search import RawResult


logger = logging.getLogger(__name__)

# This value is a starting point, not a universal truth. It must be tuned
# empirically against representative data for the configured detector model;
# cosine-score distributions depend on the embedding space and use case.
DEFAULT_AUTO_THRESHOLD = 0.60

THUMBNAIL_TIMEOUT = (3, 5)
MAX_THUMBNAIL_BYTES = 10 * 1024 * 1024
MAX_THUMBNAIL_WORKERS = 6


@dataclass(frozen=True, slots=True)
class RankedResult:
    """A provider candidate paired with its query-embedding similarity."""

    candidate: RawResult
    score: float


@dataclass(frozen=True, slots=True)
class CandidateTiming:
    """Safe per-candidate timings; deliberately excludes URLs and image data."""

    position: int
    outcome: str
    total_ms: float
    thumbnail_download_ms: float
    image_decode_ms: float
    face_detection_ms: float
    embedding_ms: float


@dataclass(slots=True)
class RerankMetrics:
    """Monotonic timing totals for one reranking operation."""

    total_ms: float = 0.0
    thumbnail_download_total_ms: float = 0.0
    thumbnail_download_wall_ms: float = 0.0
    candidate_image_decode_total_ms: float = 0.0
    candidate_face_detection_total_ms: float = 0.0
    candidate_embedding_total_ms: float = 0.0
    ranking_ms: float = 0.0
    candidate_count_processed: int = 0
    candidate_count_face_valid: int = 0
    candidates: list[CandidateTiming] = field(default_factory=list)


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


def _download_thumbnail(thumbnail_url: str) -> bytes | None:
    """Fetch one public thumbnail within the existing SSRF and size bounds."""

    if not isinstance(thumbnail_url, str):
        raise TypeError("thumbnail_url must be a string")
    parts = urlsplit(thumbnail_url.strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        logger.warning("Skipping candidate with invalid thumbnail URL")
        return None

    try:
        image_bytes = public_request(
            thumbnail_url.strip(),
            method="GET",
            timeout=THUMBNAIL_TIMEOUT,
            max_bytes=MAX_THUMBNAIL_BYTES,
        )
    except (requests.RequestException, ValueError):
        logger.warning("Could not fetch candidate thumbnail")
        return None

    if not image_bytes or len(image_bytes) > MAX_THUMBNAIL_BYTES:
        logger.warning(
            "Skipping empty or oversized candidate thumbnail"
        )
        return None

    return image_bytes


def _timed_download(
    item: tuple[int, RawResult],
) -> tuple[int, RawResult, bytes | None, float]:
    position, candidate = item
    started = time.perf_counter()
    image_bytes = _download_thumbnail(candidate.thumbnail_url)
    return position, candidate, image_bytes, _elapsed_ms(started)


def _embedding_from_thumbnail(
    image_bytes: bytes,
) -> tuple[np.ndarray | None, float, float, float, str]:
    """Decode bytes and run the existing deterministic face selection policy."""

    decode_started = time.perf_counter()
    encoded = np.frombuffer(image_bytes, dtype=np.uint8)
    try:
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    except cv2.error:
        logger.warning("Could not decode candidate thumbnail")
        return None, _elapsed_ms(decode_started), 0.0, 0.0, "decode_failed"
    decode_ms = _elapsed_ms(decode_started)
    if image is None:
        logger.warning("Could not decode candidate thumbnail")
        return None, decode_ms, 0.0, 0.0, "decode_failed"

    detection_started = time.perf_counter()
    faces = detect_faces(image)
    face_detection_ms = _elapsed_ms(detection_started)
    if not faces:
        logger.info("Skipping candidate whose thumbnail contains no face")
        return None, decode_ms, face_detection_ms, 0.0, "no_face"

    # Candidate processing must not prompt once per result. Reuse Phase 2's
    # deterministic bbox-area-times-score policy when a thumbnail has many faces.
    embedding_started = time.perf_counter()
    embedding = select_subject(faces).embedding.copy()
    embedding_ms = _elapsed_ms(embedding_started)
    return embedding, decode_ms, face_detection_ms, embedding_ms, "face_valid"


def embed_candidate(thumbnail_url: str) -> np.ndarray | None:
    """Fetch a thumbnail and return its selected face embedding, if any."""

    image_bytes = _download_thumbnail(thumbnail_url)
    if image_bytes is None:
        return None
    embedding, _, _, _, _ = _embedding_from_thumbnail(image_bytes)
    return embedding


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Return cosine similarity for two non-zero, finite vectors."""

    vector_a = np.asarray(a, dtype=np.float64).reshape(-1)
    vector_b = np.asarray(b, dtype=np.float64).reshape(-1)
    if vector_a.shape != vector_b.shape or vector_a.size == 0:
        raise ValueError("embeddings must be non-empty vectors with matching shapes")
    if not np.all(np.isfinite(vector_a)) or not np.all(np.isfinite(vector_b)):
        raise ValueError("embeddings must contain only finite values")

    norm_a = float(np.linalg.norm(vector_a))
    norm_b = float(np.linalg.norm(vector_b))
    if norm_a == 0.0 or norm_b == 0.0:
        raise ValueError("cosine similarity is undefined for a zero vector")

    score = float(np.dot(vector_a, vector_b) / (norm_a * norm_b))
    # Floating-point roundoff can produce values infinitesimally outside the
    # mathematical cosine range.
    return max(-1.0, min(1.0, score))


def rerank(
    candidates: list[RawResult],
    query_embedding: np.ndarray,
    *,
    metrics: RerankMetrics | None = None,
) -> list[RankedResult]:
    """Score face-bearing candidates and sort them by descending similarity."""

    if metrics is None:
        ranked = []
        for candidate in candidates:
            candidate_embedding = embed_candidate(candidate.thumbnail_url)
            if candidate_embedding is None:
                continue
            ranked.append(
                RankedResult(
                    candidate=candidate,
                    score=cosine_similarity(query_embedding, candidate_embedding),
                )
            )
        ranked.sort(key=lambda result: result.score, reverse=True)
        return ranked

    rerank_started = time.perf_counter()
    if not candidates:
        metrics.total_ms = _elapsed_ms(rerank_started)
        return []
    ranked: list[RankedResult] = []
    worker_count = min(MAX_THUMBNAIL_WORKERS, len(candidates))
    download_batch_started = time.perf_counter()
    with ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="candidate-thumbnail",
    ) as executor:
        downloaded = list(executor.map(_timed_download, enumerate(candidates)))
    metrics.thumbnail_download_wall_ms = _elapsed_ms(download_batch_started)

    # InsightFace remains sequential: the shared ONNX sessions are not invoked
    # from the network worker threads.
    for position, candidate, image_bytes, download_ms in downloaded:
        candidate_started = time.perf_counter()
        decode_ms = 0.0
        face_detection_ms = 0.0
        embedding_ms = 0.0
        outcome = "download_failed"
        candidate_embedding: np.ndarray | None = None
        if image_bytes is not None:
            (
                candidate_embedding,
                decode_ms,
                face_detection_ms,
                embedding_ms,
                outcome,
            ) = _embedding_from_thumbnail(image_bytes)

        if metrics is not None:
            metrics.candidate_count_processed += 1
            metrics.thumbnail_download_total_ms += download_ms
            metrics.candidate_image_decode_total_ms += decode_ms
            metrics.candidate_face_detection_total_ms += face_detection_ms
            metrics.candidate_embedding_total_ms += embedding_ms
            if candidate_embedding is not None:
                metrics.candidate_count_face_valid += 1
            metrics.candidates.append(
                CandidateTiming(
                    position=position,
                    outcome=outcome,
                    total_ms=download_ms + _elapsed_ms(candidate_started),
                    thumbnail_download_ms=download_ms,
                    image_decode_ms=decode_ms,
                    face_detection_ms=face_detection_ms,
                    embedding_ms=embedding_ms,
                )
            )

        if candidate_embedding is None:
            continue
        ranked.append(
            RankedResult(
                candidate=candidate,
                score=cosine_similarity(query_embedding, candidate_embedding),
            )
        )

    # Python's sort is stable, so equal scores retain the oracle's input order.
    ranking_started = time.perf_counter()
    ranked.sort(key=lambda result: result.score, reverse=True)
    if metrics is not None:
        metrics.ranking_ms = _elapsed_ms(ranking_started)
        metrics.total_ms = _elapsed_ms(rerank_started)
    return ranked


class HumanSelectionRequired(ValueError):
    """Raised when a caller must supply a ranked-result index."""


def select_match(
    ranked: list[RankedResult],
    auto_threshold: float,
    human_index: int | None = None,
) -> tuple[RankedResult, str]:
    """Auto-select a confident result or use an explicit zero-based index.

    This function never prompts. Interactive and HTTP callers are responsible
    for collecting a human choice and passing it as ``human_index``.
    """

    if not ranked:
        raise ValueError("cannot select a match from an empty ranked list")
    if not math.isfinite(auto_threshold) or not -1.0 <= auto_threshold <= 1.0:
        raise ValueError("auto_threshold must be a finite value from -1 to 1")

    top_result = ranked[0]
    if top_result.score >= auto_threshold:
        logger.info(
            "Selected ranked result 1 using method=auto (score %.6f >= %.6f)",
            top_result.score,
            auto_threshold,
        )
        return top_result, "auto"

    if human_index is None:
        raise HumanSelectionRequired(
            "human selection is required below the auto threshold"
        )
    if not isinstance(human_index, int) or isinstance(human_index, bool):
        raise TypeError("human_index must be an integer or None")
    if not 0 <= human_index < len(ranked):
        raise ValueError("human selection is outside the ranked result range")

    logger.info("Selected ranked result %d using method=human", human_index + 1)
    return ranked[human_index], "human"
