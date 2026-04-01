"""
Prompt assembly and schema-shortlisting helpers for OpenAI rename.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Tuple


def _to_snake_case(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", (text or "").strip()).strip()
    if not cleaned:
        return "field"
    return re.sub(r"\s+", "_", cleaned.lower())


def _rects_intersect(a: List[float], b: List[float]) -> bool:
    return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])


def _rect_distance(a: List[float], b: List[float]) -> float:
    dx = max(b[0] - a[2], a[0] - b[2], 0.0)
    dy = max(b[1] - a[3], a[1] - b[3], 0.0)
    return (dx * dx + dy * dy) ** 0.5


def label_context(rect: List[float], label_bboxes: List[List[float]]) -> Tuple[float | None, bool]:
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


def prompt_hygiene_enabled() -> bool:
    return (os.getenv("SANDBOX_RENAME_PROMPT_HYGIENE", "1") or "").strip().lower() not in {
        "0",
        "false",
        "off",
        "no",
    }


def compact_prompt_noise(text: str) -> str:
    """
    Remove exact duplicate bullet lines and redundant blank lines.
    """
    if not text:
        return ""
    seen_bullets: set[str] = set()
    compacted: List[str] = []
    previous_blank = False

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            if previous_blank:
                continue
            compacted.append("")
            previous_blank = True
            continue

        previous_blank = False
        if stripped.startswith("-"):
            key = re.sub(r"\s+", " ", stripped.lower())
            if key in seen_bullets:
                continue
            seen_bullets.add(key)
        compacted.append(line)
    return "\n".join(compacted).strip()


def _dedupe_non_empty_strings(values: List[str] | None) -> List[str]:
    deduped: List[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _overlay_schema_tokens(
    overlay_fields: List[Dict[str, Any]],
    *,
    page_candidates: Dict[str, Any] | None = None,
) -> set[str]:
    tokens: set[str] = set()
    for field in overlay_fields:
        hint = str(field.get("labelHintText") or "")
        normalized_hint = _to_snake_case(hint)
        tokens.update(token for token in normalized_hint.split("_") if len(token) >= 2)

    labels = list((page_candidates or {}).get("labels") or [])
    for label in labels[:200]:
        normalized_text = _to_snake_case(str(label.get("text") or ""))
        tokens.update(token for token in normalized_text.split("_") if len(token) >= 2)
    return tokens


def select_database_prompt_fields(
    database_fields: List[str] | None,
    *,
    overlay_fields: List[Dict[str, Any]],
    page_candidates: Dict[str, Any] | None = None,
    full_threshold: int,
    shortlist_limit: int,
) -> Tuple[List[str], int, bool]:
    """
    Build the schema list shown in the prompt.

    Up to full_threshold fields are included in full. Above that threshold we rank fields
    by token overlap with page overlay labels and include a bounded shortlist.
    """
    unique_fields = _dedupe_non_empty_strings(database_fields)
    total = len(unique_fields)
    if total == 0:
        return [], 0, False

    if total <= max(0, int(full_threshold)):
        return unique_fields, total, False

    limit = max(1, min(int(shortlist_limit), total))
    overlay_tokens = _overlay_schema_tokens(overlay_fields, page_candidates=page_candidates)
    ranked: List[Tuple[int, int, str]] = []
    for idx, field_name in enumerate(unique_fields):
        normalized = _to_snake_case(field_name)
        field_tokens = {token for token in normalized.split("_") if token}
        overlap = len(field_tokens & overlay_tokens)
        prefix_bonus = 1 if any(normalized.startswith(f"{token}_") for token in overlay_tokens) else 0
        suffix_bonus = 1 if any(normalized.endswith(f"_{token}") for token in overlay_tokens) else 0
        score = (overlap * 4) + prefix_bonus + suffix_bonus
        ranked.append((score, idx, field_name))
    ranked.sort(key=lambda item: (-item[0], item[1]))

    selected: List[str] = []
    selected_set: set[str] = set()
    for score, _idx, field_name in ranked:
        if score <= 0:
            break
        selected.append(field_name)
        selected_set.add(field_name)
        if len(selected) >= limit:
            break

    if len(selected) < limit:
        for field_name in unique_fields:
            if field_name in selected_set:
                continue
            selected.append(field_name)
            selected_set.add(field_name)
            if len(selected) >= limit:
                break
    return selected, total, len(selected) < total


def build_prompt(
    page_idx: int,
    overlay_fields: List[Dict[str, Any]],
    *,
    page_candidates: Dict[str, Any],
    confidence_profile: str = "sandbox",
    database_fields: List[str] | None = None,
    database_total_fields: int | None = None,
    database_fields_truncated: bool = False,
    checkbox_rules_start: str,
    checkbox_rules_end: str,
    commonforms_thresholds: Tuple[float, float] | None = None,
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
        "- Green (>= 0.60) = confident.\n"
        "- Yellow (0.30–0.59) = double-check alignment and labels.\n"
        "- Red (< 0.30) = uncertain; avoid renaming unless the label is obvious.\n"
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
        high, medium = commonforms_thresholds if commonforms_thresholds else (0.60, 0.30)
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

    field_lines = []
    for field in overlay_fields:
        rect = field.get("rect") or []
        label_dist, overlaps_label = label_context(rect, label_bboxes)
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
        context_fields = _dedupe_non_empty_strings(database_fields)
        if context_fields:
            total_fields = int(database_total_fields or len(context_fields))
            total_fields = max(total_fields, len(context_fields))
            db_header = "DATABASE_FIELDS (context only; do not invent fields)"
            if database_fields_truncated and total_fields > len(context_fields):
                db_header = (
                    f"{db_header}; showing {len(context_fields)} likely matches from {total_fields} total"
                )

            db_block = "\n".join(f"- {field}" for field in context_fields)
            user_message = (
                f"{user_message}\n{db_header}:\n{db_block}\n"
                "If a database field clearly matches a label, use that exact name.\n"
            )
            system_message += (
                "\n\nCheckbox rules output (for database fields):\n"
                "- After ALL rename lines, output a JSON array of checkbox rules.\n"
                f"- Use the exact block:\n{checkbox_rules_start}\n[{{...}}]\n{checkbox_rules_end}\n"
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
    if prompt_hygiene_enabled():
        system_message = compact_prompt_noise(system_message)
        user_message = compact_prompt_noise(user_message)
    return system_message, user_message
