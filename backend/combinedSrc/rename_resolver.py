from __future__ import annotations

import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import cv2
from openai import OpenAI

from .concurrency import resolve_workers, run_threaded_map
from .config import LOG_OPENAI_RESPONSE, get_logger
from .field_overlay import draw_overlay
from .openai_utils import extract_response_text, responses_create_with_temperature_fallback
from .vision_utils import image_bgr_to_data_url

logger = get_logger(__name__)

DEFAULT_RENAME_MODEL = os.getenv("SANDBOX_RENAME_MODEL", "gpt-5.2")

RENAME_LINE_RE = re.compile(
    r"^\s*\|\|\s*(?P<orig>[^|]+?)\s*\|\s*(?P<suggested>[^|]*?)\s*\|\s*(?P<rename_conf>[^|]*?)\s*\|\s*(?P<field_conf>[^|]*?)\s*$"
)


def _to_snake_case(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", (text or "").strip()).strip()
    if not cleaned:
        return "field"
    return re.sub(r"\s+", "_", cleaned.lower())


def _normalize_name(name: str, field_type: str) -> str:
    base = _to_snake_case(name)
    if field_type == "checkbox" and not base.startswith("i_"):
        base = f"i_{base}"
    return base or "field"


def _parse_confidence(value: str) -> float:
    raw = (value or "").strip().strip('"').strip("'")
    if not raw:
        return 0.0
    cleaned = raw.replace("%", "").strip()
    try:
        conf = float(cleaned)
    except ValueError:
        return 0.0
    if conf > 1.0:
        conf = conf / 100.0
    return max(0.0, min(1.0, conf))


def _downscale_for_model(image_bgr: "cv2.Mat", *, max_dim: int) -> "cv2.Mat":
    if not max_dim or max_dim <= 0:
        return image_bgr
    h, w = image_bgr.shape[:2]
    largest = max(h, w)
    if largest <= max_dim:
        return image_bgr
    scale = max_dim / float(largest)
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    return cv2.resize(image_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)


def _field_sort_key(field: Dict[str, Any]) -> Tuple[int, float, float, str]:
    rect = field.get("rect") or [0, 0, 0, 0]
    page = int(field.get("page") or 1)
    y1 = float(rect[1]) if len(rect) == 4 else 0.0
    x1 = float(rect[0]) if len(rect) == 4 else 0.0
    return (page, y1, x1, str(field.get("name") or ""))


def _rects_intersect(a: List[float], b: List[float]) -> bool:
    return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])


def _rect_distance(a: List[float], b: List[float]) -> float:
    """
    Distance between two rectangles in points (0 when overlapping).
    """
    dx = max(b[0] - a[2], a[0] - b[2], 0.0)
    dy = max(b[1] - a[3], a[1] - b[3], 0.0)
    return math.hypot(dx, dy)


def _label_context(
    rect: List[float],
    label_bboxes: List[List[float]],
) -> Tuple[float | None, bool]:
    """
    Return (min_distance_to_label, overlaps_label).
    """
    if not rect or len(rect) != 4 or not label_bboxes:
        return None, False
    min_dist = None
    overlaps = False
    for lb in label_bboxes:
        if len(lb) != 4:
            continue
        if _rects_intersect(rect, lb):
            overlaps = True
            min_dist = 0.0
            break
        dist = _rect_distance(rect, lb)
        if min_dist is None or dist < min_dist:
            min_dist = dist
    return min_dist, overlaps


