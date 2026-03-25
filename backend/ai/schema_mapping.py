"""OpenAI schema-to-template mapping helpers with allowlist payloads."""

import json
import os
import re
from typing import Any, Dict, List, MutableSequence, Optional

from backend.ai.openai_client import create_openai_client
from backend.ai.openai_usage import normalize_chat_usage
from backend.logging_config import get_logger


logger = get_logger(__name__)

OPENAI_SCHEMA_MODEL = os.getenv("OPENAI_SCHEMA_MAPPING_MODEL", "gpt-5-mini")
MAX_SCHEMA_FIELDS = int(os.getenv("OPENAI_SCHEMA_MAX_FIELDS", "200"))
MAX_TEMPLATE_FIELDS = int(os.getenv("OPENAI_TEMPLATE_MAX_FIELDS", "200"))
MAX_PAYLOAD_BYTES = int(os.getenv("OPENAI_SCHEMA_MAX_PAYLOAD_BYTES", "80000"))
MAX_FIELD_NAME_LEN = int(os.getenv("OPENAI_SCHEMA_MAX_FIELD_NAME_LEN", "120"))

ALLOWED_SCHEMA_TYPES = {"string", "int", "date", "bool"}
ALLOWED_TEMPLATE_TYPES = {"text", "checkbox", "radio", "signature", "date"}

def validate_payload_size(payload: Dict[str, Any]) -> None:
    """Reject payloads that exceed the OpenAI request size budget."""
    raw = json.dumps(payload, ensure_ascii=True)
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise ValueError("OpenAI payload too large; reduce schema/template size")


# OpenAI receives schema metadata (header names/types) and template overlay tags; no row data or field values.

