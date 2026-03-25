"""Published template API endpoint helpers.

This service turns a saved form into a frozen API-fill snapshot and manages the
scoped secrets used to access that snapshot later. Materialization is delegated
to the existing Fill By Link respondent-download path so checkbox rules and text
transforms stay aligned with the current backend behavior.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from typing import Any, Dict, Iterable, List, Optional

from fastapi import HTTPException

from backend.firebaseDB.template_database import TemplateRecord
from backend.services.fill_link_download_service import materialize_fill_link_response_download
from backend.services.mapping_service import normalize_data_key
from backend.services.pdf_service import coerce_field_payloads
from backend.services.saved_form_snapshot_service import load_saved_form_editor_snapshot
from backend.time_utils import now_iso


TEMPLATE_API_SNAPSHOT_VERSION = 1
TEMPLATE_API_SECRET_PREFIX = "dpa_live_"
TEMPLATE_API_SECRET_HASH_SCHEME = "pbkdf2_sha256"
TEMPLATE_API_SECRET_HASH_ITERATIONS = 200_000
_BOOLEAN_TRUE = {"1", "true", "yes", "y", "on", "checked", "x"}
_BOOLEAN_FALSE = {"0", "false", "no", "n", "off", "unchecked"}


def _coerce_dict_list(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(entry) for entry in value if isinstance(entry, dict)]


def _resolve_saved_form_fill_rules(template_metadata: Optional[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    metadata = template_metadata if isinstance(template_metadata, dict) else {}
    fill_rules = metadata.get("fillRules") if isinstance(metadata.get("fillRules"), dict) else {}
    checkbox_rules = fill_rules.get("checkboxRules") if isinstance(fill_rules.get("checkboxRules"), list) else metadata.get("checkboxRules")
    text_transform_rules = (
        fill_rules.get("textTransformRules")
        if isinstance(fill_rules.get("textTransformRules"), list)
        else metadata.get("textTransformRules")
    )
    if not isinstance(text_transform_rules, list) and isinstance(metadata.get("templateRules"), list):
        text_transform_rules = metadata.get("templateRules")
    radio_groups = fill_rules.get("radioGroups") if isinstance(fill_rules.get("radioGroups"), list) else metadata.get("radioGroups")
    return {
        "checkboxRules": _coerce_dict_list(checkbox_rules),
        "textTransformRules": _coerce_dict_list(text_transform_rules),
        "radioGroups": _coerce_dict_list(radio_groups),
    }


def _normalize_export_mode(value: Any) -> str:
    normalized = str(value or "flat").strip().lower()
    return "editable" if normalized == "editable" else "flat"


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return str(value).strip()


def _coerce_checkbox_boolean(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = _coerce_text(value).lower()
    if not text:
        return None
    if text in _BOOLEAN_TRUE:
        return True
    if text in _BOOLEAN_FALSE:
        return False
    return None


def _split_multi_value(value: Any) -> List[str]:
    if isinstance(value, list):
        return [entry for entry in (_coerce_text(item) for item in value) if entry]
    text = _coerce_text(value)
    if not text:
        return []
    normalized = text.replace("\n", ",").replace(";", ",")
    return [entry.strip() for entry in normalized.split(",") if entry.strip()]


def _normalize_value_map(value_map: Any) -> Dict[str, str]:
    if not isinstance(value_map, dict):
        return {}
    normalized: Dict[str, str] = {}
    for key, value in value_map.items():
        normalized_key = normalize_data_key(_coerce_text(key))
        normalized_value = normalize_data_key(_coerce_text(value))
        if normalized_key and normalized_value:
            normalized[normalized_key] = normalized_value
    return normalized


def _build_option_aliases(options: Iterable[Dict[str, Any]]) -> Dict[str, str]:
    aliases: Dict[str, str] = {}
    for option in options:
        option_key = normalize_data_key(str(option.get("optionKey") or option.get("key") or ""))
        if not option_key:
            continue
        aliases[option_key] = option_key
        option_label = normalize_data_key(str(option.get("optionLabel") or option.get("label") or ""))
        if option_label:
            aliases[option_label] = option_key
        field_name = normalize_data_key(str(option.get("fieldName") or ""))
        if field_name:
            aliases[field_name] = option_key
    return aliases


def _resolve_option_alias(
    raw_value: Any,
    *,
    aliases: Dict[str, str],
    value_map: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    normalized_value = normalize_data_key(_coerce_text(raw_value))
    if not normalized_value:
        return None
    normalized_value_map = _normalize_value_map(value_map)
    mapped_value = normalized_value_map.get(normalized_value)
    if mapped_value and mapped_value in aliases:
        return aliases[mapped_value]
    return aliases.get(normalized_value)


def _resolve_checkbox_rule_value(
    key: str,
    raw_value: Any,
    schema_group: Dict[str, Any],
) -> Any:
    operation = normalize_data_key(str(schema_group.get("operation") or "yes_no")) or "yes_no"
    options = [dict(entry) for entry in schema_group.get("options") or [] if isinstance(entry, dict)]
    aliases = _build_option_aliases(options)
    value_map = schema_group.get("valueMap") if isinstance(schema_group.get("valueMap"), dict) else None

    if operation == "list":
        resolved: List[str] = []
        for entry in _split_multi_value(raw_value):
            option_key = _resolve_option_alias(entry, aliases=aliases, value_map=value_map)
            if not option_key:
                raise ValueError(f"{key} contains an invalid option.")
            if option_key not in resolved:
                resolved.append(option_key)
        return resolved

    if operation == "enum":
        values = _split_multi_value(raw_value)
        if len(values) != 1:
            raise ValueError(f"{key} expects exactly one option.")
        option_key = _resolve_option_alias(values[0], aliases=aliases, value_map=value_map)
        if not option_key:
            raise ValueError(f"{key} contains an invalid option.")
        return option_key

    boolean_value = _coerce_checkbox_boolean(raw_value)
    if boolean_value is not None:
        return boolean_value

    true_option = _resolve_option_alias(schema_group.get("trueOption"), aliases=aliases, value_map=value_map)
    false_option = _resolve_option_alias(schema_group.get("falseOption"), aliases=aliases, value_map=value_map)
    resolved_option = _resolve_option_alias(raw_value, aliases=aliases, value_map=value_map)
    if resolved_option and true_option and resolved_option == true_option:
        return True
    if resolved_option and false_option and resolved_option == false_option:
        return False
    raise ValueError(f"{key} expects a boolean-style value.")


def _resolve_radio_group_value(
    key: str,
    raw_value: Any,
    schema_group: Dict[str, Any],
) -> str:
    options = [dict(entry) for entry in schema_group.get("options") or [] if isinstance(entry, dict)]
    aliases = _build_option_aliases(options)
    values = _split_multi_value(raw_value)
    if len(values) != 1:
        raise ValueError(f"{key} expects exactly one option.")
    option_key = _resolve_option_alias(values[0], aliases=aliases)
    if not option_key:
        raise ValueError(f"{key} contains an invalid option.")
    return option_key


def _normalize_field_snapshot(field_payloads: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized_fields = [dict(entry) for entry in coerce_field_payloads(list(field_payloads))]
    if not normalized_fields:
        raise ValueError("Saved form does not contain any editor fields to publish.")
    return normalized_fields


def build_template_api_snapshot(
    template: TemplateRecord,
    *,
    export_mode: str = "flat",
) -> Dict[str, Any]:
    if not template or not getattr(template, "pdf_bucket_path", None):
        raise ValueError("Saved form PDF is required for API Fill publishing.")
    editor_snapshot = load_saved_form_editor_snapshot(template.metadata if isinstance(template.metadata, dict) else None)
    if not editor_snapshot:
        raise ValueError("Saved form needs an editor snapshot before API Fill can be published.")
    fields = _normalize_field_snapshot(editor_snapshot.get("fields") or [])
    fill_rules = _resolve_saved_form_fill_rules(template.metadata if isinstance(template.metadata, dict) else None)
    return {
        "version": TEMPLATE_API_SNAPSHOT_VERSION,
        "templateId": template.id,
        "templateName": template.name or "Saved form",
        "sourcePdfPath": template.pdf_bucket_path,
        "fields": fields,
        "pageCount": int(editor_snapshot.get("pageCount") or 0),
        "pageSizes": dict(editor_snapshot.get("pageSizes") or {}),
        "checkboxRules": fill_rules["checkboxRules"],
        "textTransformRules": fill_rules["textTransformRules"],
        "radioGroups": fill_rules["radioGroups"],
        "defaultExportMode": _normalize_export_mode(export_mode),
        "publishedAt": now_iso(),
    }


def generate_template_api_secret() -> str:
    return f"{TEMPLATE_API_SECRET_PREFIX}{secrets.token_urlsafe(24)}"


def build_template_api_key_prefix(secret: str) -> str:
    normalized = str(secret or "").strip()
    if not normalized:
        raise ValueError("secret is required")
    return normalized[:16]


def hash_template_api_secret(secret: str) -> str:
    normalized = str(secret or "").strip()
    if not normalized:
        raise ValueError("secret is required")
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        normalized.encode("utf-8"),
        salt,
        TEMPLATE_API_SECRET_HASH_ITERATIONS,
    )
    return (
        f"{TEMPLATE_API_SECRET_HASH_SCHEME}$"
        f"{TEMPLATE_API_SECRET_HASH_ITERATIONS}$"
        f"{salt.hex()}$"
        f"{digest.hex()}"
    )


def verify_template_api_secret(secret: str, secret_hash: str) -> bool:
    normalized_secret = str(secret or "").strip()
    serialized_hash = str(secret_hash or "").strip()
    if not normalized_secret or not serialized_hash:
        return False
    try:
        scheme, iterations_raw, salt_hex, digest_hex = serialized_hash.split("$", 3)
        iterations = int(iterations_raw)
    except ValueError:
        return False
    if scheme != TEMPLATE_API_SECRET_HASH_SCHEME or iterations <= 0:
        return False
    try:
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", normalized_secret.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def parse_template_api_basic_secret(authorization: Optional[str]) -> Optional[str]:
    header = str(authorization or "").strip()
    if not header or not header.lower().startswith("basic "):
        return None
    token = header.split(" ", 1)[1].strip()
    if not token:
        return None
    try:
        decoded = base64.b64decode(token).decode("utf-8")
    except Exception:
        return None
    username, _, _password = decoded.partition(":")
    return username.strip() or None


def build_template_api_schema(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    fields = [dict(entry) for entry in coerce_field_payloads(list(snapshot.get("fields") or []))]
    checkbox_rules = _coerce_dict_list(snapshot.get("checkboxRules"))
    radio_groups = _coerce_dict_list(snapshot.get("radioGroups"))

    seen_field_names: set[str] = set()
    scalar_fields: List[Dict[str, Any]] = []
    checkbox_fields: List[Dict[str, Any]] = []
    checkbox_groups: Dict[str, Dict[str, Any]] = {}
    direct_radio_groups: Dict[str, Dict[str, Any]] = {}

    for field in fields:
        field_name = str(field.get("name") or "").strip()
        field_type = str(field.get("type") or "text").strip().lower()
        normalized_field_name = normalize_data_key(field_name)
        if field_type == "checkbox":
            group_key = normalize_data_key(str(field.get("groupKey") or field_name))
            option_key = normalize_data_key(str(field.get("optionKey") or field_name))
            if field.get("groupKey") and field.get("optionKey") and group_key and option_key:
                option_payload = {
                    "optionKey": option_key,
                    "optionLabel": str(field.get("optionLabel") or option_key),
                    "fieldName": field_name,
                }
                group = checkbox_groups.setdefault(
                    group_key,
                    {"groupKey": group_key, "type": "checkbox_group", "options": []},
                )
                group["options"].append(option_payload)
                continue
            if not normalized_field_name or normalized_field_name in seen_field_names:
                continue
            seen_field_names.add(normalized_field_name)
            checkbox_fields.append(
                {
                    "key": normalized_field_name,
                    "fieldName": field_name,
                    "type": "checkbox",
                    "page": field.get("page"),
                }
            )
            continue
        if field_type == "radio":
            group_key = normalize_data_key(str(field.get("groupKey") or field_name))
            option_key = normalize_data_key(str(field.get("optionKey") or field_name))
            if not group_key or not option_key:
                continue
            option_payload = {
                "optionKey": option_key,
                "optionLabel": str(field.get("optionLabel") or option_key),
                "fieldName": field_name,
            }
            group = direct_radio_groups.setdefault(
                group_key,
                {"groupKey": group_key, "type": "radio", "options": []},
            )
            group["options"].append(option_payload)
            continue
        if not normalized_field_name or normalized_field_name in seen_field_names:
            continue
        seen_field_names.add(normalized_field_name)
        scalar_fields.append(
            {
                "key": normalized_field_name,
                "fieldName": field_name,
                "type": field_type,
                "page": field.get("page"),
            }
        )

    checkbox_rule_groups: List[Dict[str, Any]] = []
    example_data: Dict[str, Any] = {}

    for entry in scalar_fields:
        example_data.setdefault(entry["key"], f"<{entry['key']}>")
    for entry in checkbox_fields:
        example_data.setdefault(entry["key"], True)

    for radio_group in radio_groups:
        group_key = normalize_data_key(str(radio_group.get("groupKey") or radio_group.get("key") or ""))
        if not group_key:
            continue
        options = [
            {
                "optionKey": normalize_data_key(str(option.get("optionKey") or option.get("key") or "")),
                "optionLabel": str(option.get("optionLabel") or option.get("label") or ""),
            }
            for option in radio_group.get("options") or []
            if normalize_data_key(str(option.get("optionKey") or option.get("key") or ""))
        ]
        direct_radio_groups[group_key] = {
            "groupKey": group_key,
            "type": "radio",
            "options": options,
        }
        if options:
            example_data.setdefault(group_key, options[0]["optionKey"])

    for rule in checkbox_rules:
        database_field = normalize_data_key(str(rule.get("databaseField") or rule.get("key") or ""))
        group_key = normalize_data_key(str(rule.get("groupKey") or ""))
        if not database_field or not group_key:
            continue
        operation = normalize_data_key(str(rule.get("operation") or "yes_no")) or "yes_no"
        group = checkbox_groups.get(group_key) or {"groupKey": group_key, "type": "checkbox_group", "options": []}
        checkbox_rule_groups.append(
            {
                "key": database_field,
                "groupKey": group_key,
                "type": "checkbox_rule",
                "operation": operation,
                "options": group.get("options") or [],
                "trueOption": rule.get("trueOption"),
                "falseOption": rule.get("falseOption"),
                "valueMap": rule.get("valueMap") if isinstance(rule.get("valueMap"), dict) else None,
            }
        )
        if operation == "list":
            first_option = next(iter(group.get("options") or []), None)
            example_data.setdefault(database_field, [first_option.get("optionKey")] if first_option else [])
        elif operation == "enum":
            first_option = next(iter(group.get("options") or []), None)
            if first_option:
                example_data.setdefault(database_field, first_option.get("optionKey"))
        else:
            example_data.setdefault(database_field, True)

    return {
        "snapshotVersion": int(snapshot.get("version") or TEMPLATE_API_SNAPSHOT_VERSION),
        "defaultExportMode": _normalize_export_mode(snapshot.get("defaultExportMode")),
        "fields": sorted(scalar_fields, key=lambda entry: entry["key"]),
        "checkboxFields": sorted(checkbox_fields, key=lambda entry: entry["key"]),
        "checkboxGroups": sorted(checkbox_rule_groups, key=lambda entry: entry["key"]),
        "radioGroups": sorted(direct_radio_groups.values(), key=lambda entry: entry["groupKey"]),
        "exampleData": example_data,
    }


def resolve_template_api_request_data(
    snapshot: Dict[str, Any],
    data: Dict[str, Any],
    *,
    strict: bool = False,
) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="API Fill data must be a JSON object.")

    schema = build_template_api_schema(snapshot)
    scalar_keys = {str(entry.get("key") or "") for entry in schema.get("fields") or [] if isinstance(entry, dict)}
    checkbox_field_map = {
        str(entry.get("key") or ""): dict(entry)
        for entry in schema.get("checkboxFields") or []
        if isinstance(entry, dict) and str(entry.get("key") or "").strip()
    }
    checkbox_group_map = {
        str(entry.get("key") or ""): dict(entry)
        for entry in schema.get("checkboxGroups") or []
        if isinstance(entry, dict) and str(entry.get("key") or "").strip()
    }
    radio_group_map = {
        str(entry.get("groupKey") or ""): dict(entry)
        for entry in schema.get("radioGroups") or []
        if isinstance(entry, dict) and str(entry.get("groupKey") or "").strip()
    }

    resolved: Dict[str, Any] = {}
    errors: List[str] = []
    unknown_keys: List[str] = []

    for key, raw_value in data.items():
        normalized_key = normalize_data_key(str(key or ""))
        if not normalized_key or raw_value is None:
            continue
        if isinstance(raw_value, str) and not raw_value.strip():
            continue
        if normalized_key in scalar_keys:
            if isinstance(raw_value, (dict, list)):
                errors.append(f"{normalized_key} expects a scalar value.")
                continue
            resolved[normalized_key] = raw_value
            continue
        if normalized_key in checkbox_field_map:
            boolean_value = _coerce_checkbox_boolean(raw_value)
            if boolean_value is None:
                errors.append(f"{normalized_key} expects true or false.")
                continue
            resolved[normalized_key] = boolean_value
            continue
        if normalized_key in checkbox_group_map:
            try:
                resolved[normalized_key] = _resolve_checkbox_rule_value(
                    normalized_key,
                    raw_value,
                    checkbox_group_map[normalized_key],
                )
            except ValueError as exc:
                errors.append(str(exc))
            continue
        if normalized_key in radio_group_map:
            try:
                resolved[normalized_key] = _resolve_radio_group_value(
                    normalized_key,
                    raw_value,
                    radio_group_map[normalized_key],
                )
            except ValueError as exc:
                errors.append(str(exc))
            continue
        if strict:
            unknown_keys.append(normalized_key)

    if unknown_keys:
        unknown_label = ", ".join(sorted(unknown_keys))
        errors.append(f"Unknown API Fill keys: {unknown_label}.")
    if errors:
        raise HTTPException(status_code=400, detail=" ".join(errors))
    return resolved


def materialize_template_api_snapshot(
    snapshot: Dict[str, Any],
    *,
    data: Dict[str, Any],
    export_mode: Optional[str] = None,
    filename: Optional[str] = None,
):
    if not isinstance(snapshot, dict) or not snapshot:
        raise HTTPException(status_code=500, detail="Template API snapshot is missing.")
    resolved_snapshot = {
        "sourcePdfPath": snapshot.get("sourcePdfPath"),
        "fields": snapshot.get("fields") or [],
        "checkboxRules": snapshot.get("checkboxRules") or [],
        "textTransformRules": snapshot.get("textTransformRules") or [],
        "radioGroups": snapshot.get("radioGroups") or [],
        "downloadMode": _normalize_export_mode(export_mode or snapshot.get("defaultExportMode")),
        "filename": filename or snapshot.get("templateName") or "api-fill-response",
    }
    return materialize_fill_link_response_download(
        resolved_snapshot,
        answers=data,
        export_mode=export_mode,
    )
