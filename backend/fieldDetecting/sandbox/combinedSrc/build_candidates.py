import os
import re
from typing import Dict, List, Optional

from .checkbox_glyphs import is_checkbox_glyph
from .concurrency import resolve_workers, run_threaded_map
from .config import get_logger

logger = get_logger(__name__)

_TOKEN_Y = re.compile(r"(?<![a-z])y(?![a-z])")
_TOKEN_N = re.compile(r"(?<![a-z])n(?![a-z])")

_LINE_GLYPHS = {
    "_",
    "-",
    "\u2010",  # hyphen
    "\u2011",  # non-breaking hyphen
    "\u2012",  # figure dash
    "\u2013",  # en dash
    "\u2014",  # em dash
    "\u2015",  # horizontal bar
    "\u2212",  # minus sign
    "\ufe63",  # small hyphen-minus
    "\uff0d",  # fullwidth hyphen-minus
    "\uff3f",  # fullwidth low line
}


def _is_line_glyph(token: str) -> bool:
    return token in _LINE_GLYPHS


def _inter_area(a: List[float], b: List[float]) -> float:
    ax1, ay1, ax2, ay2 = [float(v) for v in a]
    bx1, by1, bx2, by2 = [float(v) for v in b]
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    return float(ix2 - ix1) * float(iy2 - iy1)


def _overlap_ratio(a: List[float], b: List[float]) -> float:
    inter = _inter_area(a, b)
    if inter <= 0.0:
        return 0.0
    area_a = max(0.0, float(a[2]) - float(a[0])) * max(0.0, float(a[3]) - float(a[1]))
    area_b = max(0.0, float(b[2]) - float(b[0])) * max(0.0, float(b[3]) - float(b[1]))
    min_area = min(area_a, area_b)
    if min_area <= 0.0:
        return 0.0
    return inter / min_area


def _checkbox_dedupe_key(candidate: Dict) -> tuple[float, float]:
    """
    Rank checkbox candidates for dedupe.

    Higher rank wins when two candidates overlap heavily.
    """
    bbox = candidate.get("bbox") or [0, 0, 0, 0]
    if len(bbox) == 4:
        area = max(0.0, float(bbox[2]) - float(bbox[0])) * max(
            0.0, float(bbox[3]) - float(bbox[1])
        )
    else:
        area = 0.0
    detector = str(candidate.get("detector") or "")
    priority = {
        "glyph": 3.0,
        "vector_rect": 2.5,
        "table_cells": 2.0,
        "contour": 1.5,
        "text_mask_raw": 1.0,
        "text_mask_close": 1.0,
    }.get(detector, 0.5)
    return (priority, area)


def _dedupe_overlapping_checkboxes(
    checkbox_candidates: List[Dict],
    *,
    overlap_threshold: float,
    page_index: int,
) -> List[Dict]:
    """
    Drop near-duplicate checkbox candidates that overlap heavily.
    """
    if len(checkbox_candidates) <= 1:
        return checkbox_candidates
    sorted_candidates = sorted(
        checkbox_candidates,
        key=_checkbox_dedupe_key,
        reverse=True,
    )
    kept: List[Dict] = []
    dropped = 0
    for cand in sorted_candidates:
        bbox = cand.get("bbox") or []
        if len(bbox) != 4:
            continue
        if any(_overlap_ratio(bbox, prev.get("bbox") or []) >= overlap_threshold for prev in kept):
            dropped += 1
            continue
        kept.append(cand)
    if dropped:
        logger.debug(
            "Deduped %s overlapping checkboxes on page %s (threshold=%.2f)",
            dropped,
            page_index,
            overlap_threshold,
        )
    return sorted(kept, key=_bbox_sort_key)


def _color_is_white(color: object, *, threshold: float = 0.97) -> bool:
    if color is None:
        return False
    if isinstance(color, (int, float)):
        return float(color) >= threshold
    if isinstance(color, (list, tuple)):
        if not color:
            return False
        return all(float(c) >= threshold for c in color)
    return False


def _rect_is_invisible_fill(rect_entry: Dict[str, object]) -> bool:
    fill = rect_entry.get("fill")
    stroke = rect_entry.get("stroke")
    if not fill or stroke:
        return False
    linewidth = rect_entry.get("linewidth")
    try:
        lw = float(linewidth or 0.0)
    except (TypeError, ValueError):
        lw = 0.0
    if lw > 0.05:
        return False
    return _color_is_white(rect_entry.get("non_stroking_color"))