def build_allowlist_payload(schema_fields: List[Dict[str, Any]], template_fields: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Build a strict allowlist payload for OpenAI with only schema + overlay metadata.

    We normalize types, trim names, and drop invalid entries to prevent prompt injection.
    """
    cleaned_schema = []
    for field in schema_fields[:MAX_SCHEMA_FIELDS]:
        name = str(field.get("name") or "").strip()
        if not name:
            continue
        field_type = str(field.get("type") or "string").strip().lower()
        if field_type not in ALLOWED_SCHEMA_TYPES:
            field_type = "string"
        cleaned_schema.append({
            "name": name[:MAX_FIELD_NAME_LEN],
            "type": field_type,
        })

    cleaned_template = []
    for field in template_fields[:MAX_TEMPLATE_FIELDS]:
        tag = str(field.get("name") or "").strip()
        if not tag:
            continue
        field_type = str(field.get("type") or "text").strip().lower()
        if field_type not in ALLOWED_TEMPLATE_TYPES:
            field_type = "text"
        page = field.get("page")
        try:
            page_value = int(page) if page is not None else 1
        except (TypeError, ValueError):
            page_value = 1
        rect = field.get("rect")
        rect_payload: Dict[str, float] = {}
        if isinstance(rect, dict):
            for key in ("x", "y", "width", "height"):
                value = rect.get(key)
                if isinstance(value, (int, float)):
                    rect_payload[key] = float(value)
        option_label = field.get("optionLabel") or field.get("option_label")
        group_label = field.get("groupLabel") or field.get("group_label")
        cleaned_template.append({
            "fieldId": str(field.get("id") or "").strip() or None,
            "tag": tag[:MAX_FIELD_NAME_LEN],
            "type": field_type,
            "page": page_value,
            "rect": rect_payload or None,
            "groupKey": str(field.get("groupKey") or "").strip() or None,
            "optionKey": str(field.get("optionKey") or "").strip() or None,
            "optionLabel": str(option_label).strip()[:MAX_FIELD_NAME_LEN] if option_label else None,
            "groupLabel": str(group_label).strip()[:MAX_FIELD_NAME_LEN] if group_label else None,
            "radioGroupKey": str(field.get("radioGroupKey") or "").strip() or None,
            "radioGroupLabel": str(field.get("radioGroupLabel") or "").strip()[:MAX_FIELD_NAME_LEN] if field.get("radioGroupLabel") else None,
            "radioOptionKey": str(field.get("radioOptionKey") or "").strip() or None,
            "radioOptionLabel": str(field.get("radioOptionLabel") or "").strip()[:MAX_FIELD_NAME_LEN] if field.get("radioOptionLabel") else None,
        })

    payload = {
        "schemaFields": cleaned_schema,
        "templateTags": cleaned_template,
        "totalSchemaFields": len(cleaned_schema),
        "totalTemplateTags": len(cleaned_template),
    }
    return payload


def _payload_size(payload: Dict[str, Any]) -> int:
    """Return the JSON payload size in bytes using the same encoding rules as OpenAI calls."""
    return len(json.dumps(payload, ensure_ascii=True))


def _assemble_payload(
    schema_fields: List[Dict[str, Any]],
    template_tags: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build an allowlist payload with per-chunk totals."""
    return {
        "schemaFields": schema_fields,
        "templateTags": template_tags,
        "totalSchemaFields": len(schema_fields),
        "totalTemplateTags": len(template_tags),
    }


def _split_template_tags(
    schema_fields: List[Dict[str, Any]],
    template_tags: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Greedily split template tags into payload-sized chunks to satisfy size limits.

    Implementation note:
    Instead of repeatedly json.dumps() the full candidate payload (O(T * P)),
    we precompute JSON sizes for schema + per-tag fragments and maintain an
    incremental byte budget (O(T)).
    """
    schema_fields_json = json.dumps(schema_fields, ensure_ascii=True)
    schema_count_str = str(len(schema_fields))

    # Reconstruct the exact JSON layout produced by json.dumps(_assemble_payload(...)).
    prefix = f'{{"schemaFields": {schema_fields_json}, "templateTags": '
    suffix_prefix = f', "totalSchemaFields": {schema_count_str}, "totalTemplateTags": '
    suffix_end_len = 1  # "}"

    # Empty templateTags list ("[]") and totalTemplateTags=0.
    base_len = len(prefix) + 2 + len(suffix_prefix) + 1 + suffix_end_len
    if base_len > MAX_PAYLOAD_BYTES:
        raise ValueError("OpenAI payload too large; reduce schema/template size")

    chunks: List[Dict[str, Any]] = []
    current: List[Dict[str, Any]] = []
    current_tag_json_lens: List[int] = []
    current_tags_sum_len = 0

    def _template_tags_list_len(tag_lens: List[int], total_len: int) -> int:
        """Return the length of json.dumps(templateTags) for a list of dicts."""
        if not tag_lens:
            return 2  # "[]"
        # "[" + tag0 + ", " + tag1 + ... + "]"
        return 2 + total_len + (2 * (len(tag_lens) - 1))

    def _payload_len(template_tags_len: int, total_template_tags: int) -> int:
        return (
            len(prefix)
            + template_tags_len
            + len(suffix_prefix)
            + len(str(total_template_tags))
            + suffix_end_len
        )

    for tag in template_tags:
        tag_json_len = len(json.dumps(tag, ensure_ascii=True))
        candidate_tag_lens = current_tag_json_lens + [tag_json_len]
        candidate_sum_len = current_tags_sum_len + tag_json_len
        candidate_list_len = _template_tags_list_len(candidate_tag_lens, candidate_sum_len)
        candidate_payload_len = _payload_len(candidate_list_len, len(candidate_tag_lens))

        if candidate_payload_len > MAX_PAYLOAD_BYTES:
            if not current:
                raise ValueError("OpenAI payload too large; reduce schema/template size")
            chunks.append(_assemble_payload(schema_fields, current))
            current = [tag]
            current_tag_json_lens = [tag_json_len]
            current_tags_sum_len = tag_json_len
            continue

        current.append(tag)
        current_tag_json_lens = candidate_tag_lens
        current_tags_sum_len = candidate_sum_len

    if current:
        chunks.append(_assemble_payload(schema_fields, current))
    return chunks


def _append_usage_event(
    usage_collector: Optional[MutableSequence[Dict[str, Any]]],
    response: Any,
    *,
    chunk_index: Optional[int] = None,
    chunk_count: Optional[int] = None,
) -> None:
    if usage_collector is None:
        return
    usage = normalize_chat_usage(response)
    event: Dict[str, Any] = {
        "api": "chat_completions",
        "model": OPENAI_SCHEMA_MODEL,
        **usage,
    }
    if chunk_index is not None:
        event["chunk"] = int(chunk_index)
    if chunk_count is not None:
        event["chunkCount"] = int(chunk_count)
    usage_collector.append(event)


def call_openai_schema_mapping(
    payload: Dict[str, Any],
    *,
    usage_collector: Optional[MutableSequence[Dict[str, Any]]] = None,
    openai_max_retries: Optional[int] = None,
    chunk_index: Optional[int] = None,
    chunk_count: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Call OpenAI with a schema + overlay payload and return parsed JSON output.
    """
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        err = RuntimeError("OpenAI API key not configured. Set OPENAI_API_KEY.")
        setattr(err, "status_code", 503)
        raise err

    system_prompt = (
        "You map database schema fields to PDF template overlay tags. "
        "You only see schema field names/types and template tags. "
        "Return JSON with keys: mappings, templateRules, textTransformRules, checkboxRules, radioGroupSuggestions, "
        "identifierKey, notes. Each mapping must include schemaField, templateTag, "
        "confidence (0..1), reasoning. "
        "radioGroupSuggestions should identify single-choice checkbox clusters that should become "
        "explicit radio groups in the editor."
    )
    user_prompt = (
        "Schema + template overlay payload (no row values):\n"
        f"{json.dumps(payload, ensure_ascii=True)}\n"
        "\nRules:\n"
        "- Only reference schemaField values that appear in schemaFields.\n"
        "- Only reference templateTag values that appear in templateTags.\n"
        "- Avoid inventing data; prefer leaving unmapped if unsure.\n"
        "- textTransformRules are deterministic fill-time transforms for text fields.\n"
        "- Allowed textTransformRules.operation: copy, concat, split_name_first_rest, split_delimiter.\n"
        "- textTransformRules entries should use keys: targetField, operation, sources, "
        "optional separator/delimiter/part/index, confidence, requiresReview, reasoning.\n"
        "- If split is ambiguous, set requiresReview=true and lower confidence.\n"
        "- checkboxRules should map one schemaField to one template groupKey when possible.\n"
        "- radioGroupSuggestions should only describe single-choice groups such as yes/no, enum, "
        "or binary pairs. Never use them for multi-select lists.\n"
        "- radioGroupSuggestions should be a list of objects with: suggestedType (radio_group), "
        "groupKey, groupLabel, suggestedFields, optional sourceField, optional selectionReason "
        "(yes_no|enum|binary_pair|label_pattern), confidence, reasoning.\n"
        "- suggestedFields should be a list of at least 2 items. Each item should use: fieldId "
        "when available, fieldName, optionKey, optionLabel.\n"
        "- Only suggest radio groups for template tags whose type is checkbox or radio.\n"
        "- Do not suggest a radio group when the fields already share explicit radio metadata.\n"
    )

    client = create_openai_client(api_key=key, max_retries_override=openai_max_retries)
    base_req = {
        "model": OPENAI_SCHEMA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    json_req = {**base_req, "response_format": {"type": "json_object"}}

    try:
        response = client.chat.completions.create(**json_req)
        _append_usage_event(
            usage_collector,
            response,
            chunk_index=chunk_index,
            chunk_count=chunk_count,
        )
        content = response.choices[0].message.content or "{}"
        return _parse_json(content)
    except Exception as exc:
        msg = str(getattr(exc, "message", exc))
        param = getattr(exc, "param", None)
        if param == "response_format" or "response_format" in msg:
            response = client.chat.completions.create(**base_req)
            _append_usage_event(
                usage_collector,
                response,
                chunk_index=chunk_index,
                chunk_count=chunk_count,
            )
            content = response.choices[0].message.content or "{}"
            return _parse_json(content)
        raise


def _merge_schema_mapping_response(
    aggregate: Dict[str, Any],
    response: Dict[str, Any],
) -> None:
    """Merge a single OpenAI response into an aggregate response dict."""
    if not isinstance(response, dict):
        return

    mappings = response.get("mappings")
    if isinstance(mappings, list):
        aggregate.setdefault("mappings", []).extend([entry for entry in mappings if isinstance(entry, dict)])

    template_rules = response.get("templateRules") or response.get("template_rules")
    if isinstance(template_rules, list):
        aggregate.setdefault("templateRules", []).extend([entry for entry in template_rules if isinstance(entry, dict)])

    text_transform_rules = response.get("textTransformRules") or response.get("text_transform_rules")
    if isinstance(text_transform_rules, list):
        aggregate.setdefault("textTransformRules", []).extend(
            [entry for entry in text_transform_rules if isinstance(entry, dict)]
        )

    checkbox_rules = response.get("checkboxRules") or response.get("checkbox_rules")
    if isinstance(checkbox_rules, list):
        aggregate.setdefault("checkboxRules", []).extend([entry for entry in checkbox_rules if isinstance(entry, dict)])

    radio_group_suggestions = (
        response.get("radioGroupSuggestions")
        or response.get("radio_group_suggestions")
    )
    if isinstance(radio_group_suggestions, list):
        aggregate.setdefault("radioGroupSuggestions", []).extend(
            [entry for entry in radio_group_suggestions if isinstance(entry, dict)]
        )

    identifier_key = response.get("identifierKey") or response.get("patientIdentifierField")
    if identifier_key and not aggregate.get("identifierKey"):
        aggregate["identifierKey"] = str(identifier_key)

    notes = response.get("notes")
    if notes:
        aggregate.setdefault("notes", []).append(str(notes))


def call_openai_schema_mapping_chunked(
    payload: Dict[str, Any],
    *,
    usage_collector: Optional[MutableSequence[Dict[str, Any]]] = None,
    openai_max_retries: Optional[int] = None,
) -> Dict[str, Any]:
    """Call OpenAI for schema mapping, splitting template tags when the payload is too large.

    This merges mappings and rules across chunks so the caller sees one unified result.
    """
    if _payload_size(payload) <= MAX_PAYLOAD_BYTES:
        if usage_collector is None and openai_max_retries is None:
            return call_openai_schema_mapping(payload)
        return call_openai_schema_mapping(
            payload,
            usage_collector=usage_collector,
            openai_max_retries=openai_max_retries,
        )

    schema_fields = payload.get("schemaFields") or []
    template_tags = payload.get("templateTags") or []
    chunks = _split_template_tags(schema_fields, template_tags)
    if not chunks:
        raise ValueError("OpenAI payload too large; reduce schema/template size")

    logger.info(
        "OpenAI schema mapping chunked into %s payloads (schema=%s tags=%s)",
        len(chunks),
        len(schema_fields),
        len(template_tags),
    )

    aggregate: Dict[str, Any] = {
        "mappings": [],
        "templateRules": [],
        "textTransformRules": [],
        "checkboxRules": [],
        "radioGroupSuggestions": [],
        "notes": [],
    }
    chunk_count = len(chunks)
    for idx, chunk in enumerate(chunks, start=1):
        response = call_openai_schema_mapping(
            chunk,
            usage_collector=usage_collector,
            openai_max_retries=openai_max_retries,
            chunk_index=idx,
            chunk_count=chunk_count,
        )
        _merge_schema_mapping_response(aggregate, response)

    notes = aggregate.get("notes") or []
    aggregate["notes"] = "; ".join(notes) if notes else ""
    return aggregate


def _parse_json(content: str) -> Dict[str, Any]:
    """Parse JSON output, falling back to a best-effort object extraction."""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", content)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        return {"mappings": [], "notes": "Non-JSON response received"}
