"""Image ingestion helpers shared by non-browser interfaces."""

from __future__ import annotations

import cv2
import numpy as np


def decode_image_bytes(data: bytes) -> np.ndarray:
    """Decode uploaded image bytes into OpenCV's BGR uint8 representation."""

    if not isinstance(data, bytes):
        raise TypeError("image data must be bytes")
    if not data:
        raise ValueError("image data must not be empty")
    encoded = np.frombuffer(data, dtype=np.uint8)
    try:
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    except cv2.error as exc:
        raise ValueError("photo is not a decodable image") from exc
    if image is None:
        raise ValueError("photo is not a decodable image")
    return image