def filter_checkbox_candidates_by_char_overlap(
    candidates: List[Dict],
    char_bboxes_by_page: Dict[int, List[Dict[str, object]]],
    *,
    overlap_threshold: float,
) -> int:
    """
    Drop checkbox candidates whose bbox overlaps text glyphs on native PDFs.

    This is a precision guardrail against hollow glyphs ("O", "0", "D") that look boxy in
    the binary mask. We only apply it when a reliable text layer is available.
    """
    if not candidates or not char_bboxes_by_page:
        return 0

    dropped_total = 0
    kept_due_to_glyph = 0
    for page in candidates:
        page_idx = int(page.get("page") or 0)
        char_bboxes = char_bboxes_by_page.get(page_idx) or []
        if not char_bboxes:
            continue
        checkbox_candidates = list(page.get("checkboxCandidates") or [])
        if not checkbox_candidates:
            continue
        kept: List[Dict] = []
        dropped_page = 0
        for cb in checkbox_candidates:
            if cb.get("detector") == "glyph":
                kept.append(cb)
                continue
            if cb.get("detector") == "vector_rect":
                kept.append(cb)
                continue
            bbox = cb.get("bbox") or []
            if len(bbox) != 4:
                kept.append(cb)
                continue
            width = float(bbox[2]) - float(bbox[0])
            height = float(bbox[3]) - float(bbox[1])
            area = float(width * height) if width > 0.0 and height > 0.0 else 0.0
            if area <= 0.0:
                kept.append(cb)
                continue
            overlaps_text = False
            overlaps_checkbox_glyph = False
            for char_entry in char_bboxes:
                if not isinstance(char_entry, dict):
                    continue
                char_bbox = char_entry.get("bbox") if isinstance(char_entry.get("bbox"), list) else None
                if not char_bbox or len(char_bbox) != 4:
                    continue
                inter_area = _inter_area(bbox, char_bbox)
                if inter_area <= 0.0:
                    continue
                if (inter_area / area) >= float(overlap_threshold):
                    raw_text = str(char_entry.get("text") or "")
                    if not raw_text or raw_text.isspace() or not raw_text.isprintable():
                        continue
                    char_text = raw_text.strip()
                    if not char_text:
                        continue
                    char_font = char_entry.get("fontname")
                    if is_checkbox_glyph(char_text, char_font):
                        overlaps_checkbox_glyph = True
                        continue
                    overlaps_text = True
                    break
            if overlaps_text:
                dropped_total += 1
                dropped_page += 1
                continue
            if overlaps_checkbox_glyph:
                kept_due_to_glyph += 1
            kept.append(cb)
        if dropped_page:
            page["checkboxCandidates"] = kept
            logger.debug(
                "Native checkbox text-overlap filter dropped %s candidates on page %s",
                dropped_page,
                page_idx,
            )
    if dropped_total:
        logger.debug(
            "Native checkbox text-overlap filter dropped %s candidates total (threshold=%.2f)",
            dropped_total,
            float(overlap_threshold),
        )
    if kept_due_to_glyph:
        logger.debug(
            "Native checkbox text-overlap filter kept %s candidates due to checkbox glyphs",
            kept_due_to_glyph,
        )
    return dropped_total


def filter_line_candidates_by_char_overlap(
    candidates: List[Dict],
    char_bboxes_by_page: Dict[int, List[Dict[str, object]]],
    *,
    overlap_threshold: float,
) -> int:
    """
    Drop line candidates that overlap native text glyphs.

    Hough/underline detection can latch onto text baselines in native PDFs. When the
    line bbox is mostly filled by glyph ink, it is a text row, not a fillable underline.
    """
    if not candidates or not char_bboxes_by_page:
        return 0

    dropped_total = 0
    for page in candidates:
        page_idx = int(page.get("page") or 0)
        char_bboxes = char_bboxes_by_page.get(page_idx) or []
        if not char_bboxes:
            continue
        line_candidates = list(page.get("lineCandidates") or [])
        if not line_candidates:
            continue
        kept: List[Dict] = []
        dropped_page = 0
        x_overlap_threshold = float(os.getenv("SANDBOX_NATIVE_LINE_CHAR_XOVERLAP", "0.85"))
        for ln in line_candidates:
            bbox = ln.get("bbox") or []
            if len(bbox) != 4:
                kept.append(ln)
                continue
            width = float(bbox[2]) - float(bbox[0])
            height = float(bbox[3]) - float(bbox[1])
            area = float(width * height) if width > 0.0 and height > 0.0 else 0.0
            if area <= 0.0:
                kept.append(ln)
                continue
            overlap_area = 0.0
            overlap_line_area = 0.0
            overlap_x_segments: List[List[float]] = []
            for char_entry in char_bboxes:
                if not isinstance(char_entry, dict):
                    continue
                char_bbox = char_entry.get("bbox") if isinstance(char_entry.get("bbox"), list) else None
                if not char_bbox or len(char_bbox) != 4:
                    continue
                inter_area = _inter_area(bbox, char_bbox)
                if inter_area <= 0.0:
                    continue
                overlap_area += inter_area
                char_text = str(char_entry.get("text") or "")
                if _is_line_glyph(char_text.strip()):
                    overlap_line_area += inter_area
                overlap_x0 = max(float(bbox[0]), float(char_bbox[0]))
                overlap_x1 = min(float(bbox[2]), float(char_bbox[2]))
                if overlap_x1 > overlap_x0:
                    overlap_x_segments.append([overlap_x0, overlap_x1])
                if overlap_area >= area:
                    overlap_area = area
                    break
            if overlap_area > 0.0:
                line_ratio = overlap_line_area / overlap_area
            else:
                line_ratio = 0.0
            overlap_x_ratio = 0.0
            if overlap_x_segments and width > 0.0:
                overlap_x_segments.sort(key=lambda seg: seg[0])
                merged = [overlap_x_segments[0]]
                for seg in overlap_x_segments[1:]:
                    last = merged[-1]
                    if seg[0] <= last[1]:
                        last[1] = max(last[1], seg[1])
                    else:
                        merged.append(seg)
                overlap_x_ratio = sum(seg[1] - seg[0] for seg in merged) / width
            if (
                (overlap_area / area) >= float(overlap_threshold)
                and line_ratio < 0.7
                and overlap_x_ratio >= x_overlap_threshold
            ):
                dropped_total += 1
                dropped_page += 1
                continue
            kept.append(ln)
        if dropped_page:
            page["lineCandidates"] = kept
            logger.debug(
                "Native line text-overlap filter dropped %s candidates on page %s",
                dropped_page,
                page_idx,
            )
    if dropped_total:
        logger.debug(
            "Native line text-overlap filter dropped %s candidates total (threshold=%.2f)",
            dropped_total,
            float(overlap_threshold),
        )
    return dropped_total


