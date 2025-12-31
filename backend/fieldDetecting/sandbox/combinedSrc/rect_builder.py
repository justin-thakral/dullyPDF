from typing import Dict, List, Optional, Tuple


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def make_text_field_rect_from_underline(
    underline_bbox: List[float],
    calibration: Dict,
    page_width: float,
    page_height: float,
    label_bboxes: Optional[List[List[float]]] = None,
) -> List[float]:
    """
    Build a text field rectangle anchored to an underline stroke.

    underline_bbox: [x1, y1, x2, y2] originTop points; y2 treated as baseline.
    calibration: per-page dict with medianLabelHeight key.
    """
    if not underline_bbox or len(underline_bbox) != 4:
        raise ValueError("Invalid underline bbox")

    median_label_height = calibration.get("medianLabelHeight", 12.0)
    target_height = clamp(round(median_label_height * 1.35), 18, 28)

    # Keep the typing area just above the underline; thinner rules need less offset.
    underline_thickness = max(0.5, float(underline_bbox[3]) - float(underline_bbox[1]))
    below = clamp(underline_thickness * 0.6, 1.0, 2.5)
    above = target_height - below

    x1, y1, x2, y2 = underline_bbox
    rect_y2 = y2 + below
    rect_y1 = rect_y2 - target_height
    rect_x1 = x1 - 1.0
    rect_x2 = x2 + 1.0

    rect = [rect_x1, rect_y1, rect_x2, rect_y2]

    # Avoid pushing underline-based fields below the underline.
    # Overlap between label text and typing area is common (same baseline rows); we prioritize
    # keeping the field anchored above the underline instead of shifting the whole rect downward.
    if label_bboxes:
        rect = _nudge_horizontally_off_labels(rect, underline_bbox, label_bboxes)

    # Clamp within page bounds.
    rect[0] = clamp(rect[0], 0, page_width)
    rect[2] = clamp(rect[2], 0, page_width)
    rect[1] = clamp(rect[1], 0, page_height)
    rect[3] = clamp(rect[3], 0, page_height)
    return rect


def make_signature_field_rect_from_underline(
    underline_bbox: List[float],
    calibration: Dict,
    page_width: float,
    page_height: float,
    label_bboxes: Optional[List[List[float]]] = None,
) -> List[float]:
    """
    Build a signature field rectangle anchored to an underline stroke.

    Signatures usually need more vertical space than standard text inputs, so this uses
    the same underline anchoring as text but increases the height.
    """
    median_label_height = calibration.get("medianLabelHeight", 12.0)
    base_height = clamp(round(median_label_height * 1.35), 18, 28)
    target_height = clamp(base_height + 8, 26, 40)

    underline_thickness = max(0.5, float(underline_bbox[3]) - float(underline_bbox[1]))
    below = clamp(underline_thickness * 0.6, 1.0, 2.5)
    x1, y1, x2, y2 = underline_bbox
    rect_y2 = y2 + below
    rect_y1 = rect_y2 - target_height
    rect_x1 = x1 - 1.0
    rect_x2 = x2 + 1.0
    rect = [rect_x1, rect_y1, rect_x2, rect_y2]

    if label_bboxes:
        rect = _nudge_horizontally_off_labels(rect, underline_bbox, label_bboxes)

    rect[0] = clamp(rect[0], 0, page_width)
    rect[2] = clamp(rect[2], 0, page_width)
    rect[1] = clamp(rect[1], 0, page_height)
    rect[3] = clamp(rect[3], 0, page_height)
    return rect


