"""Schema/rename payload normalization and AI output sanitization."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from backend.api.schemas import TemplateOverlayField


def sanitize_pdf_field_name_candidate(raw_name: str, fallback_base: str = "field") -> str:
    """Sanitize a PDF field name for rename suggestions."""
    max_len = 96

    def _coerce(value: str, fallback: str) -> str:
        return (
            str(value or fallback or "field")
            .strip()
            .replace(" ", "_")
            .replace("\t", "_")
            .replace("\n", "_")
            .replace("\r", "_")
            .replace("\u00a0", "_")
            .replace("\u2007", "_")
            .replace("\u202f", "_")
        )

    base = _coerce(raw_name, fallback_base)
    base = re.sub(r"\s+", "_", base)
    base = re.sub(r"[^a-zA-Z0-9_.-]", "_", base)
    base = re.sub(r"_{2,}", "_", base)
    base = base.strip("_").lower()
    base = base[:max_len]
    if base:
        return base
    fallback = _coerce(fallback_base, "field")
    fallback = re.sub(r"\s+", "_", fallback)
    fallback = re.sub(r"[^a-zA-Z0-9_.-]", "_", fallback)
    fallback = re.sub(r"_{2,}", "_", fallback)
    fallback = fallback.strip("_").lower()
    fallback = fallback[:max_len]
    return fallback or "field"


def normalize_data_key(value: str) -> str:
    """Normalize schema/template keys to a stable lowercase underscore form."""
    normalized = str(value or "").strip().lower()
    if not normalized:
        return ""
    normalized = re.sub(r"[\s-]+", "_", normalized)
    normalized = re.sub(r"[^a-z0-9_]", "", normalized)
    return normalized


def template_fields_to_rename_fields(fields: List[TemplateOverlayField]) -> List[Dict[str, Any]]:
    """Convert template overlay fields into rename-friendly payloads."""
    rename_fields: List[Dict[str, Any]] = []
    for field in fields:
        rect = field.rect or {}
        x = rect.get("x")
        y = rect.get("y")
        width = rect.get("width")
        height = rect.get("height")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            continue
        if not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
            continue
        rename_fields.append(
            {
                "name": field.name,
                "type": field.type or "text",
                "page": int(field.page or 1),
                "rect": [float(x), float(y), float(x) + float(width), float(y) + float(height)],
                "groupKey": field.groupKey,
                "optionKey": field.optionKey,
                "optionLabel": field.optionLabel,
                "groupLabel": field.groupLabel,
            }
        )
    return rename_fields


def build_schema_mapping_payload(
    schema_fields: List[Dict[str, Any]],
    template_tags: List[Dict[str, Any]],
    ai_response: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a JSON-friendly mapping response for schema-to-template results."""
    allowed_schema = [str(field.get("name") or "").strip() for field in schema_fields]
    allowed_schema = [field for field in allowed_schema if field]
    allowed_template = [str(tag.get("tag") or "").strip() for tag in template_tags]
    allowed_template = [tag for tag in allowed_template if tag]

    allowed_schema_set = set(allowed_schema)
    allowed_schema_map: Dict[str, str] = {}
    for field in allowed_schema:
        normalized = normalize_data_key(field)
        if normalized and normalized not in allowed_schema_map:
            allowed_schema_map[normalized] = field
    allowed_template_set = set(allowed_template)
    allowed_group_key_map: Dict[str, str] = {}
    for tag in template_tags:
        raw_group_key = str(tag.get("groupKey") or "").strip()
        if not raw_group_key:
            continue
        normalized_group_key = normalize_data_key(raw_group_key)
        if not normalized_group_key:
            continue
        if normalized_group_key not in allowed_group_key_map:
            allowed_group_key_map[normalized_group_key] = raw_group_key

    sanitized_mappings = []
    mapped_schema = set()
    mapped_template = set()
    raw_mappings = ai_response.get("mappings") or []
    for entry in raw_mappings if isinstance(raw_mappings, list) else []:
        if not isinstance(entry, dict):
            continue
        schema_field = (
            entry.get("schemaField")
            or entry.get("databaseField")
            or entry.get("source")
            or ""
        )
        template_tag = (
            entry.get("templateTag")
            or entry.get("pdfField")
            or entry.get("targetField")
            or ""
        )
        schema_field = str(schema_field).strip()
        template_tag = str(template_tag).strip()
        if not schema_field or not template_tag:
            continue
        if schema_field not in allowed_schema_set or template_tag not in allowed_template_set:
            continue

        try:
            confidence_value = float(entry.get("confidence", 0.6))
        except (TypeError, ValueError):
            confidence_value = 0.6
        confidence_value = min(max(confidence_value, 0.0), 1.0)

        desired_name = sanitize_pdf_field_name_candidate(schema_field, schema_field)
        sanitized_mappings.append(
            {
                "databaseField": schema_field,
                "pdfField": desired_name,
                "originalPdfField": template_tag,
                "confidence": confidence_value,
                "reasoning": entry.get("reasoning", "AI suggested mapping"),
                "id": re.sub(r"[^a-zA-Z0-9_]", "_", f"{schema_field}_to_{template_tag}"),
            }
        )
        mapped_schema.add(schema_field)
        mapped_template.add(template_tag)

    raw_templates = (
        ai_response.get("templateRules")
        or ai_response.get("template_rules")
        or ai_response.get("derivedMappings")
        or []
    )
    template_rules = []
    if isinstance(raw_templates, list):
        for raw in raw_templates:
            if not isinstance(raw, dict):
                continue
            target = (
                raw.get("targetField")
                or raw.get("pdfField")
                or raw.get("target")
                or raw.get("name")
            )
            target = str(target or "").strip()
            if target not in allowed_template_set:
                continue
            sources = raw.get("sources")
            if isinstance(sources, list):
                filtered = [src for src in sources if str(src).strip() in allowed_schema_set]
                if not filtered:
                    continue
                raw = dict(raw)
                raw["sources"] = filtered
            template_rules.append(raw)

    raw_checkbox = ai_response.get("checkboxRules") or ai_response.get("checkbox_rules") or []
    checkbox_rules = []
    if isinstance(raw_checkbox, list):
        for raw in raw_checkbox:
            if not isinstance(raw, dict):
                continue
            schema_field_raw = str(raw.get("databaseField") or "").strip()
            if not schema_field_raw:
                continue
            schema_field = (
                schema_field_raw
                if schema_field_raw in allowed_schema_set
                else allowed_schema_map.get(normalize_data_key(schema_field_raw))
            )
            if not schema_field:
                continue
            raw_group_key = str(raw.get("groupKey") or "").strip()
            normalized_group_key = normalize_data_key(raw_group_key)
            normalized_schema_key = normalize_data_key(schema_field)
            resolved_group_key = None
            if normalized_group_key:
                resolved_group_key = allowed_group_key_map.get(normalized_group_key)
            if not resolved_group_key and normalized_schema_key:
                resolved_group_key = allowed_group_key_map.get(normalized_schema_key)
            if allowed_group_key_map and not resolved_group_key:
                continue
            group_key = resolved_group_key or normalized_group_key or normalized_schema_key
            if not group_key:
                continue
            normalized_rule = dict(raw)
            normalized_rule["databaseField"] = schema_field
            normalized_rule["groupKey"] = group_key
            checkbox_rules.append(normalized_rule)

    def _coerce_hint_bool(value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            raw = value.strip().lower()
            if raw in {"1", "true", "yes", "y", "t"}:
                return True
            if raw in {"0", "false", "no", "n", "f"}:
                return False
        return None

    raw_hints = ai_response.get("checkboxHints") or ai_response.get("checkbox_hints") or []
    checkbox_hints: List[Dict[str, Any]] = []
    if isinstance(raw_hints, list):
        for raw in raw_hints:
            if not isinstance(raw, dict):
                continue
            schema_field_raw = str(raw.get("databaseField") or "").strip()
            if not schema_field_raw:
                continue
            schema_field = (
                schema_field_raw
                if schema_field_raw in allowed_schema_set
                else allowed_schema_map.get(normalize_data_key(schema_field_raw))
            )
            if not schema_field:
                continue
            raw_group_key = str(raw.get("groupKey") or "").strip()
            normalized_group_key = normalize_data_key(raw_group_key)
            resolved_group_key = None
            if normalized_group_key:
                resolved_group_key = allowed_group_key_map.get(normalized_group_key)
            if allowed_group_key_map and not resolved_group_key:
                continue
            group_key = resolved_group_key or normalized_group_key
            if not group_key:
                continue
            direct_boolean = _coerce_hint_bool(
                raw.get("directBooleanPossible") if "directBooleanPossible" in raw else raw.get("direct_boolean_possible")
            )
            operation = str(raw.get("operation") or "").strip().lower()
            if operation not in {"yes_no", "enum", "list", "presence"}:
                operation = ""
            hint: Dict[str, Any] = {
                "databaseField": schema_field,
                "groupKey": group_key,
            }
            if direct_boolean is not None:
                hint["directBooleanPossible"] = direct_boolean
            if operation:
                hint["operation"] = operation
            checkbox_hints.append(hint)

    identifier_key = str(
        ai_response.get("identifierKey")
        or ai_response.get("patientIdentifierField")
        or ""
    ).strip()
    if identifier_key not in allowed_schema_set:
        identifier_key = None

    confidence_values = [entry.get("confidence", 0.0) for entry in sanitized_mappings]
    try:
        overall_confidence = (
            sum(float(val) for val in confidence_values) / len(confidence_values)
            if confidence_values
            else 0.0
        )
    except (TypeError, ValueError):
        overall_confidence = 0.0

    return {
        "success": True,
        "mappings": sanitized_mappings,
        "templateRules": template_rules,
        "checkboxRules": checkbox_rules,
        "checkboxHints": checkbox_hints,
        "identifierKey": identifier_key,
        "notes": ai_response.get("notes") or "",
        "unmappedDatabaseFields": [field for field in allowed_schema if field not in mapped_schema],
        "unmappedPdfFields": [tag for tag in allowed_template if tag not in mapped_template],
        "confidence": overall_confidence,
        "totalMappings": len(sanitized_mappings),
    }
