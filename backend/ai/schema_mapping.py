"""OpenAI schema-to-template mapping helpers with allowlist payloads."""

import json
import os
import re
from typing import Any, Dict, List

from openai import OpenAI

from ..fieldDetecting.rename_pipeline.combinedSrc.config import get_logger


logger = get_logger(__name__)

OPENAI_SCHEMA_MODEL = os.getenv("OPENAI_SCHEMA_MAPPING_MODEL", "gpt-5.2")
MAX_SCHEMA_FIELDS = int(os.getenv("OPENAI_SCHEMA_MAX_FIELDS", "200"))
MAX_TEMPLATE_FIELDS = int(os.getenv("OPENAI_TEMPLATE_MAX_FIELDS", "200"))
MAX_PAYLOAD_BYTES = int(os.getenv("OPENAI_SCHEMA_MAX_PAYLOAD_BYTES", "80000"))
MAX_FIELD_NAME_LEN = int(os.getenv("OPENAI_SCHEMA_MAX_FIELD_NAME_LEN", "120"))

ALLOWED_SCHEMA_TYPES = {"string", "int", "date", "bool"}
ALLOWED_TEMPLATE_TYPES = {"text", "checkbox", "signature", "date"}

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
        cleaned_template.append({
            "tag": tag[:MAX_FIELD_NAME_LEN],
            "type": field_type,
            "page": page_value,
            "rect": rect_payload or None,
            "groupKey": str(field.get("groupKey") or "").strip() or None,
            "optionKey": str(field.get("optionKey") or "").strip() or None,
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

    We repeatedly serialize candidate payloads to stay under the byte cap.
    Time complexity: O(T * P) for T tags and payload size P due to JSON size checks.
    """
    base_payload = _assemble_payload(schema_fields, [])
    if _payload_size(base_payload) > MAX_PAYLOAD_BYTES:
        raise ValueError("OpenAI payload too large; reduce schema/template size")

    chunks: List[Dict[str, Any]] = []
    current: List[Dict[str, Any]] = []
    for tag in template_tags:
        current.append(tag)
        candidate = _assemble_payload(schema_fields, current)
        if _payload_size(candidate) > MAX_PAYLOAD_BYTES:
            if len(current) == 1:
                raise ValueError("OpenAI payload too large; reduce schema/template size")
            current.pop()
            chunks.append(_assemble_payload(schema_fields, current))
            current = [tag]
    if current:
        chunks.append(_assemble_payload(schema_fields, current))
    return chunks


def call_openai_schema_mapping(payload: Dict[str, Any]) -> Dict[str, Any]:
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
        "Return JSON with keys: mappings, templateRules, checkboxRules, identifierKey, notes. "
        "Each mapping must include schemaField, templateTag, confidence (0..1), reasoning."
    )
    user_prompt = (
        "Schema + template overlay payload (no row values):\n"
        f"{json.dumps(payload, ensure_ascii=True)}\n"
        "\nRules:\n"
        "- Only reference schemaField values that appear in schemaFields.\n"
        "- Only reference templateTag values that appear in templateTags.\n"
        "- Avoid inventing data; prefer leaving unmapped if unsure.\n"
        "- checkboxRules should map one schemaField to one template groupKey when possible.\n"
    )

    client = OpenAI(api_key=key)
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
        content = response.choices[0].message.content or "{}"
        return _parse_json(content)
    except Exception as exc:
        msg = str(getattr(exc, "message", exc))
        param = getattr(exc, "param", None)
        if param == "response_format" or "response_format" in msg:
            response = client.chat.completions.create(**base_req)
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

    checkbox_rules = response.get("checkboxRules") or response.get("checkbox_rules")
    if isinstance(checkbox_rules, list):
        aggregate.setdefault("checkboxRules", []).extend([entry for entry in checkbox_rules if isinstance(entry, dict)])

    identifier_key = response.get("identifierKey") or response.get("patientIdentifierField")
    if identifier_key and not aggregate.get("identifierKey"):
        aggregate["identifierKey"] = str(identifier_key)

    notes = response.get("notes")
    if notes:
        aggregate.setdefault("notes", []).append(str(notes))


def call_openai_schema_mapping_chunked(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Call OpenAI for schema mapping, splitting template tags when the payload is too large.

    This merges mappings and rules across chunks so the caller sees one unified result.
    """
    if _payload_size(payload) <= MAX_PAYLOAD_BYTES:
        return call_openai_schema_mapping(payload)

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

    aggregate: Dict[str, Any] = {"mappings": [], "templateRules": [], "checkboxRules": [], "notes": []}
    for chunk in chunks:
        response = call_openai_schema_mapping(chunk)
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
            return json.loads(match.group(0))
        return {"mappings": [], "notes": "Non-JSON response received"}
