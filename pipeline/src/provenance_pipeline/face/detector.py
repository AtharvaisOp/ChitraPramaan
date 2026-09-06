"""Deterministic face detection, selection, and crop primitives.

Images passed to this module use OpenCV's BGR channel order. Raw embeddings
remain in memory on :class:`FaceDetection`; callers must persist only a digest
of an embedding, never the vector itself.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import logging
import math
from threading import RLock
from typing import Sequence

import numpy as np
from PIL import Image


logger = logging.getLogger(__name__)

DETECTOR_MODEL_VERSION = "buffalo_l"
FACE_ANALYZER_MODULES = ("detection", "recognition")
_face_analyzer = None
_face_analyzer_lock = RLock()


@dataclass(slots=True)
class FaceDetection:
    """One detected face and its in-memory 512-dimensional embedding."""

    bbox: tuple[float, float, float, float]
    det_score: float
    embedding: np.ndarray

    def __post_init__(self) -> None:
        bbox = tuple(float(coordinate) for coordinate in self.bbox)
        if len(bbox) != 4 or not all(math.isfinite(value) for value in bbox):
            raise ValueError("bbox must contain four finite coordinates")
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            raise ValueError("bbox must have positive width and height")

        det_score = float(self.det_score)
        if not math.isfinite(det_score):
            raise ValueError("det_score must be finite")

        embedding = np.asarray(self.embedding, dtype=np.float32).reshape(-1)
        if embedding.shape != (512,):
            raise ValueError("embedding must contain exactly 512 values")

        self.bbox = bbox
        self.det_score = det_score
        self.embedding = embedding.copy()


def _get_face_analyzer():
    """Create the InsightFace analyzer only when detection is requested."""

    global _face_analyzer
    if _face_analyzer is not None:
        return _face_analyzer

    with _face_analyzer_lock:
        if _face_analyzer is not None:
            return _face_analyzer
        try:
            from insightface.app import FaceAnalysis
        except ImportError as exc:  # pragma: no cover - depends on optional runtime
            raise RuntimeError(
                "InsightFace is required for detect_faces; install insightface "
                "and onnxruntime before running detection"
            ) from exc

        analyzer = FaceAnalysis(
            name=DETECTOR_MODEL_VERSION,
            allowed_modules=list(FACE_ANALYZER_MODULES),
            providers=["CPUExecutionProvider"],
        )
        analyzer.prepare(ctx_id=-1, det_size=(640, 640))
        _face_analyzer = analyzer
    return _face_analyzer


def detect_faces(image: np.ndarray) -> list[FaceDetection]:
    """Detect every face and return them in stable left-to-right order."""

    _validate_image(image)
    # The analyzer owns shared ONNX sessions. Serialize inference rather than
    # assuming that every loaded provider/session combination is thread-safe.
    with _face_analyzer_lock:
        detected = _get_face_analyzer().get(image)
    faces = [
        FaceDetection(
            bbox=tuple(face.bbox),
            det_score=face.det_score,
            embedding=face.embedding,
        )
        for face in detected
    ]

    # InsightFace does not make its return order part of its public contract.
    # Sorting makes a face index stable when detections themselves are stable.
    faces.sort(key=lambda face: (*face.bbox, -face.det_score))
    return faces


def _area_score(face: FaceDetection) -> float:
    x1, y1, x2, y2 = face.bbox
    return (x2 - x1) * (y2 - y1) * face.det_score


def _auto_subject(faces: Sequence[FaceDetection]) -> tuple[int, FaceDetection]:
    # The negative index makes an exact tie resolve to the earliest stable face.
    index, face = max(
        enumerate(faces),
        key=lambda indexed: (_area_score(indexed[1]), -indexed[0]),
    )
    return index, face


def select_subject(
    faces: list[FaceDetection], selected_index: int | None = None
) -> FaceDetection:
    """Select an explicit zero-based face index or use the deterministic fallback.

    User interaction belongs to a caller such as the CLI or backend. Passing no
    index applies the stable ``bbox_area * det_score`` rule without blocking.
    """

    if not faces:
        raise ValueError("cannot select a subject when no faces were detected")

    if selected_index is not None:
        if not isinstance(selected_index, int) or isinstance(selected_index, bool):
            raise TypeError("selected_index must be an integer or None")
        if not 0 <= selected_index < len(faces):
            raise ValueError("selected_index is outside the detected face range")
        logger.info("Selected face %d using method=human", selected_index + 1)
        return faces[selected_index]

    if len(faces) == 1:
        logger.info("Selected face 1 using method=auto (only detected face)")
        return faces[0]

    selected_index, selected_face = _auto_subject(faces)
    logger.info(
        "Selected face %d using method=auto (bbox_area * det_score)",
        selected_index + 1,
    )
    return selected_face


def crop_face(
    image: np.ndarray,
    bbox,
    margin: float = 0.3,
    out_size: int = 320,
    jpeg_quality: int = 95,
) -> bytes:
    """Return a reproducible JPEG crop for a face bounding box.

    Geometry uses floor for the expanded top/left edges and ceil for the
    bottom/right edges, followed by clamping. Resizing is bilinear, the JPEG
    uses fixed 4:2:0 subsampling, and no source metadata is copied.
    """

    _validate_image(image)
    if not math.isfinite(margin) or margin < 0:
        raise ValueError("margin must be a finite non-negative number")
    if not isinstance(out_size, int) or isinstance(out_size, bool) or out_size <= 0:
        raise ValueError("out_size must be a positive integer")
    if (
        not isinstance(jpeg_quality, int)
        or isinstance(jpeg_quality, bool)
        or not 1 <= jpeg_quality <= 100
    ):
        raise ValueError("jpeg_quality must be an integer from 1 to 100")

    coordinates = tuple(float(coordinate) for coordinate in bbox)
    if len(coordinates) != 4 or not all(math.isfinite(v) for v in coordinates):
        raise ValueError("bbox must contain four finite coordinates")
    x1, y1, x2, y2 = coordinates
    if x2 <= x1 or y2 <= y1:
        raise ValueError("bbox must have positive width and height")

    height, width = image.shape[:2]
    bbox_width = x2 - x1
    bbox_height = y2 - y1
    left = max(0, math.floor(x1 - margin * bbox_width))
    top = max(0, math.floor(y1 - margin * bbox_height))
    right = min(width, math.ceil(x2 + margin * bbox_width))
    bottom = min(height, math.ceil(y2 + margin * bbox_height))
    if right <= left or bottom <= top:
        raise ValueError("bbox does not intersect the image")

    crop_bgr = np.ascontiguousarray(image[top:bottom, left:right])
    crop_rgb = crop_bgr[:, :, ::-1]
    pil_image = Image.fromarray(crop_rgb, mode="RGB")
    resized = pil_image.resize(
        (out_size, out_size),
        resample=Image.Resampling.BILINEAR,
        reducing_gap=None,
    )

    encoded = io.BytesIO()
    resized.save(
        encoded,
        format="JPEG",
        quality=jpeg_quality,
        subsampling=2,
        optimize=False,
        progressive=False,
    )
    return encoded.getvalue()


def sha256_bytes(data: bytes) -> str:
    """Return the lowercase SHA-256 hex digest of bytes.

    For the upload audit hash, call this on the original uploaded bytes before
    decoding, resizing, drawing, or annotating the image::

        image_sha256 = sha256_bytes(uploaded_bytes)
    """

    return hashlib.sha256(data).hexdigest()


def _validate_image(image: np.ndarray) -> None:
    if not isinstance(image, np.ndarray):
        raise TypeError("image must be a numpy array")
    if image.dtype != np.uint8:
        raise ValueError("image must use uint8 pixels")
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("image must have shape (height, width, 3) in BGR order")
    if image.shape[0] == 0 or image.shape[1] == 0:
        raise ValueError("image dimensions must be non-zero")
