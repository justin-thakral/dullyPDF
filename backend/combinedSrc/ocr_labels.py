from __future__ import annotations

import re
from typing import Dict, List, Optional

import cv2
import numpy as np
import pytesseract

from .config import get_logger
from .coords import PageBox, px_bbox_to_pts_bbox

logger = get_logger(__name__)

_CHECKBOX_OCR_SINGLETONS = {"0", "O", "o", "6", "□", "■"}
_CHECKBOX_ARTIFACT_CORE_RE = re.compile(r"^[0Oo6]{1,4}$")


def _looks_like_checkbox_artifact(text: str, w_px: int, h_px: int) -> bool:
    """
    Return True when an OCR token likely corresponds to a checkbox/square glyph, not text.

    Motivation:
    - On scanned forms, Tesseract often "reads" an empty checkbox as `0` or `O`.
    - If we keep those tokens, our phrase grouper can merge real labels into junk like:
        "Gender 0 Male O Female"
      which then steals nearby underlines and creates false text fields.
    - Checkbox fields are detected via geometry; OCR should focus on labels.
    """
    token = (text or "").strip()
    if not token:
        return False
    if w_px <= 0 or h_px <= 0:
        return False
    size = max(int(w_px), int(h_px))
    aspect = float(w_px) / float(max(1, h_px))
    # Checkbox bboxes are roughly square and small compared to real words.
    #
    # NOTE:
    # - We OCR on a downscaled image (see `_maybe_downscale_for_ocr`), so checkbox glyphs
    #   typically fall in the ~20–40px range at 2200px width.
    # - Using a slightly higher cap avoids missing artifacts on less aggressively scaled pages.
    if not (0.70 <= aspect <= 1.30 and size <= 50):
        return False

    # OCR often adds punctuation to the checkbox "glyph" token:
    # - `0)` / `O)` / `O)=` prefixing real labels (e.g., `0) Colonoscopy`)
    # - mixed-case `oO` / `Oooo` for the same square artifact
    #
    # Strip common punctuation wrappers and then check for a small set of known checkbox-like
    # character clusters. We intentionally keep this tight to avoid dropping legitimate digits.
    compact = re.sub(r"\\s+", "", token)
    # Handle common bullet-like oddities (e.g., `©) ...`) without globally stripping `©` from text.
    compact = compact.lstrip("©")
    core = compact.strip("()[]{}<>.,;:+-=*'\"|/\\\\")
    if not core:
        core = compact

    if core in _CHECKBOX_OCR_SINGLETONS:
        return True
    if bool(_CHECKBOX_ARTIFACT_CORE_RE.fullmatch(core)):
        return True
    return False


def _is_punctuation_noise(text: str) -> bool:
    token = (text or "").strip()
    if not token:
        return True
    compact = re.sub(r"\\s+", "", token)
    if not compact:
        return True
    # Common OCR noise:
    # - divider-like punctuation (`----`, `____`, `|`, `=`) often coming from table rules
    # - stray quote marks / ticks
    # - lone periods introduced by OCR around faint text
    return bool(
        re.fullmatch(r"[_\\-|\\u2013\\u2014=]+", compact)
        or re.fullmatch(r"[\\\"'`]+", compact)
        or re.fullmatch(r"[.]{1,3}", compact)
    )


def _salvage_low_conf_token(text: str) -> Optional[str]:
    """
    Salvage an OCR token even when Tesseract confidence is low.

    Problem:
    - Tesseract can assign `conf=0` to real label words in dense form layouts (e.g., "Height").
      If we drop them, we miss legitimate fields because the resolver relies on labels.

    Strategy:
    - Be conservative: only salvage word-like tokens (>=3 letters) that look like form labels.
    - Strip leading/trailing punctuation so "Height." becomes "Height".
    """
    raw = (text or "").strip()
    if not raw:
        return None
    cleaned = re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$", "", raw)
    if not cleaned:
        return None
    letters = re.sub(r"[^A-Za-z]+", "", cleaned)
    if len(letters) < 3:
        return None
    # Prefer Title-Case style label words; this avoids salvaging lots of low-confidence noise.
    first_alpha = next((ch for ch in cleaned if ch.isalpha()), "")
    if first_alpha and not first_alpha.isupper():
        return None
    # Avoid extremely long junk tokens.
    if len(cleaned) > 28:
        return None
    return cleaned


