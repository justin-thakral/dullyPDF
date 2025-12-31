import math
import os
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from .concurrency import resolve_workers, run_threaded_map
from .config import get_logger
from .coords import PageBox, get_scale_factors, px_bbox_to_pts_bbox
from ..ML.ml_detector import detect_ml_geometry

logger = get_logger(__name__)

# Inline blank detection is recall-biased; thresholds can be loosened via env vars.
UNDERLINE_ABOVE_RATIO = float(os.getenv("SANDBOX_UNDERLINE_ABOVE_RATIO", "0.22"))
UNDERLINE_BELOW_RATIO = float(os.getenv("SANDBOX_UNDERLINE_BELOW_RATIO", "0.26"))
UNDERLINE_SHORT_NEAR_ABOVE_RATIO = float(
    os.getenv("SANDBOX_UNDERLINE_SHORT_NEAR_ABOVE_RATIO", "0.16")
)
UNDERLINE_SHORT_ABOVE_RATIO = float(os.getenv("SANDBOX_UNDERLINE_SHORT_ABOVE_RATIO", "0.16"))
UNDERLINE_SHORT_BELOW_RATIO = float(os.getenv("SANDBOX_UNDERLINE_SHORT_BELOW_RATIO", "0.22"))
UNDERLINE_SHORT_WIDE_ABOVE_RATIO = float(
    os.getenv("SANDBOX_UNDERLINE_SHORT_WIDE_ABOVE_RATIO", "0.14")
)

def _to_points_bbox(
    bbox_px: Tuple[int, int, int, int],
    image_width_px: int,
    image_height_px: int,
    page_box: PageBox,
) -> List[float]:
    """Convert an OpenCV pixel rect (x,y,w,h) to PDF points (originTop, cropbox space)."""
    return px_bbox_to_pts_bbox(bbox_px, image_width_px, image_height_px, page_box)


def _inter_area_px(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> int:
    """
    Return intersection area between two pixel-space bounding boxes.

    Used to filter overlapping artifacts (decorative headers, checkbox borders).
    """
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0
    return int(ix2 - ix1) * int(iy2 - iy1)


def _detect_horizontal_lines(
    binary: np.ndarray,
    text_mask: np.ndarray,
    image_width_px: int,
    image_height_px: int,
    page_box: PageBox,
    vertical_mask: np.ndarray | None = None,
    gray: np.ndarray | None = None,
) -> List[Dict]:
    """Detect likely underline segments representing text inputs (long rules)."""
    return _detect_horizontal_lines_morph(
        binary,
        text_mask,
        image_width_px,
        image_height_px,
        page_box,
        kernel_width_px=max(40, binary.shape[1] // 80),
        min_length_pt=24.0,
        max_length_pt=None,
        max_thickness_pt=8.0,
        detector="morph_long",
        vertical_mask=vertical_mask,
        gray=gray,
    )


def _build_vertical_mask(binary: np.ndarray, image_height_px: int) -> np.ndarray:
    """
    Extract a vertical-line mask from a permissive binary image.

    This is used to:
    - Identify table/grid structures (lots of vertical rules).
    - Filter out short horizontal segments that are actually table cell borders.
    """
    kernel_height_px = max(35, image_height_px // 80)
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, kernel_height_px))
    return cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel, iterations=1)


def _build_horizontal_mask(binary: np.ndarray, image_width_px: int) -> np.ndarray:
    """
    Extract a horizontal-line mask from a permissive binary image.

    This is used to detect "grid-like" rectangles (tables) so we don't emit one giant
    box candidate for an entire table region.
    """
    kernel_width_px = max(35, image_width_px // 80)
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_width_px, 2))
    return cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel, iterations=1)


