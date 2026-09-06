from types import SimpleNamespace
from threading import Lock
import time

import numpy as np
import pytest

from provenance_pipeline.search.rerank import (
    MAX_THUMBNAIL_WORKERS,
    RankedResult,
    RerankMetrics,
    cosine_similarity,
    embed_candidate,
    rerank,
    select_match,
)
from provenance_pipeline.search.reverse_search import RawResult


def _candidate(name: str) -> RawResult:
    return RawResult(
        url=f"https://instagram.com/p/{name}",
        title=name,
        thumbnail_url=f"https://images.example.test/{name}.jpg",
        source="fixture",
    )


def test_rerank_orders_hand_computed_cosine_scores(monkeypatch) -> None:
    candidates = [_candidate("orthogonal"), _candidate("diagonal"), _candidate("same")]
    embeddings = {
        candidates[0].thumbnail_url: np.array([0.0, 1.0]),
        candidates[1].thumbnail_url: np.array([1.0, 1.0]),
        candidates[2].thumbnail_url: np.array([1.0, 0.0]),
    }
    monkeypatch.setattr(
        "provenance_pipeline.search.rerank.embed_candidate",
        lambda url: embeddings[url],
    )

    ranked = rerank(candidates, np.array([1.0, 0.0]))

    assert [result.candidate.title for result in ranked] == [
        "same",
        "diagonal",
        "orthogonal",
    ]
    assert [result.score for result in ranked] == pytest.approx(
        [1.0, 1.0 / np.sqrt(2.0), 0.0]
    )


def test_embed_candidate_returns_none_when_thumbnail_has_no_face(monkeypatch) -> None:
    fake_image = np.zeros((32, 32, 3), dtype=np.uint8)
    response = SimpleNamespace(
        content=b"fixture-image-bytes",
        raise_for_status=lambda: None,
    )
    monkeypatch.setattr(
        "provenance_pipeline.search.rerank.public_request",
        lambda *_args, **_kwargs: response.content,
    )
    monkeypatch.setattr(
        "provenance_pipeline.search.rerank.cv2.imdecode",
        lambda *_args, **_kwargs: fake_image,
    )
    monkeypatch.setattr(
        "provenance_pipeline.search.rerank.detect_faces", lambda _image: []
    )

    assert embed_candidate("https://images.example.test/no-face.jpg") is None


def test_rerank_excludes_candidate_without_detectable_face(monkeypatch) -> None:
    no_face = _candidate("no-face")
    has_face = _candidate("has-face")

    def fake_embed(url: str):
        if url == no_face.thumbnail_url:
            return None
        return np.array([1.0, 0.0])

    monkeypatch.setattr(
        "provenance_pipeline.search.rerank.embed_candidate", fake_embed
    )

    ranked = rerank([no_face, has_face], np.array([1.0, 0.0]))

    assert [result.candidate for result in ranked] == [has_face]


def test_select_match_auto_path_does_not_prompt(monkeypatch) -> None:
    ranked = [RankedResult(candidate=_candidate("top"), score=0.91)]

    def fail_if_prompted(_message: str) -> str:
        raise AssertionError("automatic selection must not prompt")

    monkeypatch.setattr("builtins.input", fail_if_prompted)

    selected, method = select_match(ranked, auto_threshold=0.85)

    assert selected is ranked[0]
    assert method == "auto"


def test_select_match_below_threshold_uses_explicit_human_pick() -> None:
    ranked = [
        RankedResult(candidate=_candidate("top"), score=0.79),
        RankedResult(candidate=_candidate("second"), score=0.72),
    ]
    selected, method = select_match(
        ranked, auto_threshold=0.80, human_index=1
    )

    assert selected is ranked[1]
    assert method == "human"


def test_cosine_similarity_rejects_zero_vectors() -> None:
    with pytest.raises(ValueError, match="zero vector"):
        cosine_similarity(np.zeros(2), np.ones(2))


def test_instrumented_rerank_keeps_late_best_candidate_and_isolates_failure(
    monkeypatch,
) -> None:
    candidates = [_candidate(str(index)) for index in range(12)]

    def fake_download(url: str) -> bytes | None:
        position = int(url.rsplit("/", 1)[-1].split(".", 1)[0])
        return None if position == 3 else bytes([position])

    def fake_embedding(image_bytes: bytes):
        position = image_bytes[0]
        embedding = np.array([1.0, 0.0]) if position == 11 else np.array([0.0, 1.0])
        return embedding, 0.0, 0.0, 0.0, "face_valid"

    monkeypatch.setattr(
        "provenance_pipeline.search.rerank._download_thumbnail", fake_download
    )
    monkeypatch.setattr(
        "provenance_pipeline.search.rerank._embedding_from_thumbnail",
        fake_embedding,
    )
    metrics = RerankMetrics()

    ranked = rerank(candidates, np.array([1.0, 0.0]), metrics=metrics)

    assert ranked[0].candidate is candidates[11]
    assert metrics.candidate_count_processed == 12
    assert metrics.candidate_count_face_valid == 11
    assert any(item.position == 3 and item.outcome == "download_failed" for item in metrics.candidates)


def test_thumbnail_retrieval_concurrency_is_bounded(monkeypatch) -> None:
    candidates = [_candidate(str(index)) for index in range(18)]
    lock = Lock()
    active = 0
    peak = 0

    def fake_download(_url: str) -> bytes:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return b"fixture"

    monkeypatch.setattr(
        "provenance_pipeline.search.rerank._download_thumbnail", fake_download
    )
    monkeypatch.setattr(
        "provenance_pipeline.search.rerank._embedding_from_thumbnail",
        lambda _bytes: (np.array([1.0, 0.0]), 0.0, 0.0, 0.0, "face_valid"),
    )

    rerank(candidates, np.array([1.0, 0.0]), metrics=RerankMetrics())

    assert 1 < peak <= MAX_THUMBNAIL_WORKERS
