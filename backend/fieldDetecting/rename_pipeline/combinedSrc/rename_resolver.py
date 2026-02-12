"""
OpenAI rename resolver for the rename pipeline.

This module renders per-page overlays with short IDs, prompts the model to rename
fields using the overlay context, parses the line-based response, and applies
normalization/gating to the final field list.

Key data structures:
- overlay_map: short overlay ID -> original field index (stable mapping for rename output).
- page_contexts: page index -> prompt text + image URLs + overlay map.
- entries_by_index: field index -> best rename entry selected from model output.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import cv2

from backend.ai.openai_client import create_openai_client
from backend.ai.openai_usage import build_openai_usage_summary
from .concurrency import resolve_workers, run_threaded_map
from .config import LOG_OPENAI_RESPONSE, get_logger
from .field_overlay import draw_overlay
from .openai_utils import (
    extract_response_text,
    extract_response_usage,
    responses_create_with_temperature_fallback,
)
from .vision_utils import image_bgr_to_data_url

logger = get_logger(__name__)

DEFAULT_RENAME_MODEL = os.getenv("SANDBOX_RENAME_MODEL", "gpt-5-mini")
COMMONFORMS_CONFIDENCE_GREEN = float(os.getenv("COMMONFORMS_CONFIDENCE_GREEN", "0.8"))
COMMONFORMS_CONFIDENCE_YELLOW = float(os.getenv("COMMONFORMS_CONFIDENCE_YELLOW", "0.65"))

BASE32_TAG_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
# Precompute all 3-character tags for deterministic sampling per page.
BASE32_TAGS = tuple(
    a + b + c
    for a in BASE32_TAG_ALPHABET
    for b in BASE32_TAG_ALPHABET
    for c in BASE32_TAG_ALPHABET
)

RENAME_LINE_RE = re.compile(
    r"^\s*\|\|\s*(?P<orig>[^|]+?)\s*\|\s*(?P<suggested>[^|]*?)\s*\|\s*(?P<rename_conf>[^|]*?)\s*\|\s*(?P<field_conf>[^|]*?)\s*$"
)
CHECKBOX_RULES_START = "BEGIN_CHECKBOX_RULES_JSON"
CHECKBOX_RULES_END = "END_CHECKBOX_RULES_JSON"


def _to_snake_case(text: str) -> str:
    """
    Normalize text into snake_case for stable downstream naming.
    """
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", (text or "").strip()).strip()
    if not cleaned:
        return "field"
    return re.sub(r"\s+", "_", cleaned.lower())


def _normalize_name(name: str, field_type: str) -> str:
    """
    Normalize field names and enforce checkbox prefixes.
    """
    base = _to_snake_case(name)
    if field_type == "checkbox" and not base.startswith("i_"):
        base = f"i_{base}"
    return base or "field"


def _normalize_checkbox_component(value: str) -> str:
    """
    Normalize checkbox group/option tokens to snake_case.
    """
    return _to_snake_case(value)


def _humanize_group_label(group_key: str) -> str:
    """
    Convert a normalized group key into a display-friendly label.
    """
    if not group_key:
        return ""
    return group_key.replace("_", " ")


def _parse_confidence(value: str) -> float:
    """
    Parse confidence strings in percent or decimal form into [0, 1].
    """
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


def _stable_seed(value: str) -> int:
    """
    Stable hash seed for deterministic overlay tag sampling.
    """
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _generate_base32_tags(count: int, *, seed: int) -> List[str]:
    """
    Sample unique 3-character IDs using a stable random seed.
    """
    if count <= 0:
        return []
    if count > len(BASE32_TAGS):
        raise ValueError(f"Requested {count} tags, but only {len(BASE32_TAGS)} are available.")
    rng = random.Random(seed)
    return rng.sample(BASE32_TAGS, count)


def _downscale_for_model(image_bgr: "cv2.Mat", *, max_dim: int) -> "cv2.Mat":
    """
    Downscale large images to cap token/latency cost while preserving detail.
    """
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


def _crop_prev_page_context(image_bgr: "cv2.Mat", *, fraction: float) -> "cv2.Mat":
    """
    Crop the bottom slice of the previous page for label carry-over context.
    """
    if image_bgr is None or image_bgr.size == 0:
        return image_bgr
    if fraction <= 0 or fraction > 1:
        return image_bgr
    height = image_bgr.shape[0]
    crop_height = max(1, int(round(height * fraction)))
    start = max(0, height - crop_height)
    return image_bgr[start:height, :].copy()


def _should_include_prev_context(
    page_fields: List[Tuple[int, Dict[str, Any]]],
    *,
    page_height: float,
    top_fraction: float,
) -> bool:
    """
    Decide if prior-page context helps, based on fields near the top of the page.
    """
    if not page_fields or page_height <= 0 or top_fraction <= 0:
        return False
    threshold = page_height * top_fraction
    for _idx, field in page_fields:
        rect = field.get("rect")
        if not isinstance(rect, list) or len(rect) != 4:
            continue
        try:
            y1 = float(rect[1])
        except (TypeError, ValueError):
            continue
        if y1 <= threshold:
            return True
    return False


def _commonforms_thresholds() -> Tuple[float, float]:
    """
    Compute high/medium confidence thresholds for CommonForms profiles.
    """
    high = COMMONFORMS_CONFIDENCE_GREEN
    medium = COMMONFORMS_CONFIDENCE_YELLOW
    if medium > high:
        medium = high
    return high, medium


def _commonforms_category(confidence: float) -> str:
    """
    Convert confidence into a green/yellow/red category label.
    """
    high, medium = _commonforms_thresholds()
    if confidence >= high:
        return "green"
    if confidence >= medium:
        return "yellow"
    return "red"


def _field_sort_key(field: Dict[str, Any]) -> Tuple[int, float, float, str]:
    """
    Stable ordering for renames: page -> y -> x -> name.
    """
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


def _min_center_distance(rects: List[List[float]], *, early_stop: float | None = None) -> float | None:
    """
    Compute the minimum distance between field centers (used to detect dense pages).

    This uses a pairwise scan with an optional early-exit threshold.
    Time complexity: O(N^2) for N rects.
    """
    if len(rects) < 2:
        return None
    centers = []
    for rect in rects:
        if len(rect) != 4:
            continue
        x1, y1, x2, y2 = [float(v) for v in rect]
        centers.append(((x1 + x2) / 2.0, (y1 + y2) / 2.0))
    if len(centers) < 2:
        return None
    min_dist = None
    for i in range(len(centers)):
        x1, y1 = centers[i]
        for j in range(i + 1, len(centers)):
            x2, y2 = centers[j]
            dist = math.hypot(x2 - x1, y2 - y1)
            if min_dist is None or dist < min_dist:
                min_dist = dist
                if early_stop is not None and min_dist <= early_stop:
                    return min_dist
    return min_dist


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
    page_idx: int,
    page_fields: List[Tuple[int, Dict[str, Any]]],
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    Build overlay field labels that are unique per page.

    We keep a mapping back to the original field index so rename output can be applied
    deterministically without mutating the baseline field list.
    """
    overlay_fields: List[Dict[str, Any]] = []
    overlay_map: Dict[str, int] = {}

    seed = _stable_seed(f"{page_idx}:{len(page_fields)}")
    tags = _generate_base32_tags(len(page_fields), seed=seed)

    for (field_index, field), display in zip(page_fields, tags):
        # Use compact, deterministic IDs so they can be drawn inside fields without overlapping
        # nearby labels (especially in dense common forms).
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


