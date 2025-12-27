from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import cv2
import numpy as np

from .config import get_logger
from .coords import PageBox, pts_bbox_to_px_bbox

logger = get_logger(__name__)


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
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.38
    text_thickness = 1
    tx = int(x1 + 2)
    ty = int(max(12, y1 - 4))
    cv2.putText(canvas, label, (tx, ty), font, font_scale, color_bgr, text_thickness, cv2.LINE_AA)


def draw_overlay(
    image_bgr: np.ndarray,
    page_candidates: Dict,
    fields: List[Dict],
    out_path: Path,
    *,
    draw_candidates: bool = True,
    draw_fields: bool = True,
    return_image: bool = False,
) -> Optional[np.ndarray]:
    """
    Draw a visual QA overlay for one page that includes candidates and fields.
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
        "field_text": (0, 0, 255),
        "field_checkbox": (0, 165, 255),
        "field_other": (0, 120, 255),
    }

    if draw_candidates:
        for label in page_candidates.get("labels", []) or []:
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

    if draw_fields:
        page_num = int(page_candidates.get("page") or 1)
        page_fields = [f for f in (fields or []) if int(f.get("page") or 1) == page_num]
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
            label = name[:28] + ("…" if len(name) > 28 else "")
            _draw_rect(
                canvas,
                bbox_pts=rect,
                image_width_px=image_width_px,
                image_height_px=image_height_px,
                page_box=page_box,
                color_bgr=color,
                thickness=2,
                label=label if label else None,
            )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(out_path), canvas)
    if not ok:
        raise RuntimeError(f"Failed to write overlay image: {out_path}")
    logger.info("Wrote overlay %s", out_path)
    if return_image:
        return canvas
    return None
