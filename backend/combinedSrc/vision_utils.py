from __future__ import annotations

import base64

import cv2
import numpy as np


def image_bgr_to_data_url(
    image_bgr: np.ndarray,
    *,
    format: str = "jpg",
    quality: int = 85,
) -> str:
    """
    Encode a BGR image into a data URL for OpenAI vision input.
    """
    fmt = format.lower().lstrip(".")
    ext = f".{fmt}"
    params = []
    if fmt in {"jpg", "jpeg"}:
        params = [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)]
    ok, buf = cv2.imencode(ext, image_bgr, params)
    if not ok:
        raise RuntimeError(f"Failed to encode image as {ext}")
    b64 = base64.b64encode(buf.tobytes()).decode("ascii")
    mime = "image/jpeg" if fmt in {"jpg", "jpeg"} else f"image/{fmt}"
    return f"data:{mime};base64,{b64}"