def _has_vertical_at_both_ends(
    vertical_mask: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
    *,
    pad_y_px: int = 4,
    end_band_px: int = 8,
) -> bool:
    """
    Return True when a (short) horizontal segment intersects vertical lines on BOTH ends.

    This is a strong signal that the segment is a piece of a grid/table rule, not an
    underline meant for data entry.
    """
    if vertical_mask is None or vertical_mask.size == 0:
        return False
    if w <= 0 or h <= 0:
        return False

    h_img, w_img = vertical_mask.shape[:2]
    y0 = max(0, y - pad_y_px)
    y1 = min(h_img, y + h + pad_y_px)
    x0 = max(0, x)
    x1 = min(w_img, x + w)
    if y0 >= y1 or x0 >= x1:
        return False

    band = max(3, min(int(end_band_px), max(3, w // 3)))
    left = vertical_mask[y0:y1, x0 : min(x0 + band, x1)]
    right = vertical_mask[y0:y1, max(x1 - band, x0) : x1]
    return int(np.count_nonzero(left)) > 0 and int(np.count_nonzero(right)) > 0


def _has_vertical_near_both_ends(
    vertical_mask: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
    *,
    pad_x_px: int,
    scan_up_px: int,
    scan_down_px: int,
    end_band_px: int,
) -> bool:
    """
    Return True when vertical-rule ink appears near BOTH ends of a horizontal segment.

    This is used to filter decorative "pill"/header borders that show up as underline
    candidates:
    - The underline morphology passes tend to isolate the bottom border as a horizontal
      line, while the vertical "endcaps" can sit slightly outside the line bbox (rounded
      corners or thresholding artifacts).
    - By expanding the ROI slightly in X and scanning a taller band above the line, we
      can detect those endcaps and drop the false underline candidate.
    """
    if vertical_mask is None or vertical_mask.size == 0:
        return False
    if w <= 0 or h <= 0:
        return False

    h_img, w_img = vertical_mask.shape[:2]
    x0 = max(0, int(x) - int(pad_x_px))
    x1 = min(w_img, int(x + w) + int(pad_x_px))
    y0 = max(0, int(y) - int(scan_up_px))
    y1 = min(h_img, int(y + h) + int(scan_down_px))
    if x1 <= x0 or y1 <= y0:
        return False

    band = max(4, min(int(end_band_px), int(round((x1 - x0) * 0.12))))
    band = max(4, min(band, max(4, (x1 - x0) // 3)))

    left = vertical_mask[y0:y1, x0 : min(x0 + band, x1)]
    right = vertical_mask[y0:y1, max(x1 - band, x0) : x1]
    if left.size == 0 or right.size == 0:
        return False

    left_nz = int(np.count_nonzero(left))
    right_nz = int(np.count_nonzero(right))
    # Require both ends to contain a meaningful amount of vertical ink. This avoids
    # triggering on isolated noise pixels.
    min_nz = 18
    min_ratio = 0.03
    left_ratio = float(left_nz) / float(left.size)
    right_ratio = float(right_nz) / float(right.size)
    return (
        left_nz >= min_nz
        and right_nz >= min_nz
        and left_ratio >= min_ratio
        and right_ratio >= min_ratio
    )


def _detect_horizontal_lines_morph(
    binary: np.ndarray,
    text_mask: np.ndarray,
    image_width_px: int,
    image_height_px: int,
    page_box: PageBox,
    *,
    kernel_width_px: int,
    min_length_pt: float,
    max_length_pt: float | None,
    max_thickness_pt: float,
    detector: str,
    vertical_mask: np.ndarray | None,
    gray: np.ndarray | None = None,
) -> List[Dict]:
    """
    Detect near-horizontal segments using morphology and contour bounding boxes.

    Note on "charts"/questionnaires:
    - Scanned medical forms often encode "score blanks" as short underscore lines.
      These are real text inputs but are much shorter than typical name/address underlines.
    - We handle them via a second (short-line) pass with a smaller kernel and lower
      min_length_pt, while filtering out grid/table cell borders.
    """
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (int(kernel_width_px), 2))
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel, iterations=1)
    contours, _ = cv2.findContours(horizontal, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    segments: List[Tuple[int, int, int, int]] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w <= 0 or h <= 0:
            continue

        # Pixel-space gating first to keep point conversions cheap.
        # Underlines are skinny; very tall bboxes are usually paragraph blobs.
        if h > 28:
            continue
        if w < 8:
            continue
        segments.append((int(x), int(y), int(x + w), int(y + h)))

    # Merge adjacent segments on the same row. This is essential for questionnaire blanks like
    # "____", which are multiple underscore glyphs separated by small gaps.
    # Score questionnaires often render blanks as "____" where underscore glyphs have
    # relatively large gaps (especially after thresholding). Use a larger tolerance so the
    # full blank becomes a single candidate.
    # `morph_short` is used for underscore-style blanks. We want to merge glyph fragments
    # inside ONE blank, but we must avoid merging across neighboring blanks/checkboxes.
    # A too-large tolerance merges an entire row into one candidate and then gets filtered out.
    # Merge tolerance: underscore blanks need some tolerance, but excessive merging can
    # combine unrelated glyph strokes into long segments and explode candidate counts.
    merge_x_gap_tol = max(12, min(35, int(image_width_px // 140))) if detector == "morph_short" else 20
    merged_bboxes = _merge_horizontal_segments(
        segments,
        y_tol=4 if detector == "morph_short" else 3,
        x_gap_tol=merge_x_gap_tol,
    )

    candidates: List[Dict] = []
    # A line used as an input underline typically has blank space immediately above it.
    # Underlined *words* (styling) and dense text rows can produce short horizontal strokes
    # that should not be treated as fillable fields. We detect those by measuring how much
    # "ink" sits above the line within the mid-span of the candidate.
    _, sy = get_scale_factors(image_width_px, image_height_px, page_box)
    band_height_px = int(round(12.0 / max(sy, 1e-6)))
    band_height_px = max(20, min(band_height_px, 160))

    for x, y, w, h in merged_bboxes:
        if _looks_like_shaded_header_rule(
            gray,
            int(x),
            int(y),
            int(w),
            int(h),
            band_height_px=band_height_px,
        ):
            continue
        if detector == "morph_short":
            if _looks_like_text_underline_short(
                text_mask,
                int(x),
                int(y),
                int(w),
                int(h),
                band_height_px=band_height_px,
            ):
                continue
        else:
            if _looks_like_text_underline(
                text_mask,
                int(x),
                int(y),
                int(w),
                int(h),
                band_height_px=band_height_px,
            ):
                continue
        bbox_pts = _to_points_bbox((x, y, w, h), image_width_px, image_height_px, page_box)
        length_pt = float(bbox_pts[2] - bbox_pts[0])
        thickness_pt = float(bbox_pts[3] - bbox_pts[1])

        if thickness_pt > float(max_thickness_pt):
            continue
        if length_pt < float(min_length_pt):
            continue
        if max_length_pt is not None and length_pt > float(max_length_pt):
            continue

        # Filter out short grid/table rule segments (intersecting vertical rules at both ends).
        if vertical_mask is not None and length_pt <= 60:
            if _has_vertical_at_both_ends(vertical_mask, int(x), int(y), int(w), int(h)):
                continue
        # Filter out decorative header "pill" borders:
        # - These are often ~80–170pt wide and have vertical endcaps.
        # - The endcaps can sit slightly outside the extracted line bbox, so we scan a padded ROI.
        if vertical_mask is not None and 80.0 < float(length_pt) <= 170.0:
            scan_up_px = max(18, min(180, int(round(band_height_px * 1.4))))
            scan_down_px = max(6, min(60, int(round(band_height_px * 0.35))))
            pad_x_px = max(10, min(22, int(round(band_height_px * 0.18))))
            end_band_px = max(8, min(14, int(round(band_height_px * 0.12))))
            if _has_vertical_near_both_ends(
                vertical_mask,
                int(x),
                int(y),
                int(w),
                int(h),
                pad_x_px=pad_x_px,
                scan_up_px=scan_up_px,
                scan_down_px=scan_down_px,
                end_band_px=end_band_px,
            ):
                continue

        candidates.append(
            {
                "bbox": bbox_pts,
                "bboxPx": [int(x), int(y), int(x + w), int(y + h)],
                "length": length_pt,
                "thickness": thickness_pt,
                "type": "line",
                "detector": detector,
            }
        )
    return candidates


def _merge_horizontal_segments(
    segments: List[Tuple[int, int, int, int]],
    *,
    y_tol: int = 3,
    x_gap_tol: int = 20,
) -> List[Tuple[int, int, int, int]]:
    """
    Merge horizontal line segments into longer pixel-space bboxes.

    This is primarily used for Hough-based detection, where dotted underlines can produce
    multiple adjacent segments that should become a single candidate.
    """
    if not segments:
        return []

    normalized: List[Tuple[int, int, int, int]] = []
    for x1, y1, x2, y2 in segments:
        if x2 < x1:
            x1, x2 = x2, x1
        if y2 < y1:
            y1, y2 = y2, y1
        normalized.append((x1, y1, x2, y2))
    normalized.sort(key=lambda s: (s[1], s[0]))

    merged: List[Tuple[int, int, int, int]] = []
    # pixels: segments on the same underline will share similar y.
    y_tol = int(y_tol)
    # pixels: allow small gaps between dotted/underscore segments.
    x_gap_tol = int(x_gap_tol)

    cur_x1, cur_y1, cur_x2, cur_y2 = normalized[0]
    for x1, y1, x2, y2 in normalized[1:]:
        same_row = abs(((y1 + y2) / 2.0) - ((cur_y1 + cur_y2) / 2.0)) <= y_tol
        # Treat segments as mergeable if they overlap (or nearly overlap) in X.
        #
        # Important: segments are sorted primarily by Y, so segments considered "same_row"
        # can still arrive out-of-order in X when their Y differs slightly (scan jitter).
        # A one-sided check like `x1 <= cur_x2 + x_gap_tol` can incorrectly merge a far-left
        # segment into a far-right one (because the inequality is trivially true), and if we
        # then fail to expand `cur_x1`, we can *drop* the left segment entirely.
        #
        # This manifested on `medical-history-intake-form.pdf` where "First Name ____" was
        # present in the morphology mask but never emitted as a candidate, causing downstream
        # label->underline matches to shift (First Name matched Middle Name underline, etc.).
        overlaps_or_close = (x1 <= cur_x2 + x_gap_tol) and (x2 >= cur_x1 - x_gap_tol)
        if same_row and overlaps_or_close:
            cur_x1 = min(cur_x1, x1)
            cur_x2 = max(cur_x2, x2)
            cur_y1 = min(cur_y1, y1)
            cur_y2 = max(cur_y2, y2)
            continue
        merged.append((cur_x1, cur_y1, cur_x2 - cur_x1, max(2, cur_y2 - cur_y1)))
        cur_x1, cur_y1, cur_x2, cur_y2 = x1, y1, x2, y2
    merged.append((cur_x1, cur_y1, cur_x2 - cur_x1, max(2, cur_y2 - cur_y1)))
    return merged


def _detect_horizontal_lines_hough(
    gray: np.ndarray,
    text_mask: np.ndarray,
    image_width_px: int,
    image_height_px: int,
    page_box: PageBox,
    vertical_mask: np.ndarray | None = None,
) -> List[Dict]:
    """
    Secondary underline detector using Canny + HoughLinesP.

    This is a fallback for faint/dotted underlines that may be missed by thresholding +
    morphology. We only keep long, near-horizontal segments.
    """
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(blurred, threshold1=30, threshold2=120, apertureSize=3)
    # Bridge small gaps (dotted lines) before Hough.
    edges = cv2.dilate(edges, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 1)), iterations=1)

    # Hough is a fallback used only when morphology produced very few underlines. Keep this
    # conservative so we don't pick up decorative header borders and short rule segments.
    #
    # We express the threshold in points to make it stable across render DPI.
    sx, _ = get_scale_factors(image_width_px, image_height_px, page_box)
    min_line_length = int(round(120.0 / max(sx, 1e-6)))
    min_line_length = max(min_line_length, max(260, image_width_px // 10))
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180.0,
        threshold=120,
        minLineLength=min_line_length,
        maxLineGap=30,
    )
    if lines is None:
        return []

    segments: List[Tuple[int, int, int, int]] = []
    for x1, y1, x2, y2 in lines[:, 0, :]:
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
        if abs(y2 - y1) > 2:
            continue
        if abs(x2 - x1) < min_line_length:
            continue
        segments.append((x1, y1, x2, y2))

    merged_bboxes = _merge_horizontal_segments(segments)
    candidates: List[Dict] = []
    for x, y, w, h in merged_bboxes:
        _, sy = get_scale_factors(image_width_px, image_height_px, page_box)
        band_height_px = int(round(12.0 / max(sy, 1e-6)))
        band_height_px = max(20, min(band_height_px, 160))
        if _looks_like_text_underline(
            text_mask,
            int(x),
            int(y),
            int(w),
            int(h),
            band_height_px=band_height_px,
        ):
            continue
        bbox_pts = _to_points_bbox((x, y, w, h), image_width_px, image_height_px, page_box)
        length_pt = bbox_pts[2] - bbox_pts[0]
        thickness_pt = bbox_pts[3] - bbox_pts[1]
        if length_pt < 24 or thickness_pt > 8:
            continue
        if vertical_mask is not None and 80.0 < float(length_pt) <= 170.0:
            _, sy = get_scale_factors(image_width_px, image_height_px, page_box)
            band_height_px = int(round(12.0 / max(sy, 1e-6)))
            band_height_px = max(20, min(band_height_px, 160))
            scan_up_px = max(18, min(180, int(round(band_height_px * 1.4))))
            scan_down_px = max(6, min(60, int(round(band_height_px * 0.35))))
            pad_x_px = max(10, min(22, int(round(band_height_px * 0.18))))
            end_band_px = max(8, min(14, int(round(band_height_px * 0.12))))
            if _has_vertical_near_both_ends(
                vertical_mask,
                int(x),
                int(y),
                int(w),
                int(h),
                pad_x_px=pad_x_px,
                scan_up_px=scan_up_px,
                scan_down_px=scan_down_px,
                end_band_px=end_band_px,
            ):
                continue
        candidates.append(
            {
                "bbox": bbox_pts,
                "bboxPx": [int(x), int(y), int(x + w), int(y + h)],
                "length": length_pt,
                "thickness": thickness_pt,
                "type": "line",
                "detector": "hough",
            }
        )
    return candidates


def _enhance_contrast(gray: np.ndarray) -> np.ndarray:
    """Boost contrast to help detect faint rule lines."""
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def _binarize_for_line_detection(gray: np.ndarray, image_width_px: int) -> np.ndarray:
    """
    Build a permissive binary mask for underline detection.

    We combine:
    - Otsu inverse threshold: high precision on high-contrast forms.
    - Adaptive inverse threshold: rescues low-contrast / unevenly lit scans.
    - Blackhat: emphasizes thin strokes on light backgrounds (dotted underlines).

    We then horizontally close to connect dotted segments before applying a horizontal
    morphology pass in _detect_horizontal_lines().
    """
    gray_eq = _enhance_contrast(gray)
    blurred = cv2.GaussianBlur(gray_eq, (3, 3), 0)

    _, binary_otsu = cv2.threshold(
        blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )

    binary_adapt = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        35,
        9,
    )

    bh_width = max(25, image_width_px // 160)
    bh_height = max(25, gray.shape[0] // 160)
    bh_kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (bh_width, 3))
    bh_kernel_v = cv2.getStructuringElement(cv2.MORPH_RECT, (3, bh_height))
    blackhat_h = cv2.morphologyEx(blurred, cv2.MORPH_BLACKHAT, bh_kernel_h)
    blackhat_v = cv2.morphologyEx(blurred, cv2.MORPH_BLACKHAT, bh_kernel_v)
    _, binary_bh_h = cv2.threshold(blackhat_h, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, binary_bh_v = cv2.threshold(blackhat_v, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    binary = cv2.bitwise_or(binary_otsu, binary_adapt)
    binary = cv2.bitwise_or(binary, binary_bh_h)
    binary = cv2.bitwise_or(binary, binary_bh_v)

    connect_width = max(9, image_width_px // 500)
    connect_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (connect_width, 1))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, connect_kernel, iterations=1)
    return binary


def _binarize_for_checkbox_detection(gray: np.ndarray, image_width_px: int) -> np.ndarray:
    """
    Build a permissive binary mask intended for *checkbox* detection.

    Why this exists:
    - Many forms draw checkbox borders in light gray. A single global Otsu threshold can miss
      these thin strokes, especially near shaded regions.
    - Our box detector ORs `binary` with `binary_lines` (which includes a horizontal close),
      which can merge a checkbox with nearby label text and cause the checkbox contour to
      disappear.

    Strategy:
    - Combine Otsu inverse + adaptive inverse threshold on a contrast-enhanced grayscale image.
    - Apply a tiny close to reconnect broken checkbox corners without aggressively merging
      nearby text.
    """
    gray_eq = _enhance_contrast(gray)
    blurred = cv2.GaussianBlur(gray_eq, (3, 3), 0)

    _, binary_otsu = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    binary_adapt = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        7,
    )

    binary = cv2.bitwise_or(binary_otsu, binary_adapt)

    # Light blackhat highlights faint checkbox borders that can vanish under global/adaptive
    # thresholding. The small kernel keeps text noise manageable while boosting thin strokes.
    bh_size = max(7, image_width_px // 600)
    bh_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (bh_size, bh_size))
    blackhat = cv2.morphologyEx(blurred, cv2.MORPH_BLACKHAT, bh_kernel)
    _, binary_bh = cv2.threshold(blackhat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    binary = cv2.bitwise_or(binary, binary_bh)

    # Light close: reconnect broken corners without "dragging" the checkbox into the label text.
    close_k = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, close_k, iterations=1)

    # Very mild open to reduce speckle noise on low-quality scans.
    open_k = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, open_k, iterations=1)
    return binary


def _iou(a: List[float], b: List[float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, (ax2 - ax1)) * max(0.0, (ay2 - ay1))
    area_b = max(0.0, (bx2 - bx1)) * max(0.0, (by2 - by1))
    denom = area_a + area_b - inter
    if denom <= 0:
        return 0.0
    return inter / denom


def _merge_ml_candidates(
    opencv_candidates: List[Dict],
    ml_candidates: List[Dict],
    *,
    iou_threshold: float,
    preserve_detectors: Tuple[str, ...] = (),
) -> List[Dict]:
    """
    Merge ML candidates into OpenCV results with ML priority on overlap.

    Table/grid candidates are preserved so downstream logic can rely on their tags.
    """
    if not ml_candidates:
        return opencv_candidates
    if not opencv_candidates:
        return ml_candidates

    merged: List[Dict] = list(ml_candidates)
    for cand in opencv_candidates:
        detector = cand.get("detector")
        if detector and detector in preserve_detectors:
            merged.append(cand)
            continue
        bbox = cand.get("bbox")
        if not bbox or len(bbox) != 4:
            merged.append(cand)
            continue
        if any(_iou(bbox, ml.get("bbox") or [0, 0, 0, 0]) >= float(iou_threshold) for ml in ml_candidates):
            continue
        merged.append(cand)
    return merged


def _foreground_ratio(mask: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> float:
    """
    Return fraction of non-zero pixels in the requested ROI of a binary mask.

    The mask is expected to be 0/255 (or 0/1); any non-zero is treated as "ink".
    """
    if mask is None or mask.size == 0:
        return 0.0
    h, w = mask.shape[:2]
    x0 = max(0, min(w, int(x0)))
    x1 = max(0, min(w, int(x1)))
    y0 = max(0, min(h, int(y0)))
    y1 = max(0, min(h, int(y1)))
    if x1 <= x0 or y1 <= y0:
        return 0.0
    roi = mask[y0:y1, x0:x1]
    if roi.size == 0:
        return 0.0
    return float(np.count_nonzero(roi)) / float(roi.size)


def _count_clustered_indices(indices: np.ndarray, *, gap_tol_px: int) -> int:
    """
    Count clusters in a sorted list of integer indices.

    Used to estimate how many distinct horizontal/vertical rules exist inside a region.
    """
    if indices is None or len(indices) == 0:
        return 0
    indices = np.sort(indices.astype(int))
    clusters = 1
    last = int(indices[0])
    for idx in indices[1:]:
        idx = int(idx)
        if idx - last > int(gap_tol_px):
            clusters += 1
        last = idx
    return clusters


def _looks_like_table_grid_region(
    vertical_mask: np.ndarray,
    horizontal_mask: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
) -> bool:
    """
    Return True if a rectangle region looks like a table/grid.

    Motivation:
    - Table borders often form one large rectangular contour.
    - If we emit that as a "box" candidate, the resolver creates ONE giant text field
      instead of cell-per-cell fields (charts/tables regression).

    Heuristic:
    - Count long horizontal rule bands inside the rectangle.
    - Count long vertical rule bands inside the rectangle.
    - A normal input box has ~2 horizontal rules (top/bottom) and ~2 vertical (left/right).
    - A table typically has >=3 horizontal rules (rows) and at least one interior vertical rule.
    """
    if vertical_mask is None or horizontal_mask is None:
        return False
    if w <= 0 or h <= 0:
        return False

    img_h, img_w = vertical_mask.shape[:2]
    pad = max(3, min(int(min(w, h) * 0.06), 14))
    x0 = max(0, min(img_w, int(x + pad)))
    x1 = max(0, min(img_w, int(x + w - pad)))
    y0 = max(0, min(img_h, int(y + pad)))
    y1 = max(0, min(img_h, int(y + h - pad)))
    if x1 <= x0 or y1 <= y0:
        return False

    v_roi = vertical_mask[y0:y1, x0:x1]
    h_roi = horizontal_mask[y0:y1, x0:x1]
    if v_roi.size == 0 or h_roi.size == 0:
        return False

    # Identify columns/rows that contain a near-full-span line.
    v_span_thresh = int(v_roi.shape[0] * 0.65)
    # A strict "near full-width" threshold fails on dense grids because intersections with
    # vertical rules can break the horizontal mask into segments. We only need to know that
    # there are *many* long horizontal rules, not that each rule is continuous end-to-end.
    h_span_thresh = int(h_roi.shape[1] * 0.35)
    v_cols = np.where(np.sum(v_roi > 0, axis=0) >= v_span_thresh)[0]
    h_rows = np.where(np.sum(h_roi > 0, axis=1) >= h_span_thresh)[0]

    vertical_rules = _count_clustered_indices(v_cols, gap_tol_px=4)
    horizontal_rules = _count_clustered_indices(h_rows, gap_tol_px=4)

    return horizontal_rules >= 3 and vertical_rules >= 1


def _checkbox_border_and_inner_ink(
    text_mask: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
) -> Tuple[float, float]:
    """
    Compute (border_ratio, inner_ratio) for a checkbox-like candidate in pixel space.

    Why:
    - On scanned pages, contour finding will often return small rectangle-ish blobs for
      individual glyphs (e.g. letters like "o", "D", digits, punctuation).
    - True checkboxes have:
      - A mostly empty interior (low inner_ratio)
      - Ink concentrated near the perimeter (moderate-to-high border_ratio)

    We compute ratios on the Otsu text mask (foreground=non-zero).
    """
    if text_mask is None or text_mask.size == 0:
        return 0.0, 0.0
    if w <= 0 or h <= 0:
        return 0.0, 0.0

    img_h, img_w = text_mask.shape[:2]
    x0 = max(0, min(img_w, int(x)))
    y0 = max(0, min(img_h, int(y)))
    x1 = max(0, min(img_w, int(x + w)))
    y1 = max(0, min(img_h, int(y + h)))
    if x1 <= x0 or y1 <= y0:
        return 0.0, 0.0

    roi = text_mask[y0:y1, x0:x1]
    rh, rw = roi.shape[:2]
    if rw <= 2 or rh <= 2:
        return 0.0, 0.0

    # Inner area (exclude the perimeter). Use proportional padding so it scales with DPI.
    pad = max(1, int(round(min(rw, rh) * 0.22)))
    pad = min(pad, (rw - 2) // 2, (rh - 2) // 2)
    if pad <= 0:
        inner_ratio = 0.0
    else:
        inner = roi[pad : rh - pad, pad : rw - pad]
        inner_ratio = float(np.count_nonzero(inner)) / float(inner.size) if inner.size else 0.0

    # Border area: a thicker band around the edges. Checkbox borders should show up here.
    bt = max(1, int(round(min(rw, rh) * 0.18)))
    bt = min(bt, (rw - 1) // 2, (rh - 1) // 2)
    if bt <= 0:
        border_ratio = 0.0
    else:
        border_mask = np.zeros((rh, rw), dtype=np.uint8)
        border_mask[:bt, :] = 1
        border_mask[-bt:, :] = 1
        border_mask[:, :bt] = 1
        border_mask[:, -bt:] = 1
        border_area = int(np.count_nonzero(border_mask))
        if border_area <= 0:
            border_ratio = 0.0
        else:
            border_ink = int(np.count_nonzero((roi > 0) & (border_mask > 0)))
            border_ratio = float(border_ink) / float(border_area)

    return border_ratio, inner_ratio


def _corner_ink_count(
    mask: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
    *,
    patch_ratio: float = 0.26,
    min_ratio: float = 0.06,
) -> int:
    """
    Count how many corners contain "ink" in a binary mask within the given bbox.

    Motivation:
    - Glyphs like \"O\" and \"D\" can produce hollow, square-ish contours that pass
      border/inner heuristics and get misclassified as checkboxes.
    - True checkbox squares usually have ink at the four corners where the border turns.
    - Rounded glyphs typically do not place ink in the extreme corners of their bbox.

    This helper is intentionally conservative and is used as a precision filter in both:
    - contour-based checkbox detection (`_detect_boxes`)
    - checkbox recovery from the raw text mask (`_detect_checkboxes_from_text_mask`)
    """
    if mask is None or mask.size == 0:
        return 0
    if w <= 0 or h <= 0:
        return 0

    img_h, img_w = mask.shape[:2]
    x0 = max(0, min(img_w, int(x)))
    y0 = max(0, min(img_h, int(y)))
    x1 = max(0, min(img_w, int(x + w)))
    y1 = max(0, min(img_h, int(y + h)))
    if x1 <= x0 or y1 <= y0:
        return 0

    roi = mask[y0:y1, x0:x1]
    rh, rw = roi.shape[:2]
    if rh < 6 or rw < 6:
        return 0

    patch = max(3, int(round(min(rw, rh) * float(patch_ratio))))
    patch = min(patch, rw, rh)
    if patch <= 0:
        return 0

    def _ratio(px0: int, py0: int) -> float:
        sub = roi[py0 : py0 + patch, px0 : px0 + patch]
        if sub.size == 0:
            return 0.0
        return float(np.count_nonzero(sub)) / float(sub.size)

    corners = [
        (0, 0),
        (max(0, rw - patch), 0),
        (0, max(0, rh - patch)),
        (max(0, rw - patch), max(0, rh - patch)),
    ]
    count = 0
    for px0, py0 in corners:
        if _ratio(px0, py0) >= float(min_ratio):
            count += 1
    return count


def _contour_extent_and_solidity(contour: np.ndarray, w: int, h: int) -> Tuple[float, float]:
    """
    Return (extent, solidity) for a contour given its bounding-box width/height.

    extent   = contour_area / bbox_area
    solidity = contour_area / convex_hull_area
    """
    if w <= 0 or h <= 0:
        return 0.0, 0.0
    area = float(cv2.contourArea(contour))
    extent = area / float(w * h)
    hull = cv2.convexHull(contour)
    hull_area = float(cv2.contourArea(hull)) or 1.0
    solidity = area / hull_area
    return extent, solidity


def _hole_area_ratio_from_mask_bbox(
    text_mask: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
    *,
    pad_px: int = 2,
) -> float:
    """
    Estimate the interior "hole" area ratio for a bbox in a binary text mask.

    Returned value is:
      hole_area / bbox_area

    Why this exists:
    - Contour-based checkbox detection (`_detect_boxes`) uses `cv2.RETR_EXTERNAL`, so we don't
      naturally get hole contours (hierarchy) for hollow shapes.
    - Hollow glyphs like "O" and "0" can satisfy border/inner heuristics and look boxy enough
      to be misclassified as checkboxes.
    - Real checkboxes usually have a relatively *large* interior hole (thin border),
      whereas glyphs have thicker strokes → smaller hole ratio.

    Implementation notes:
    - We pad the ROI before computing holes to avoid bounding-rect cropping artifacts where the
      shape touches the ROI border (which can incorrectly classify outer background as a "hole").
    - Holes are computed via flood-fill on the *background* pixels that are not connected to the
      ROI border (classic hole-filling technique).
    """
    if text_mask is None or text_mask.size == 0:
        return 0.0
    if w <= 0 or h <= 0:
        return 0.0

    height, width = text_mask.shape[:2]
    pad = max(0, int(pad_px))
    x0 = max(0, int(x) - pad)
    y0 = max(0, int(y) - pad)
    x1 = min(width, int(x + w) + pad)
    y1 = min(height, int(y + h) + pad)
    roi = text_mask[y0:y1, x0:x1]
    if roi.size == 0:
        return 0.0

    # Work in 0/1 for speed and to avoid dealing with 0/255 semantics.
    ink = (roi > 0).astype(np.uint8)
    if int(np.count_nonzero(ink)) == 0:
        return 0.0

    # background=1, ink=0
    bg = (1 - ink).astype(np.uint8)

    # Flood fill the background that is connected to the ROI border (outside region).
    # We pad with a 1-valued border so the flood fill seed is always background.
    bg_padded = np.pad(bg, ((1, 1), (1, 1)), mode="constant", constant_values=1)
    mask = np.zeros((bg_padded.shape[0] + 2, bg_padded.shape[1] + 2), dtype=np.uint8)
    try:
        cv2.floodFill(bg_padded, mask, (0, 0), 0)
    except cv2.error:
        return 0.0

    holes = bg_padded[1:-1, 1:-1]
    hole_area = float(np.count_nonzero(holes))
    bbox_area = float(int(w) * int(h))
    return hole_area / bbox_area if bbox_area > 0.0 else 0.0


def _checkbox_edge_coverages(
    text_mask: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
) -> Tuple[float, float, float, float]:
    """
    Estimate how "straight" each of the 4 checkbox edges appears in the binary mask.

    Motivation:
    - Hollow glyphs like "O" can look square-ish after thresholding, especially when the
      glyph stroke is thin (large interior hole) and the bbox is near-square.
    - Real checkbox borders usually have strong, straight edges spanning most of the side.
      Curved glyphs do not.

    Implementation:
    - Extract a thin strip near each side of the bbox ROI.
    - Compute coverage:
      - top/bottom: fraction of columns with any ink in the strip
      - left/right: fraction of rows with any ink in the strip

    Returns (top, bottom, left, right) coverages, each in [0, 1].
    """
    if text_mask is None or text_mask.size == 0 or w <= 2 or h <= 2:
        return 0.0, 0.0, 0.0, 0.0

    img_h, img_w = text_mask.shape[:2]
    x0 = max(0, min(img_w, int(x)))
    y0 = max(0, min(img_h, int(y)))
    x1 = max(0, min(img_w, int(x + w)))
    y1 = max(0, min(img_h, int(y + h)))
    if x1 <= x0 or y1 <= y0:
        return 0.0, 0.0, 0.0, 0.0

    roi = text_mask[y0:y1, x0:x1]
    rh, rw = roi.shape[:2]
    if rw <= 2 or rh <= 2:
        return 0.0, 0.0, 0.0, 0.0

    edge_th = int(round(min(rw, rh) * 0.18))
    edge_th = max(1, min(edge_th, 8, (rw - 1) // 2, (rh - 1) // 2))

    top_strip = roi[0:edge_th, :]
    bottom_strip = roi[rh - edge_th : rh, :]
    left_strip = roi[:, 0:edge_th]
    right_strip = roi[:, rw - edge_th : rw]

    top_cov = float(np.count_nonzero(np.any(top_strip > 0, axis=0))) / float(rw)
    bottom_cov = float(np.count_nonzero(np.any(bottom_strip > 0, axis=0))) / float(rw)
    left_cov = float(np.count_nonzero(np.any(left_strip > 0, axis=1))) / float(rh)
    right_cov = float(np.count_nonzero(np.any(right_strip > 0, axis=1))) / float(rh)
    return top_cov, bottom_cov, left_cov, right_cov


def _hole_bbox_aspect_from_contour(
    text_mask: np.ndarray,
    contour: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
) -> float:
    """
    Estimate the aspect ratio of the *largest* interior hole for a contour candidate.

    Motivation:
    - Some hollow glyphs (notably the letter "D") can look extremely similar to a checkbox
      in simple border/inner and edge-coverage tests:
        - they are boxy and convex-ish
        - they have a large interior hole
        - they hit multiple corners due to font geometry
    - A true checkbox hole is typically close to square, even when the outer bbox is slightly
      rectangular due to scan skew.
    - The interior hole of a "D" is usually noticeably *rectangular* (taller than wide).

    Implementation detail:
    - We rasterize the contour as a filled mask in its bbox, then locate background pixels
      inside that contour (`filled && !ink`) and take the largest connected component.
    - The returned value is `hole_width / hole_height` in pixel space.
    """
    if text_mask is None or text_mask.size == 0 or w <= 4 or h <= 4:
        return 0.0
    img_h, img_w = text_mask.shape[:2]
    x0 = max(0, min(img_w, int(x)))
    y0 = max(0, min(img_h, int(y)))
    x1 = max(0, min(img_w, int(x + w)))
    y1 = max(0, min(img_h, int(y + h)))
    if x1 <= x0 or y1 <= y0:
        return 0.0
    roi = text_mask[y0:y1, x0:x1]
    if roi.size == 0:
        return 0.0

    shifted = contour.copy()
    shifted[:, :, 0] -= int(x0)
    shifted[:, :, 1] -= int(y0)
    filled = np.zeros((roi.shape[0], roi.shape[1]), dtype=np.uint8)
    try:
        cv2.drawContours(filled, [shifted], -1, 1, thickness=-1)
    except cv2.error:
        return 0.0
    # Inside-the-contour background: candidates for the "hole" region.
    inside_bg = ((filled == 1) & (roi == 0)).astype(np.uint8)
    if inside_bg.size == 0 or int(np.count_nonzero(inside_bg)) == 0:
        return 0.0

    try:
        holes, _ = cv2.findContours(inside_bg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    except cv2.error:
        holes = []
    if not holes:
        return 0.0
    hole = max(holes, key=lambda c: abs(float(cv2.contourArea(c))))
    hx, hy, hw, hh = cv2.boundingRect(hole)
    if hw <= 0 or hh <= 0:
        return 0.0
    return float(hw) / float(max(hh, 1))


def _checkbox_neighbor_ink_lr(
    text_mask: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
    *,
    pad_px: int,
) -> Tuple[float, float]:
    """
    Measure how much ink exists immediately to the left/right of a checkbox candidate.

    Motivation:
    - Letters inside words (notably "O") can form hollow contours that look square-ish in a
      binarized scan.
    - A true checkbox is usually separated from adjacent text by some whitespace gap (even
      when a label is printed next to it). A glyph inside a word typically has ink on both
      sides with little to no gap.

    Returns (left_ratio, right_ratio) in [0,1], where each ratio is the fraction of non-zero
    pixels in a thin strip adjacent to the bbox.
    """
    if text_mask is None or text_mask.size == 0 or w <= 0 or h <= 0:
        return 0.0, 0.0
    pad = max(1, int(pad_px))
    img_h, img_w = text_mask.shape[:2]

    x0 = max(0, min(img_w, int(x)))
    y0 = max(0, min(img_h, int(y)))
    x1 = max(0, min(img_w, int(x + w)))
    y1 = max(0, min(img_h, int(y + h)))
    if x1 <= x0 or y1 <= y0:
        return 0.0, 0.0

    lx0 = max(0, x0 - pad)
    lx1 = x0
    rx0 = x1
    rx1 = min(img_w, x1 + pad)
    if lx1 <= lx0 or rx1 <= rx0:
        return 0.0, 0.0

    left = text_mask[y0:y1, lx0:lx1]
    right = text_mask[y0:y1, rx0:rx1]
    left_ratio = float(np.count_nonzero(left)) / float(left.size) if left.size else 0.0
    right_ratio = float(np.count_nonzero(right)) / float(right.size) if right.size else 0.0
    return left_ratio, right_ratio


def _is_strong_checkbox_shape(
    contour: np.ndarray,
    approx: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
    text_mask: np.ndarray,
) -> bool:
    """
    Return True when the contour is a strong checkbox candidate.

    Why this exists:
    - Scanned documents often produce rectangle-ish blobs for individual glyphs.
    - The border/inner heuristic alone can mistakenly accept some letters (e.g. "U").
    - True checkboxes are typically:
      - High extent + high solidity (boxy in the binary mask)
      - Often convex with 4-ish vertices (allow some noise)
    """
    border_ratio, inner_ratio = _checkbox_border_and_inner_ink(text_mask, x, y, w, h)
    # Border threshold tuning:
    # - Some scanned forms render very thin checkbox borders; Otsu thresholding can break corners,
    #   reducing border_ratio.
    # - We keep the inner_ratio constraint strict (checkbox interior should be mostly blank) but
    #   relax the border_ratio slightly to improve recall on dense Y/N grids.
    if inner_ratio >= 0.22 or border_ratio <= 0.040:
        return False
    # Glyph-like candidates (especially \"O\") can satisfy the border/inner constraints due to
    # their hollow interiors. A true checkbox border should leave ink in the extreme bbox
    # corners where the border turns.
    #
    # IMPORTANT: Use a smaller corner patch than the default helper settings.
    # - A large corner patch can overlap mid-edge strokes on round glyphs, making them appear
    #   to have "corner ink".
    # - Real checkboxes usually hit the extreme corners; round glyphs do not.
    if _corner_ink_count(text_mask, x, y, w, h, patch_ratio=0.14, min_ratio=0.08) < 2:
        return False

    # Edge straightness filter: reject curved hollow glyphs ("O", "0") that can otherwise pass
    # the hole ratio + corner ink checks when their stroke is thin.
    top_cov, bottom_cov, left_cov, right_cov = _checkbox_edge_coverages(text_mask, x, y, w, h)
    edge_covs = [top_cov, bottom_cov, left_cov, right_cov]
    strong_edges = sum(1 for v in edge_covs if v >= 0.58)
    mean_edge = float(sum(edge_covs)) / 4.0
    if strong_edges < 2 and mean_edge < 0.48:
        return False

    # Precision filter: reject hollow glyphs ("O", "0") using a hole-area ratio measured on the
    # raw text mask.
    #
    # Important nuance:
    # - Some PDFs draw checkbox borders with a noticeably thicker stroke (see
    #   `backend/fieldDetecting/pdfs/native/intake/patient-Intake-pdf.pdf` page 3 "Living? □Y □N"), which lowers the hole ratio
    #   even though the candidate is a real checkbox.
    #
    # Strategy:
    # - Require the higher hole ratio when edge straightness is weak (glyph-like).
    # - Allow a lower hole ratio only when we already have strong straight-edge evidence.
    hole_ratio = _hole_area_ratio_from_mask_bbox(text_mask, x, y, w, h, pad_px=2)
    min_hole_ratio = 0.20 if (strong_edges >= 3 and mean_edge >= 0.66) else 0.32
    if hole_ratio < min_hole_ratio:
        return False
    # Hole-shape filter: reject hollow glyphs like the letter "D" whose interior hole tends
    # to be noticeably rectangular even when the outer bbox is square-ish.
    hole_aspect = _hole_bbox_aspect_from_contour(text_mask, contour, x, y, w, h)
    if hole_aspect and not (0.75 <= float(hole_aspect) <= 1.35):
        return False

    # Neighbor-ink filter (soft):
    # - Embedded glyphs tend to have ink immediately on BOTH sides (inside a word).
    # - Some real checkboxes are tightly packed between label text and an option word, so we
    #   only apply this filter when the edge coverage signal is weak (glyph-like).
    pad_px = max(2, min(10, int(round(min(w, h) * 0.20))))
    left_ratio, right_ratio = _checkbox_neighbor_ink_lr(text_mask, x, y, w, h, pad_px=pad_px)
    if left_ratio >= 0.18 and right_ratio >= 0.18:
        # Strong straight edges override this filter; tightly-spaced option checkboxes are common.
        if mean_edge < 0.62 and strong_edges < 3:
            return False

    extent, solidity = _contour_extent_and_solidity(contour, w, h)
    if extent < 0.50 or solidity < 0.74:
        return False

    # Convexity is a strong discriminator for letters. Some scanned boxes can be slightly
    # non-convex due to noise, so allow non-convex only when solidity is very high.
    is_convex = bool(cv2.isContourConvex(approx))
    if not is_convex and solidity < 0.90:
        return False

    # Very noisy shapes tend to have many vertices.
    if len(approx) > 12:
        return False

    return True


def _is_loose_checkbox_shape(
    contour: np.ndarray,
    approx: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
    text_mask: np.ndarray,
    *,
    width_pt: float,
    height_pt: float,
) -> bool:
    """
    Fallback checkbox heuristic for small, heavy-stroke squares.

    Some native PDFs render tiny checkbox borders so thick that the binarized mask
    fills much of the interior. This rejects the strict hole/inner checks but still
    preserves strong, square-ish edges. We accept those only for small squares.
    """
    if width_pt < 5.5 or height_pt < 5.5 or width_pt > 14.0 or height_pt > 14.0:
        return False
    border_ratio, inner_ratio = _checkbox_border_and_inner_ink(text_mask, x, y, w, h)
    if border_ratio < 0.45 or inner_ratio > 0.72:
        return False
    if _corner_ink_count(text_mask, x, y, w, h, patch_ratio=0.14, min_ratio=0.05) < 1:
        return False
    top_cov, bottom_cov, left_cov, right_cov = _checkbox_edge_coverages(text_mask, x, y, w, h)
    strong_edges = sum(1 for v in (top_cov, bottom_cov, left_cov, right_cov) if v >= 0.55)
    mean_edge = float(top_cov + bottom_cov + left_cov + right_cov) / 4.0
    if strong_edges < 3 and mean_edge < 0.70:
        return False
    extent, solidity = _contour_extent_and_solidity(contour, w, h)
    if extent < 0.55 or solidity < 0.65:
        return False
    if len(approx) > 12:
        return False
    return True


def _dedupe_by_iou(candidates: List[Dict], *, threshold: float = 0.72) -> List[Dict]:
    """Dedupe candidates by bbox IoU (originTop points)."""
    if not candidates:
        return []
    sorted_candidates = sorted(
        candidates,
        key=lambda c: (
            float((c.get("bbox") or [0, 0, 0, 0])[1]),
            float((c.get("bbox") or [0, 0, 0, 0])[0]),
        ),
    )
    kept: List[Dict] = []
    for cand in sorted_candidates:
        bbox = cand.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        if any(_iou(bbox, prev.get("bbox") or [0, 0, 0, 0]) >= float(threshold) for prev in kept):
            continue
        kept.append(cand)
    return kept


def _checkbox_detector_priority(detector: str) -> int:
    det = (detector or "").lower()
    if det == "table_cells":
        return 0
    if det == "contour":
        return 1
    if det.startswith("text_mask"):
        return 2
    if det == "grid_complete":
        return 3
    if det in {"glyph", "vector_rect"}:
        return 4
    return 5


def _dedupe_checkbox_candidates(
    candidates: List[Dict],
    *,
    iou_threshold: float = 0.70,
    center_tol_ratio: float = 0.35,
) -> List[Dict]:
    """
    Dedupe checkbox candidates, preferring higher-confidence detectors.

    We remove near-identical boxes that can arise from double-line borders or overlapping
    detectors (e.g., contour vs table-cell detection). IoU is the primary gate; a small
    center-distance fallback catches nested rectangles with lower IoU.
    """
    if not candidates:
        return []

    def _sort_key(cand: Dict) -> tuple[float, float, float, float]:
        bbox = cand.get("bbox") or [0, 0, 0, 0]
        return (
            float(_checkbox_detector_priority(str(cand.get("detector") or ""))),
            float(bbox[1]),
            float(bbox[0]),
            -float(max(0.0, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))),
        )

    kept: List[Dict] = []
    for cand in sorted(candidates, key=_sort_key):
        bbox = cand.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        cx = (float(bbox[0]) + float(bbox[2])) / 2.0
        cy = (float(bbox[1]) + float(bbox[3])) / 2.0
        w = float(bbox[2]) - float(bbox[0])
        h = float(bbox[3]) - float(bbox[1])
        max_size = max(w, h, 1.0)
        tol = max_size * float(center_tol_ratio)
        tol_sq = tol * tol

        duplicate = False
        for prev in kept:
            prev_bbox = prev.get("bbox") or []
            if len(prev_bbox) != 4:
                continue
            if _iou(bbox, prev_bbox) >= float(iou_threshold):
                duplicate = True
                break
            px = (float(prev_bbox[0]) + float(prev_bbox[2])) / 2.0
            py = (float(prev_bbox[1]) + float(prev_bbox[3])) / 2.0
            dx = cx - px
            dy = cy - py
            if (dx * dx + dy * dy) <= tol_sq:
                pw = float(prev_bbox[2]) - float(prev_bbox[0])
                ph = float(prev_bbox[3]) - float(prev_bbox[1])
                if 0.6 <= (w / max(pw, 1e-6)) <= 1.6 and 0.6 <= (h / max(ph, 1e-6)) <= 1.6:
                    duplicate = True
                    break
        if not duplicate:
            kept.append(cand)

    return kept


def _detect_checkboxes_from_text_mask(
    text_mask: np.ndarray,
    image_width_px: int,
    image_height_px: int,
    page_box: PageBox,
    *,
    anchor_rows_y_px: List[float] | None = None,
    anchor_y_tol_px: int = 14,
    text_height_mask: np.ndarray | None = None,
) -> List[Dict]:
    """
    Detect checkbox squares using only the Otsu text mask.

    Why:
    - Our box detection path uses `binary_boxes = text_mask OR binary_lines` and a small close,
      which can merge a checkbox with adjacent label text (especially in dense rows like
      `Marital Status: □Single ... □Widow`).
    - Running a second, checkbox-only pass directly on the text mask recovers those missed
      squares without impacting rectangle/box detection.
    """
    if text_mask is None or text_mask.size == 0:
        return []
    anchored_mode = bool(anchor_rows_y_px)
    # This recovery path is intentionally conservative to avoid mistaking glyphs (e.g. "0", "O")
    # for checkboxes on pages that do not contain any checkbox rows.
    #
    # Historically we only enabled it when we already had at least one checkbox detected via
    # contour detection ("anchor rows"). That avoids false positives, but it fails badly on
    # dense checkbox grids where contour detection returns *zero* squares (e.g., "Y/N" columns
    # with very tight spacing and aggressive closing merges boxes into adjacent text).
    #
    # In unanchored mode we still run this detector, but we only return results when there is
    # strong evidence of a real checkbox pattern:
    # - Enough candidates (dense page section, not a few glyphs)
    # - Tight size clustering (checkboxes share a consistent box size)
    # - Grid-like layout (multiple distinct rows and columns)

    # IMPORTANT: Do NOT rely on a single morphology setting here.
    #
    # We have seen two real-world failure modes:
    # 1) Checkboxes with broken borders (need a light close to connect the box).
    # 2) Dense "Y/N" grids where a close can merge a checkbox into adjacent text,
    #    causing the checkbox contour to disappear.
    #
    # So we run this detector on:
    # - the raw text mask (higher precision for dense grids)
    # - a lightly-closed mask (higher recall for broken borders)
    #
    # Then we union + IoU-dedupe the results before applying the (anchored/unanchored)
    # evidence gates.
    close2 = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    close3 = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    closed_mask_2 = cv2.morphologyEx(text_mask, cv2.MORPH_CLOSE, close2, iterations=1)
    # Some scans have broken checkbox corners; a slightly stronger close can reconnect borders.
    closed_mask_2_iter2 = cv2.morphologyEx(text_mask, cv2.MORPH_CLOSE, close2, iterations=2)
    closed_mask_3 = cv2.morphologyEx(text_mask, cv2.MORPH_CLOSE, close3, iterations=1)

    def _estimate_text_height_px(mask: np.ndarray) -> float | None:
        """
        Estimate median text glyph height in pixel space.

        This is used to filter unanchored checkbox recoveries that are much smaller
        than typical text (e.g., bullet glyphs inside long paragraphs).
        """
        try:
            line_kernel = cv2.getStructuringElement(
                cv2.MORPH_RECT, (max(40, image_width_px // 90), 1)
            )
            line_mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, line_kernel, iterations=1)
            num, _, stats, _ = cv2.connectedComponentsWithStats(line_mask, connectivity=8)
        except cv2.error:
            num = 0
            stats = None
        if num > 1 and stats is not None:
            line_heights: List[int] = []
            for idx in range(1, num):
                x, y, w, h, area = stats[idx]
                if area < 120:
                    continue
                if h < 6 or h > 160:
                    continue
                if w < max(60, h * 4):
                    continue
                line_heights.append(int(h))
            if len(line_heights) >= 3:
                return float(np.median(line_heights))
        try:
            num, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        except cv2.error:
            return None
        if num <= 1:
            return None
        heights: List[int] = []
        for idx in range(1, num):
            x, y, w, h, area = stats[idx]
            if area < 20:
                continue
            if h < 6 or h > 160:
                continue
            if w < 2 or w > 220:
                continue
            if w / max(h, 1) > 12.0 or h / max(w, 1) > 12.0:
                continue
            heights.append(int(h))
        if len(heights) < 20:
            return None
        return float(np.median(heights))

    def _hole_area_ratio_from_ccomp(
        contours: List[np.ndarray],
        hierarchy: np.ndarray,
        *,
        outer_idx: int,
        bbox_w: int,
        bbox_h: int,
    ) -> float:
        """
        Return the (hole_area / bbox_area) ratio for an outer contour in a CCOMP hierarchy.

        Why this exists:
        - Hollow glyphs like "O" can satisfy our border/inner + corner-ink tests and look
          "boxy" enough in the binary mask to be misclassified as a checkbox.
        - True checkboxes typically have a *larger* interior hole relative to their bounding box
          than thick-stroked glyphs, because checkbox borders are usually thin.

        We compute the total area of child contours (holes) for the outer contour and normalize
        by the outer contour's bounding-box area. This is fast and works on the same mask used
        to generate the contours (raw / lightly-closed).
        """
        if bbox_w <= 0 or bbox_h <= 0:
            return 0.0
        bbox_area = float(bbox_w * bbox_h)
        hole_area = 0.0
        child = int(hierarchy[outer_idx][2])
        while child != -1:
            hole_area += abs(float(cv2.contourArea(contours[child])))
            child = int(hierarchy[child][0])
        return hole_area / bbox_area if bbox_area > 0.0 else 0.0

    def _collect_from_mask(mask_for_contours: np.ndarray, *, detector_tag: str) -> List[Dict]:
        # Use RETR_CCOMP so we can measure hole geometry for precision filtering.
        contours, hierarchy = cv2.findContours(mask_for_contours, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        if hierarchy is None or len(hierarchy) == 0:
            return []
        hierarchy = hierarchy[0]

        collected: List[Dict] = []
        rejected_hole = 0
        hole_samples: List[Tuple[float, List[int]]] = []
        for idx, contour in enumerate(contours):
            # Keep only outer contours (holes are children in CCOMP hierarchy).
            if int(hierarchy[idx][3]) != -1:
                continue

            x, y, w, h = cv2.boundingRect(contour)
            if w <= 0 or h <= 0:
                continue
            # Anchored mode: only consider recovered candidates that align with an existing checkbox row.
            if anchored_mode:
                y_mid = (float(y) + float(y + h)) / 2.0
                if all(
                    abs(y_mid - float(anchor)) > float(anchor_y_tol_px)
                    for anchor in (anchor_rows_y_px or [])
                ):
                    continue

            bbox_pts = _to_points_bbox((x, y, w, h), image_width_px, image_height_px, page_box)
            width_pt = float(bbox_pts[2] - bbox_pts[0])
            height_pt = float(bbox_pts[3] - bbox_pts[1])
            # This is a recovery detector. Tighten the minimum size to avoid glyph-like false
            # positives ("O", "D", etc.) that are typically smaller than real checkboxes.
            if width_pt < 6.0 or height_pt < 6.0:
                continue

            aspect_ratio = width_pt / max(height_pt, 0.01)
            if not (4 <= width_pt <= 44 and 4 <= height_pt <= 44 and 0.65 <= aspect_ratio <= 1.40):
                continue

            # Keep approximation reasonably fine to avoid accepting rounded glyphs as 4-vertex
            # rectangles, but do not over-tighten (noisy scanned checkboxes can have extra verts).
            approx = cv2.approxPolyDP(contour, 0.03 * cv2.arcLength(contour, True), True)
            is_rect_like = 4 <= len(approx) <= 10
            if not is_rect_like:
                continue

            # Precision filter: reject thick-stroke hollow glyphs (notably "O") which can look
            # like small squares in the binarized mask, especially near real checkbox rows.
            #
            # Rationale:
            # - A checkbox border is usually thin relative to its size, so the interior hole
            #   occupies a large fraction of the bbox.
            # - An "O" has a comparatively thick stroke, yielding a smaller hole ratio.
            hole_ratio = _hole_area_ratio_from_ccomp(
                contours,
                hierarchy,
                outer_idx=int(idx),
                bbox_w=int(w),
                bbox_h=int(h),
            )
            # Tuned on `medical-history-intake-form.pdf`:
            # - "O" glyphs in headers (e.g., HOSPITALIZATIONS) land around ~0.30–0.33.
            # - Real checkboxes on the same pages are ~0.42–0.55.
            #
            # Allow thick-border checkboxes to proceed to the stronger, straight-edge checks in
            # `_is_strong_checkbox_shape`. Curved glyphs ("O") will still be rejected there.
            min_hole_ratio = 0.20
            if hole_ratio < min_hole_ratio:
                top_cov, bottom_cov, left_cov, right_cov = _checkbox_edge_coverages(
                    text_mask, int(x), int(y), int(w), int(h)
                )
                edge_covs = [top_cov, bottom_cov, left_cov, right_cov]
                strong_edges = sum(1 for v in edge_covs if v >= 0.60)
                mean_edge = float(sum(edge_covs)) / 4.0
                if strong_edges < 3 or mean_edge < 0.62:
                    rejected_hole += 1
                    if len(hole_samples) < 6:
                        hole_samples.append(
                            (float(hole_ratio), [int(x), int(y), int(x + w), int(y + h)])
                        )
                    continue

            # Precision filter: glyph-like candidates rarely have ink in >=2 corners.
            # For unanchored recovery (dense grids), allow >=1 to improve recall on broken borders.
            min_corners = 2 if anchored_mode else 1
            if _corner_ink_count(mask_for_contours, int(x), int(y), int(w), int(h)) < min_corners:
                continue
            # Precision filter: require a reasonably checkbox-like border + interior on the
            # *raw* text mask (not the morphology-modified one).
            #
            # This rejects some hollow glyphs even when their corners are noisy.
            if not _is_strong_checkbox_shape(contour, approx, int(x), int(y), int(w), int(h), text_mask):
                if not _is_loose_checkbox_shape(
                    contour,
                    approx,
                    int(x),
                    int(y),
                    int(w),
                    int(h),
                    text_mask,
                    width_pt=width_pt,
                    height_pt=height_pt,
                ):
                    continue

            collected.append(
                {
                    "bbox": bbox_pts,
                    "bboxPx": [int(x), int(y), int(x + w), int(y + h)],
                    "type": "checkbox",
                    # Keep a tag so we can debug which pass detected the box.
                    "detector": f"text_mask_{detector_tag}",
                }
            )
        if rejected_hole:
            logger.debug(
                "Rejected %s checkbox candidates by hole-ratio filter in %s (samples=%s)",
                rejected_hole,
                detector_tag,
                hole_samples,
            )
        return collected

    def _collect_circle_from_mask(mask_for_contours: np.ndarray, *, detector_tag: str) -> List[Dict]:
        contours, hierarchy = cv2.findContours(mask_for_contours, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        if hierarchy is None or len(hierarchy) == 0:
            return []
        hierarchy = hierarchy[0]

        collected: List[Dict] = []
        for idx, contour in enumerate(contours):
            if int(hierarchy[idx][3]) != -1:
                continue

            x, y, w, h = cv2.boundingRect(contour)
            if w <= 0 or h <= 0:
                continue
            if anchored_mode:
                y_mid = (float(y) + float(y + h)) / 2.0
                if all(
                    abs(y_mid - float(anchor)) > float(anchor_y_tol_px)
                    for anchor in (anchor_rows_y_px or [])
                ):
                    continue

            bbox_pts = _to_points_bbox((x, y, w, h), image_width_px, image_height_px, page_box)
            width_pt = float(bbox_pts[2] - bbox_pts[0])
            height_pt = float(bbox_pts[3] - bbox_pts[1])
            if width_pt < 4.0 or height_pt < 4.0:
                continue

            aspect_ratio = width_pt / max(height_pt, 0.01)
            if not (4 <= width_pt <= 44 and 4 <= height_pt <= 44 and 0.70 <= aspect_ratio <= 1.30):
                continue

            area = float(cv2.contourArea(contour))
            perimeter = float(cv2.arcLength(contour, True))
            if perimeter <= 0.0 or area <= 0.0:
                continue

            circularity = (4.0 * math.pi * area) / (perimeter * perimeter)
            if circularity < 0.78:
                continue

            approx = cv2.approxPolyDP(contour, 0.04 * perimeter, True)
            if len(approx) < 5:
                continue

            extent, _ = _contour_extent_and_solidity(contour, w, h)
            if extent < 0.55 or extent > 0.92:
                continue

            hole_ratio = _hole_area_ratio_from_ccomp(
                contours,
                hierarchy,
                outer_idx=int(idx),
                bbox_w=int(w),
                bbox_h=int(h),
            )
            if hole_ratio < 0.16:
                continue

            border_ratio, inner_ratio = _checkbox_border_and_inner_ink(text_mask, int(x), int(y), int(w), int(h))
            if inner_ratio >= 0.35 or border_ratio <= 0.02:
                continue

            left_ratio, right_ratio = _checkbox_neighbor_ink_lr(text_mask, int(x), int(y), int(w), int(h), pad_px=4)
            if left_ratio >= 0.22 and right_ratio >= 0.22:
                continue

            collected.append(
                {
                    "bbox": bbox_pts,
                    "bboxPx": [int(x), int(y), int(x + w), int(y + h)],
                    "type": "checkbox",
                    "detector": f"text_mask_circle_{detector_tag}",
                }
            )
        return collected

    checkbox_candidates: List[Dict] = []
    checkbox_candidates.extend(_collect_from_mask(text_mask, detector_tag="raw"))
    checkbox_candidates.extend(_collect_from_mask(closed_mask_2, detector_tag="close2"))
    checkbox_candidates.extend(_collect_from_mask(closed_mask_2_iter2, detector_tag="close2x2"))
    checkbox_candidates.extend(_collect_from_mask(closed_mask_3, detector_tag="close3"))
    checkbox_candidates.extend(_collect_circle_from_mask(text_mask, detector_tag="raw"))
    checkbox_candidates.extend(_collect_circle_from_mask(closed_mask_2, detector_tag="close2"))
    checkbox_candidates.extend(_collect_circle_from_mask(closed_mask_2_iter2, detector_tag="close2x2"))
    checkbox_candidates.extend(_collect_circle_from_mask(closed_mask_3, detector_tag="close3"))
    checkbox_candidates = _dedupe_by_iou(checkbox_candidates, threshold=0.70)

    widths_pt: List[float] = []
    heights_pt: List[float] = []
    x_mids_px: List[float] = []
    y_mids_px: List[float] = []
    for cand in checkbox_candidates:
        bbox = cand.get("bbox") or []
        bpx = cand.get("bboxPx") or []
        if len(bbox) != 4 or len(bpx) != 4:
            continue
        widths_pt.append(float(bbox[2] - bbox[0]))
        heights_pt.append(float(bbox[3] - bbox[1]))
        x_mids_px.append((float(bpx[0]) + float(bpx[2])) / 2.0)
        y_mids_px.append((float(bpx[1]) + float(bpx[3])) / 2.0)

    if not anchored_mode and checkbox_candidates:
        height_mask = text_height_mask if text_height_mask is not None else text_mask
        text_height_px = _estimate_text_height_px(height_mask)
        if text_height_px:
            _, sy = get_scale_factors(image_width_px, image_height_px, page_box)
            text_height_pt = float(text_height_px) * float(sy)
            min_checkbox_pt = max(4.0, text_height_pt * 0.45)
            filtered: List[Dict] = []
            filtered_w: List[float] = []
            filtered_h: List[float] = []
            filtered_x: List[float] = []
            filtered_y: List[float] = []
            for cand, wpt, hpt, xmid, ymid in zip(
                checkbox_candidates, widths_pt, heights_pt, x_mids_px, y_mids_px
            ):
                if wpt < min_checkbox_pt or hpt < min_checkbox_pt:
                    continue
                filtered.append(cand)
                filtered_w.append(wpt)
                filtered_h.append(hpt)
                filtered_x.append(xmid)
                filtered_y.append(ymid)
            if len(filtered) < len(checkbox_candidates):
                logger.debug(
                    "Filtered %s unanchored checkbox candidates below %.2fpt (text=%.2fpt)",
                    len(checkbox_candidates) - len(filtered),
                    min_checkbox_pt,
                    text_height_pt,
                )
            checkbox_candidates = filtered
            widths_pt = filtered_w
            heights_pt = filtered_h
            x_mids_px = filtered_x
            y_mids_px = filtered_y
            if not checkbox_candidates:
                return []

    if anchored_mode:
        # Anchored mode is enabled when we already detected at least one checkbox row via contours.
        #
        # We want two properties simultaneously:
        # 1) Precision: avoid hallucinating checkboxes from stray glyphs on pages without checklists.
        # 2) Recall: recover intermittently-missed squares on rows that clearly contain checkboxes.
        #
        # The row-alignment filter (anchor_rows_y_px) handles (1) by only keeping candidates that
        # align with an existing checkbox row. For (2), we optionally run a *conservative* grid
        # completion pass on the anchored candidates.
        #
        # IMPORTANT:
        # - We do NOT run the full unanchored evidence gate here because anchored candidates are
        #   already constrained to known checkbox rows. We still gate grid completion heavily to
        #   avoid filling giant cross-products when multiple checkbox groups exist on the page.

        # Not enough signal to justify completion; just return what we have.
        # Lower the threshold slightly to recover missing boxes in shorter lists.
        if len(checkbox_candidates) < 6:
            return checkbox_candidates

        # Size clustering: only use the dominant checkbox size cluster for grid completion.
        median_w = float(np.median(widths_pt)) if widths_pt else 0.0
        median_h = float(np.median(heights_pt)) if heights_pt else 0.0
        if median_w <= 0.0 or median_h <= 0.0:
            return checkbox_candidates

        def _rel_dev(v: float, med: float) -> float:
            return abs(float(v) - float(med)) / max(float(med), 1e-6)

        clustered: List[Dict] = []
        clustered_x: List[float] = []
        clustered_y: List[float] = []
        for cand, wpt, hpt, xmid, ymid in zip(
            checkbox_candidates, widths_pt, heights_pt, x_mids_px, y_mids_px
        ):
            if _rel_dev(wpt, median_w) > 0.25 or _rel_dev(hpt, median_h) > 0.25:
                continue
            clustered.append(cand)
            clustered_x.append(xmid)
            clustered_y.append(ymid)

        # If the dominant cluster is too small, completion is unlikely to help.
        if len(clustered) < 6:
            return checkbox_candidates

        def _cluster_centers(values: List[float], tol: float) -> List[float]:
            if not values:
                return []
            values = sorted(float(v) for v in values)
            centers: List[float] = []
            for v in values:
                if not centers or abs(v - centers[-1]) > tol:
                    centers.append(v)
                else:
                    centers[-1] = (centers[-1] + v) / 2.0
            return centers

        row_centers = _cluster_centers(clustered_y, tol=18.0)
        col_centers = _cluster_centers(clustered_x, tol=18.0)
        expected_total = len(row_centers) * len(col_centers)

        # Avoid pathological cross-products (multiple checkbox groups / tables on the same page).
        if expected_total <= 0 or expected_total > 420:
            return checkbox_candidates
        # Most checkbox groups are small-column checklists (Yes/No, Past/Ongoing, etc.).
        if len(col_centers) > 6:
            return checkbox_candidates

        coverage = float(len(clustered)) / float(expected_total)
        # Only complete when we already cover a meaningful fraction of the grid; otherwise
        # our (row,col) clustering is probably mixing unrelated checkbox groups.
        if coverage < 0.55:
            return checkbox_candidates

        # Median checkbox size in pixel space (more stable for local patch validation).
        clustered_w_px: List[int] = []
        clustered_h_px: List[int] = []
        for cand in clustered:
            bpx = cand.get("bboxPx") or []
            if len(bpx) != 4:
                continue
            clustered_w_px.append(int(bpx[2]) - int(bpx[0]))
            clustered_h_px.append(int(bpx[3]) - int(bpx[1]))
        median_w_px = int(np.median(clustered_w_px)) if clustered_w_px else 0
        median_h_px = int(np.median(clustered_h_px)) if clustered_h_px else 0
        if median_w_px <= 0 or median_h_px <= 0:
            return checkbox_candidates

        near_tol = max(8.0, min(24.0, float(max(median_w_px, median_h_px)) * 0.55))
        existing_centers = list(zip(clustered_x, clustered_y))

        completed: List[Dict] = []
        for yc in row_centers:
            for xc in col_centers:
                if any(abs(ex - xc) <= near_tol and abs(ey - yc) <= near_tol for ex, ey in existing_centers):
                    continue

                bw = int(round(median_w_px))
                bh = int(round(median_h_px))
                x0 = int(round(xc - bw / 2.0))
                y0 = int(round(yc - bh / 2.0))

                x0 = max(0, min(image_width_px - 1, x0))
                y0 = max(0, min(image_height_px - 1, y0))
                bw = max(1, min(image_width_px - x0, bw))
                bh = max(1, min(image_height_px - y0, bh))

                border_ratio, inner_ratio = _checkbox_border_and_inner_ink(text_mask, x0, y0, bw, bh)
                if inner_ratio >= 0.25 or border_ratio <= 0.03:
                    continue
                if _corner_ink_count(text_mask, x0, y0, bw, bh) < 1:
                    continue
                # Edge straightness: avoid filling in phantom boxes from weak/noisy borders.
                top_cov, bottom_cov, left_cov, right_cov = _checkbox_edge_coverages(
                    text_mask, x0, y0, bw, bh
                )
                edge_covs = [top_cov, bottom_cov, left_cov, right_cov]
                strong_edges = sum(1 for v in edge_covs if v >= 0.55)
                mean_edge = float(sum(edge_covs)) / 4.0
                if strong_edges < 2 and mean_edge < 0.45:
                    continue

                bbox_pts = _to_points_bbox((x0, y0, bw, bh), image_width_px, image_height_px, page_box)
                completed.append(
                    {
                        "bbox": bbox_pts,
                        "bboxPx": [int(x0), int(y0), int(x0 + bw), int(y0 + bh)],
                        "type": "checkbox",
                        "detector": "grid_complete",
                    }
                )
                existing_centers.append((float(xc), float(yc)))

        if completed:
            merged = _dedupe_by_iou(checkbox_candidates + completed, threshold=0.70)
            logger.debug(
                "Anchored checkbox grid completion: expected=%s clustered=%s added=%s -> %s",
                expected_total,
                len(clustered),
                len(completed),
                len(merged),
            )
            return merged

        return checkbox_candidates

    # Unanchored mode: require strong evidence of a checkbox pattern.
    #
    # Why this guard matters:
    # - Some glyphs (e.g., "O", "D", "0") can pass shape tests in isolation on noisy scans.
    # - A true "checkbox section" typically contains MANY repeated squares of consistent size
    #   distributed across multiple rows/columns (e.g., "Yes/No" tables).
    # Minimum number of checkbox-like candidates required before we even consider unanchored
    # recovery results. This is intentionally > a handful of stray glyphs, but low enough to
    # allow common small option groups (Gender/Language/Marital Status) that can be 6–10 total
    # checkboxes across a couple of rows on a single page (e.g. patient intake forms).
    min_required = 6
    if len(checkbox_candidates) < min_required:
        if len(checkbox_candidates) < 5:
            return []

    median_w = float(np.median(widths_pt)) if widths_pt else 0.0
    median_h = float(np.median(heights_pt)) if heights_pt else 0.0
    if median_w <= 0.0 or median_h <= 0.0:
        return []

    def _rel_dev(v: float, med: float) -> float:
        return abs(float(v) - float(med)) / max(float(med), 1e-6)

    clustered: List[Dict] = []
    clustered_x: List[float] = []
    clustered_y: List[float] = []
    clustered_w: List[float] = []
    clustered_h: List[float] = []
    for cand, wpt, hpt, xmid, ymid in zip(
        checkbox_candidates, widths_pt, heights_pt, x_mids_px, y_mids_px
    ):
        # Tight size clustering: checkbox squares should share a common size.
        if _rel_dev(wpt, median_w) > 0.25 or _rel_dev(hpt, median_h) > 0.25:
            continue
        clustered.append(cand)
        clustered_x.append(xmid)
        clustered_y.append(ymid)
        clustered_w.append(wpt)
        clustered_h.append(hpt)

    if len(clustered) < min_required:
        if len(clustered) < 5:
            return []

    def _cluster_count(values: List[float], tol: float) -> int:
        if not values:
            return 0
        values = sorted(float(v) for v in values)
        centers: List[float] = []
        for v in values:
            if not centers or abs(v - centers[-1]) > tol:
                centers.append(v)
            else:
                centers[-1] = (centers[-1] + v) / 2.0
        return len(centers)

    # At 500 DPI, checkboxes are ~60–90px wide. Rows are separated by ~45–85px depending on font.
    # Use loose clustering tolerances to count distinct rows/cols while allowing scan jitter.
    row_clusters = _cluster_count(clustered_y, tol=18.0)
    col_clusters = _cluster_count(clustered_x, tol=18.0)

    # Evidence gates for unanchored recovery:
    # - Many forms have "Y/N" checklists: two checkbox columns repeated across many rows.
    # - Other forms have broader grids (>=3 columns) or multiple Y/N groups (4 columns).
    #
    # We accept either:
    # - a reasonably grid-like layout (>=3 rows and >=3 columns), OR
    # - a dense repeated checklist (>=6 rows and >=2 columns) with enough total samples.
    grid_like = row_clusters >= 3 and col_clusters >= 2 and len(clustered) >= 8
    repeated_checklist = row_clusters >= 5 and col_clusters >= 2 and len(clustered) >= 12
    # Single-column checklists are common; allow a strong vertical stack.
    single_column = row_clusters >= 6 and col_clusters == 1 and len(clustered) >= 8
    single_row = row_clusters == 1 and col_clusters >= 5 and len(clustered) >= 5
    if not (grid_like or repeated_checklist or single_column or single_row):
        # Not structured enough to trust unanchored detection.
        return []

    logger.debug(
        "Recovered %s unanchored checkboxes (median=%.2fpt x %.2fpt, rows=%s cols=%s)",
        len(clustered),
        median_w,
        median_h,
        row_clusters,
        col_clusters,
    )

    # Grid completion pass:
    # - Dense Y/N tables sometimes have a subset of squares missed due to broken borders or
    #   thresholding artifacts.
    # - Once we have strong evidence of a checkbox grid (above), we can "fill in" missing
    #   squares by checking expected row/col intersections and validating the border/inner ink.
    #
    # This significantly improves recall on pages like errorYesNoCheckBox.png where every row
    # repeats the same small checkbox size.
    def _cluster_centers(values: List[float], tol: float) -> List[float]:
        if not values:
            return []
        values = sorted(float(v) for v in values)
        centers: List[float] = []
        for v in values:
            if not centers or abs(v - centers[-1]) > tol:
                centers.append(v)
            else:
                centers[-1] = (centers[-1] + v) / 2.0
        return centers

    row_centers = _cluster_centers(clustered_y, tol=18.0)
    col_centers = _cluster_centers(clustered_x, tol=18.0)
    expected_total = len(row_centers) * len(col_centers)
    if expected_total <= 0 or expected_total > 800:
        return clustered

    # Median checkbox size in pixel space (more stable for local patch validation).
    clustered_w_px: List[int] = []
    clustered_h_px: List[int] = []
    for cand in clustered:
        bpx = cand.get("bboxPx") or []
        if len(bpx) != 4:
            continue
        clustered_w_px.append(int(bpx[2]) - int(bpx[0]))
        clustered_h_px.append(int(bpx[3]) - int(bpx[1]))
    median_w_px = int(np.median(clustered_w_px)) if clustered_w_px else 0
    median_h_px = int(np.median(clustered_h_px)) if clustered_h_px else 0
    if median_w_px <= 0 or median_h_px <= 0:
        return clustered

    # Tolerance to consider an existing detection "close enough" to the expected center.
    near_tol = max(8.0, min(24.0, float(max(median_w_px, median_h_px)) * 0.55))
    existing_centers = list(zip(clustered_x, clustered_y))

    completed: List[Dict] = []
    for yc in row_centers:
        for xc in col_centers:
            if any(abs(ex - xc) <= near_tol and abs(ey - yc) <= near_tol for ex, ey in existing_centers):
                continue

            bw = int(round(median_w_px))
            bh = int(round(median_h_px))
            x0 = int(round(xc - bw / 2.0))
            y0 = int(round(yc - bh / 2.0))

            # Clamp within image bounds.
            x0 = max(0, min(image_width_px - 1, x0))
            y0 = max(0, min(image_height_px - 1, y0))
            bw = max(1, min(image_width_px - x0, bw))
            bh = max(1, min(image_height_px - y0, bh))

            # Validate the local patch: checkbox borders should have perimeter ink and low interior ink.
            border_ratio, inner_ratio = _checkbox_border_and_inner_ink(text_mask, x0, y0, bw, bh)
            if inner_ratio >= 0.25 or border_ratio <= 0.03:
                continue
            if _corner_ink_count(text_mask, x0, y0, bw, bh) < 1:
                continue
            # Edge straightness: avoid filling in phantom boxes from weak/noisy borders.
            top_cov, bottom_cov, left_cov, right_cov = _checkbox_edge_coverages(
                text_mask, x0, y0, bw, bh
            )
            edge_covs = [top_cov, bottom_cov, left_cov, right_cov]
            strong_edges = sum(1 for v in edge_covs if v >= 0.55)
            mean_edge = float(sum(edge_covs)) / 4.0
            if strong_edges < 2 and mean_edge < 0.45:
                continue

            bbox_pts = _to_points_bbox((x0, y0, bw, bh), image_width_px, image_height_px, page_box)
            completed.append(
                {
                    "bbox": bbox_pts,
                    "bboxPx": [int(x0), int(y0), int(x0 + bw), int(y0 + bh)],
                    "type": "checkbox",
                    "detector": "grid_complete",
                }
            )
            existing_centers.append((float(xc), float(yc)))

    if completed:
        merged = _dedupe_by_iou(clustered + completed, threshold=0.70)
        logger.debug(
            "Checkbox grid completion: expected=%s existing=%s added=%s -> %s",
            expected_total,
            len(clustered),
            len(completed),
            len(merged),
        )
        return merged

    return clustered


def _looks_like_shaded_header_rule(
    gray: np.ndarray | None,
    x: int,
    y: int,
    w: int,
    h: int,
    *,
    band_height_px: int,
) -> bool:
    """
    Return True when a horizontal segment is likely a decorative header/pill border.

    Motivation:
    - Scanned forms often have shaded/filled header pills with a thick border.
    - The bottom border can be detected as a long "underline" candidate and becomes a
      false text field (see errorHeaderClassifiedAsField.png).

    Heuristic:
    - Compare grayscale mean above vs below the candidate (mid-span only).
    - If below is meaningfully darker, it indicates a shaded fill below the border.
    """
    if gray is None or gray.size == 0:
        return False
    if w <= 0 or h <= 0:
        return False

    # Only apply this check to longer rules; short candidates are unlikely to be header pills.
    if w < 420:
        return False

    h_img, w_img = gray.shape[:2]
    x0 = int(x + w * 0.20)
    x1 = int(x + w * 0.80)
    if x1 <= x0:
        x0, x1 = int(x), int(x + w)
    x0 = max(0, min(w_img, x0))
    x1 = max(0, min(w_img, x1))

    # IMPORTANT: Use a *local* probe band rather than the full band_height_px.
    #
    # Why:
    # - This function is meant to detect decorative borders where the region immediately
    #   adjacent to the rule is shaded (e.g., header pills / filled sections).
    # - On real input underlines, the band *further down* often contains printed text from
    #   the next row, which lowers the grayscale mean and can cause false positives.
    #
    # Using a smaller band focuses on the adjacent fill and ignores unrelated text below.
    probe_h = int(round(float(band_height_px) * 0.35))
    probe_h = max(12, min(probe_h, int(band_height_px)))

    above_y0 = max(0, int(y - probe_h))
    above_y1 = max(0, min(h_img, int(y)))
    below_y0 = max(0, min(h_img, int(y + h)))
    below_y1 = max(0, min(h_img, int(y + h + probe_h)))
    if above_y1 <= above_y0 or below_y1 <= below_y0 or x1 <= x0:
        return False

    above = gray[above_y0:above_y1, x0:x1]
    below = gray[below_y0:below_y1, x0:x1]
    if above.size == 0 or below.size == 0:
        return False

    mean_above = float(np.mean(above))
    mean_below = float(np.mean(below))
    # When below is darker by a noticeable margin, treat as decorative.
    return mean_below < (mean_above - 12.0) and mean_below < 245.0


def _looks_like_text_underline(
    text_mask: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
    *,
    band_height_px: int,
) -> bool:
    """
    Detect underlined *text* (styling) that should NOT become a fillable underline candidate.

    Heuristic:
    - Measure "ink" density immediately above the candidate within the *middle* span.
      This avoids false positives when a form prints the label above the start of a long
      underline (label occupies the left edge only, while the typing area remains blank).
    - Only reject when the above-band is meaningfully dense; real underlines should have a
      mostly blank band above the typing area.
    """
    if text_mask is None or text_mask.size == 0:
        return False
    if w <= 0 or h <= 0:
        return False

    # Only consider a band above the line's top edge; clamp to image bounds in _foreground_ratio.
    above_y0 = y - int(band_height_px)
    above_y1 = y

    # Also consider a smaller band *below* the line. This helps reject horizontal strokes
    # inside normal text glyphs (crossbars, baseline noise), where ink exists immediately
    # below the detected segment.
    below_h = max(8, int(round(band_height_px * 0.5)))
    below_y0 = y + int(h)
    below_y1 = below_y0 + int(below_h)

    # Focus on the middle 60% of the underline span to avoid label-above patterns.
    x0 = x + int(round(w * 0.20))
    x1 = x + int(round(w * 0.80))
    if x1 <= x0:
        x0, x1 = x, x + w

    ratio_above = _foreground_ratio(text_mask, x0, above_y0, x1, above_y1)
    if ratio_above >= UNDERLINE_ABOVE_RATIO:
        # Underlined words/headers typically have dense ink immediately above the underline.
        return True

    # Stricter rejection for very short segments: these are often letter strokes.
    if w <= 500 and ratio_above >= UNDERLINE_SHORT_ABOVE_RATIO:
        return True

    ratio_below = _foreground_ratio(text_mask, x0, below_y0, x1, below_y1)
    # Reject if there is meaningful ink immediately below. Real input underlines should
    # have a mostly blank band below the stroke.
    if ratio_below >= UNDERLINE_BELOW_RATIO:
        return True

    return False


def _looks_like_text_underline_short(
    text_mask: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
    *,
    band_height_px: int,
) -> bool:
    """
    Variant of `_looks_like_text_underline()` tuned for short blanks ("____") in questionnaires.

    Problem we solve:
    - On scanned forms, the Otsu mask often contains speckle noise.
    - The long-underline filter is intentionally strict and can reject legitimate short blanks
      because a tiny amount of noise in the band above crosses the threshold.

    Strategy:
    - Use a narrower x-span (middle 40%) so nearby label text on either side does not poison
      the "ink above" measurement.
    - Use higher thresholds (more tolerant) so we keep real blanks and rely on downstream
      matching to ignore decorative underlines.
    """
    if text_mask is None or text_mask.size == 0:
        return False
    if w <= 0 or h <= 0:
        return False

    # For short blanks we want a *local* neighborhood, not the full typography band.
    # A large band dilutes ink density (lots of whitespace) and can let letter strokes pass.
    local_band = max(10, min(28, int(round(max(h * 6.0, 12.0)))))

    # Extra guard for false positives:
    # - The short-line morphology pass can pick up tiny horizontal strokes inside normal text
    #   glyphs (e.g., the baseline of a letter) and treat them as "____" blanks.
    # - These strokes often have printed ink immediately above them, but in a *very thin* band.
    # - The larger `local_band` ratio can miss that because it is diluted by whitespace.
    #
    # So we also check a very small "near-above" band to strongly reject candidates that are
    # actually attached to printed text.
    near_band = max(4, min(10, int(round(max(h * 2.0, 6.0)))))

    above_y0 = y - int(local_band)
    above_y1 = y
    below_y0 = y + int(h)
    below_y1 = below_y0 + int(local_band)

    # Middle 40% of the candidate span.
    x0 = x + int(round(w * 0.30))
    x1 = x + int(round(w * 0.70))
    if x1 <= x0:
        x0, x1 = x, x + w

    ratio_near_above = _foreground_ratio(text_mask, x0, y - int(near_band), x1, y)
    # Real blanks tend to have an almost entirely clean band immediately above the line.
    # If this band is meaningfully inky, the candidate is likely a text-glyph stroke.
    if ratio_near_above >= UNDERLINE_SHORT_NEAR_ABOVE_RATIO:
        return True

    ratio_above = _foreground_ratio(text_mask, x0, above_y0, x1, above_y1)
    # Short text strokes will have meaningful ink immediately above.
    if ratio_above >= UNDERLINE_SHORT_ABOVE_RATIO:
        return True

    ratio_below = _foreground_ratio(text_mask, x0, below_y0, x1, below_y1)
    # Reject when there is meaningful ink below; real blanks usually sit on whitespace.
    if ratio_below >= UNDERLINE_SHORT_BELOW_RATIO:
        return True

    # Wide-band header pill / table-header rejection:
    #
    # Some pages render section headers inside bordered "pills" (rounded rectangles with
    # text inside). The bottom border of these pills is frequently detected as a short
    # underline candidate by the `morph_short` pass.
    #
    # The local above-band checks can miss this because the pill text can sit farther above
    # the bottom border than `local_band`. A wider band (roughly 12pt in page space) captures
    # that interior text density and cleanly separates decorative borders from real blanks.
    wide_above = _foreground_ratio(text_mask, x0, y - int(band_height_px), x1, y)
    # Only apply this to longer "short" candidates; very small underscore blanks can have
    # noisy ratios in a wide band and are handled by the local checks above.
    if w >= 250 and wide_above >= UNDERLINE_SHORT_WIDE_ABOVE_RATIO:
        return True

    return False


def _dedupe_line_candidates(candidates: List[Dict]) -> List[Dict]:
    """
    Remove near-duplicate underline candidates produced by multiple detectors.

    We keep the first candidate in y/x order and discard later candidates with a high
    IoU overlap. This reduces resolver confusion on dense pages.
    """
    if not candidates:
        return []
    sorted_candidates = sorted(
        candidates,
        key=lambda c: (
            float((c.get("bbox") or [0, 0, 0, 0])[1]),
            float((c.get("bbox") or [0, 0, 0, 0])[0]),
        ),
    )
    kept: List[Dict] = []
    for cand in sorted_candidates:
        bbox = cand.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        is_dup = False
        for prev in kept:
            prev_bbox = prev.get("bbox")
            if not prev_bbox or len(prev_bbox) != 4:
                continue
            if _iou(bbox, prev_bbox) >= 0.88:
                is_dup = True
                break
        if not is_dup:
            kept.append(cand)
    return kept


def _dedupe_contained_lines(candidates: List[Dict]) -> List[Dict]:
    """
    Drop short segments fully contained by a longer line on the same row.

    This keeps the resolver payload small and avoids confusing "one underline becomes many
    candidates" when multiple detectors fire.
    """
    if not candidates:
        return []
    sorted_candidates = sorted(
        candidates,
        key=lambda c: (
            float((c.get("bbox") or [0, 0, 0, 0])[1]),
            float((c.get("bbox") or [0, 0, 0, 0])[0]),
            -float((c.get("bbox") or [0, 0, 0, 0])[2] - (c.get("bbox") or [0, 0, 0, 0])[0]),
        ),
    )
    kept: List[Dict] = []
    y_tol = 3.0
    for cand in sorted_candidates:
        bbox = cand.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        cx1, cy1, cx2, cy2 = [float(v) for v in bbox]
        contained = False
        for prev in kept:
            pb = prev.get("bbox")
            if not pb or len(pb) != 4:
                continue
            px1, py1, px2, py2 = [float(v) for v in pb]
            same_row = abs(((cy1 + cy2) / 2.0) - ((py1 + py2) / 2.0)) <= y_tol
            if not same_row:
                continue
            # Containment with small tolerance.
            if cx1 >= px1 - 2 and cx2 <= px2 + 2 and cy1 >= py1 - 2 and cy2 <= py2 + 2:
                # Only drop if the previous candidate is meaningfully longer.
                if (px2 - px1) >= (cx2 - cx1) + 12:
                    contained = True
                    break
        if not contained:
            kept.append(cand)
    return kept


def _extract_table_lines_multiscale(
    binary_lines: np.ndarray,
    image_width_px: int,
    image_height_px: int,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Extract table/grid rule lines using multiple morphology scales.

    Why this exists:
    - Large tables span most of the page and need large kernels to suppress text strokes.
    - Small tables (e.g., "Hospitalizations") are short in height, so large kernels like
      `image_height_px // 6` erase vertical rules entirely.

    We union multiple kernel sizes so both large and small grids survive. Downstream table
    detection still requires BOTH vertical and horizontal evidence, so this does not turn
    every underline-heavy page into a "table".
    """
    # Kernel sizing notes (500 DPI typical):
    # - US Letter render is ~4250x5500.
    # - Small tables can be ~300–600px tall; vertical kernels must be below that.
    # - Kernels that are too small start picking up glyph stems; keep a conservative floor.
    horiz_kernel_ws = sorted(
        {
            max(120, image_width_px // 24),
            max(220, image_width_px // 12),
            max(220, image_width_px // 6),
        }
    )
    vert_kernel_hs = sorted(
        {
            max(40, image_height_px // 120),
            max(60, image_height_px // 80),
            max(90, image_height_px // 60),
            max(120, image_height_px // 24),
            max(220, image_height_px // 12),
            max(220, image_height_px // 6),
        }
    )

    horiz_union = np.zeros_like(binary_lines)
    for kw in horiz_kernel_ws:
        horiz_union = cv2.bitwise_or(
            horiz_union,
            cv2.morphologyEx(
                binary_lines,
                cv2.MORPH_OPEN,
                cv2.getStructuringElement(cv2.MORPH_RECT, (int(kw), 2)),
                iterations=1,
            ),
        )

    vert_union = np.zeros_like(binary_lines)
    for kh in vert_kernel_hs:
        vert_union = cv2.bitwise_or(
            vert_union,
            cv2.morphologyEx(
                binary_lines,
                cv2.MORPH_OPEN,
                cv2.getStructuringElement(cv2.MORPH_RECT, (2, int(kh))),
                iterations=1,
            ),
        )
    # Suppress short glyph stems and keep only meaningful vertical rules.
    min_vert_height = max(40, int(image_height_px * 0.008))
    max_vert_width = max(6, int(image_width_px * 0.002))
    try:
        num, labels, stats, _ = cv2.connectedComponentsWithStats(vert_union, connectivity=8)
        if num > 1:
            keep = np.zeros(num, dtype=bool)
            for idx in range(1, num):
                comp_h = int(stats[idx, cv2.CC_STAT_HEIGHT])
                comp_w = int(stats[idx, cv2.CC_STAT_WIDTH])
                comp_area = int(stats[idx, cv2.CC_STAT_AREA])
                if comp_h >= min_vert_height and comp_w <= max_vert_width and comp_area >= min_vert_height:
                    keep[idx] = True
            vert_union = (keep[labels].astype(np.uint8)) * 255
    except cv2.error:
        pass

    table_lines = cv2.bitwise_or(horiz_union, vert_union)
    # Light close to reconnect faint or broken grid lines so rows do not merge.
    table_lines = cv2.morphologyEx(
        table_lines,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
        iterations=1,
    )
    return table_lines, horiz_union, vert_union


def _detect_table_checkbox_cells(
    binary_lines: np.ndarray,
    text_mask: np.ndarray,
    image_width_px: int,
    image_height_px: int,
    page_box: PageBox,
) -> List[Dict]:
    """
    Detect checkbox-like cells inside chart/table grids.

    Why this exists:
    - On grid "charts" (e.g., family history tables), the checkable areas are the *cells*.
    - Contour-based box detection struggles because the grid lines are one connected component.
    - We instead isolate long horizontal/vertical rules, invert, then contour the *empty spaces*
      (cells) and keep only small, boxy regions.
    """
    table_lines, horiz, vert = _extract_table_lines_multiscale(
        binary_lines, image_width_px, image_height_px
    )
    # Require meaningful vertical AND horizontal rule evidence; this prevents false positives
    # on pages that have a single column divider line or just many underlines.
    min_vert = max(240, int(image_height_px * 0.035))
    min_horiz = max(2800, int(image_width_px * 0.55))
    if int(np.count_nonzero(vert)) < min_vert or int(np.count_nonzero(horiz)) < min_horiz:
        return []

    contours, _ = cv2.findContours(table_lines, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []

    candidates: List[Dict] = []
    image_area = float(image_width_px * image_height_px)
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w <= 0 or h <= 0:
            continue
        # Only consider large regions; we will carve cell interiors inside them.
        if float(w * h) < image_area * 0.008:
            continue
        if w < int(image_width_px * 0.18) or h < int(image_height_px * 0.10):
            continue

        region = table_lines[y : y + h, x : x + w]
        if region.size == 0:
            continue

        # Invert so cell interiors become white regions separated by black table lines.
        cells = cv2.bitwise_not(region)
        # Force border to black so the "outside" doesn't merge into one giant region.
        cells[0, :] = 0
        cells[-1, :] = 0
        cells[:, 0] = 0
        cells[:, -1] = 0

        cell_contours, _ = cv2.findContours(cells, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cc in cell_contours:
            cx, cy, cw, ch = cv2.boundingRect(cc)
            if cw <= 0 or ch <= 0:
                continue
            # Convert to page pts for sizing filters (stable across DPI).
            bbox_pts = _to_points_bbox(
                (x + cx, y + cy, cw, ch),
                image_width_px,
                image_height_px,
                page_box,
            )
            width_pt = float(bbox_pts[2] - bbox_pts[0])
            height_pt = float(bbox_pts[3] - bbox_pts[1])
            if width_pt < 6 or height_pt < 6:
                continue
            if width_pt > 80 or height_pt > 80:
                # Avoid wide label columns and header blocks.
                continue
            aspect = width_pt / max(height_pt, 0.01)
            if aspect < 0.55 or aspect > 1.8:
                continue

            # Header cells often contain rotated text (family-member labels). Those regions
            # have high "ink" density inside the cell. Real checkable cells are blank.
            pad_px = max(2, min(int(min(cw, ch) * 0.12), 10))
            inner_ink = _foreground_ratio(
                text_mask,
                x + cx + pad_px,
                y + cy + pad_px,
                x + cx + cw - pad_px,
                y + cy + ch - pad_px,
            )
            if inner_ink >= 0.14:
                continue

            candidates.append(
                {
                    "bbox": bbox_pts,
                    "bboxPx": [int(x + cx), int(y + cy), int(x + cx + cw), int(y + cy + ch)],
                    "type": "checkbox",
                    "detector": "table_cells",
                }
            )
    return candidates


def _detect_table_text_cells(
    binary_lines: np.ndarray,
    text_mask: np.ndarray,
    image_width_px: int,
    image_height_px: int,
    page_box: PageBox,
) -> List[Dict]:
    """
    Detect blank, text-entry table cells inside chart/table grids.

    Motivation:
    - Some forms encode repeating entry areas as a table (e.g., "Hospitalizations",
      "Food diary", immunizations grids).
    - These are not checkbox-like near-squares; they are wider rectangles that should
      become text fields.
    - Contour-based box detection often fails because the grid is one connected component.

    Approach:
    - Reuse the "invert table lines and contour empty spaces" strategy from
      `_detect_table_checkbox_cells`.
    - Keep wider aspect cells (rectangles) and reject cells containing significant ink
      (headers/labels inside the table).

    Why the ink filter needs to be strict:
    - Example/header rows in some tables contain *small* amounts of text (e.g., a single word
      like "Moderate"). The overall foreground ratio inside the cell can be surprisingly low,
      which makes a naive `ink_ratio` threshold too permissive.
    - We add a connected-components check on the interior to catch these cases without
      relying on OCR availability.
    """
    sx, sy = get_scale_factors(image_width_px, image_height_px, page_box)
    table_lines, horiz, vert = _extract_table_lines_multiscale(
        binary_lines, image_width_px, image_height_px
    )
    # Require both vertical and horizontal evidence to avoid treating stacked underlines
    # (questionnaire blanks) as a "table".
    # Be more permissive so sparse/faint grids still qualify as tables.
    min_vert = max(160, int(image_height_px * 0.015))
    min_horiz = max(2500, int(image_width_px * 0.55))
    if int(np.count_nonzero(vert)) < min_vert or int(np.count_nonzero(horiz)) < min_horiz:
        return []

    contours, _ = cv2.findContours(table_lines, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []

    candidates: List[Dict] = []
    total_cells = 0
    skipped_ink = 0
    skipped_text = 0
    skipped_corner = 0
    image_area = float(image_width_px * image_height_px)
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w <= 0 or h <= 0:
            continue
        # Only consider large regions that plausibly contain a grid/table.
        if float(w * h) < image_area * 0.004:
            continue
        # Small-table support:
        # - "Hospitalizations" style tables can be short (only a few rows) but still very wide.
        # - A 12% height threshold excludes those.
        # Keep the area gating above as the main safety check.
        if w < int(image_width_px * 0.10) or h < int(image_height_px * 0.015):
            continue

        region = table_lines[y : y + h, x : x + w]
        if region.size == 0:
            continue
        cells = cv2.bitwise_not(region)
        cells[0, :] = 0
        cells[-1, :] = 0
        cells[:, 0] = 0
        cells[:, -1] = 0

        cell_contours, _ = cv2.findContours(cells, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cell_rects: List[Tuple[int, int, int, int]] = []
        for cc in cell_contours:
            cx, cy, cw, ch = cv2.boundingRect(cc)
            if cw <= 0 or ch <= 0:
                continue
            cell_rects.append((cx, cy, cw, ch))
        if not cell_rects:
            continue

        min_cy = min(cy for _, cy, _, _ in cell_rects)
        max_x = max(cx + cw for cx, _, cw, _ in cell_rects)
        heights = sorted(ch for _, _, _, ch in cell_rects)
        widths = sorted(cw for _, _, cw, _ in cell_rects)
        median_h = heights[len(heights) // 2]
        median_w = widths[len(widths) // 2]
        # Reject the top-right header cell if it exists. It is typically a label cell,
        # not a fillable input, and tends to create false positives in charts.
        top_row_tol = max(4, min(int(median_h * 0.6), int(h * 0.12)))
        right_col_tol = max(4, min(int(median_w * 0.6), int(w * 0.08)))

        # Identify checkbox columns inside wide tables (e.g., "Daily/Some/None" grids).
        # We cluster cells by X center, then flag narrow, repeated columns as checkboxes
        # when they occupy only a minority of the table width (labels live to the left).
        cell_meta: List[Dict] = []
        for cx, cy, cw, ch in cell_rects:
            if cw <= 0 or ch <= 0:
                continue
            cell_meta.append(
                {
                    "cx": cx,
                    "cy": cy,
                    "cw": cw,
                    "ch": ch,
                    "abs_x1": x + cx,
                    "abs_x2": x + cx + cw,
                    "abs_y1": y + cy,
                    "abs_y2": y + cy + ch,
                    "center_x": x + cx + (cw / 2.0),
                    "center_y": y + cy + (ch / 2.0),
                    "width_pt": float(cw) * sx,
                    "height_pt": float(ch) * sy,
                }
            )
        promote_checkbox_columns: List[Tuple[float, float]] = []
        if cell_meta:
            col_tol_px = max(6, int(median_w * 0.45))
            columns: List[Dict] = []
            for meta in sorted(cell_meta, key=lambda m: m["center_x"]):
                if not columns or abs(meta["center_x"] - columns[-1]["center_x"]) > col_tol_px:
                    columns.append({"center_x": meta["center_x"], "cells": [meta]})
                else:
                    col = columns[-1]
                    col["cells"].append(meta)
                    col["center_x"] = (
                        (col["center_x"] * (len(col["cells"]) - 1)) + meta["center_x"]
                    ) / float(len(col["cells"]))
            for col in columns:
                col_cells = col["cells"]
                col_widths = sorted(c["width_pt"] for c in col_cells)
                col_heights = sorted(c["height_pt"] for c in col_cells)
                col_aspects = sorted(
                    c["width_pt"] / max(c["height_pt"], 0.01) for c in col_cells
                )
                col["median_width_pt"] = col_widths[len(col_widths) // 2]
                col["median_height_pt"] = col_heights[len(col_heights) // 2]
                col["median_aspect"] = col_aspects[len(col_aspects) // 2]
                col["count"] = len(col_cells)
                col["min_x_px"] = min(c["abs_x1"] for c in col_cells)
                col["max_x_px"] = max(c["abs_x2"] for c in col_cells)
            narrow_columns = []
            for col in columns:
                if col["count"] < 4:
                    continue
                if (
                    col["median_width_pt"] <= 55.0
                    and col["median_height_pt"] <= 22.0
                    and 0.7 <= col["median_aspect"] <= 1.6
                ):
                    narrow_columns.append(col)
            if len(narrow_columns) >= 2:
                narrow_min = min(col["min_x_px"] for col in narrow_columns)
                narrow_max = max(col["max_x_px"] for col in narrow_columns)
                narrow_span_ratio = float(narrow_max - narrow_min) / max(float(w), 1.0)
                if narrow_span_ratio <= 0.72:
                    promote_checkbox_columns = [
                        (float(col["min_x_px"]), float(col["max_x_px"])) for col in narrow_columns
                    ]

        for cx, cy, cw, ch in cell_rects:
            total_cells += 1
            if (cy - min_cy) <= top_row_tol and (max_x - (cx + cw)) <= right_col_tol:
                skipped_corner += 1
                continue

            bbox_pts = _to_points_bbox(
                (x + cx, y + cy, cw, ch),
                image_width_px,
                image_height_px,
                page_box,
            )
            width_pt = float(bbox_pts[2] - bbox_pts[0])
            height_pt = float(bbox_pts[3] - bbox_pts[1])
            if width_pt < 18 or height_pt < 6:
                continue
            if width_pt > 720 or height_pt > 170:
                continue
            aspect = width_pt / max(height_pt, 0.01)
            if aspect < 1.1 or aspect > 60.0:
                continue

            # Reject cells containing printed text (headers/labels inside the table).
            pad_px = max(3, min(int(min(cw, ch) * 0.10), 14))
            inner_ink = _foreground_ratio(
                text_mask,
                x + cx + pad_px,
                y + cy + pad_px,
                x + cx + cw - pad_px,
                y + cy + ch - pad_px,
            )
            # First-pass ink gating: eliminate obvious non-empty cells quickly.
            if inner_ink >= 0.22:
                skipped_ink += 1
                continue
            # Second-pass: detect "real text" even when ink ratio is relatively low.
            #
            # Why we run this even for small `inner_ink`:
            # - Header/example cells can contain a single word ("Moderate") that occupies a tiny
            #   fraction of the cell area, yielding a low foreground ratio.
            # - Relying only on `inner_ink` causes those header cells to slip through and become
            #   false fields (see errorChartsNewPerfectButSomeHeadersIncluded.png).
            ix1 = int(max(0, x + cx + pad_px))
            iy1 = int(max(0, y + cy + pad_px))
            ix2 = int(min(image_width_px, x + cx + cw - pad_px))
            iy2 = int(min(image_height_px, y + cy + ch - pad_px))
            if ix2 > ix1 and iy2 > iy1:
                # The padding above can fully exclude top-aligned text in short cells (e.g.,
                # the example row in the "Please rank..." table). Use a smaller probe padding
                # for the text check, and remove table rule lines so grid fragments do not
                # swamp the connected-components analysis.
                probe_pad = max(1, min(int(pad_px), 4))
                tx1 = int(max(0, x + cx + probe_pad))
                ty1 = int(max(0, y + cy + probe_pad))
                tx2 = int(min(image_width_px, x + cx + cw - probe_pad))
                ty2 = int(min(image_height_px, y + cy + ch - probe_pad))
                if tx2 <= tx1 or ty2 <= ty1:
                    roi = None
                    roi_lines = None
                else:
                    roi = text_mask[ty1:ty2, tx1:tx2]
                    roi_lines = table_lines[ty1:ty2, tx1:tx2]
                if roi is None or roi.size == 0:
                    roi = text_mask[iy1:iy2, ix1:ix2]
                    roi_lines = table_lines[iy1:iy2, ix1:ix2]
                if roi is None or roi.size == 0:
                    roi = None
                    roi_lines = None
                if roi is None or roi_lines is None or roi.size == 0:
                    roi_clean = None
                else:
                    roi_clean = roi.copy()
                    # Remove table grid rule pixels; we only care about printed text.
                    roi_clean[roi_lines > 0] = 0
                # `text_mask` is 0/255. Convert to 0/1 for connected components.
                bin_roi = (roi_clean > 0).astype(np.uint8) if roi_clean is not None else None
                try:
                    if bin_roi is not None:
                        num, _, stats, _ = cv2.connectedComponentsWithStats(bin_roi, connectivity=8)
                    else:
                        num = 0
                        stats = None
                except cv2.error:
                    num = 0
                    stats = None
                if num and stats is not None and int(num) > 1:
                    # Components >= 60 px are typically letters/words at 500 DPI.
                    # Ignore thin table-rule fragments by requiring a meaningful component size.
                    areas = stats[1:, cv2.CC_STAT_AREA]
                    widths = stats[1:, cv2.CC_STAT_WIDTH]
                    heights = stats[1:, cv2.CC_STAT_HEIGHT]
                    looks_like_text = (areas >= 110) & (widths >= 9) & (heights >= 9)
                    if int(np.count_nonzero(looks_like_text)) >= 1:
                        skipped_text += 1
                        continue

            cell_is_checkbox = False
            if promote_checkbox_columns:
                center_x = x + cx + (cw / 2.0)
                for col_min, col_max in promote_checkbox_columns:
                    if (col_min - 2.0) <= center_x <= (col_max + 2.0):
                        # Guard against wide table cells that were clustered into a
                        # checkbox column by position but are not checkbox-shaped.
                        if 0.7 <= aspect <= 1.6:
                            cell_is_checkbox = True
                        break

            candidates.append(
                {
                    "bbox": bbox_pts,
                    "bboxPx": [int(x + cx), int(y + cy), int(x + cx + cw), int(y + cy + ch)],
                    "type": "checkbox" if cell_is_checkbox else "box",
                    "detector": "table_text_cell",
                }
            )
    if total_cells and (skipped_ink or skipped_text):
        logger.debug(
            "table_text_cell: kept=%s total=%s skipped_ink=%s skipped_text=%s",
            len(candidates),
            total_cells,
            skipped_ink,
            skipped_text,
        )
    if skipped_corner:
        logger.debug("table_text_cell: dropped %s top-right header cells", skipped_corner)
    return candidates


def _detect_boxes(
    binary: np.ndarray,
    text_mask: np.ndarray,
    vertical_mask: np.ndarray | None,
    horizontal_mask: np.ndarray | None,
    image_width_px: int,
    image_height_px: int,
    page_box: PageBox,
) -> Dict[str, List[Dict]]:
    """Detect rectangular contours for text boxes and checkboxes."""
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    box_candidates: List[Dict] = []
    checkbox_candidates: List[Dict] = []
    decorative_box_candidates: List[Dict] = []

    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w <= 0 or h <= 0:
            continue
        bbox_pts = _to_points_bbox((x, y, w, h), image_width_px, image_height_px, page_box)
        width_pt = bbox_pts[2] - bbox_pts[0]
        height_pt = bbox_pts[3] - bbox_pts[1]
        if width_pt < 5 or height_pt < 5:
            continue

        aspect_ratio = width_pt / max(height_pt, 0.01)
        approx = cv2.approxPolyDP(contour, 0.04 * cv2.arcLength(contour, True), True)
        # Scanned boxes can be noisy and many forms use rounded rectangles for section headers.
        # Rounded "pill" headers often approximate to ~8–12 vertices, so we allow a few more
        # here and rely on later interior-ink/text checks to avoid treating them as inputs.
        is_rect_like = 4 <= len(approx) <= 12

        # Checkbox: near-square and modest size.
        if (
            4 <= width_pt <= 44
            and 4 <= height_pt <= 44
            and 0.65 <= aspect_ratio <= 1.40
            and is_rect_like
        ):
            # Filter out glyph blobs misclassified as checkboxes by verifying:
            # - Interior is mostly empty
            # - Ink is concentrated near the perimeter
            # - Shape is sufficiently boxy (extent/solidity/convexity)
            if not _is_strong_checkbox_shape(contour, approx, int(x), int(y), int(w), int(h), text_mask):
                continue
            checkbox_candidates.append(
                {
                    "bbox": bbox_pts,
                    "bboxPx": [int(x), int(y), int(x + w), int(y + h)],
                    "type": "checkbox",
                    "detector": "contour",
                }
            )
            continue

        # General box for text or signature inputs.
        if is_rect_like and width_pt >= 28 and height_pt <= 160:
            # Tables/grids often form a single large rectangle. Treat those as chart regions
            # (handled separately) rather than a single giant text field candidate.
            if vertical_mask is not None and width_pt >= 140 and height_pt >= 40:
                if horizontal_mask is not None and _looks_like_table_grid_region(
                    vertical_mask, horizontal_mask, int(x), int(y), int(w), int(h)
                ):
                    continue
                # Fallback: when we cannot compute a horizontal mask, keep the legacy guard
                # to avoid emitting one giant box for obvious grid regions.
                if horizontal_mask is None:
                    pad_px = max(2, min(int(min(w, h) * 0.08), 10))
                    v_ratio = _foreground_ratio(
                        vertical_mask,
                        x + pad_px,
                        y + pad_px,
                        x + w - pad_px,
                        y + h - pad_px,
                    )
                    if v_ratio >= 0.02:
                        continue

            # Exclude decorative header bars and filled shapes:
            # - Real input boxes are mostly blank inside (low ink ratio).
            # - Scanned documents can produce rectangle-ish blobs around individual words
            #   when thresholding merges glyphs (see errorRandomWordField.png).
            #
            # Apply the "blank interior" check to ALL box candidates (not only wide ones)
            # so we don't feed word-blobs into the resolver.
            pad = max(2, min(int(min(w, h) * 0.12), 10))
            inner_w = int(w - 2 * pad)
            inner_h = int(h - 2 * pad)
            if inner_w >= 6 and inner_h >= 6:
                ink_ratio = _foreground_ratio(
                    text_mask,
                    x + pad,
                    y + pad,
                    x + w - pad,
                    y + h - pad,
                )
                # Threshold choice:
                # - Empty input boxes should be near 0.00–0.05.
                # - Shaded header pills and word-blobs tend to be much higher (> 0.22).
                if ink_ratio >= 0.22:
                    continue

                # Some decorative header pills are unfilled (low ink ratio) but contain large text.
                # Those should NOT become box candidates because they are not input areas.
                #
                # We detect this by running a connected-components pass on the inner ROI. Real
                # empty input boxes contain very few (if any) components above a small size
                # threshold, while header text yields multiple sizable components.
                roi = text_mask[
                    int(max(0, y + pad)) : int(min(text_mask.shape[0], y + h - pad)),
                    int(max(0, x + pad)) : int(min(text_mask.shape[1], x + w - pad)),
                ]
                if roi.size:
                    bin_roi = (roi > 0).astype(np.uint8)
                    try:
                        num, _, stats, _ = cv2.connectedComponentsWithStats(bin_roi, connectivity=8)
                    except cv2.error:
                        num = 0
                        stats = None
                    if num and stats is not None and int(num) > 1:
                        areas = stats[1:, cv2.CC_STAT_AREA]
                        widths = stats[1:, cv2.CC_STAT_WIDTH]
                        heights = stats[1:, cv2.CC_STAT_HEIGHT]
                        looks_like_text = (areas >= 120) & (widths >= 12) & (heights >= 12)
                        if int(np.count_nonzero(looks_like_text)) >= 3:
                            # Record (but do not emit) decorative boxes so downstream code can
                            # filter underline candidates that are actually part of these borders.
                            #
                            # This directly targets rounded header "pills" on
                            # `medical-history-intake-form.pdf` page 13, where the bottom border of
                            # the pill is often detected as a short underline.
                            decorative_box_candidates.append(
                                {
                                    "bbox": bbox_pts,
                                    "bboxPx": [int(x), int(y), int(x + w), int(y + h)],
                                    "type": "decorative_box",
                                    "detector": "decorative_text_box",
                                }
                            )
                            continue
            box_candidates.append(
                {
                    "bbox": bbox_pts,
                    "bboxPx": [int(x), int(y), int(x + w), int(y + h)],
                    "type": "box",
                    "detector": "contour_box",
                }
            )

    return {
        "boxCandidates": box_candidates,
        "checkboxCandidates": checkbox_candidates,
        "decorativeBoxCandidates": decorative_box_candidates,
    }


def _detect_boxes_from_edges(
    gray: np.ndarray,
    text_mask: np.ndarray,
    vertical_mask: np.ndarray | None,
    horizontal_mask: np.ndarray | None,
    image_width_px: int,
    image_height_px: int,
    page_box: PageBox,
) -> List[Dict]:
    """
    Fallback: detect large rectangular input boxes using edge contours.
    """
    if gray is None or gray.size == 0:
        return []

    gray_eq = _enhance_contrast(gray)
    blurred = cv2.GaussianBlur(gray_eq, (3, 3), 0)
    median = float(np.median(blurred))
    lower = int(max(0, 0.66 * median))
    upper = int(min(255, 1.33 * median))
    edges = cv2.Canny(blurred, lower, upper)

    close_k = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, close_k, iterations=1)
    edges = cv2.dilate(edges, cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)), iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates: List[Dict] = []
    page_width_pt = float(page_box.page_width)
    page_height_pt = float(page_box.page_height)

    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w <= 0 or h <= 0:
            continue
        bbox_pts = _to_points_bbox((x, y, w, h), image_width_px, image_height_px, page_box)
        width_pt = bbox_pts[2] - bbox_pts[0]
        height_pt = bbox_pts[3] - bbox_pts[1]
        if width_pt < 60 or height_pt < 18:
            continue
        if width_pt > page_width_pt * 0.97 and height_pt > page_height_pt * 0.85:
            continue
        if height_pt > 260:
            continue

        aspect_ratio = width_pt / max(height_pt, 0.01)
        approx = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
        if not (4 <= len(approx) <= 12):
            continue
        if aspect_ratio < 0.6 or aspect_ratio > 20.0:
            continue

        if vertical_mask is not None and width_pt >= 140 and height_pt >= 40:
            if horizontal_mask is not None and _looks_like_table_grid_region(
                vertical_mask, horizontal_mask, int(x), int(y), int(w), int(h)
            ):
                continue

        pad = max(2, min(int(min(w, h) * 0.10), 12))
        inner_w = int(w - 2 * pad)
        inner_h = int(h - 2 * pad)
        if inner_w >= 6 and inner_h >= 6:
            ink_ratio = _foreground_ratio(
                text_mask,
                x + pad,
                y + pad,
                x + w - pad,
                y + h - pad,
            )
            if ink_ratio >= 0.24:
                continue

        candidates.append(
            {
                "bbox": bbox_pts,
                "bboxPx": [int(x), int(y), int(x + w), int(y + h)],
                "type": "box",
                "detector": "edge_box",
            }
        )

    return candidates


def detect_geometry_for_page(page: Dict, *, use_ml: bool) -> Dict:
    """
    Detect candidate geometry for a single rendered page.

    Algorithm outline:
    1) Binarize the image (Otsu + morphology) to isolate lines/boxes.
    2) Detect horizontal rules (long + short) for underline candidates.
    3) Detect boxes/checkboxes via contour analysis and heuristic filters.
    4) Dedupe and filter overlapping artifacts (decorative headers, checkbox borders).
    5) Optionally merge ML detections with OpenCV outputs.

    Runtime: dominated by image-size-dependent OpenCV operations (roughly O(pixels)).
    """
    image = page["image"]
    image_width_px = page.get("image_width_px") or image.shape[1]
    image_height_px = page.get("image_height_px") or image.shape[0]
    page_box = PageBox(
        page_width=float(page["width_points"]),
        page_height=float(page["height_points"]),
        rotation=int(page.get("rotation", 0)),
    )
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    text_mask_for_underline = cv2.morphologyEx(
        binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)), iterations=1
    )
    try:
        num, lab, stats, _ = cv2.connectedComponentsWithStats(text_mask_for_underline, connectivity=8)
        if num > 1:
            keep = np.zeros(num, dtype=bool)
            keep[0] = False
            keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= 30
            text_mask_for_underline = (keep[lab].astype(np.uint8)) * 255
    except cv2.error:
        pass

    binary_lines = _binarize_for_line_detection(gray, image_width_px)
    binary_checkboxes = _binarize_for_checkbox_detection(gray, image_width_px)
    vertical_mask = _build_vertical_mask(binary_lines, image_height_px)
    horizontal_mask = _build_horizontal_mask(binary_lines, image_width_px)

    lines = _detect_horizontal_lines(
        binary_lines,
        text_mask_for_underline,
        image_width_px,
        image_height_px,
        page_box,
        vertical_mask=vertical_mask,
        gray=gray,
    )
    lines.extend(
        _detect_horizontal_lines_morph(
            binary_lines,
            text_mask_for_underline,
            image_width_px,
            image_height_px,
            page_box,
            kernel_width_px=max(18, image_width_px // 170),
            min_length_pt=10.0,
            max_length_pt=180.0,
            max_thickness_pt=8.0,
            detector="morph_short",
            vertical_mask=vertical_mask,
            gray=gray,
        )
    )
    if len(lines) < 3:
        lines.extend(
            _detect_horizontal_lines_hough(
                _enhance_contrast(gray),
                text_mask_for_underline,
                image_width_px,
                image_height_px,
                page_box,
                vertical_mask=vertical_mask,
            )
        )
    lines = _dedupe_line_candidates(lines)
    lines = _dedupe_contained_lines(lines)
    binary_boxes = cv2.bitwise_or(binary_checkboxes, binary_lines)
    closed = cv2.morphologyEx(
        binary_boxes, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    )
    boxes = _detect_boxes(
        closed,
        binary,
        vertical_mask,
        horizontal_mask,
        image_width_px,
        image_height_px,
        page_box,
    )
    if not boxes.get("boxCandidates"):
        edge_boxes = _detect_boxes_from_edges(
            gray,
            binary,
            vertical_mask,
            horizontal_mask,
            image_width_px,
            image_height_px,
            page_box,
        )
        if edge_boxes:
            boxes["boxCandidates"].extend(edge_boxes)
            logger.debug(
                "Edge-box fallback added %s box candidates on page %s",
                len(edge_boxes),
                page.get("page_index"),
            )

    if (boxes.get("decorativeBoxCandidates") or []) and lines:
        deco_px: List[tuple[int, int, int, int]] = []
        for bx in boxes.get("decorativeBoxCandidates") or []:
            bpx = bx.get("bboxPx") or []
            if len(bpx) != 4:
                continue
            deco_px.append(tuple(int(v) for v in bpx))

        kept_lines: List[Dict] = []
        dropped = 0
        for ln in lines:
            lpx = ln.get("bboxPx") or []
            if len(lpx) != 4:
                kept_lines.append(ln)
                continue
            ax1, ay1, ax2, ay2 = [int(v) for v in lpx]
            line_w = max(1, ax2 - ax1)
            line_h = max(1, ay2 - ay1)
            line_area = float(line_w * line_h)
            inside_decorative = False
            for deco in deco_px:
                bx1, by1, bx2, by2 = deco
                if ay2 <= by1 or ay1 >= by2 or ax2 <= bx1 or ax1 >= bx2:
                    continue
                inter = float(_inter_area_px((ax1, ay1, ax2, ay2), deco))
                if inter / line_area >= 0.65:
                    inside_decorative = True
                    break
            if inside_decorative:
                dropped += 1
                continue
            kept_lines.append(ln)
        if dropped:
            logger.debug(
                "Filtered %s line candidates overlapping decorative header boxes (kept=%s total=%s)",
                dropped,
                len(kept_lines),
                len(lines),
            )
        lines = kept_lines

    anchor_rows: List[float] = []
    contour_ymids: List[float] = []
    for cb in boxes.get("checkboxCandidates") or []:
        if cb.get("detector") != "contour":
            continue
        bpx = cb.get("bboxPx") or []
        if len(bpx) != 4:
            continue
        contour_ymids.append((float(bpx[1]) + float(bpx[3])) / 2.0)
    contour_ymids.sort()
    use_anchor_rows = len(contour_ymids) >= 3
    if use_anchor_rows:
        for y_mid in contour_ymids:
            if not anchor_rows or abs(y_mid - anchor_rows[-1]) > 16.0:
                anchor_rows.append(float(y_mid))
            else:
                anchor_rows[-1] = (anchor_rows[-1] + float(y_mid)) / 2.0

    recovered_checkboxes = _detect_checkboxes_from_text_mask(
        binary_checkboxes,
        image_width_px,
        image_height_px,
        page_box,
        anchor_rows_y_px=anchor_rows if anchor_rows else None,
        anchor_y_tol_px=14,
        text_height_mask=text_mask_for_underline,
    )
    if recovered_checkboxes:
        boxes["checkboxCandidates"].extend(recovered_checkboxes)
        boxes["checkboxCandidates"] = _dedupe_checkbox_candidates(
            boxes["checkboxCandidates"],
            iou_threshold=0.70,
        )

    table_cells = _detect_table_checkbox_cells(
        binary_lines,
        binary,
        image_width_px,
        image_height_px,
        page_box,
    )
    if table_cells:
        boxes["checkboxCandidates"].extend(table_cells)
        boxes["checkboxCandidates"] = _dedupe_checkbox_candidates(
            boxes["checkboxCandidates"],
            iou_threshold=0.68,
        )

    if len(table_cells) < 120:
        table_text_cells = _detect_table_text_cells(
            binary_lines,
            binary,
            image_width_px,
            image_height_px,
            page_box,
        )
        if table_text_cells:
            checkbox_text_cells = [
                cell for cell in table_text_cells if cell.get("type") == "checkbox"
            ]
            if checkbox_text_cells:
                boxes["checkboxCandidates"].extend(checkbox_text_cells)
                boxes["checkboxCandidates"] = _dedupe_checkbox_candidates(
                    boxes["checkboxCandidates"],
                    iou_threshold=0.68,
                )
            box_text_cells = [
                cell for cell in table_text_cells if cell.get("type") != "checkbox"
            ]
            if box_text_cells:
                boxes["boxCandidates"].extend(box_text_cells)
                boxes["boxCandidates"] = _dedupe_by_iou(boxes["boxCandidates"], threshold=0.88)

    if boxes.get("checkboxCandidates") and lines:
        cb_px = []
        for cb in boxes.get("checkboxCandidates") or []:
            bpx = cb.get("bboxPx") or []
            if len(bpx) != 4:
                continue
            cb_px.append(tuple(int(v) for v in bpx))

        kept_lines: List[Dict] = []
        dropped = 0
        for ln in lines:
            lpx = ln.get("bboxPx") or []
            if len(lpx) != 4:
                kept_lines.append(ln)
                continue
            ax1, ay1, ax2, ay2 = [int(v) for v in lpx]
            line_w = max(1, ax2 - ax1)
            line_h = max(1, ay2 - ay1)
            line_area = float(line_w * line_h)
            overlaps_checkbox = False
            for cb in cb_px:
                bx1, by1, bx2, by2 = cb
                if ay2 <= by1 or ay1 >= by2 or ax2 <= bx1 or ax1 >= bx2:
                    continue
                inter = float(_inter_area_px((ax1, ay1, ax2, ay2), cb))
                if inter / line_area >= 0.75:
                    overlaps_checkbox = True
                    break
            if overlaps_checkbox:
                dropped += 1
                continue
            kept_lines.append(ln)
        if dropped:
            logger.debug(
                "Filtered %s line candidates overlapping checkboxes (kept=%s total=%s)",
                dropped,
                len(kept_lines),
                len(lines),
            )
        lines = kept_lines

    line_candidates = lines
    box_candidates = boxes["boxCandidates"]
    checkbox_candidates = boxes["checkboxCandidates"]

    ml_result = detect_ml_geometry(page) if use_ml else None
    if use_ml and ml_result is None:
        logger.warning("ML detector unavailable; falling back to OpenCV-only geometry.")
    if ml_result:
        line_candidates = _merge_ml_candidates(
            line_candidates,
            ml_result.get("lineCandidates", []),
            iou_threshold=0.70,
        )
        box_candidates = _merge_ml_candidates(
            box_candidates,
            ml_result.get("boxCandidates", []),
            iou_threshold=0.72,
        )
        checkbox_candidates = _merge_ml_candidates(
            checkbox_candidates,
            ml_result.get("checkboxCandidates", []),
            iou_threshold=0.60,
            preserve_detectors=("table_cells",),
        )
        checkbox_candidates = _dedupe_checkbox_candidates(
            checkbox_candidates,
            iou_threshold=0.66,
        )
        logger.debug(
            "Merged ML candidates on page %s -> lines:%s boxes:%s checkboxes:%s",
            page["page_index"],
            len(line_candidates),
            len(box_candidates),
            len(checkbox_candidates),
        )

    result = {
        "page_index": page["page_index"],
        "lineCandidates": line_candidates,
        "boxCandidates": box_candidates,
        "checkboxCandidates": checkbox_candidates,
    }
    logger.debug(
        "Page %s geometry: %s lines, %s boxes, %s checkboxes",
        page["page_index"],
        len(lines),
        len(boxes["boxCandidates"]),
        len(boxes["checkboxCandidates"]),
    )
    return result


def detect_geometry(
    pages: List[Dict],
    *,
    max_workers: Optional[int] = None,
) -> List[Dict]:
    """
    Run OpenCV-driven geometry detection on rendered pages.

    Expects each page dict from render_pdf_to_images, returns aligned geometry
    candidates for every page.
    """
    use_ml = os.getenv("SANDBOX_USE_ML_DETECTOR", "0").lower() in ("1", "true", "yes")
    logger.debug(
        "Underline filters: long_above=%.2f long_short_above=%.2f long_below=%.2f short_near_above=%.2f short_above=%.2f short_below=%.2f short_wide_above=%.2f",
        UNDERLINE_ABOVE_RATIO,
        UNDERLINE_SHORT_ABOVE_RATIO,
        UNDERLINE_BELOW_RATIO,
        UNDERLINE_SHORT_NEAR_ABOVE_RATIO,
        UNDERLINE_SHORT_ABOVE_RATIO,
        UNDERLINE_SHORT_BELOW_RATIO,
        UNDERLINE_SHORT_WIDE_ABOVE_RATIO,
    )
    max_workers = max_workers or resolve_workers("geometry", default=min(4, os.cpu_count() or 4))
    # Each page can be processed independently, so geometry detection is parallel-friendly.
    return run_threaded_map(
        pages,
        lambda page: detect_geometry_for_page(page, use_ml=use_ml),
        max_workers=max_workers,
        label="geometry",
    )