def _maybe_downscale_for_ocr(image_bgr: np.ndarray, *, max_width_px: int = 2200) -> np.ndarray:
    """
    Downscale high-DPI renders for OCR to keep runtime reasonable.

    Notes:
    - We are mapping OCR pixel bboxes back to PDF points via `PageBox` and image dimensions.
      Downscaling is safe as long as we use the downscaled image dimensions consistently in
      px->pts conversion.
    - We keep aspect ratio and use `INTER_AREA` to preserve stroke quality.
    """
    if image_bgr is None:
        return image_bgr
    h, w = image_bgr.shape[:2]
    if w <= max_width_px:
        return image_bgr
    scale = max_width_px / float(w)
    new_w = int(round(w * scale))
    new_h = int(round(h * scale))
    resized = cv2.resize(image_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
    logger.debug("Downscaled OCR image: %sx%s -> %sx%s", w, h, new_w, new_h)
    return resized


def _preprocess_for_ocr(image_bgr: np.ndarray) -> np.ndarray:
    """
    Preprocess a rendered page image for OCR.

    Goal:
    - Improve contrast and suppress background shading so Tesseract can see small text.
    - Keep this lightweight (no heavy ML) so it remains fast enough for multi-page forms.
    """
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 7, 55, 55)
    # Adaptive threshold tends to work better on scanned pages with uneven lighting.
    binary = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        7,
    )
    return binary


def ocr_words_to_labels(
    image_bgr: np.ndarray,
    *,
    page_box: PageBox,
    min_confidence: int = 40,
    max_width_px: int = 2200,
    tess_config: Optional[str] = None,
) -> List[Dict]:
    """
    Run OCR on a page image and return word-like dicts compatible with `extract_labels.py`.

    Output word dicts:
      { text, x0, x1, top, bottom }
    where all coordinates are PDF points in originTop, unrotated CropBox space.

    We deliberately return *word-level* bboxes because the label grouper already merges
    words into phrase-level labels.
    """
    if image_bgr is None:
        return []

    image_bgr = _maybe_downscale_for_ocr(image_bgr, max_width_px=max_width_px)
    processed = _preprocess_for_ocr(image_bgr)
    rgb = cv2.cvtColor(processed, cv2.COLOR_GRAY2RGB)

    # `psm 6` assumes a uniform block of text, which generally works well for forms.
    # `oem 1` selects the LSTM engine for better small-text recognition.
    config = tess_config or "--oem 1 --psm 6"
    data = pytesseract.image_to_data(rgb, output_type=pytesseract.Output.DICT, config=config)

    words: List[Dict] = []
    confident_kept = 0
    low_conf_salvaged = 0
    skipped_noise = 0
    skipped_low_conf = 0
    n = len(data.get("text") or [])
    img_h, img_w = rgb.shape[:2]
    for i in range(n):
        text_raw = (data["text"][i] or "").strip()
        if not text_raw:
            continue
        try:
            conf = int(float(data["conf"][i]))
        except Exception:
            conf = -1

        x = int(data["left"][i])
        y = int(data["top"][i])
        w = int(data["width"][i])
        h = int(data["height"][i])
        if w <= 0 or h <= 0:
            continue

        # Drop high-frequency OCR noise to keep phrase grouping stable.
        if _looks_like_checkbox_artifact(text_raw, w, h) or _is_punctuation_noise(text_raw):
            skipped_noise += 1
            continue

        text = text_raw
        if conf < int(min_confidence):
            salvaged = _salvage_low_conf_token(text_raw)
            if not salvaged:
                skipped_low_conf += 1
                continue
            text = salvaged
            low_conf_salvaged += 1
        else:
            confident_kept += 1

        bbox_pts = px_bbox_to_pts_bbox((x, y, w, h), img_w, img_h, page_box)
        words.append(
            {
                "text": text,
                "x0": float(bbox_pts[0]),
                "x1": float(bbox_pts[2]),
                "top": float(bbox_pts[1]),
                "bottom": float(bbox_pts[3]),
            }
        )

    logger.info(
        "OCR extracted %s words (kept=%s salvagedLowConf=%s skippedLowConf=%s skippedNoise=%s min_conf=%s)",
        len(words),
        confident_kept,
        low_conf_salvaged,
        skipped_low_conf,
        skipped_noise,
        min_confidence,
    )
    return words