def _attach_checkbox_label_hints(
    overlay_fields: List[Dict[str, Any]],
    *,
    page_candidates: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Attach a best-effort label hint to checkbox fields.

    Checkboxes are too small to host long IDs + label context. We draw the checkbox ID
    centered on the checkbox in the overlay and attach a nearby label hint for prompt
    context (or optional debug arrows).
    """
    labels = [
        entry
        for entry in (page_candidates.get("labels") or [])
        if isinstance(entry, dict)
        and isinstance(entry.get("bbox"), list)
        and len(entry.get("bbox")) == 4
        and str(entry.get("text") or "").strip()
    ]
    if not labels:
        return overlay_fields

    for field in overlay_fields:
        if str(field.get("type") or "").lower() != "checkbox":
            continue
        rect = field.get("rect")
        if not isinstance(rect, list) or len(rect) != 4:
            continue

        cb_x1, cb_y1, cb_x2, cb_y2 = [float(v) for v in rect]
        cb_h = max(1.0, cb_y2 - cb_y1)
        cb_center_y = (cb_y1 + cb_y2) / 2.0

        # Score candidate labels by distance, alignment, and right-side bias.
        best = None
        best_score = None
        for label in labels:
            bbox = label["bbox"]
            x1, y1, x2, y2 = [float(v) for v in bbox]
            label_center_y = (y1 + y2) / 2.0

            overlap = min(cb_y2, y2) - max(cb_y1, y1)
            overlap_ratio = max(0.0, overlap) / cb_h
            # Prefer labels to the right of a checkbox, near its vertical centerline.
            right_bias = 0.0 if x1 >= (cb_x2 - cb_h * 0.5) else 40.0
            alignment_penalty = abs(label_center_y - cb_center_y) / max(1.0, cb_h) * 8.0
            overlap_bonus = -12.0 if overlap_ratio >= 0.25 else 0.0
            dist = _rect_distance([cb_x1, cb_y1, cb_x2, cb_y2], [x1, y1, x2, y2])
            score = dist + right_bias + alignment_penalty + overlap_bonus
            if best_score is None or score < best_score:
                best_score = score
                best = label

        if best:
            hint_text = str(best.get("text") or "").strip()
            hint_text = re.sub(r"[\r\n\t]+", " ", hint_text).strip().replace('"', "'")
            if len(hint_text) > 48:
                hint_text = hint_text[:47] + "…"
            field["labelHintText"] = hint_text
            field["labelHintBbox"] = best.get("bbox")

    return overlay_fields


def _build_prompt(
    page_idx: int,
    overlay_fields: List[Dict[str, Any]],
    *,
    page_candidates: Dict[str, Any],
    confidence_profile: str = "sandbox",
    database_fields: List[str] | None = None,
) -> Tuple[str, str]:
    """
    Build the system/user prompt text for the rename pass.
    """
    system_message = (
        "You are a PDF form renaming assistant. You will receive:\n"
        "1) The original PDF page image (no overlays).\n"
        "2) The same page image with an overlay of field IDs.\n"
        "Each detected field is drawn as a box and tagged with a short 3-character ID "
        "(base32, e.g., k7m):\n"
        "- Text/date/signature fields: the ID is printed centered *inside* the field box.\n"
        "- Checkbox fields: the ID is centered on the checkbox square (no callout box).\n"
        "- If present, a third image shows the bottom of the previous page (no overlays). "
        "It is context only—do NOT label or rename fields from that image.\n"
        "- Use the previous-page image only to recognize labels that belong to the prior page.\n"
        "Use that ID as originalFieldName. Do NOT invent IDs.\n"
        "Candidates with isItAfieldConfidence below 0.30 are treated as not-a-field, but you must "
        "still output a line for them and provide a best-guess standardized suggestedRename. "
        "Do NOT repeat the originalFieldName as suggestedRename.\n\n"
        "Output format (one line per field, no extra text):\n"
        "|| originalFieldName | suggestedRename | renameConfidence | isItAfieldConfidence\n"
        "Example format only (do not reuse names):\n"
        "|| k7m | patient_name | 0.92 | 0.98\n\n"
        "Rules:\n"
        "- Output exactly one line for every originalFieldName provided, in the same order.\n"
        "- Only use originalFieldName values from the provided list.\n"
        "- IDs are random (not sequential); do not assume ordering beyond the provided list.\n"
        "- Use snake_case for suggestedRename.\n"
        "- Never output the overlay ID (originalFieldName) as suggestedRename.\n"
        "- Checkbox names should start with 'i_'.\n"
        "- Confidence values must be between 0 and 1 (not percent).\n"
        "- If the item is not a real field, set isItAfieldConfidence < 0.30.\n"
        "- If isItAfieldConfidence < 0.30, set renameConfidence to 0 but still provide a best-guess suggestedRename.\n\n"
        "Swap avoidance:\n"
        "- Do not swap IDs between neighboring fields. The ID inside each box is authoritative.\n"
        "- If a tight cluster makes the label ambiguous, still provide your best-guess suggestedRename "
        "and set renameConfidence to 0.0.\n"
        "- Do not shift label associations downward because of labels from the previous page.\n\n"
        "Row alignment (CRITICAL, highest priority):\n"
        "- For text fields, the correct label is directly to the left on the same horizontal line.\n"
        "- Never assign a label below/above a field if a same-row label exists for the neighboring field.\n"
        "- Before final output, perform a global shift check: if most fields look shifted by one "
        "row/column (up/down/left/right), correct the shift so each field aligns to its same-row label.\n"
        "- If the topmost field has no same-row label and the next label aligns with the next field, "
        "mark the topmost field as not-a-field (isItAfieldConfidence < 0.30) instead of shifting all names.\n"
        "- If any row is ambiguous, still provide your best-guess suggestedRename and set renameConfidence = 0.0.\n"
        "- Never cascade a one-row mistake across the page; alignment beats ordering every time.\n"
        "- In extreme misalignment cases, you may lower isItAfieldConfidence to medium/low even if the "
        "detector was confident; reserve < 0.30 for clear non-fields.\n\n"
        "Missing-field rule:\n"
        "- If matching labels would require shifting every field down/up by one to make room for "
        "a suspected missing field, treat that suspected field as not-a-field "
        "(isItAfieldConfidence < 0.30) and keep the original per-box alignments. "
        "Still output a best-guess suggestedRename with renameConfidence = 0.\n\n"
        "Common field naming:\n"
        "- Address line 1 (street/mailing address/line 1): use street_address.\n"
        "- Address line 2 (apt/unit/suite/line 2): use address_line_2.\n"
        "- City: city. State/province: state. Zip/postal: postal_code or zip.\n"
        "- Group prefixes for non-checkbox fields:\n"
        "  - Patient demographics/contact/address: prefix with patient_.\n"
        "  - Employer sections: prefix with employer_.\n"
        "  - Emergency contact: emergency_contact_. Guardian/guarantor/responsible party: guardian_/guarantor_/responsible_party_.\n"
        "  - Spouse/partner: spouse_ or spouse_partner_. Providers/facility: attending_provider_/ordering_provider_/referring_provider_/facility_.\n"
        "- Normalize any synonym groups to these canonical prefixes:\n"
        "  - Use patient_ (not client_, pt_, member_, subscriber_).\n"
        "  - Use employer_ (not workplace_, job_).\n"
        "  - Use emergency_contact_ (not emergency_, contact_).\n"
        "- Checkbox names must start with i_.\n"
        "- Checkbox options must use i_<groupKey>_<optionKey> (e.g., i_marital_status_single).\n"
        "- groupKey is the shared base for a question (marital_status, sex, patient_issues).\n"
        "- optionKey is the option label text (single, married, female, anemia).\n"
        "- If option_hint is provided in the field list, use it as the option label.\n"
        "- Preserve logical connectors in optionKey (e.g., loose_teeth_or_broken_fillings, bleeding_gums_and_swelling).\n"
        "- Yes/No pairs should be named i_<groupKey>_yes and i_<groupKey>_no.\n"
        "- Single boolean checkboxes with no explicit options should be named i_<groupKey>.\n\n"
        "Search & Fill schema (CRITICAL):\n"
        "- Search & Fill parses checkbox groups from i_<groupKey>_<optionKey> names.\n"
        "- groupKey should be a stable, database-like base (dental_problem, medical_history, marital_status).\n"
        "- optionKey should be a short, normalized suffix that matches the option label meaning.\n"
        "- If database fields are provided, match optionKey to the DB suffix after groupKey_ whenever possible.\n"
        "- For non-checkbox fields, keep the group prefix in the name (patient_, employer_, emergency_contact_, responsible_party_).\n"
        "- Normalize group wording conceptually (e.g., client vs patient, workplace vs employer).\n"
        "- Prefer a repeatable <group>_<field> pattern when naming (e.g., patient_name, employer_address).\n"
        "- If database fields are provided, prefer exact database field names for suggestedRename.\n"
        "- Avoid overly generic names; choose the most specific label available.\n\n"
        "Database alignment (if database fields are provided):\n"
        "- Prefer suggestedRename values that match database field names when the label meaning is the same.\n"
        "- Do not force a database field name if it conflicts with the visible label.\n\n"
        "- If a database field exists that clearly matches the label, use it exactly (avoid inventing new synonyms).\n"
        "- For repeated lines or list entries, use a stable base name with numeric suffixes that matches the database list when possible.\n\n"
        "Confidence tiers:\n"
        "- Green (>= 0.80) = confident.\n"
        "- Yellow (0.65–0.79) = double-check alignment and labels.\n"
        "- Red (< 0.65) = uncertain; avoid renaming unless the label is obvious.\n"
        "- If CommonForms thresholds are provided below, use those values instead.\n\n"
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
    if confidence_profile == "commonforms":
        high, medium = _commonforms_thresholds()
        system_message += (
            "\n\nCommonForms confidence guidance:\n"
            "- You may adjust isItAfieldConfidence to reflect detection quality; it replaces field confidence.\n"
            f"- Green >= {high:.2f}, yellow between {medium:.2f} and {high:.2f}, red < {medium:.2f}.\n"
            "- If isItAfieldConfidence < 0.30, set renameConfidence to 0."
        )

    label_bboxes = [
        lb.get("bbox")
        for lb in (page_candidates.get("labels") or [])
        if isinstance(lb.get("bbox"), list) and len(lb.get("bbox")) == 4
    ]
    page_width = float(page_candidates.get("pageWidth") or 0.0)
    page_height = float(page_candidates.get("pageHeight") or 0.0)

    # Build per-field metadata so the model can reason about label proximity and sizing.
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
        option_hint = ""
        if str(field.get("type") or "").lower() == "checkbox":
            hint = str(field.get("labelHintText") or "").strip()
            if hint:
                option_hint = f', option_hint="{hint}"'
        field_lines.append(
            f"{field.get('name')}\t(type={field.get('type')}, label_dist={label_dist_str}, "
            f"overlaps_label={overlaps_str}, w_ratio={width_ratio:.2f}, h_ratio={height_ratio:.2f}{option_hint})"
        )
    field_block = "\n".join(field_lines)

    user_message = (
        f"Page {page_idx} field IDs (originalFieldName list). Return one output line per entry in the same order.\n"
        "BEGIN_FIELD_LIST\n"
        f"{field_block}\n"
        "END_FIELD_LIST\n"
    )
    if database_fields:
        unique_fields = [str(field).strip() for field in database_fields if str(field).strip()]
        if unique_fields:
            db_block = "\n".join(f"- {field}" for field in unique_fields[:400])
            user_message = (
                f"{user_message}\nDATABASE_FIELDS (context only; do not invent fields):\n{db_block}\n"
                "If a database field clearly matches a label, use that exact name.\n"
            )
            system_message += (
                "\n\nCheckbox rules output (for database fields):\n"
                "- After ALL rename lines, output a JSON array of checkbox rules.\n"
                f"- Use the exact block:\n{CHECKBOX_RULES_START}\n[{{...}}]\n{CHECKBOX_RULES_END}\n"
                "- Each rule must include databaseField, groupKey, operation.\n"
                "- operation must be one of: yes_no, enum, list, presence.\n"
                "- Optional keys: trueOption, falseOption, valueMap, confidence, reasoning.\n"
                "- groupKey must match the checkbox group (without the i_ prefix).\n"
                "- Only include rules when a schema field clearly represents the checkbox group.\n"
                "- If no rules apply, output an empty array.\n"
            )
            user_message = (
                f"{user_message}\nAfter the rename lines, output the checkbox rules JSON block."
            )
    user_message = f"{user_message}\nReturn the rename output lines now."
    return system_message, user_message


def _parse_openai_lines(
    response_text: str,
    *,
    overlay_map: Dict[str, int],
) -> List[Dict[str, Any]]:
    """
    Parse the line-based OpenAI response into rename entries.
    """
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


def _parse_checkbox_rules(response_text: str) -> List[Dict[str, Any]]:
    """
    Extract checkbox rule JSON blocks from an OpenAI response.
    """
    if not response_text:
        return []
    rules: List[Dict[str, Any]] = []
    pattern = re.compile(
        rf"{re.escape(CHECKBOX_RULES_START)}\s*(\[[\s\S]*?\])\s*{re.escape(CHECKBOX_RULES_END)}",
        re.IGNORECASE,
    )
    for match in pattern.finditer(response_text):
        payload = (match.group(1) or "").strip()
        if not payload:
            continue
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            logger.debug("Checkbox rules JSON ignored (parse failed).")
            continue
        if isinstance(parsed, list):
            rules.extend([rule for rule in parsed if isinstance(rule, dict)])
    return rules


def _normalize_checkbox_rule(
    rule: Dict[str, Any],
    *,
    allowed_schema_map: Dict[str, str],
    allowed_group_keys: set[str],
) -> Dict[str, Any] | None:
    """
    Normalize and validate a checkbox rule against allowed schema fields and group keys.
    """
    database_field_raw = str(rule.get("databaseField") or "").strip()
    if not database_field_raw:
        return None
    schema_key = _to_snake_case(database_field_raw)
    canonical_schema = allowed_schema_map.get(schema_key)
    if not canonical_schema:
        return None

    group_key = _normalize_checkbox_component(str(rule.get("groupKey") or ""))
    if not group_key or group_key not in allowed_group_keys:
        return None

    operation = str(rule.get("operation") or "").strip().lower()
    if operation not in {"yes_no", "enum", "list", "presence"}:
        return None

    normalized: Dict[str, Any] = {
        "databaseField": canonical_schema,
        "groupKey": group_key,
        "operation": operation,
    }

    if operation == "yes_no":
        true_option = rule.get("trueOption")
        false_option = rule.get("falseOption")
        if true_option:
            normalized["trueOption"] = _normalize_checkbox_component(str(true_option))
        if false_option:
            normalized["falseOption"] = _normalize_checkbox_component(str(false_option))

    value_map = rule.get("valueMap")
    if isinstance(value_map, dict):
        cleaned_map = {}
        for key, value in value_map.items():
            if key is None or value is None:
                continue
            cleaned_map[str(key)] = str(value)
        if cleaned_map:
            normalized["valueMap"] = cleaned_map

    confidence = rule.get("confidence")
    if confidence is not None:
        normalized["confidence"] = _parse_confidence(str(confidence))

    reasoning = rule.get("reasoning")
    if reasoning:
        normalized["reasoning"] = str(reasoning)

    return normalized


def _dedupe_field_names(fields: List[Dict[str, Any]]) -> None:
    """
    Apply deterministic suffixes so final field names are unique.
    """
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
    confidence_profile: str = "sandbox",
    adjust_field_confidence: bool = False,
    database_fields: List[str] | None = None,
    openai_max_retries: int | None = None,
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
    overlay_quality_default = 92
    overlay_max_dim_default = 6000
    overlay_format_default = "png"
    label_max_dist_default: float | None = None

    if confidence_profile == "commonforms":
        # CommonForms pages tend to be dense with many nearby widgets. Use higher-resolution,
        # less-lossy overlays so field IDs remain readable and alignment errors are reduced.
        overlay_quality_default = 96
        overlay_max_dim_default = 7000
        overlay_format_default = "png"
        label_max_dist_default = 140.0

    overlay_quality = int(os.getenv("SANDBOX_RENAME_OVERLAY_QUALITY", str(overlay_quality_default)))
    overlay_max_dim = int(os.getenv("SANDBOX_RENAME_OVERLAY_MAX_DIM", str(overlay_max_dim_default)))
    overlay_format = (os.getenv("SANDBOX_RENAME_OVERLAY_FORMAT", overlay_format_default) or "").strip().lower()
    if not overlay_format:
        overlay_format = overlay_format_default
    dense_field_count = int(os.getenv("SANDBOX_RENAME_DENSE_FIELD_COUNT", "20"))
    dense_min_center_dist = float(os.getenv("SANDBOX_RENAME_DENSE_MIN_CENTER_DIST", "45"))
    dense_max_dim = int(os.getenv("SANDBOX_RENAME_DENSE_MAX_DIM", "7000"))
    dense_format = (os.getenv("SANDBOX_RENAME_DENSE_FORMAT", "png") or "").strip().lower()
    prev_page_fraction = float(os.getenv("SANDBOX_RENAME_PREV_PAGE_FRACTION", "0.2"))
    prev_page_top_fraction = float(os.getenv("SANDBOX_RENAME_PREV_PAGE_TOP_FRACTION", "0.15"))

    raw_label_max = (os.getenv("SANDBOX_RENAME_LABEL_MAX_DIST") or "").strip()
    label_max_dist_pts: float | None
    if raw_label_max:
        try:
            label_max_dist_pts = float(raw_label_max)
        except ValueError:
            label_max_dist_pts = label_max_dist_default
    else:
        label_max_dist_pts = label_max_dist_default
    max_output_tokens = int(os.getenv("SANDBOX_RENAME_MAX_OUTPUT_TOKENS", "4096"))
    max_workers = resolve_workers("openai", default=6, use_global=False)
    min_field_conf = float(os.getenv("SANDBOX_RENAME_MIN_FIELD_CONF", "0.3"))

    # Group fields and candidates by page to keep overlays/prompt context local.
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
    label_hints_by_index: Dict[int, str] = {}

    rendered_by_page = {int(p.get("page_index") or 0): p for p in rendered_pages}

    for page in rendered_pages:
        page_idx = int(page.get("page_index") or 1)
        page_fields = fields_by_page.get(page_idx, [])
        if not page_fields:
            continue
        page_fields_sorted = sorted(page_fields, key=lambda item: _field_sort_key(item[1]))
        overlay_fields, overlay_map = _build_overlay_fields(page_idx, page_fields_sorted)
        page_candidates = candidates_by_page.get(page_idx)
        if page_candidates is None:
            continue
        overlay_fields = _attach_checkbox_label_hints(overlay_fields, page_candidates=page_candidates)
        for overlay_field in overlay_fields:
            if str(overlay_field.get("type") or "").lower() != "checkbox":
                continue
            hint_text = str(overlay_field.get("labelHintText") or "").strip()
            if not hint_text:
                continue
            field_index = overlay_map.get(overlay_field.get("name"))
            if field_index is None:
                continue
            label_hints_by_index[field_index] = hint_text

        rects = [
            rect
            for _field_idx, field in page_fields_sorted
            if isinstance((rect := field.get("rect")), list) and len(rect) == 4
        ]
        min_center_dist = _min_center_distance(rects, early_stop=dense_min_center_dist)
        # Dense pages benefit from higher-resolution overlays to preserve ID readability.
        dense_page = len(page_fields_sorted) >= dense_field_count or (
            min_center_dist is not None and min_center_dist <= dense_min_center_dist
        )
        page_overlay_max_dim = overlay_max_dim
        page_overlay_format = overlay_format
        if dense_page:
            page_overlay_max_dim = max(overlay_max_dim, dense_max_dim)
            if dense_format:
                page_overlay_format = dense_format

        overlay_path = output_dir / f"page_{page_idx}.png"
        overlay = draw_overlay(
            page.get("image"),
            page_candidates,
            overlay_fields,
            overlay_path,
            draw_candidates=False,
            field_labels_inside=True,
            label_max_dist_pts=label_max_dist_pts,
            highlight_checkbox_labels=False,
            checkbox_tag_scale=1.6,
            return_image=True,
        )
        if overlay is None:
            raise RuntimeError(f"Failed to render overlay image: {overlay_path}")

        clean_page_for_model = _downscale_for_model(page.get("image"), max_dim=page_overlay_max_dim)
        clean_page_url = image_bgr_to_data_url(
            clean_page_for_model,
            format=page_overlay_format,
            quality=overlay_quality,
        )
        overlay_for_model = _downscale_for_model(overlay, max_dim=page_overlay_max_dim)
        overlay_url = image_bgr_to_data_url(
            overlay_for_model,
            format=page_overlay_format,
            quality=overlay_quality,
        )
        prev_page_url = None
        if page_idx > 1 and prev_page_fraction > 0:
            prev_page = rendered_by_page.get(page_idx - 1)
            if prev_page:
                page_height = float(page_candidates.get("pageHeight") or 0.0)
                # Only include previous-page context when fields sit near the top edge.
                include_prev = _should_include_prev_context(
                    page_fields_sorted,
                    page_height=page_height,
                    top_fraction=prev_page_top_fraction,
                )
                if include_prev:
                    prev_crop = _crop_prev_page_context(
                        prev_page.get("image"),
                        fraction=prev_page_fraction,
                    )
                    prev_crop = _downscale_for_model(prev_crop, max_dim=page_overlay_max_dim)
                    prev_page_url = image_bgr_to_data_url(
                        prev_crop,
                        format=page_overlay_format,
                        quality=overlay_quality,
                    )
        system_message, user_message = _build_prompt(
            page_idx,
            overlay_fields,
            page_candidates=page_candidates,
            confidence_profile=confidence_profile,
            database_fields=database_fields,
        )

        page_contexts[page_idx] = {
            "overlay_map": overlay_map,
            "system_message": system_message,
            "user_message": user_message,
            "clean_page_url": clean_page_url,
            "overlay_url": overlay_url,
            "prev_page_url": prev_page_url,
        }
        tasks.append({"page_idx": page_idx})

    def _run_page(task: Dict[str, Any]) -> Dict[str, Any]:
        page_idx = task["page_idx"]
        context = page_contexts[page_idx]
        user_content = [
            {"type": "input_text", "text": context["user_message"]},
            {"type": "input_image", "image_url": context["clean_page_url"], "detail": "high"},
            {"type": "input_image", "image_url": context["overlay_url"], "detail": "high"},
        ]
        if context.get("prev_page_url"):
            user_content.append(
                {"type": "input_image", "image_url": context["prev_page_url"], "detail": "low"}
            )

        # Responses API expects structured content blocks for text and images.
        messages = [
            {"role": "system", "content": [{"type": "input_text", "text": context["system_message"]}]},
            {
                "role": "user",
                "content": user_content,
            },
        ]
        client = create_openai_client(max_retries_override=openai_max_retries)
        response = responses_create_with_temperature_fallback(
            client,
            model=model,
            input=messages,
            temperature=None,
            max_output_tokens=max_output_tokens,
            text={"format": {"type": "text"}},
        )
        response_text = extract_response_text(response)
        response_usage = extract_response_usage(response)
        if LOG_OPENAI_RESPONSE:
            logger.info(
                "OpenAI rename response page %s (model %s):\n%s",
                page_idx,
                model,
                response_text,
            )
        entries = _parse_openai_lines(response_text, overlay_map=context["overlay_map"])
        checkbox_rules = _parse_checkbox_rules(response_text)
        if len(entries) < len(context["overlay_map"]):
            logger.warning(
                "OpenAI rename page %s returned %s/%s lines; missing fields will keep defaults.",
                page_idx,
                len(entries),
                len(context["overlay_map"]),
            )
        return {
            "page_idx": page_idx,
            "entries": entries,
            "checkbox_rules": checkbox_rules,
            "usage": response_usage,
        }

    if tasks:
        results = run_threaded_map(
            tasks,
            _run_page,
            max_workers=max_workers,
            label="rename_openai",
        )
    else:
        results = []

    raw_checkbox_rules: List[Dict[str, Any]] = []
    usage_by_page: List[Dict[str, Any]] = []
    for result in results:
        for rule in result.get("checkbox_rules") or []:
            if isinstance(rule, dict):
                raw_checkbox_rules.append(rule)
        usage = result.get("usage")
        if isinstance(usage, dict):
            usage_by_page.append(
                {
                    "page": int(result.get("page_idx") or 0),
                    "api": "responses",
                    "model": model,
                    **usage,
                }
            )

    # Keep the highest-confidence entry per field index (multiple pages can reference a field).
    entries_by_index: Dict[int, Dict[str, Any]] = {}
    for result in results:
        for entry in result["entries"]:
            idx = entry["fieldIndex"]
            existing = entries_by_index.get(idx)
            if existing is None or entry["isItAfieldConfidence"] > existing["isItAfieldConfidence"]:
                entries_by_index[idx] = entry

    renamed_fields: List[Dict[str, Any]] = []
    dropped: List[str] = []

    for idx, field in enumerate(fields):
        entry = entries_by_index.get(idx)
        baseline_conf = float(field.get("confidence") or 0.6)
        rename_conf = float(entry.get("renameConfidence") or 0.0) if entry else 0.0
        field_conf = float(entry.get("isItAfieldConfidence") or baseline_conf) if entry else baseline_conf
        original_name = str(field.get("name") or "")
        suggested = str(entry.get("suggestedRename") or original_name) if entry else original_name

        is_not_field = field_conf < min_field_conf
        if is_not_field:
            dropped.append(original_name or f"field_{idx}")
            rename_conf = 0.0

        updated = dict(field)
        updated["originalName"] = original_name
        if entry:
            updated["overlayId"] = entry.get("originalFieldName")
        updated["renameConfidence"] = rename_conf
        updated["isItAfieldConfidence"] = field_conf
        if adjust_field_confidence:
            updated["confidence"] = field_conf
            if str(updated.get("source") or "").lower() == "commonforms":
                updated["category"] = _commonforms_category(field_conf)
        updated["name"] = _normalize_name(suggested, str(updated.get("type") or "text").lower())
        renamed_fields.append(updated)

    _dedupe_field_names(renamed_fields)
    checkbox_prefix_counts: Dict[str, int] = {}
    checkbox_bases: Dict[int, Tuple[str, List[str], str | None]] = {}
    for idx, field in enumerate(renamed_fields):
        if str(field.get("type") or "").lower() != "checkbox":
            continue
        base = _to_snake_case(str(field.get("name") or ""))
        if base.startswith("i_"):
            base = base[2:]
        base = re.sub(r"_\d+$", "", base)
        if not base:
            continue
        tokens = [token for token in base.split("_") if token]
        option_label = label_hints_by_index.get(idx)
        checkbox_bases[idx] = (base, tokens, option_label)
        if len(tokens) < 2:
            continue
        for i in range(1, len(tokens)):
            prefix = "_".join(tokens[:i])
            checkbox_prefix_counts[prefix] = checkbox_prefix_counts.get(prefix, 0) + 1

    for idx, field in enumerate(renamed_fields):
        if str(field.get("type") or "").lower() != "checkbox":
            continue
        base, tokens, option_label = checkbox_bases.get(idx, ("", [], None))
        if not base:
            continue
        option_from_label = _normalize_checkbox_component(option_label or "") if option_label else ""
        group_key = ""
        option_key = ""
        if option_from_label and base.endswith(f"_{option_from_label}"):
            group_key = base[: -(len(option_from_label) + 1)]
            option_key = option_from_label
        if not group_key:
            for i in range(len(tokens) - 1, 0, -1):
                prefix = "_".join(tokens[:i])
                if checkbox_prefix_counts.get(prefix, 0) >= 2:
                    group_key = prefix
                    option_key = "_".join(tokens[i:]) or "yes"
                    break
        if not group_key:
            last = tokens[-1] if tokens else ""
            if last in {"yes", "no", "true", "false", "y", "n", "m", "f"} and len(tokens) >= 2:
                group_key = "_".join(tokens[:-1])
                option_key = last
            else:
                group_key = base
                option_key = "yes"
        field["groupKey"] = group_key or None
        field["optionKey"] = option_key or None
        if option_label:
            field["optionLabel"] = option_label
        if group_key:
            field["groupLabel"] = _humanize_group_label(group_key) or None

    allowed_schema_map: Dict[str, str] = {}
    if database_fields:
        for field_name in database_fields:
            normalized = _to_snake_case(str(field_name or "").strip())
            if normalized and normalized not in allowed_schema_map:
                allowed_schema_map[normalized] = str(field_name).strip()

    allowed_group_keys = {
        _normalize_checkbox_component(str(field.get("groupKey") or ""))
        for field in renamed_fields
        if field.get("groupKey")
    }

    for field in renamed_fields:
        field_type = str(field.get("type") or "text").lower()
        normalized_name = _normalize_name(str(field.get("name") or ""), field_type)
        if normalized_name and normalized_name in allowed_schema_map:
            field["mappingConfidence"] = float(field.get("renameConfidence") or 0.0)
        else:
            field["mappingConfidence"] = None

    checkbox_rules: List[Dict[str, Any]] = []
    if raw_checkbox_rules and allowed_schema_map and allowed_group_keys:
        deduped: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for raw_rule in raw_checkbox_rules:
            normalized = _normalize_checkbox_rule(
                raw_rule,
                allowed_schema_map=allowed_schema_map,
                allowed_group_keys=allowed_group_keys,
            )
            if not normalized:
                continue
            key = (
                normalized["databaseField"],
                normalized["groupKey"],
                normalized["operation"],
            )
            existing = deduped.get(key)
            if not existing:
                deduped[key] = normalized
                continue
            existing_conf = existing.get("confidence")
            next_conf = normalized.get("confidence")
            if isinstance(next_conf, float) and (
                not isinstance(existing_conf, float) or next_conf > existing_conf
            ):
                deduped[key] = normalized
        checkbox_rules = list(deduped.values())

    renames_report: List[Dict[str, Any]] = []
    for field in renamed_fields:
        renames_report.append(
            {
                "page": int(field.get("page") or 1),
                "candidateId": field.get("candidateId"),
                "originalFieldName": field.get("originalName") or "",
                "overlayId": field.get("overlayId"),
                "suggestedRename": field.get("name") or "",
                "renameConfidence": float(field.get("renameConfidence") or 0.0),
                "isItAfieldConfidence": float(field.get("isItAfieldConfidence") or 0.0),
                "mappingConfidence": field.get("mappingConfidence"),
            }
        )

    usage_summary = build_openai_usage_summary(usage_by_page, model=model)
    return (
        {
            "generatedAt": datetime.now(tz=timezone.utc).isoformat(),
            "model": model,
            "renames": renames_report,
            "dropped": dropped,
            "checkboxRules": checkbox_rules,
            "usage": usage_summary,
            "usageByPage": usage_by_page,
        },
        renamed_fields,
    )