def inject_checkbox_glyph_candidates(
    candidates: List[Dict],
    char_bboxes_by_page: Dict[int, List[Dict[str, object]]],
    *,
    overlap_threshold: float,
) -> int:
    """
    Add checkbox candidates for checkbox glyphs in the native text layer.

    This restores recall when checkboxes are rendered as text glyphs (e.g., "☐") that do not
    always survive rasterization/thresholding in the OpenCV pass.
    """
    if not candidates or not char_bboxes_by_page:
        return 0

    added_total = 0
    for page in candidates:
        page_idx = int(page.get("page") or 0)
        char_bboxes = char_bboxes_by_page.get(page_idx) or []
        if not char_bboxes:
            continue

        glyph_bboxes: List[List[float]] = []
        for char_entry in char_bboxes:
            if not isinstance(char_entry, dict):
                continue
            char_text = str(char_entry.get("text") or "").strip()
            char_font = char_entry.get("fontname")
            if not is_checkbox_glyph(char_text, char_font):
                continue
            bbox = char_entry.get("bbox") if isinstance(char_entry.get("bbox"), list) else None
            if not bbox or len(bbox) != 4:
                continue
            bbox_vals = [float(v) for v in bbox]
            width = float(bbox_vals[2]) - float(bbox_vals[0])
            height = float(bbox_vals[3]) - float(bbox_vals[1])
            if width <= 0.0 or height <= 0.0:
                continue
            aspect = width / max(height, 0.01)
            if width < 4.0 or height < 4.0 or width > 44.0 or height > 44.0:
                continue
            if not (0.65 <= aspect <= 1.40):
                continue
            glyph_bboxes.append(bbox_vals)

        if not glyph_bboxes:
            continue

        existing = list(page.get("checkboxCandidates") or [])
        existing_bboxes = [
            cb.get("bbox")
            for cb in existing
            if isinstance(cb.get("bbox"), list) and len(cb.get("bbox")) == 4
        ]

        added_page = 0
        for bbox in glyph_bboxes:
            if any(_overlap_ratio(bbox, eb) >= float(overlap_threshold) for eb in existing_bboxes):
                continue
            existing.append(
                {
                    "bbox": bbox,
                    "type": "checkbox",
                    "detector": "glyph",
                }
            )
            existing_bboxes.append(bbox)
            added_page += 1

        if added_page:
            sorted_candidates = sorted(existing, key=_bbox_sort_key)
            for idx, cand in enumerate(sorted_candidates, start=1):
                cand["id"] = f"checkbox-{page_idx}-{idx}"
            page["checkboxCandidates"] = sorted_candidates
            added_total += added_page
            logger.debug(
                "Injected %s checkbox glyph candidates on page %s",
                added_page,
                page_idx,
            )

    if added_total:
        logger.debug(
            "Injected %s checkbox glyph candidates total (overlap_threshold=%.2f)",
            added_total,
            float(overlap_threshold),
        )
    return added_total


