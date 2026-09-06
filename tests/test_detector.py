import hashlib
import logging
from types import SimpleNamespace

import numpy as np

from provenance_pipeline.face import detector
from provenance_pipeline.face.detector import (
    FaceDetection,
    crop_face,
    detect_faces,
    select_subject,
    sha256_bytes,
)


def _fixture_image() -> np.ndarray:
    """Create a deterministic, non-uniform BGR image without fixture files."""

    y, x = np.indices((96, 112), dtype=np.uint16)
    return np.stack(
        (
            (x * 3 + y * 5) % 256,
            (x * x + y * 7) % 256,
            (x * 11 + y * y) % 256,
        ),
        axis=2,
    ).astype(np.uint8)


def _face(bbox: tuple[float, float, float, float], score: float) -> FaceDetection:
    return FaceDetection(
        bbox=bbox,
        det_score=score,
        embedding=np.full(512, score, dtype=np.float32),
    )


def test_same_crop_policy_produces_identical_bytes_and_hash() -> None:
    image = _fixture_image()
    bbox = (24.25, 18.75, 72.5, 68.25)

    first = crop_face(image, bbox)
    second = crop_face(image, bbox)

    assert first == second
    assert sha256_bytes(first) == sha256_bytes(second)


def test_margin_change_changes_crop_hash() -> None:
    image = _fixture_image()
    bbox = (24.25, 18.75, 72.5, 68.25)

    margin_30_hash = sha256_bytes(crop_face(image, bbox, margin=0.3))
    margin_40_hash = sha256_bytes(crop_face(image, bbox, margin=0.4))

    assert margin_30_hash != margin_40_hash


def test_original_upload_bytes_can_be_hashed_before_image_processing() -> None:
    uploaded_bytes = b"fixture upload bytes\x00\xff"

    image_sha256 = sha256_bytes(uploaded_bytes)

    assert image_sha256 == hashlib.sha256(uploaded_bytes).hexdigest()


def test_explicit_and_auto_multi_face_selection(caplog) -> None:
    # These detections stand in for a two-face fixture image. Face 1 wins the
    # automatic rule: 40*40*0.90 > 20*20*0.99.
    faces = [
        _face((0, 0, 40, 40), 0.90),
        _face((50, 10, 70, 30), 0.99),
    ]
    caplog.set_level(logging.INFO, logger="provenance_pipeline.face.detector")
    assert select_subject(faces, selected_index=1) is faces[1]
    assert "method=human" in caplog.text

    caplog.clear()
    assert select_subject(faces) is faces[0]
    assert "method=auto" in caplog.text


def test_missing_selection_falls_back_to_auto(caplog) -> None:
    faces = [
        _face((0, 0, 40, 40), 0.90),
        _face((50, 10, 70, 30), 0.99),
    ]
    caplog.set_level(logging.INFO, logger="provenance_pipeline.face.detector")

    assert select_subject(faces) is faces[0]
    assert "method=auto" in caplog.text


def test_detect_faces_returns_all_faces_in_stable_order(monkeypatch) -> None:
    raw_faces = [
        SimpleNamespace(
            bbox=np.array([50, 10, 70, 30]),
            det_score=0.99,
            embedding=np.ones(512, dtype=np.float32),
        ),
        SimpleNamespace(
            bbox=np.array([0, 0, 40, 40]),
            det_score=0.90,
            embedding=np.zeros(512, dtype=np.float32),
        ),
    ]

    class FakeAnalyzer:
        def get(self, image: np.ndarray):
            assert image.shape == (96, 112, 3)
            return raw_faces

    monkeypatch.setattr(detector, "_get_face_analyzer", lambda: FakeAnalyzer())
    faces = detect_faces(_fixture_image())

    assert len(faces) == 2
    assert faces[0].bbox == (0.0, 0.0, 40.0, 40.0)
    assert faces[1].bbox == (50.0, 10.0, 70.0, 30.0)
    assert all(face.embedding.shape == (512,) for face in faces)
