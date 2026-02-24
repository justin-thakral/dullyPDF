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
from .checkbox_label_hints import normalize_checkbox_hint_text, pick_best_checkbox_label
from .concurrency import resolve_workers, run_threaded_map
from .config import LOG_OPENAI_RESPONSE, get_logger
from .field_overlay import draw_overlay
from .openai_utils import (
    extract_response_text,
    extract_response_usage,
    responses_create_with_temperature_fallback,
)
from .payload_budgeter import (
    budget_page_payload as _budget_page_payload_impl,
    estimate_data_url_bytes as _estimate_data_url_bytes_impl,
    estimate_page_payload as _estimate_page_payload_impl,
    normalize_image_detail as _normalize_image_detail_impl,
    normalize_image_format as _normalize_image_format_impl,
)
from .prompt_builder import (
    build_prompt as _build_prompt_impl,
    compact_prompt_noise as _compact_prompt_noise_impl,
    label_context as _label_context_impl,
    prompt_hygiene_enabled as _prompt_hygiene_enabled_impl,
    select_database_prompt_fields as _select_database_prompt_fields_impl,
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


def _normalize_image_format(value: str, *, default: str) -> str:
    return _normalize_image_format_impl(value, default=default)


def _normalize_image_detail(value: str, *, default: str) -> str:
    return _normalize_image_detail_impl(value, default=default)


def _encode_model_image(
    image_bgr: "cv2.Mat",
    *,
    max_dim: int,
    format: str,
    quality: int,
) -> str:
    model_image = _downscale_for_model(image_bgr, max_dim=max_dim)
    return image_bgr_to_data_url(model_image, format=format, quality=quality)


def _estimate_data_url_bytes(data_url: str | None) -> int:
    return _estimate_data_url_bytes_impl(data_url)


def _estimate_page_payload(
    *,
    system_message: str,
    user_message: str,
    clean_page_url: str | None,
    overlay_url: str | None,
    prev_page_url: str | None,
) -> Dict[str, int]:
    return _estimate_page_payload_impl(
        system_message=system_message,
        user_message=user_message,
        clean_page_url=clean_page_url,
        overlay_url=overlay_url,
        prev_page_url=prev_page_url,
    )


def _prompt_hygiene_enabled() -> bool:
    return _prompt_hygiene_enabled_impl()


def _compact_prompt_noise(text: str) -> str:
    return _compact_prompt_noise_impl(text)


def _select_database_prompt_fields(
    database_fields: List[str] | None,
    *,
    overlay_fields: List[Dict[str, Any]],
    page_candidates: Dict[str, Any] | None = None,
    full_threshold: int,
    shortlist_limit: int,
) -> Tuple[List[str], int, bool]:
    return _select_database_prompt_fields_impl(
        database_fields,
        overlay_fields=overlay_fields,
        page_candidates=page_candidates,
        full_threshold=full_threshold,
        shortlist_limit=shortlist_limit,
    )


def _field_sort_key(field: Dict[str, Any]) -> Tuple[int, float, float, str]:
    """
    Stable ordering for renames: page -> y -> x -> name.
    """
    rect = field.get("rect") or [0, 0, 0, 0]
    page = int(field.get("page") or 1)
    y1 = float(rect[1]) if len(rect) == 4 else 0.0
    x1 = float(rect[0]) if len(rect) == 4 else 0.0
    return (page, y1, x1, str(field.get("name") or ""))


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
    return _label_context_impl(rect, label_bboxes)


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

        best = pick_best_checkbox_label([float(v) for v in rect], labels)
        if best:
            hint_text = normalize_checkbox_hint_text(str(best.get("text") or ""), max_chars=48)
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
    database_total_fields: int | None = None,
    database_fields_truncated: bool = False,
) -> Tuple[str, str]:
    return _build_prompt_impl(
        page_idx,
        overlay_fields,
        page_candidates=page_candidates,
        confidence_profile=confidence_profile,
        database_fields=database_fields,
        database_total_fields=database_total_fields,
        database_fields_truncated=database_fields_truncated,
        checkbox_rules_start=CHECKBOX_RULES_START,
        checkbox_rules_end=CHECKBOX_RULES_END,
        commonforms_thresholds=_commonforms_thresholds(),
    )


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
    # Step 1: Fast exit when there is nothing to rename.
    if not fields:
        return {
            "generatedAt": datetime.now(tz=timezone.utc).isoformat(),
            "model": model,
            "renames": [],
            "dropped": [],
        }, []

    # Step 2: Ensure OpenAI credentials are present before doing any heavy work.
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY not set; cannot run OpenAI rename.")

    # Step 3: Resolve run-time tuning knobs for image quality, density handling, and thresholds.
    output_dir.mkdir(parents=True, exist_ok=True)
    overlay_quality_default = 92
    overlay_max_dim_default = 6000
    overlay_format_default = "png"
    overlay_detail_default = "high"
    clean_quality_default = 82
    clean_max_dim_default = 3000
    clean_format_default = "jpg"
    clean_detail_default = "low"
    label_max_dist_default: float | None = None

    if confidence_profile == "commonforms":
        # CommonForms pages tend to be dense with many nearby widgets. Use higher-resolution,
        # less-lossy overlays so field IDs remain readable and alignment errors are reduced.
        overlay_quality_default = 96
        overlay_max_dim_default = 7000
        overlay_format_default = "png"
        clean_quality_default = 84
        clean_max_dim_default = 3200
        label_max_dist_default = 140.0

    overlay_quality = int(os.getenv("SANDBOX_RENAME_OVERLAY_QUALITY", str(overlay_quality_default)))
    overlay_max_dim = int(os.getenv("SANDBOX_RENAME_OVERLAY_MAX_DIM", str(overlay_max_dim_default)))
    overlay_format = _normalize_image_format(
        os.getenv("SANDBOX_RENAME_OVERLAY_FORMAT", overlay_format_default),
        default=overlay_format_default,
    )
    overlay_detail = _normalize_image_detail(
        os.getenv("SANDBOX_RENAME_OVERLAY_DETAIL", overlay_detail_default),
        default=overlay_detail_default,
    )
    clean_quality = int(os.getenv("SANDBOX_RENAME_CLEAN_QUALITY", str(clean_quality_default)))
    clean_max_dim = int(os.getenv("SANDBOX_RENAME_CLEAN_MAX_DIM", str(clean_max_dim_default)))
    clean_format = _normalize_image_format(
        os.getenv("SANDBOX_RENAME_CLEAN_FORMAT", clean_format_default),
        default=clean_format_default,
    )
    clean_detail = _normalize_image_detail(
        os.getenv("SANDBOX_RENAME_CLEAN_DETAIL", clean_detail_default),
        default=clean_detail_default,
    )
    prev_detail = _normalize_image_detail(
        os.getenv("SANDBOX_RENAME_PREV_PAGE_DETAIL", "low"),
        default="low",
    )
    dense_field_count = int(os.getenv("SANDBOX_RENAME_DENSE_FIELD_COUNT", "20"))
    dense_min_center_dist = float(os.getenv("SANDBOX_RENAME_DENSE_MIN_CENTER_DIST", "45"))
    dense_max_dim = int(os.getenv("SANDBOX_RENAME_DENSE_MAX_DIM", "7000"))
    dense_format = _normalize_image_format(
        os.getenv("SANDBOX_RENAME_DENSE_FORMAT", overlay_format),
        default=overlay_format,
    )
    overlay_min_dim = int(os.getenv("SANDBOX_RENAME_OVERLAY_MIN_DIM", "3600"))
    prev_page_fraction = float(os.getenv("SANDBOX_RENAME_PREV_PAGE_FRACTION", "0.2"))
    prev_page_top_fraction = float(os.getenv("SANDBOX_RENAME_PREV_PAGE_TOP_FRACTION", "0.15"))
    db_prompt_full_threshold = int(os.getenv("SANDBOX_RENAME_DB_PROMPT_FULL_THRESHOLD", "1000"))
    db_prompt_shortlist_limit = int(os.getenv("SANDBOX_RENAME_DB_PROMPT_SHORTLIST_LIMIT", "450"))
    db_prompt_budget_shortlist_limit = int(
        os.getenv("SANDBOX_RENAME_DB_PROMPT_BUDGET_SHORTLIST_LIMIT", "250")
    )
    page_prompt_char_budget = int(os.getenv("SANDBOX_RENAME_PAGE_PROMPT_CHAR_BUDGET", "18000"))
    page_image_byte_budget = int(os.getenv("SANDBOX_RENAME_PAGE_IMAGE_BYTE_BUDGET", "5200000"))
    budget_clean_max_dim = int(os.getenv("SANDBOX_RENAME_BUDGET_CLEAN_MAX_DIM", "2400"))
    budget_clean_quality = int(os.getenv("SANDBOX_RENAME_BUDGET_CLEAN_QUALITY", "76"))
    budget_clean_format = _normalize_image_format(
        os.getenv("SANDBOX_RENAME_BUDGET_CLEAN_FORMAT", "jpg"),
        default="jpg",
    )

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

    # Step 4: Index fields/candidates by page so each OpenAI call has localized context.
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

    # Step 5: Build per-page OpenAI payload inputs (overlay IDs, prompt text, and page images).
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
        # Attach optional checkbox label hints so naming can use visible option text.
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
        page_overlay_quality = overlay_quality
        if dense_page:
            page_overlay_max_dim = max(overlay_max_dim, dense_max_dim)
            page_overlay_format = dense_format

        # Render the visual overlay (field IDs drawn on top of the page).
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

        page_db_fields: List[str] | None = None
        page_db_total = 0
        page_db_truncated = False
        if database_fields:
            page_db_fields, page_db_total, page_db_truncated = _select_database_prompt_fields(
                database_fields,
                overlay_fields=overlay_fields,
                page_candidates=page_candidates,
                full_threshold=db_prompt_full_threshold,
                shortlist_limit=db_prompt_shortlist_limit,
            )

        # Build the system/user text prompt for this page.
        system_message, user_message = _build_prompt(
            page_idx,
            overlay_fields,
            page_candidates=page_candidates,
            confidence_profile=confidence_profile,
            database_fields=page_db_fields,
            database_total_fields=page_db_total,
            database_fields_truncated=page_db_truncated,
        )
        prompt_metrics = _estimate_page_payload(
            system_message=system_message,
            user_message=user_message,
            clean_page_url=None,
            overlay_url=None,
            prev_page_url=None,
        )
        if (
            prompt_metrics["prompt_chars"] > page_prompt_char_budget
            and page_db_total > db_prompt_full_threshold
            and page_db_fields
            and len(page_db_fields) > db_prompt_budget_shortlist_limit
        ):
            page_db_fields, page_db_total, page_db_truncated = _select_database_prompt_fields(
                database_fields,
                overlay_fields=overlay_fields,
                page_candidates=page_candidates,
                full_threshold=0,
                shortlist_limit=db_prompt_budget_shortlist_limit,
            )
            system_message, user_message = _build_prompt(
                page_idx,
                overlay_fields,
                page_candidates=page_candidates,
                confidence_profile=confidence_profile,
                database_fields=page_db_fields,
                database_total_fields=page_db_total,
                database_fields_truncated=page_db_truncated,
            )

        prev_crop = None
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
        payload_context = _budget_page_payload_impl(
            page_idx=page_idx,
            page_image=page.get("image"),
            overlay_image=overlay,
            prev_crop_image=prev_crop,
            system_message=system_message,
            user_message=user_message,
            clean_profile={
                "max_dim": clean_max_dim,
                "quality": clean_quality,
                "format": clean_format,
                "detail": clean_detail,
            },
            overlay_profile={
                "max_dim": page_overlay_max_dim,
                "quality": page_overlay_quality,
                "format": page_overlay_format,
                "detail": overlay_detail,
            },
            prev_detail=prev_detail,
            page_prompt_char_budget=page_prompt_char_budget,
            page_image_byte_budget=page_image_byte_budget,
            overlay_min_dim=overlay_min_dim,
            budget_clean_profile={
                "max_dim": budget_clean_max_dim,
                "quality": budget_clean_quality,
                "format": budget_clean_format,
            },
            encode_model_image=_encode_model_image,
            logger=logger,
        )

        page_contexts[page_idx] = {
            "overlay_map": overlay_map,
            "system_message": system_message,
            "user_message": user_message,
            "clean_page_url": payload_context["clean_page_url"],
            "clean_detail": payload_context["clean_detail"],
            "overlay_url": payload_context["overlay_url"],
            "overlay_detail": payload_context["overlay_detail"],
            "prev_page_url": payload_context["prev_page_url"],
            "prev_detail": payload_context["prev_detail"],
        }
        tasks.append({"page_idx": page_idx})

    def _run_page(task: Dict[str, Any]) -> Dict[str, Any]:
        # Step 6: Execute one page-level OpenAI request and parse both rename lines + checkbox JSON rules.
        page_idx = task["page_idx"]
        context = page_contexts[page_idx]
        user_content = [
            {"type": "input_text", "text": context["user_message"]},
            {
                "type": "input_image",
                "image_url": context["clean_page_url"],
                "detail": context.get("clean_detail") or "low",
            },
            {
                "type": "input_image",
                "image_url": context["overlay_url"],
                "detail": context.get("overlay_detail") or "high",
            },
        ]
        if context.get("prev_page_url"):
            user_content.append(
                {
                    "type": "input_image",
                    "image_url": context["prev_page_url"],
                    "detail": context.get("prev_detail") or "low",
                }
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

    # Step 7: Run page calls in parallel and collect raw model outputs.
    if tasks:
        results = run_threaded_map(
            tasks,
            _run_page,
            max_workers=max_workers,
            label="rename_openai",
        )
    else:
        results = []

    # Step 8: Flatten usage and checkbox-rule outputs across pages.
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

    # Step 9: Keep the best rename suggestion per original field index.
    # (Multiple pages can reference a field in edge cases.)
    entries_by_index: Dict[int, Dict[str, Any]] = {}
    for result in results:
        for entry in result["entries"]:
            idx = entry["fieldIndex"]
            existing = entries_by_index.get(idx)
            if existing is None or entry["isItAfieldConfidence"] > existing["isItAfieldConfidence"]:
                entries_by_index[idx] = entry

    renamed_fields: List[Dict[str, Any]] = []
    dropped: List[str] = []

    # Step 10: Apply model output onto baseline fields (or fall back to original names).
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

    # Step 11: Enforce unique final names and derive checkbox group/option metadata.
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

    # Step 12: Build schema lookup for mapping confidence and checkbox-rule validation.
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

    # Step 13: Normalize + dedupe model-emitted checkbox rules against allowed schema/group keys.
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

    # Step 14: Build API-facing rename report rows and usage summary.
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
    # Step 15: Return both the compact report and the fully updated field payload.
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