def _build_overlay_fields(
    page_fields: List[Tuple[int, Dict[str, Any]]],
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    Build overlay field labels that are unique per page.

    We keep a mapping back to the original field index so rename output can be applied
    deterministically without mutating the baseline field list.
    """
    counts: Dict[str, int] = {}
    overlay_fields: List[Dict[str, Any]] = []
    overlay_map: Dict[str, int] = {}

    for field_index, field in page_fields:
        base_name = field.get("name") or field.get("candidateId") or f"field_{field_index}"
        base = _to_snake_case(str(base_name))
        n = counts.get(base, 0)
        counts[base] = n + 1
        display = base if n == 0 else f"{base}_{n}"
        overlay_map[display] = field_index
        overlay_fields.append(
            {
                "page": int(field.get("page") or 1),
                "rect": field.get("rect"),
                "type": field.get("type") or "text",
                "name": display,
                "displayName": display,
            }
        )

    return overlay_fields, overlay_map


def _build_prompt(
    page_idx: int,
    overlay_fields: List[Dict[str, Any]],
    *,
    page_candidates: Dict[str, Any],
) -> Tuple[str, str]:
    """
    Build the system/user prompt text for the rename pass.
    """
    system_message = (
        "You are a PDF form renaming assistant. You will receive a page overlay image with "
        "field boxes labeled using their current names. Use the labels as originalFieldName.\n"
        "Candidates with isItAfieldConfidence below 0.30 are treated as not-a-field and will be "
        "dropped from output.\n\n"
        "Output format (one line per field, no extra text):\n"
        "|| originalFieldName | suggestedRename | renameConfidence | isItAfieldConfidence\n"
        "Example format only (do not reuse names):\n"
        "|| example_field | patient_name | 0.92 | 0.98\n\n"
        "Rules:\n"
        "- Output exactly one line for every originalFieldName provided, in the same order.\n"
        "- Do not invent names that are not listed.\n"
        "- Use snake_case for suggestedRename.\n"
        "- Checkbox names should start with 'i_'.\n"
        "- Confidence values must be between 0 and 1 (not percent).\n"
        "- If the item is not a real field, set isItAfieldConfidence < 0.30.\n"
        "- If isItAfieldConfidence < 0.30, keep suggestedRename equal to originalFieldName and "
        "set renameConfidence to 0.\n\n"
        "Field-ness rules:\n"
        "- Real fields have an empty box/underline or a checkbox aligned with nearby option text.\n"
        "- Use the per-field metadata (label_dist, overlaps_label, w_ratio, h_ratio) as hints.\n"
        "- Reject boxes sitting in paragraph text, headers/footers, logos, or decorative shapes.\n"
        "- If a field is drawn in the middle of a paragraph and there is no visible underline "
        "or checkbox tied to it, mark it as not-a-field (isItAfieldConfidence < 0.30).\n"
        "- Reject isolated boxes in whitespace with no prompt label.\n"
        "- For text fields: if label_dist >= 60 and overlaps_label=0, treat it as not-a-field "
        "unless it is clearly inside a repeating table grid.\n"
        "- For long rules: if w_ratio >= 0.80 and h_ratio <= 0.02, treat as a page break "
        "or separator (not a field).\n"
        "- If a field is in the middle of empty whitespace with no nearby label or prompt text, set "
        "isItAfieldConfidence < 0.30 (treat as not-a-field).\n"
        "- Reject page-break lines or section separators that look like long rules; set "
        "isItAfieldConfidence < 0.30 for those.\n"
        "- Reject any checkbox drawn on top of paragraph text or embedded between paragraphs; set "
        "isItAfieldConfidence < 0.30.\n"
        "- For checkboxes: require option text on the same row/column or clear grid alignment with "
        "other checkboxes; a lone square is not-a-field.\n"
        "- Double-checkbox problem: sometimes two checkbox boxes overlap the same option label. "
        "If two boxes overlap or are nearly identical, keep the best one and set the duplicate "
        "isItAfieldConfidence < 0.30.\n"
        "- Reject legend markers, bullets, table headers, or column labels that are not fillable."
    )

    label_bboxes = [
        lb.get("bbox")
        for lb in (page_candidates.get("labels") or [])
        if isinstance(lb.get("bbox"), list) and len(lb.get("bbox")) == 4
    ]
    page_width = float(page_candidates.get("pageWidth") or 0.0)
    page_height = float(page_candidates.get("pageHeight") or 0.0)

    field_lines = []
    for field in overlay_fields:
        rect = field.get("rect") or []
        label_dist, overlaps_label = _label_context(rect, label_bboxes)
        if page_width > 0.0 and rect and len(rect) == 4:
            width_ratio = max(0.0, (float(rect[2]) - float(rect[0])) / page_width)
        else:
            width_ratio = 0.0
        if page_height > 0.0 and rect and len(rect) == 4:
            height_ratio = max(0.0, (float(rect[3]) - float(rect[1])) / page_height)
        else:
            height_ratio = 0.0
        label_dist_str = "na" if label_dist is None else f"{int(round(label_dist))}"
        overlaps_str = "1" if overlaps_label else "0"
        field_lines.append(
            f"{field.get('name')}\t(type={field.get('type')}, label_dist={label_dist_str}, "
            f"overlaps_label={overlaps_str}, w_ratio={width_ratio:.2f}, h_ratio={height_ratio:.2f})"
        )
    field_block = "\n".join(field_lines)

    user_message = (
        f"Page {page_idx} fields (originalFieldName list). Return one output line per entry "
        "in the same order.\n"
        "BEGIN_FIELD_LIST\n"
        f"{field_block}\n"
        "END_FIELD_LIST\n\n"
        "Return the rename output lines now."
    )
    return system_message, user_message


def _parse_openai_lines(
    response_text: str,
    *,
    overlay_map: Dict[str, int],
) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for raw in (response_text or "").splitlines():
        line = raw.strip()
        if not line.startswith("||"):
            continue
        match = RENAME_LINE_RE.match(line)
        if not match:
            logger.debug("Rename line ignored (format mismatch): %s", line)
            continue
        original_raw = match.group("orig").strip()
        original = _to_snake_case(original_raw)
        suggested = match.group("suggested").strip().strip('"').strip("'")
        rename_conf = _parse_confidence(match.group("rename_conf"))
        field_conf = _parse_confidence(match.group("field_conf"))
        if not original or original not in overlay_map:
            continue
        entries.append(
            {
                "originalFieldName": original,
                "suggestedRename": suggested,
                "renameConfidence": rename_conf,
                "isItAfieldConfidence": field_conf,
                "fieldIndex": overlay_map[original],
            }
        )
    return entries


def _dedupe_field_names(fields: List[Dict[str, Any]]) -> None:
    counts: Dict[str, int] = {}
    for field in sorted(fields, key=_field_sort_key):
        field_type = str(field.get("type") or "text").lower()
        base = _normalize_name(str(field.get("name") or "field"), field_type)
        n = counts.get(base, 0)
        counts[base] = n + 1
        field["name"] = base if n == 0 else f"{base}_{n}"


def run_openai_rename_pipeline(
    rendered_pages: List[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
    fields: List[Dict[str, Any]],
    *,
    output_dir: Path,
    model: str = DEFAULT_RENAME_MODEL,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Rename fields via OpenAI using one overlay per page.

    The overlay includes candidate geometry plus field names so the model can align
    each label with its on-page context. Output is parsed from line-based responses.
    """
    if not fields:
        return {
            "generatedAt": datetime.now(tz=timezone.utc).isoformat(),
            "model": model,
            "renames": [],
            "dropped": [],
        }, []

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY not set; cannot run OpenAI rename.")

    output_dir.mkdir(parents=True, exist_ok=True)
    overlay_quality = int(os.getenv("SANDBOX_RENAME_OVERLAY_QUALITY", "80"))
    overlay_max_dim = int(os.getenv("SANDBOX_RENAME_OVERLAY_MAX_DIM", "2400"))
    max_output_tokens = int(os.getenv("SANDBOX_RENAME_MAX_OUTPUT_TOKENS", "4096"))
    max_workers = resolve_workers("openai", default=6, use_global=False)
    min_field_conf = float(os.getenv("SANDBOX_RENAME_MIN_FIELD_CONF", "0.3"))

    fields_by_page: Dict[int, List[Tuple[int, Dict[str, Any]]]] = {}
    for idx, field in enumerate(fields):
        page = int(field.get("page") or 1)
        fields_by_page.setdefault(page, []).append((idx, field))

    candidates_by_page: Dict[int, Dict[str, Any]] = {}
    for page_candidates in candidates:
        page_idx = int(page_candidates.get("page") or 1)
        if page_idx not in candidates_by_page:
            candidates_by_page[page_idx] = page_candidates

    tasks: List[Dict[str, Any]] = []
    page_contexts: Dict[int, Dict[str, Any]] = {}

    for page in rendered_pages:
        page_idx = int(page.get("page_index") or 1)
        page_fields = fields_by_page.get(page_idx, [])
        if not page_fields:
            continue
        page_fields_sorted = sorted(page_fields, key=lambda item: _field_sort_key(item[1]))
        overlay_fields, overlay_map = _build_overlay_fields(page_fields_sorted)
        page_candidates = candidates_by_page.get(page_idx)
        if page_candidates is None:
            continue

        overlay_path = output_dir / f"page_{page_idx}.png"
        overlay = draw_overlay(
            page.get("image"),
            page_candidates,
            overlay_fields,
            overlay_path,
            return_image=True,
        )
        if overlay is None:
            raise RuntimeError(f"Failed to render overlay image: {overlay_path}")

        overlay_for_model = _downscale_for_model(overlay, max_dim=overlay_max_dim)
        overlay_url = image_bgr_to_data_url(
            overlay_for_model,
            format="jpg",
            quality=overlay_quality,
        )
        system_message, user_message = _build_prompt(
            page_idx,
            overlay_fields,
            page_candidates=page_candidates,
        )

        page_contexts[page_idx] = {
            "overlay_map": overlay_map,
            "system_message": system_message,
            "user_message": user_message,
            "overlay_url": overlay_url,
        }
        tasks.append({"page_idx": page_idx})

    def _run_page(task: Dict[str, Any]) -> Dict[str, Any]:
        page_idx = task["page_idx"]
        context = page_contexts[page_idx]
        messages = [
            {"role": "system", "content": [{"type": "input_text", "text": context["system_message"]}]},
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": context["user_message"]},
                    {"type": "input_image", "image_url": context["overlay_url"], "detail": "high"},
                ],
            },
        ]
        client = OpenAI()
        response = responses_create_with_temperature_fallback(
            client,
            model=model,
            input=messages,
            temperature=None,
            max_output_tokens=max_output_tokens,
            text={"format": {"type": "text"}},
        )
        response_text = extract_response_text(response)
        if LOG_OPENAI_RESPONSE:
            logger.info(
                "OpenAI rename response page %s (model %s):\n%s",
                page_idx,
                model,
                response_text,
            )
        entries = _parse_openai_lines(response_text, overlay_map=context["overlay_map"])
        if len(entries) < len(context["overlay_map"]):
            logger.warning(
                "OpenAI rename page %s returned %s/%s lines; missing fields will keep defaults.",
                page_idx,
                len(entries),
                len(context["overlay_map"]),
            )
        return {"page_idx": page_idx, "entries": entries}

    if tasks:
        results = run_threaded_map(
            tasks,
            _run_page,
            max_workers=max_workers,
            label="rename_openai",
        )
    else:
        results = []

    entries_by_index: Dict[int, Dict[str, Any]] = {}
    for result in results:
        for entry in result["entries"]:
            idx = entry["fieldIndex"]
            existing = entries_by_index.get(idx)
            if existing is None or entry["isItAfieldConfidence"] > existing["isItAfieldConfidence"]:
                entries_by_index[idx] = entry

    renamed_fields: List[Dict[str, Any]] = []
    renames_report: List[Dict[str, Any]] = []
    dropped: List[str] = []

    for idx, field in enumerate(fields):
        entry = entries_by_index.get(idx)
        baseline_conf = float(field.get("confidence") or 0.6)
        rename_conf = float(entry.get("renameConfidence") or 0.0) if entry else 0.0
        field_conf = float(entry.get("isItAfieldConfidence") or baseline_conf) if entry else baseline_conf
        original_name = str(field.get("name") or "")
        suggested = str(entry.get("suggestedRename") or original_name) if entry else original_name

        if field_conf < min_field_conf:
            dropped.append(original_name or f"field_{idx}")
            continue

        updated = dict(field)
        if entry:
            updated["originalName"] = entry.get("originalFieldName") or original_name
        else:
            updated["originalName"] = original_name
        updated["renameConfidence"] = rename_conf
        updated["isItAfieldConfidence"] = field_conf
        updated["name"] = _normalize_name(suggested, str(updated.get("type") or "text").lower())
        renamed_fields.append(updated)

        renames_report.append(
            {
                "page": int(field.get("page") or 1),
                "candidateId": field.get("candidateId"),
                "originalFieldName": entry.get("originalFieldName") if entry else original_name,
                "suggestedRename": updated["name"],
                "renameConfidence": rename_conf,
                "isItAfieldConfidence": field_conf,
            }
        )

    _dedupe_field_names(renamed_fields)

    return (
        {
            "generatedAt": datetime.now(tz=timezone.utc).isoformat(),
            "model": model,
            "renames": renames_report,
            "dropped": dropped,
        },
        renamed_fields,
    )
