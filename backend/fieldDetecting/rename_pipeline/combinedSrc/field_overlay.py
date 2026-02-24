"""
Overlay rendering helpers for QA and OpenAI rename prompts.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import cv2
import numpy as np

from .checkbox_label_hints import pick_best_checkbox_label
from .config import get_logger
from .coords import PageBox, pts_bbox_to_px_bbox

logger = get_logger(__name__)

_FONT = cv2.FONT_HERSHEY_SIMPLEX


def _clamp_int(value: float, lo: int, hi: int) -> int:
    return int(max(lo, min(hi, int(round(float(value))))))


def _to_px_corners(
    bbox_pts: Iterable[float],
    *,
    image_width_px: int,
    image_height_px: int,
    page_box: PageBox,
) -> Tuple[int, int, int, int]:
    """
    Convert a points bbox [x1,y1,x2,y2] into pixel-space corners (x1,y1,x2,y2).

    The pipeline stores geometry in originTop point space; we convert back into the
    rendered image pixel coordinates for visual QA overlays.
    """
    px = pts_bbox_to_px_bbox(bbox_pts, image_width_px, image_height_px, page_box)
    x1, y1, x2, y2 = px
    x1i = _clamp_int(x1, 0, image_width_px - 1)
    y1i = _clamp_int(y1, 0, image_height_px - 1)
    x2i = _clamp_int(x2, 0, image_width_px - 1)
    y2i = _clamp_int(y2, 0, image_height_px - 1)
    if x2i < x1i:
        x1i, x2i = x2i, x1i
    if y2i < y1i:
        y1i, y2i = y2i, y1i
    return x1i, y1i, x2i, y2i


def _draw_rect(
    canvas: np.ndarray,
    *,
    bbox_pts: Iterable[float],
    image_width_px: int,
    image_height_px: int,
    page_box: PageBox,
    color_bgr: Tuple[int, int, int],
    thickness: int,
    label: Optional[str] = None,
) -> None:
    x1, y1, x2, y2 = _to_px_corners(
        bbox_pts,
        image_width_px=image_width_px,
        image_height_px=image_height_px,
        page_box=page_box,
    )
    if x2 <= x1 or y2 <= y1:
        return
    cv2.rectangle(canvas, (x1, y1), (x2, y2), color_bgr, int(thickness))
    if not label:
        return

    # Keep labels compact so overlays stay readable.
    font = _FONT
    font_scale = 0.38
    text_thickness = 1
    tx = int(x1 + 2)
    ty = int(max(12, y1 - 4))
    cv2.putText(canvas, label, (tx, ty), font, font_scale, color_bgr, text_thickness, cv2.LINE_AA)


def _rect_distance_pts(a: List[float], b: List[float]) -> float:
    dx = max(float(b[0]) - float(a[2]), float(a[0]) - float(b[2]), 0.0)
    dy = max(float(b[1]) - float(a[3]), float(a[1]) - float(b[3]), 0.0)
    return math.hypot(dx, dy)


def _fit_text_in_box(text: str, *, max_width: int, max_height: int) -> tuple[str, float]:
    """
    Choose a readable label + font scale that fits inside a box.

    We search for the largest scale that fits, then truncate and fall back to a
    smaller scale when space is tight.
    """
    label = (text or "").strip()
    if not label:
        return "", 0.0

    thickness = 1
    max_width = max(1, int(max_width))
    max_height = max(1, int(max_height))

    scale = 0.7
    min_scale = 0.28
    for _ in range(12):
        (tw, th), baseline = cv2.getTextSize(label, _FONT, scale, thickness)
        height = th + baseline
        if tw <= max_width and height <= max_height:
            return label, scale
        scale *= 0.88
        if scale < min_scale:
            break

    scale = max(min_scale, min(0.42, max_height / 22.0))
    if len(label) > 12:
        label = f"{label[:10]}…"
    return label, scale


def _draw_text_with_outline(
    canvas: np.ndarray,
    text: str,
    org: Tuple[int, int],
    *,
    font_scale: float,
    color_bgr: Tuple[int, int, int],
    thickness: int = 1,
    outline_bgr: Tuple[int, int, int] = (0, 0, 0),
    outline_thickness: int = 3,
) -> None:
    if not text:
        return
    cv2.putText(canvas, text, org, _FONT, font_scale, outline_bgr, outline_thickness, cv2.LINE_AA)
    cv2.putText(canvas, text, org, _FONT, font_scale, color_bgr, thickness, cv2.LINE_AA)


def _draw_centered_label(
    canvas: np.ndarray,
    *,
    label: str,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
) -> None:
    if not label:
        return
    box_w = max(1, x2 - x1)
    box_h = max(1, y2 - y1)
    pad_x = max(2, int(round(box_w * 0.05)))
    pad_y = max(2, int(round(box_h * 0.05)))
    inner_w = max(1, box_w - (pad_x * 2))
    inner_h = max(1, box_h - (pad_y * 2))
    target_h = inner_h
    (base_w, base_h), base_baseline = cv2.getTextSize(label, _FONT, 1.0, 1)
    if base_w <= 0 or base_h <= 0:
        return
    scale_by_height = target_h / max(1.0, base_h + base_baseline)
    scale_by_width = inner_w / max(1.0, base_w)
    scale = max(0.4, min(scale_by_height, scale_by_width, 8.0))
    (tw, th), _baseline = cv2.getTextSize(label, _FONT, scale, 1)
    tx = int(x1 + (x2 - x1 - tw) / 2)
    ty = int(y1 + (y2 - y1 + th) / 2)
    thickness = 2 if scale >= 1.2 else 1
    outline = 5 if scale >= 1.4 else 4
    _draw_text_with_outline(
        canvas,
        label,
        (tx, ty),
        font_scale=scale,
        color_bgr=(255, 255, 255),
        thickness=thickness,
        outline_thickness=outline,
    )


def _pick_checkbox_label(
    checkbox_rect: List[float],
    labels: List[Dict],
) -> Optional[Dict]:
    """
    Pick the most likely label for a checkbox based on proximity and alignment.

    Time complexity:
    - O(L) for L candidate labels on the page.
    """
    return pick_best_checkbox_label(checkbox_rect, labels)


def _fit_checkbox_tag(
    label: str,
    *,
    box_w: int,
    box_h: int,
    preferred_scale: float,
) -> tuple[str, float]:
    """
    Fit checkbox tag text inside checkbox bounds while preserving readability.
    """
    text = (label or "").strip()
    if not text:
        return "", 0.0

    inner_w = max(1, int(round(max(1, box_w) * 0.84)))
    inner_h = max(1, int(round(max(1, box_h) * 0.84)))
    max_scale = max(0.28, min(4.0, float(preferred_scale)))
    min_scale = 0.10
    attempt = text
    for _ in range(max(2, len(text) + 2)):
        (base_w, base_h), base_baseline = cv2.getTextSize(attempt, _FONT, 1.0, 1)
        if base_w <= 0 or base_h <= 0:
            return "", 0.0

        scale_by_width = inner_w / max(1.0, base_w)
        scale_by_height = inner_h / max(1.0, base_h + base_baseline)
        fitted_scale = min(max_scale, scale_by_width, scale_by_height)
        if fitted_scale >= min_scale:
            return attempt, fitted_scale

        if len(attempt) <= 1:
            break
        if len(attempt) == 2:
            attempt = attempt[:1]
        else:
            attempt = f"{attempt[:-2]}…"

    # Final fallback for extremely tiny boxes.
    return attempt[:1], min_scale


def _draw_checkbox_tag(
    canvas: np.ndarray,
    *,
    label: str,
    cb_px: Tuple[int, int, int, int],
    color_bgr: Tuple[int, int, int],
    tag_scale: float = 1.6,
) -> None:
    x1, y1, x2, y2 = cb_px
    if x2 <= x1 or y2 <= y1 or not label:
        return

    fitted_label, scale = _fit_checkbox_tag(
        label,
        box_w=(x2 - x1),
        box_h=(y2 - y1),
        preferred_scale=tag_scale,
    )
    if not fitted_label or scale <= 0.0:
        return

    (tw, th), _baseline = cv2.getTextSize(fitted_label, _FONT, scale, 1)
    tx = int(round(x1 + (x2 - x1 - tw) / 2))
    ty = int(round(y1 + (y2 - y1 + th) / 2))
    tx = max(x1 + 1, min(tx, x2 - max(2, tw)))
    ty = max(y1 + max(2, th), min(ty, y2 - 1))
    thickness = 2 if scale >= 1.2 else 1
    outline = 4 if scale >= 1.2 else 3
    _draw_text_with_outline(
        canvas,
        fitted_label,
        (tx, ty),
        font_scale=scale,
        color_bgr=color_bgr,
        thickness=thickness,
        outline_thickness=outline,
    )


def draw_overlay(
    image_bgr: np.ndarray,
    page_candidates: Dict,
    fields: List[Dict],
    out_path: Path,
    *,
    draw_candidates: bool = True,
    draw_fields: bool = True,
    field_labels_inside: bool = False,
    label_max_dist_pts: float | None = None,
    highlight_checkbox_labels: bool = False,
    checkbox_tag_scale: float = 1.6,
    return_image: bool = False,
) -> Optional[np.ndarray]:
    """
    Draw a visual QA overlay for one page that includes candidates and fields.

    Code steps:
    1) Resolve page/image geometry and select fields belonging to this page.
    2) Optionally draw detector candidates (labels/lines/boxes/checkboxes).
    3) Draw final fields with type-aware colors and compact tags.
    4) Persist the overlay to disk and optionally return the rendered canvas.

    Time complexity:
    - Candidate label filtering can reach O(L * F) where L is labels and F is fields.
    - Remaining draw passes are linear in candidate/field counts.
    """
    if image_bgr is None or image_bgr.size == 0:
        raise ValueError("draw_overlay received an empty image")

    img_h, img_w = image_bgr.shape[:2]
    image_width_px = int(page_candidates.get("imageWidthPx") or img_w)
    image_height_px = int(page_candidates.get("imageHeightPx") or img_h)
    page_box = PageBox(
        page_width=float(page_candidates.get("pageWidth") or 0.0),
        page_height=float(page_candidates.get("pageHeight") or 0.0),
        rotation=int(page_candidates.get("rotation") or 0),
    )

    canvas = image_bgr.copy()

    colors = {
        "label": (200, 200, 200),
        "line": (255, 255, 0),
        "box": (0, 200, 0),
        "checkbox": (255, 0, 255),
        "checkbox_tag": (180, 0, 180),
        "field_text": (0, 0, 255),
        "field_checkbox": (0, 165, 255),
        "field_other": (0, 120, 255),
        "checkbox_hint": (0, 140, 255),
    }

    page_num = int(page_candidates.get("page") or 1)
    # Step 1: Keep only fields assigned to the current page to avoid cross-page noise.
    page_fields = [f for f in (fields or []) if int(f.get("page") or 1) == page_num]
    field_rects_pts = [
        [float(v) for v in f.get("rect") or []]
        for f in page_fields
        if isinstance(f.get("rect"), list) and len(f.get("rect")) == 4
    ]

    # Step 2: Optionally draw candidate geometry used during rename prompt generation.
    if draw_candidates:
        labels = list(page_candidates.get("labels", []) or [])
        keep_label_indexes: set[int] = set()

        # Optionally limit label rendering to those near fields to reduce overlay noise.
        # This nearest-distance pass is O(L * F) with labels-by-fields comparisons.
        if label_max_dist_pts is not None and field_rects_pts:
            max_dist = float(label_max_dist_pts)
            for idx, label in enumerate(labels):
                bbox = label.get("bbox")
                if not isinstance(bbox, list) or len(bbox) != 4:
                    continue
                b = [float(v) for v in bbox]
                min_dist = None
                for rect in field_rects_pts:
                    dist = _rect_distance_pts(rect, b)
                    if min_dist is None or dist < min_dist:
                        min_dist = dist
                if min_dist is not None and min_dist <= max_dist:
                    keep_label_indexes.add(idx)

        # Highlight the label we would attach to each checkbox when debugging.
        if highlight_checkbox_labels and labels:
            for f in page_fields:
                if str(f.get("type") or "").lower() != "checkbox":
                    continue
                rect = f.get("rect")
                if not isinstance(rect, list) or len(rect) != 4:
                    continue
                hint_bbox = f.get("labelHintBbox")
                picked = None
                if isinstance(hint_bbox, list) and len(hint_bbox) == 4:
                    for idx, label in enumerate(labels):
                        if label.get("bbox") == hint_bbox:
                            keep_label_indexes.add(idx)
                            picked = label
                            break
                if picked is None:
                    picked = _pick_checkbox_label([float(v) for v in rect], labels)
                    if picked is None:
                        continue
                    try:
                        keep_label_indexes.add(labels.index(picked))
                    except ValueError:
                        continue

        for idx, label in enumerate(labels):
            if keep_label_indexes and idx not in keep_label_indexes:
                continue
            bbox = label.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            text = (label.get("text") or "").strip()
            tag = text[:28] + ("…" if len(text) > 28 else "")
            _draw_rect(
                canvas,
                bbox_pts=bbox,
                image_width_px=image_width_px,
                image_height_px=image_height_px,
                page_box=page_box,
                color_bgr=colors["label"],
                thickness=1,
                label=tag if tag else None,
            )

        for ln in page_candidates.get("lineCandidates", []) or []:
            bbox = ln.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            _draw_rect(
                canvas,
                bbox_pts=bbox,
                image_width_px=image_width_px,
                image_height_px=image_height_px,
                page_box=page_box,
                color_bgr=colors["line"],
                thickness=2,
                label=ln.get("id") if ln.get("id") else None,
            )

        for bx in page_candidates.get("boxCandidates", []) or []:
            bbox = bx.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            _draw_rect(
                canvas,
                bbox_pts=bbox,
                image_width_px=image_width_px,
                image_height_px=image_height_px,
                page_box=page_box,
                color_bgr=colors["box"],
                thickness=2,
                label=bx.get("id") if bx.get("id") else None,
            )

        for cb in page_candidates.get("checkboxCandidates", []) or []:
            bbox = cb.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            detector = cb.get("detector")
            suffix = f" ({detector})" if detector else ""
            _draw_rect(
                canvas,
                bbox_pts=bbox,
                image_width_px=image_width_px,
                image_height_px=image_height_px,
                page_box=page_box,
                color_bgr=colors["checkbox"],
                thickness=2,
                label=(cb.get("id") + suffix) if cb.get("id") else None,
            )

    # Step 3: Draw the final field boxes and IDs that OpenAI consumes.
    if draw_fields:
        labels = list(page_candidates.get("labels", []) or [])
        for f in page_fields:
            rect = f.get("rect")
            if not rect or len(rect) != 4:
                continue
            ftype = (f.get("type") or "").lower()
            if ftype == "checkbox":
                color = colors["field_checkbox"]
            elif ftype in ("text", "date"):
                color = colors["field_text"]
            else:
                color = colors["field_other"]
            name = (f.get("displayName") or f.get("name") or "").strip()
            label_text = name[:28] + ("…" if len(name) > 28 else "")
            if not field_labels_inside:
                _draw_rect(
                    canvas,
                    bbox_pts=rect,
                    image_width_px=image_width_px,
                    image_height_px=image_height_px,
                    page_box=page_box,
                    color_bgr=color,
                    thickness=2,
                    label=label_text if label_text else None,
                )
                continue

            x1, y1, x2, y2 = _to_px_corners(
                rect,
                image_width_px=image_width_px,
                image_height_px=image_height_px,
                page_box=page_box,
            )
            if x2 <= x1 or y2 <= y1:
                continue
            cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)

            if ftype == "checkbox":
                _draw_checkbox_tag(
                    canvas,
                    label=label_text,
                    cb_px=(x1, y1, x2, y2),
                    color_bgr=colors["checkbox_tag"],
                    tag_scale=checkbox_tag_scale,
                )
                if highlight_checkbox_labels and labels and isinstance(rect, list):
                    hint_bbox = f.get("labelHintBbox")
                    picked = None
                    if isinstance(hint_bbox, list) and len(hint_bbox) == 4:
                        for label in labels:
                            if label.get("bbox") == hint_bbox:
                                picked = label
                                break
                    if picked is None:
                        picked = _pick_checkbox_label([float(v) for v in rect], labels)
                    if picked and isinstance(picked.get("bbox"), list) and len(picked["bbox"]) == 4:
                        lbx1, lby1, lbx2, lby2 = _to_px_corners(
                            picked["bbox"],
                            image_width_px=image_width_px,
                            image_height_px=image_height_px,
                            page_box=page_box,
                        )
                        start = (int((x1 + x2) / 2), int((y1 + y2) / 2))
                        end = (int((lbx1 + lbx2) / 2), int((lby1 + lby2) / 2))
                        cv2.arrowedLine(canvas, start, end, colors["checkbox_hint"], 2, tipLength=0.2)
                        cv2.rectangle(canvas, (lbx1, lby1), (lbx2, lby2), colors["checkbox_hint"], 2)
            else:
                _draw_centered_label(canvas, label=label_text, x1=x1, y1=y1, x2=x2, y2=y2)

    # Step 4: Write overlay artifact for QA/debugging and optional model packaging.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(out_path), canvas)
    if not ok:
        raise RuntimeError(f"Failed to write overlay image: {out_path}")
    logger.info("Wrote overlay %s", out_path)
    if return_image:
        return canvas
    return None