def inject_vector_checkbox_candidates(
    candidates: List[Dict],
    rect_bboxes_by_page: Dict[int, List[Dict[str, object]]],
    *,
    overlap_threshold: float,
) -> int:
    """
    Add checkbox candidates from vector rectangle objects on native PDFs.

    Some PDFs draw checkboxes as filled/stroked rectangles in the vector layer. These can
    be missed by rasterization, so we inject them directly from pdfplumber rects.
    """
    if not candidates or not rect_bboxes_by_page:
        return 0

    added_total = 0
    for page in candidates:
        page_idx = int(page.get("page") or 0)
        rect_entries = rect_bboxes_by_page.get(page_idx) or []
        if not rect_entries:
            continue

        vector_bboxes: List[List[float]] = []
        dropped_white = 0
        for rect_entry in rect_entries:
            if not isinstance(rect_entry, dict):
                continue
            if _rect_is_invisible_fill(rect_entry):
                dropped_white += 1
                continue
            bbox = rect_entry.get("bbox") if isinstance(rect_entry.get("bbox"), list) else None
            if not bbox or len(bbox) != 4:
                continue
            bbox_vals = [float(v) for v in bbox]
            width = float(bbox_vals[2]) - float(bbox_vals[0])
            height = float(bbox_vals[3]) - float(bbox_vals[1])
            if width <= 0.0 or height <= 0.0:
                continue
            aspect = width / max(height, 0.01)
            if width < 4.0 or height < 4.0 or width > 44.0 or height > 44.0:
                continue
            if not (0.65 <= aspect <= 1.40):
                continue
            vector_bboxes.append(bbox_vals)

        if dropped_white:
            logger.debug(
                "Skipped %s white-fill vector rects on page %s",
                dropped_white,
                page_idx,
            )
        if not vector_bboxes:
            continue

        existing = list(page.get("checkboxCandidates") or [])
        existing_bboxes = [
            cb.get("bbox")
            for cb in existing
            if isinstance(cb.get("bbox"), list) and len(cb.get("bbox")) == 4
        ]

        added_page = 0
        for bbox in vector_bboxes:
            if any(_overlap_ratio(bbox, eb) >= float(overlap_threshold) for eb in existing_bboxes):
                continue
            existing.append(
                {
                    "bbox": bbox,
                    "type": "checkbox",
                    "detector": "vector_rect",
                }
            )
            existing_bboxes.append(bbox)
            added_page += 1

        if added_page:
            sorted_candidates = sorted(existing, key=_bbox_sort_key)
            for idx, cand in enumerate(sorted_candidates, start=1):
                cand["id"] = f"checkbox-{page_idx}-{idx}"
            page["checkboxCandidates"] = sorted_candidates
            added_total += added_page
            logger.debug(
                "Injected %s vector-rect checkbox candidates on page %s",
                added_page,
                page_idx,
            )

    if added_total:
        logger.debug(
            "Injected %s vector-rect checkbox candidates total (overlap_threshold=%.2f)",
            added_total,
            float(overlap_threshold),
        )
    return added_total


def inject_line_glyph_candidates(
    candidates: List[Dict],
    char_bboxes_by_page: Dict[int, List[Dict[str, object]]],
    *,
    overlap_threshold: float,
    min_run_chars: int = 3,
    min_run_width_pt: float = 18.0,
) -> int:
    """
    Add line candidates from repeated line glyphs in the text layer (e.g. "_____").

    Some native PDFs render fillable underlines as sequences of underscore/hyphen glyphs.
    These do not appear as vector lines, so we stitch the glyph runs into line candidates.
    """
    if not candidates or not char_bboxes_by_page:
        return 0

    added_total = 0
    for page in candidates:
        page_idx = int(page.get("page") or 0)
        char_bboxes = char_bboxes_by_page.get(page_idx) or []
        if not char_bboxes:
            continue

        glyph_items = []
        heights = []
        for char_entry in char_bboxes:
            if not isinstance(char_entry, dict):
                continue
            raw_text = str(char_entry.get("text") or "").strip()
            if not raw_text or not _is_line_glyph(raw_text):
                continue
            bbox = char_entry.get("bbox") if isinstance(char_entry.get("bbox"), list) else None
            if not bbox or len(bbox) != 4:
                continue
            x0, y0, x1, y1 = [float(v) for v in bbox]
            width = x1 - x0
            height = y1 - y0
            if width <= 0.0 or height <= 0.0:
                continue
            glyph_items.append(
                {
                    "bbox": [x0, y0, x1, y1],
                    "x0": x0,
                    "x1": x1,
                    "y0": y0,
                    "y1": y1,
                    "y_mid": (y0 + y1) / 2.0,
                    "width": width,
                    "height": height,
                }
            )
            heights.append(height)

        if not glyph_items:
            continue

        glyph_items.sort(key=lambda item: (item["y_mid"], item["x0"]))
        median_h = _median(heights) or 2.0
        y_tol = max(1.5, median_h * 0.6)

        line_groups: List[List[Dict[str, float]]] = []
        for item in glyph_items:
            if not line_groups:
                line_groups.append([item])
                continue
            last_group = line_groups[-1]
            last_mid = sum(entry["y_mid"] for entry in last_group) / float(len(last_group))
            if abs(item["y_mid"] - last_mid) <= y_tol:
                last_group.append(item)
            else:
                line_groups.append([item])

        existing = list(page.get("lineCandidates") or [])
        existing_bboxes = [
            ln.get("bbox")
            for ln in existing
            if isinstance(ln.get("bbox"), list) and len(ln.get("bbox")) == 4
        ]

        added_page = 0
        for group in line_groups:
            if len(group) < min_run_chars:
                continue
            group.sort(key=lambda item: item["x0"])
            widths = [item["width"] for item in group]
            median_w = _median(widths) or 2.0
            gap_tol = max(2.0, median_w * 0.8)

            run: List[Dict[str, float]] = [group[0]]
            runs: List[List[Dict[str, float]]] = []
            for item in group[1:]:
                gap = item["x0"] - run[-1]["x1"]
                if gap <= gap_tol:
                    run.append(item)
                else:
                    runs.append(run)
                    run = [item]
            runs.append(run)

            for run in runs:
                if len(run) < min_run_chars:
                    continue
                x0 = min(item["x0"] for item in run)
                x1 = max(item["x1"] for item in run)
                y0 = min(item["y0"] for item in run)
                y1 = max(item["y1"] for item in run)
                width = x1 - x0
                height = y1 - y0
                if width < min_run_width_pt:
                    continue
                bbox = [x0, y0, x1, y1]
                if any(_overlap_ratio(bbox, eb) >= float(overlap_threshold) for eb in existing_bboxes):
                    continue
                existing.append(
                    {
                        "bbox": bbox,
                        "length": width,
                        "thickness": height,
                        "type": "line",
                        "detector": "text_line_glyph",
                    }
                )
                existing_bboxes.append(bbox)
                added_page += 1

        if added_page:
            sorted_candidates = sorted(existing, key=_bbox_sort_key)
            for idx, cand in enumerate(sorted_candidates, start=1):
                cand["id"] = f"line-{page_idx}-{idx}"
            page["lineCandidates"] = sorted_candidates
            added_total += added_page
            logger.debug(
                "Injected %s text-glyph line candidates on page %s",
                added_page,
                page_idx,
            )

    if added_total:
        logger.debug(
            "Injected %s text-glyph line candidates total (overlap_threshold=%.2f)",
            added_total,
            float(overlap_threshold),
        )
    return added_total