def make_checkbox_rect(
    square_bbox: List[float],
    page_width: float,
    page_height: float,
    *,
    label_bbox: Optional[List[float]] = None,
    snap_y: Optional[float] = None,
    median_label_height: Optional[float] = None,
    target_size: Optional[float] = None,
    force_size: bool = False,
) -> List[float]:
    """Expand a checkbox candidate slightly outward to improve clickability."""
    if not square_bbox or len(square_bbox) != 4:
        raise ValueError("Invalid checkbox bbox")
    x1, y1, x2, y2 = square_bbox
    width = float(x2) - float(x1)
    height = float(y2) - float(y1)
    if width > 0.0 and height > 0.0:
        aspect = width / max(height, 1e-6)
        square_tol = 0.12
        should_square = force_size or aspect < (1.0 - square_tol) or aspect > (1.0 + square_tol)
        if should_square:
            # Checkbox candidates should be square. Center to avoid top-left bias when the
            # detector returns a slightly skewed bounding box.
            size = min(width, height)
            if target_size and target_size > 0.0:
                if force_size:
                    size = float(target_size)
                else:
                    min_size = float(target_size) * 0.75
                    max_size = float(target_size) * 1.35
                    size = clamp(size, min_size, max_size)
            cx = (float(x1) + float(x2)) / 2.0
            cy = (float(y1) + float(y2)) / 2.0
            target_y = None
            target_x = None
            if label_bbox and len(label_bbox) == 4:
                label_height = float(label_bbox[3]) - float(label_bbox[1])
                max_label_height = size * 2.2
                if median_label_height:
                    max_label_height = max(max_label_height, float(median_label_height) * 2.2)
                if label_height > 0.0 and label_height <= max_label_height:
                    label_mid_y = (float(label_bbox[1]) + float(label_bbox[3])) / 2.0
                    if abs(label_mid_y - cy) <= max(4.0, size * 0.7):
                        target_y = label_mid_y
                        label_mid_x = (float(label_bbox[0]) + float(label_bbox[2])) / 2.0
                        if label_mid_x >= cx + (size * 0.55):
                            target_x = float(x1) + (size / 2.0)
                        elif label_mid_x <= cx - (size * 0.55):
                            target_x = float(x2) - (size / 2.0)
            if target_y is None and snap_y is not None:
                if abs(float(snap_y) - cy) <= max(4.0, size * 0.75):
                    target_y = float(snap_y)
            if target_y is not None and abs(float(target_y) - cy) < 1.0:
                target_y = None
            if target_x is not None and abs(float(target_x) - cx) < 1.0:
                target_x = None
            if target_y is not None:
                cy = target_y
            if target_x is not None:
                cx = target_x
            x1 = cx - (size / 2.0)
            x2 = cx + (size / 2.0)
            y1 = cy - (size / 2.0)
            y2 = cy + (size / 2.0)
    rect = [x1 - 1.0, y1 - 1.0, x2 + 1.0, y2 + 1.0]
    rect[0] = clamp(rect[0], 0, page_width)
    rect[2] = clamp(rect[2], 0, page_width)
    rect[1] = clamp(rect[1], 0, page_height)
    rect[3] = clamp(rect[3], 0, page_height)
    return rect


def make_box_field_rect(
    box_bbox: List[float], page_width: float, page_height: float
) -> List[float]:
    """Pad a detected box slightly outward for comfortable interaction."""
    if not box_bbox or len(box_bbox) != 4:
        raise ValueError("Invalid box bbox")
    x1, y1, x2, y2 = box_bbox
    rect = [x1 - 2.0, y1 - 2.0, x2 + 2.0, y2 + 2.0]
    rect[0] = clamp(rect[0], 0, page_width)
    rect[2] = clamp(rect[2], 0, page_width)
    rect[1] = clamp(rect[1], 0, page_height)
    rect[3] = clamp(rect[3], 0, page_height)
    return rect


def _nudge_horizontally_off_labels(
    rect: List[float],
    underline_bbox: List[float],
    labels: List[List[float]],
) -> List[float]:
    """
    Try to avoid capturing clicks on top of nearby labels by trimming the left edge.

    Important: we do NOT move the rect down because underline-based fields must stay above
    the underline baseline.
    """
    x1, y1, x2, y2 = rect
    underline_x1 = underline_bbox[0]
    for lb in labels:
        if len(lb) != 4:
            continue
        if not _rects_intersect(rect, lb):
            continue
        # If a label sits immediately to the left of the underline, reduce left padding so
        # the field starts after the label.
        label_x2 = lb[2]
        label_y2 = lb[3]
        # Only consider labels that end near the underline start (adjacent labels).
        if label_x2 <= underline_x1 + 6 and label_y2 <= underline_bbox[3] + 6:
            x1 = max(x1, label_x2 + 2.0)
    if x1 >= x2 - 4:
        # If we trimmed too far, fall back to original x1 to avoid negative width.
        return rect
    return [x1, y1, x2, y2]


def _rects_intersect(a: List[float], b: List[float]) -> bool:
    return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])
