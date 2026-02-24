"""
Shared checkbox-label hint helpers used by overlay rendering and rename prompts.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable, List, Optional


def _rect_distance_pts(a: List[float], b: List[float]) -> float:
    dx = max(float(b[0]) - float(a[2]), float(a[0]) - float(b[2]), 0.0)
    dy = max(float(b[1]) - float(a[3]), float(a[1]) - float(b[3]), 0.0)
    return math.hypot(dx, dy)


def pick_best_checkbox_label(
    checkbox_rect: List[float],
    labels: Iterable[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Pick the most likely label for a checkbox based on proximity and alignment.

    Time complexity:
    - O(L) for L candidate labels on the page.
    """
    if not checkbox_rect or len(checkbox_rect) != 4:
        return None
    cb_x1, cb_y1, cb_x2, cb_y2 = [float(v) for v in checkbox_rect]
    cb_h = max(1.0, cb_y2 - cb_y1)
    cb_center_y = (cb_y1 + cb_y2) / 2.0

    best: Optional[Dict[str, Any]] = None
    best_score: float | None = None

    for label in labels or []:
        bbox = label.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        text = (label.get("text") or "").strip()
        if not text:
            continue

        x1, y1, x2, y2 = [float(v) for v in bbox]
        label_center_y = (y1 + y2) / 2.0
        overlap = min(cb_y2, y2) - max(cb_y1, y1)
        overlap_ratio = max(0.0, overlap) / cb_h

        # Prefer labels to the right and near the checkbox centerline, while still
        # allowing overlap when text sits tight to the box.
        right_bias = 0.0 if x1 >= (cb_x2 - cb_h * 0.5) else 40.0
        alignment_penalty = abs(label_center_y - cb_center_y) / max(1.0, cb_h) * 8.0
        overlap_bonus = -12.0 if overlap_ratio >= 0.25 else 0.0

        dist = _rect_distance_pts([cb_x1, cb_y1, cb_x2, cb_y2], [x1, y1, x2, y2])
        score = dist + right_bias + alignment_penalty + overlap_bonus
        if best_score is None or score < best_score:
            best_score = score
            best = label

    return best


def normalize_checkbox_hint_text(text: str, *, max_chars: int = 48) -> str:
    """
    Normalize OCR label text for prompt-safe checkbox option hints.
    """
    cleaned = re.sub(r"[\r\n\t]+", " ", (text or "")).strip().replace('"', "'")
    if max_chars <= 0:
        return cleaned
    if len(cleaned) > max_chars:
        return cleaned[: max_chars - 1] + "…"
    return cleaned