def inject_vector_line_candidates(
    candidates: List[Dict],
    rect_bboxes_by_page: Dict[int, List[Dict[str, object]]],
    *,
    overlap_threshold: float,
    min_length_pt: float = 20.0,
    max_height_pt: float = 3.5,
    min_aspect: float = 6.0,
) -> int:
    """
    Add line candidates from vector rectangle objects on native PDFs.

    Some PDFs encode underlines as thin vector rects that can be missed by raster
    detection. We inject those rects as line candidates to boost recall.
    """
    if not candidates or not rect_bboxes_by_page:
        return 0

    added_total = 0
    for page in candidates:
        page_idx = int(page.get("page") or 0)
        rect_entries = rect_bboxes_by_page.get(page_idx) or []
        if not rect_entries:
            continue

        vector_lines: List[List[float]] = []
        for rect_entry in rect_entries:
            if not isinstance(rect_entry, dict):
                continue
            if _rect_is_invisible_fill(rect_entry):
                continue
            bbox = rect_entry.get("bbox") if isinstance(rect_entry.get("bbox"), list) else None
            if not bbox or len(bbox) != 4:
                continue
            bbox_vals = [float(v) for v in bbox]
            width = float(bbox_vals[2]) - float(bbox_vals[0])
            height = float(bbox_vals[3]) - float(bbox_vals[1])
            if width <= 0.0 or height <= 0.0:
                continue
            if height > max_height_pt:
                continue
            if width < min_length_pt:
                continue
            aspect = width / max(height, 0.01)
            if aspect < min_aspect:
                continue
            vector_lines.append(bbox_vals)

        if not vector_lines:
            continue

        existing = list(page.get("lineCandidates") or [])
        existing_bboxes = [
            ln.get("bbox")
            for ln in existing
            if isinstance(ln.get("bbox"), list) and len(ln.get("bbox")) == 4
        ]

        added_page = 0
        for bbox in vector_lines:
            if any(_overlap_ratio(bbox, eb) >= float(overlap_threshold) for eb in existing_bboxes):
                continue
            existing.append(
                {
                    "bbox": bbox,
                    "type": "line",
                    "detector": "vector_line",
                }
            )
            existing_bboxes.append(bbox)
            added_page += 1

        if added_page:
            sorted_candidates = sorted(existing, key=_bbox_sort_key)
            for idx, cand in enumerate(sorted_candidates, start=1):
                cand["id"] = f"line-{page_idx}-{idx}"
            page["lineCandidates"] = sorted_candidates
            added_total += added_page
            logger.debug(
                "Injected %s vector-line candidates on page %s",
                added_page,
                page_idx,
            )

    if added_total:
        logger.debug(
            "Injected %s vector-line candidates total (overlap_threshold=%.2f)",
            added_total,
            float(overlap_threshold),
        )
    return added_total


def _label_text_looks_like_option_group(text: str) -> bool:
    """
    Return True when a label bbox likely represents an option group with checkboxes.

    Why this exists:
    - Some PDFs draw the checkbox squares as part of the text layer (a glyph), so the
      extracted label bbox can include both the checkbox and its neighboring words.
    - We previously used label overlap to drop glyph-derived checkbox false positives ("O"),
      but that can also drop real checkbox glyphs inside legitimate option groups.
    """
    raw = (text or "").strip()
    if not raw:
        return False
    if re.search(r"(?:^|\s)[Oo0][A-Z]", raw):
        return True
    lower = raw.lower()
    pairs = [
        ("male", "female"),
        ("yes", "no"),
        ("english", "spanish"),
        ("single", "married"),
        ("hmo", "ppo"),
        ("high school", "graduate"),
        ("graduate", "post graduate"),
    ]
    for a, b in pairs:
        if a in lower and b in lower:
            return True
    if _TOKEN_Y.search(lower) and _TOKEN_N.search(lower):
        return True
    option_tokens = {
        "male",
        "female",
        "other",
        "yes",
        "no",
        "english",
        "spanish",
        "single",
        "married",
        "divorced",
        "separated",
        "widowed",
        "hmo",
        "ppo",
        "medicare",
        "spouse",
        "child",
        "parent",
        "tobacco",
        "marijuana",
    }
    hits = sum(1 for tok in option_tokens if tok in lower)
    return hits >= 3


def _label_is_short_option(text: str) -> bool:
    """
    Return True when the label is a short, option-like token (Yes/No, Male/Female, etc.).
    """
    raw = (text or "").strip().lower()
    if not raw:
        return False
    normalized = re.sub(r"[^a-z0-9/]+", " ", raw).strip()
    if not normalized:
        return False
    words = normalized.split()
    if not words:
        return False
    if len(words) <= 2 and len(normalized) <= 10:
        return True
    option_tokens = {
        "yes",
        "no",
        "na",
        "n/a",
        "male",
        "female",
        "other",
        "true",
        "false",
        "single",
        "married",
        "divorced",
        "separated",
        "widowed",
        "full-time",
        "part-time",
        "student",
        "disabled",
        "unemployed",
        "retired",
    }
    return all(word in option_tokens for word in words)


def _checkbox_is_inline_between_words(
    bbox: List[float],
    label_bboxes: List[tuple[List[float], str]],
    *,
    median_label_height: float,
    row_count: int,
) -> bool:
    """
    Return True when a checkbox sits between two nearby words in a sentence.

    We use this to suppress false positives where a square glyph is embedded in text.
    """
    if row_count >= 3:
        return False
    if not bbox or len(bbox) != 4:
        return False
    row_labels = [
        (lbbox, text)
        for lbbox, text in label_bboxes
        if lbbox and _vertical_overlap_ratio(bbox, lbbox) >= 0.6
    ]
    if len(row_labels) < 2:
        return False
    left_gap = None
    right_gap = None
    left_text = ""
    right_text = ""
    for lbbox, text in row_labels:
        if lbbox[2] <= bbox[0]:
            gap = float(bbox[0]) - float(lbbox[2])
            if left_gap is None or gap < left_gap:
                left_gap = gap
                left_text = text
        if lbbox[0] >= bbox[2]:
            gap = float(lbbox[0]) - float(bbox[2])
            if right_gap is None or gap < right_gap:
                right_gap = gap
                right_text = text
    if left_gap is None or right_gap is None:
        return False
    cb_h = float(bbox[3]) - float(bbox[1])
    gap_limit = max(4.0, min(12.0, (median_label_height or cb_h) * 0.7))
    if left_gap > gap_limit or right_gap > gap_limit:
        return False
    combined = f"{left_text} {right_text}".strip()
    if _label_text_looks_like_option_group(combined):
        return False
    if _label_is_short_option(left_text) or _label_is_short_option(right_text):
        return False
    return True


def _median(values: List[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[mid])
    return (float(ordered[mid - 1]) + float(ordered[mid])) / 2.0


def _vertical_overlap_ratio(a: List[float], b: List[float]) -> float:
    ay1, ay2 = float(a[1]), float(a[3])
    by1, by2 = float(b[1]), float(b[3])
    inter = max(0.0, min(ay2, by2) - max(ay1, by1))
    if inter <= 0.0:
        return 0.0
    min_h = min(max(ay2 - ay1, 0.0), max(by2 - by1, 0.0))
    if min_h <= 0.0:
        return 0.0
    return inter / min_h


def _label_is_header_row(
    label_text: str,
    label_bbox: List[float],
    *,
    page_width: float,
    page_height: float,
    median_label_height: float,
) -> bool:
    """
    Identify top-of-page title/header labels to prevent false checkbox matches.

    Strategy:
    - Require the label to be wide and near the top margin.
    - Require multi-word text so short prompts ("Yes", "No") are not treated as headers.
    """
    if not label_text or len(label_bbox) != 4:
        return False
    text = label_text.strip()
    if not text:
        return False
    words = text.split()
    norm = " ".join(text.lower().split())
    header_phrases = (
        "check all",
        "check any",
        "please check",
        "please indicate",
        "mark all",
        "circle all",
        "symptoms checklist",
        "symptoms that apply",
        "checklist",
    )
    keyword_header = any(phrase in norm for phrase in header_phrases)
    if len(words) < 3 and len(text) < 18 and not keyword_header:
        return False
    x1, y1, x2, y2 = [float(v) for v in label_bbox]
    width = max(0.0, x2 - x1)
    height = max(0.0, y2 - y1)
    mid_y = (y1 + y2) / 2.0
    if page_height <= 0 or page_width <= 0:
        return False
    if mid_y > page_height * 0.18 and not (keyword_header and mid_y <= page_height * 0.25):
        return False
    if width < page_width * 0.45 and not keyword_header:
        return False
    if median_label_height > 0.0 and height < median_label_height * 0.8:
        return False
    return True


def _bbox_sort_key(item: Dict) -> tuple[float, float, float, float]:
    bbox = item.get("bbox") or [0, 0, 0, 0]
    if len(bbox) != 4:
        return (0.0, 0.0, 0.0, 0.0)
    return (float(bbox[1]), float(bbox[0]), float(bbox[3]), float(bbox[2]))


def assemble_candidates_for_page(
    page: Dict,
    page_geom: Dict,
    labels: List[Dict],
) -> Dict:
    """
    Merge per-page geometry + labels into the resolver-friendly candidate payload.

    Data structures:
    - Inputs are dicts keyed by candidate type with bbox arrays in PDF points.
    - Output is a normalized dict with stable IDs (line-#, box-#, checkbox-#).

    Runtime:
    - Sorting candidates is O(n log n).
    - Checkbox filtering compares each checkbox to each label group (O(c * l)).
    """
    page_index = page["page_index"]
    line_candidates = []
    sorted_lines = sorted(page_geom.get("lineCandidates", []), key=_bbox_sort_key)
    for idx, ln in enumerate(sorted_lines, start=1):
        candidate = dict(ln)
        candidate["id"] = f"line-{page_index}-{idx}"
        line_candidates.append(candidate)

    box_candidates = []
    sorted_boxes = sorted(page_geom.get("boxCandidates", []), key=_bbox_sort_key)
    for idx, bx in enumerate(sorted_boxes, start=1):
        candidate = dict(bx)
        candidate["id"] = f"box-{page_index}-{idx}"
        box_candidates.append(candidate)

    checkbox_candidates = []
    sorted_checkboxes = sorted(page_geom.get("checkboxCandidates", []), key=_bbox_sort_key)

    label_bboxes = [
        (lbl.get("bbox"), (lbl.get("text") or ""))
        for lbl in (labels or [])
        if isinstance(lbl.get("bbox"), list) and len(lbl.get("bbox")) == 4
    ]
    label_heights = [
        float(bbox[3]) - float(bbox[1])
        for bbox, _ in label_bboxes
        if bbox
    ]
    median_label_height = _median(label_heights)
    page_width = float(page.get("width_points") or 0.0)
    page_height = float(page.get("height_points") or 0.0)
    label_filter_enabled = len(label_bboxes) >= 6

    # Cluster checkbox rows so we can drop isolated boxes when labels are available.
    row_index_by_pos: List[int] = [-1] * len(sorted_checkboxes)
    row_counts: List[int] = []
    row_centers: List[float] = []
    row_labels_by_idx: List[List[List[float]]] = []
    row_tol = None
    if sorted_checkboxes:
        cb_heights = [
            float((cb.get("bbox") or [0, 0, 0, 0])[3])
            - float((cb.get("bbox") or [0, 0, 0, 0])[1])
            for cb in sorted_checkboxes
            if isinstance(cb.get("bbox"), list) and len(cb.get("bbox")) == 4
        ]
        median_cb_h = _median(cb_heights) or (median_label_height or 10.0)
        row_tol = max(4.0, min(16.0, median_cb_h * 0.8))

        for pos, cb in enumerate(sorted_checkboxes):
            bbox = cb.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            y_mid = (float(bbox[1]) + float(bbox[3])) / 2.0
            assigned = False
            for idx, center in enumerate(row_centers):
                if abs(y_mid - center) <= row_tol:
                    row_counts[idx] += 1
                    row_centers[idx] = (row_centers[idx] + y_mid) / 2.0
                    row_index_by_pos[pos] = idx
                    assigned = True
                    break
            if not assigned:
                row_centers.append(y_mid)
                row_counts.append(1)
                row_index_by_pos[pos] = len(row_centers) - 1
        row_labels_by_idx = [[] for _ in row_centers]
        if row_labels_by_idx and label_bboxes:
            for lbbox, text in label_bboxes:
                if not lbbox or len(lbbox) != 4:
                    continue
                if _label_is_header_row(
                    text,
                    lbbox,
                    page_width=page_width,
                    page_height=page_height,
                    median_label_height=median_label_height,
                ):
                    continue
                label_mid_y = (float(lbbox[1]) + float(lbbox[3])) / 2.0
                for row_idx, center in enumerate(row_centers):
                    if abs(label_mid_y - center) <= float(row_tol or 0.0):
                        row_labels_by_idx[row_idx].append(lbbox)
                        break

    for idx, cb in enumerate(sorted_checkboxes, start=1):
        candidate = dict(cb)
        bbox = candidate.get("bbox")
        row_idx = row_index_by_pos[idx - 1] if idx - 1 < len(row_index_by_pos) else -1
        row_count = row_counts[row_idx] if row_idx >= 0 and row_idx < len(row_counts) else 1
        if bbox and len(bbox) == 4 and label_bboxes:
            if candidate.get("detector") != "table_cells" and _checkbox_is_inline_between_words(
                bbox,
                label_bboxes,
                median_label_height=median_label_height,
                row_count=row_count,
            ):
                logger.debug(
                    "Dropping inline checkbox candidate on page %s (bbox=%s)",
                    page_index,
                    bbox,
                )
                continue
            area = float((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])) or 0.0
            if area > 0.0:
                overlaps_text = False
                for lbbox, text in label_bboxes:
                    if not text or len(text.strip()) < 2:
                        continue
                    if _label_text_looks_like_option_group(text):
                        continue
                    inter_ratio = _inter_area(bbox, lbbox) / area
                    if inter_ratio < 0.35:
                        continue
                    cb_w = float(bbox[2] - bbox[0]) or 1.0
                    lb_w = float(lbbox[2] - lbbox[0])
                    lb_h = float(lbbox[3] - lbbox[1])
                    if (
                        float(bbox[0]) - float(lbbox[0]) > (cb_w * 0.9)
                        and lb_w <= cb_w * 1.8
                        and lb_h <= cb_w * 1.8
                    ):
                        overlaps_text = True
                        break
                if overlaps_text:
                    logger.debug(
                        "Dropping checkbox candidate overlapping text on page %s (bbox=%s)",
                        page_index,
                        bbox,
                    )
                    continue
        if bbox and len(bbox) == 4 and label_bboxes and page_height > 0:
            row_labels = [
                (lbbox, text)
                for lbbox, text in label_bboxes
                if _vertical_overlap_ratio(bbox, lbbox) >= 0.6
            ]
            if row_labels:
                header_only = all(
                    _label_is_header_row(
                        text,
                        lbbox,
                        page_width=page_width,
                        page_height=page_height,
                        median_label_height=median_label_height,
                    )
                    for lbbox, text in row_labels
                )
                if header_only and bbox[1] <= page_height * 0.18:
                    logger.debug(
                        "Dropping checkbox candidate aligned with header row on page %s (bbox=%s)",
                        page_index,
                        bbox,
                    )
                    continue
            max_overlap = 0.0
            for lbbox, _ in label_bboxes:
                max_overlap = max(max_overlap, _vertical_overlap_ratio(bbox, lbbox))
            if max_overlap < 0.4 and bbox[1] <= page_height * 0.12:
                logger.debug(
                    "Dropping checkbox candidate with no nearby label near top margin on page %s (bbox=%s)",
                    page_index,
                    bbox,
                )
                continue
        if bbox and len(bbox) == 4 and label_filter_enabled:
            detector = str(candidate.get("detector") or "")
            if detector != "table_cells":
                row_labels = row_labels_by_idx[row_idx] if row_idx >= 0 and row_idx < len(row_labels_by_idx) else []
                row_has_label = bool(row_labels)
                if row_count < 2 and not row_has_label:
                    logger.debug(
                        "Dropping checkbox candidate with no row label on page %s (bbox=%s)",
                        page_index,
                        bbox,
                    )
                    continue
                if row_count == 1 and row_has_label:
                    cb_w = float(bbox[2]) - float(bbox[0])
                    max_gap = max(120.0, cb_w * 8.0)
                    best_gap = None
                    for lbbox in row_labels:
                        gap = 0.0
                        if lbbox[2] <= bbox[0]:
                            gap = float(bbox[0]) - float(lbbox[2])
                        elif lbbox[0] >= bbox[2]:
                            gap = float(lbbox[0]) - float(bbox[2])
                        else:
                            gap = 0.0
                        if best_gap is None or gap < best_gap:
                            best_gap = gap
                    if best_gap is None or best_gap > max_gap:
                        logger.debug(
                            "Dropping checkbox candidate with distant label on page %s (bbox=%s)",
                            page_index,
                            bbox,
                        )
                        continue
        candidate["id"] = f"checkbox-{page_index}-{idx}"
        checkbox_candidates.append(candidate)

    if checkbox_candidates:
        overlap_threshold = float(os.getenv("SANDBOX_CHECKBOX_DEDUPE_OVERLAP", "0.85"))
        checkbox_candidates = _dedupe_overlapping_checkboxes(
            checkbox_candidates,
            overlap_threshold=overlap_threshold,
            page_index=page_index,
        )
        for idx, cand in enumerate(checkbox_candidates, start=1):
            cand["id"] = f"checkbox-{page_index}-{idx}"

    page_entry = {
        "page": page_index,
        "pageWidth": float(page["width_points"]),
        "pageHeight": float(page["height_points"]),
        "scale": float(page.get("scale", 1.0)),
        "rotation": int(page.get("rotation", 0)),
        "imageWidthPx": int(page.get("image_width_px", 0) or 0),
        "imageHeightPx": int(page.get("image_height_px", 0) or 0),
        "labels": labels,
        "lineCandidates": line_candidates,
        "boxCandidates": box_candidates,
        "checkboxCandidates": checkbox_candidates,
    }
    logger.debug(
        "Page %s candidates -> labels:%s lines:%s boxes:%s checkboxes:%s",
        page_index,
        len(labels),
        len(page_entry["lineCandidates"]),
        len(page_entry["boxCandidates"]),
        len(page_entry["checkboxCandidates"]),
    )
    return page_entry


def assemble_candidates(
    rendered_pages: List[Dict],
    geometry: List[Dict],
    labels_by_page: Dict[int, List[Dict]],
    *,
    max_workers: Optional[int] = None,
) -> List[Dict]:
    """Merge geometry and label detections into the resolver-friendly payload."""
    geometry_by_page = {g["page_index"]: g for g in geometry}
    max_workers = max_workers or resolve_workers("candidates", default=min(4, os.cpu_count() or 4))

    def _worker(page: Dict) -> Dict:
        page_index = page["page_index"]
        page_geom = geometry_by_page.get(page_index, {})
        labels = labels_by_page.get(page_index, [])
        return assemble_candidates_for_page(page, page_geom, labels)

    # Each page is independent, so we can assemble candidates in parallel.
    candidates = run_threaded_map(
        rendered_pages,
        _worker,
        max_workers=max_workers,
        label="candidates",
    )
    logger.info("Prepared %s pages of candidates", len(candidates))
    return candidates
