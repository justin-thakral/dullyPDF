"""Fill By Link helpers for question derivation, public payloads, and limits."""

from __future__ import annotations

import base64
from collections import defaultdict
from dataclasses import dataclass
import hashlib
import hmac
import secrets
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from backend.env_utils import env_value as _env_value
from backend.logging_config import get_logger


_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_CAMEL_CASE_RE = re.compile(r"([a-z0-9])([A-Z])")
_KNOWN_BOOLEAN_TRUE = {"true", "1", "yes", "y", "on", "checked", "x"}
_KNOWN_BOOLEAN_FALSE = {"false", "0", "no", "n", "off", "unchecked"}
_CLOSED_REASONS_BLOCKING_DOWNLOAD = frozenset({
    "template_deleted",
    "group_deleted",
    "group_updated",
    "downgrade_retention",
})
"""Closed reasons that make the underlying PDF asset unavailable.

User-initiated closures (``owner_closed``) and limit-based closures
(``response_limit``, ``downgrade_link_limit``) should still allow
respondents to download PDFs for responses that were already submitted.
"""

_RESPONDENT_IDENTIFIER_KEY = "respondent_identifier"
_RESPONDENT_IDENTIFIER_LABEL = "Respondent Name or ID"
_PUBLIC_TOKEN_PREFIX = "v2"
_IDENTIFIER_NAME_KEYS = {
    "full_name",
    "name",
    "patient_name",
    "respondent_name",
    "first_name",
    "last_name",
}
_IDENTIFIER_ID_KEYS = {
    "id",
    "member_id",
    "patient_id",
    "record_id",
    "user_id",
    "employee_id",
    "customer_id",
    "case_id",
    "mrn",
}
_FILL_LINK_WEB_FORM_SCHEMA_VERSION = 2
_FILL_LINK_TEXT_TYPES = frozenset({"text", "textarea", "date", "email", "phone"})
_FILL_LINK_OPTION_TYPES = frozenset({"radio", "multi_select", "select"})
_FILL_LINK_BOOLEAN_TYPES = frozenset({"boolean", "checkbox"})
logger = get_logger(__name__)
_DEV_FILL_LINK_TOKEN_SECRET = secrets.token_urlsafe(48)
_WARNED_DEV_FILL_LINK_TOKEN_SECRET = False


@dataclass(frozen=True)
class FillLinkAnswerLimits:
    max_value_chars: int
    max_total_chars: int
    max_multi_select_values: int


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    try:
        value = int(_env_value(name) or str(default))
    except ValueError:
        value = default
    return max(minimum, value)


def _is_prod_env() -> bool:
    return (_env_value("ENV") or "").strip().lower() in {"prod", "production"}


def fill_link_token_secret_is_weak(secret: Optional[str]) -> bool:
    normalized = (secret or "").strip()
    if not normalized:
        return True
    if normalized in {
        "change_me_prod_fill_link_token_secret",
        "dullypdf-fill-link-dev-secret",
        "fill-link-secret",
    }:
        return True
    return len(normalized) < 32


def _resolve_fill_link_token_secret() -> str:
    secret = (_env_value("FILL_LINK_TOKEN_SECRET") or "").strip()
    if secret and not (_is_prod_env() and fill_link_token_secret_is_weak(secret)):
        return secret
    if _is_prod_env():
        raise RuntimeError("FILL_LINK_TOKEN_SECRET must be unique and at least 32 characters in production")
    global _WARNED_DEV_FILL_LINK_TOKEN_SECRET
    if not _WARNED_DEV_FILL_LINK_TOKEN_SECRET:
        logger.warning(
            "FILL_LINK_TOKEN_SECRET is unset outside production; using a process-local ephemeral secret. "
            "Public Fill By Link tokens created in this process will stop working after the backend restarts."
        )
        _WARNED_DEV_FILL_LINK_TOKEN_SECRET = True
    return _DEV_FILL_LINK_TOKEN_SECRET


def _urlsafe_b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _urlsafe_b64decode(value: str) -> bytes:
    padded = value + ("=" * ((4 - (len(value) % 4)) % 4))
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _fill_link_signature(link_id: str) -> str:
    digest = hmac.new(
        _resolve_fill_link_token_secret().encode("utf-8"),
        f"fill_link:{link_id}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _urlsafe_b64encode(digest)


def normalize_fill_link_token(value: Optional[str]) -> str:
    token = (value or "").strip()
    if not token:
        return ""
    return re.sub(r"[^A-Za-z0-9_.-]", "", token)

def build_fill_link_public_token(link_id: str) -> str:
    normalized_link_id = (link_id or "").strip()
    if not normalized_link_id:
        raise ValueError("link_id is required")
    return ".".join(
        [
            _PUBLIC_TOKEN_PREFIX,
            _urlsafe_b64encode(normalized_link_id.encode("utf-8")),
            _fill_link_signature(normalized_link_id),
        ]
    )


def parse_fill_link_public_token(token: Optional[str]) -> Optional[str]:
    normalized = normalize_fill_link_token(token)
    if not normalized:
        return None
    parts = normalized.split(".")
    if len(parts) != 3 or parts[0] != _PUBLIC_TOKEN_PREFIX:
        return None
    try:
        link_id = _urlsafe_b64decode(parts[1]).decode("utf-8").strip()
    except Exception:
        return None
    if not link_id:
        return None
    expected_signature = _fill_link_signature(link_id)
    if not hmac.compare_digest(parts[2], expected_signature):
        return None
    return link_id


def allow_legacy_fill_link_public_tokens() -> bool:
    raw = (_env_value("FILL_LINK_ALLOW_LEGACY_PUBLIC_TOKENS") or "").strip().lower()
    if not raw:
        return False
    return raw in {"1", "true", "yes"}


def normalize_fill_link_key(value: Optional[str]) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    collapsed = _CAMEL_CASE_RE.sub(r"\1_\2", raw)
    return _NON_ALNUM_RE.sub("_", collapsed.lower()).strip("_")


def humanize_fill_link_label(value: Optional[str], *, fallback: str = "Field") -> str:
    raw = (value or "").strip()
    if not raw:
        return fallback
    collapsed = _CAMEL_CASE_RE.sub(r"\1 \2", raw)
    collapsed = re.sub(r"[_\-.]+", " ", collapsed)
    collapsed = re.sub(r"\s+", " ", collapsed).strip()
    if not collapsed:
        return fallback
    words = collapsed.split(" ")
    formatted: list[str] = []
    for word in words:
        upper_word = word.upper()
        if upper_word in {"SSN", "DOB", "ZIP", "ID", "MRN", "PDF", "URL"}:
            formatted.append(upper_word)
            continue
        formatted.append(word[:1].upper() + word[1:])
    return " ".join(formatted)


def resolve_fill_link_submit_rate_limits() -> Tuple[int, int, int]:
    window_seconds = _env_int("FILL_LINK_SUBMIT_RATE_WINDOW_SECONDS", 300, minimum=1)
    per_ip = _env_int("FILL_LINK_SUBMIT_RATE_PER_IP", 20, minimum=1)
    global_limit = _env_int("FILL_LINK_SUBMIT_RATE_GLOBAL", 0, minimum=0)
    return window_seconds, per_ip, global_limit


def resolve_fill_link_view_rate_limits() -> Tuple[int, int, int]:
    window_seconds = _env_int("FILL_LINK_VIEW_RATE_WINDOW_SECONDS", 60, minimum=1)
    per_ip = _env_int("FILL_LINK_VIEW_RATE_PER_IP", 60, minimum=1)
    global_limit = _env_int("FILL_LINK_VIEW_RATE_GLOBAL", 0, minimum=0)
    return window_seconds, per_ip, global_limit


def is_closed_reason_blocking_download(closed_reason: Optional[str]) -> bool:
    """Return ``True`` when a link's closed reason makes PDF download impossible."""
    return normalize_fill_link_key(closed_reason) in _CLOSED_REASONS_BLOCKING_DOWNLOAD


def resolve_fill_link_download_rate_limits() -> Tuple[int, int, int]:
    window_seconds = _env_int("FILL_LINK_DOWNLOAD_RATE_WINDOW_SECONDS", 300, minimum=1)
    per_ip = _env_int("FILL_LINK_DOWNLOAD_RATE_PER_IP", 20, minimum=1)
    global_limit = _env_int("FILL_LINK_DOWNLOAD_RATE_GLOBAL", 0, minimum=0)
    return window_seconds, per_ip, global_limit


def resolve_fill_link_answer_limits() -> FillLinkAnswerLimits:
    return FillLinkAnswerLimits(
        max_value_chars=_env_int("FILL_LINK_MAX_ANSWER_VALUE_CHARS", 500, minimum=32),
        max_total_chars=_env_int("FILL_LINK_MAX_TOTAL_ANSWER_CHARS", 4000, minimum=256),
        max_multi_select_values=_env_int("FILL_LINK_MAX_MULTI_SELECT_VALUES", 25, minimum=1),
    )


def _question_supports_respondent_identity(question: Dict[str, Any]) -> bool:
    if bool(question.get("requiredForRespondentIdentity")):
        return True
    candidates = {
        normalize_fill_link_key(question.get("key")),
        normalize_fill_link_key(question.get("sourceField")),
        normalize_fill_link_key(question.get("label")),
    }
    return any(
        candidate in _IDENTIFIER_NAME_KEYS
        or candidate in _IDENTIFIER_ID_KEYS
        or candidate.endswith("_id")
        for candidate in candidates
        if candidate
    )


def _ensure_fill_link_identifier_question(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized_questions: list[dict[str, Any]] = []
    found_identifier = False
    for index, question in enumerate(questions):
        if not isinstance(question, dict):
            continue
        next_question = dict(question)
        if _question_supports_respondent_identity(next_question):
            next_question["requiredForRespondentIdentity"] = True
            found_identifier = True
        next_question.setdefault("id", _default_fill_link_question_id(next_question.get("key"), next_question.get("sourceType")))
        next_question.setdefault("visible", True)
        next_question.setdefault("required", False)
        next_question.setdefault("order", index)
        normalized_questions.append(next_question)
    if found_identifier:
        return normalized_questions
    synthetic_question = {
        "id": _default_fill_link_question_id(_RESPONDENT_IDENTIFIER_KEY, "synthetic"),
        "key": _RESPONDENT_IDENTIFIER_KEY,
        "label": _RESPONDENT_IDENTIFIER_LABEL,
        "type": "text",
        "sourceType": "synthetic",
        "requiredForRespondentIdentity": True,
        "required": True,
        "synthetic": True,
        "visible": True,
        "order": -1,
    }
    return [synthetic_question, *normalized_questions]


def _normalize_rule_map(checkbox_rules: Optional[List[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    normalized: Dict[str, Dict[str, Any]] = {}
    for rule in checkbox_rules or []:
        if not isinstance(rule, dict):
            continue
        group_key = normalize_fill_link_key(rule.get("groupKey"))
        if not group_key or group_key in normalized:
            continue
        normalized[group_key] = rule
    return normalized


def _field_sort_key(field: Dict[str, Any]) -> Tuple[int, float, float, str]:
    rect = field.get("rect")
    page = field.get("page")
    rect_x = 0.0
    rect_y = 0.0
    if isinstance(rect, dict):
        try:
            rect_x = float(rect.get("x") or 0.0)
        except (TypeError, ValueError):
            rect_x = 0.0
        try:
            rect_y = float(rect.get("y") or 0.0)
        except (TypeError, ValueError):
            rect_y = 0.0
    try:
        page_value = int(page or 0)
    except (TypeError, ValueError):
        page_value = 0
    return (page_value, rect_y, rect_x, str(field.get("name") or ""))


def _resolve_checkbox_question_type(
    option_count: int,
    operation: Optional[str],
) -> str:
    normalized_operation = normalize_fill_link_key(operation)
    if normalized_operation == "list":
        return "multi_select"
    if option_count <= 1:
        return "boolean"
    return "radio"


def _question_supports_text_limits(question_type: Optional[str]) -> bool:
    return normalize_fill_link_key(question_type) in _FILL_LINK_TEXT_TYPES


def _question_supports_options(question_type: Optional[str]) -> bool:
    return normalize_fill_link_key(question_type) in _FILL_LINK_OPTION_TYPES


def _question_is_boolean(question_type: Optional[str]) -> bool:
    return normalize_fill_link_key(question_type) in _FILL_LINK_BOOLEAN_TYPES


def _normalize_question_type(question_type: Optional[str]) -> str:
    normalized = normalize_fill_link_key(question_type) or "text"
    if normalized == "checkbox":
        return "boolean"
    if normalized in _FILL_LINK_TEXT_TYPES | _FILL_LINK_OPTION_TYPES | _FILL_LINK_BOOLEAN_TYPES:
        return normalized
    return "text"


def _question_candidate_keys(question: Dict[str, Any]) -> List[str]:
    return [
        _normalize_question_type(question.get("type")),
        normalize_fill_link_key(question.get("key")),
        normalize_fill_link_key(question.get("sourceField")),
        normalize_fill_link_key(question.get("label")),
    ]


def _question_looks_like_email(question: Dict[str, Any]) -> bool:
    for candidate in _question_candidate_keys(question):
        if not candidate:
            continue
        if candidate == "email" or candidate.endswith("_email") or "email_address" in candidate:
            return True
    return False


def _question_looks_like_phone(question: Dict[str, Any]) -> bool:
    for candidate in _question_candidate_keys(question):
        if not candidate:
            continue
        if candidate in {"phone", "mobile_phone", "telephone"}:
            return True
        if candidate.endswith("_phone") or candidate.endswith("_telephone"):
            return True
    return False


def _infer_text_question_type(field_type: Optional[str], source_field: Optional[str]) -> str:
    normalized_field_type = normalize_fill_link_key(field_type) or "text"
    if normalized_field_type == "date":
        return "date"
    probe = {
        "type": normalized_field_type,
        "key": source_field,
        "sourceField": source_field,
        "label": source_field,
    }
    if _question_looks_like_email(probe):
        return "email"
    if _question_looks_like_phone(probe):
        return "phone"
    return "text"


def _normalize_positive_int(value: Any, *, maximum: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return None
    if numeric <= 0:
        return None
    if maximum is not None:
        numeric = min(numeric, maximum)
    return numeric


def _default_fill_link_question_id(key: Optional[str], source_type: Optional[str]) -> str:
    normalized_key = normalize_fill_link_key(key) or "question"
    normalized_source = normalize_fill_link_key(source_type) or "question"
    return f"{normalized_source}:{normalized_key}"


def _normalize_fill_link_option(option: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(option, dict):
        return None
    option_key = _coerce_text_answer(option.get("key")) or normalize_fill_link_key(option.get("label"))
    normalized_option_key = normalize_fill_link_key(option_key)
    if not normalized_option_key:
        return None
    return {
        "key": option_key,
        "label": humanize_fill_link_label(option.get("label") or option_key, fallback="Option"),
    }


def build_fill_link_questions(
    fields: List[Dict[str, Any]],
    checkbox_rules: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Derive a compact mobile form schema from saved template fields.

    Complexity is O(n log n) because the incoming fields are sorted once before
    grouping repeated text fields and checkbox clusters into a smaller question
    set suitable for respondent-facing HTML rendering.
    """
    ordered_fields = sorted([field for field in fields if isinstance(field, dict)], key=_field_sort_key)
    rule_map = _normalize_rule_map(checkbox_rules)
    questions: list[dict[str, Any]] = []
    seen_text_keys: set[str] = set()
    radio_groups: dict[str, dict[str, Any]] = {}
    checkbox_groups: dict[str, dict[str, Any]] = {}

    for field in ordered_fields:
        field_type = normalize_fill_link_key(field.get("type")) or "text"
        if field_type == "radio":
            raw_group_key = (
                _coerce_text_answer(field.get("radioGroupKey"))
                or _coerce_text_answer(field.get("radioGroupLabel"))
                or _coerce_text_answer(field.get("group"))
                or _coerce_text_answer(field.get("name"))
            )
            normalized_group_key = normalize_fill_link_key(raw_group_key)
            if not raw_group_key or not normalized_group_key:
                continue
            group = radio_groups.get(normalized_group_key)
            if group is None:
                group = {
                    "id": _default_fill_link_question_id(raw_group_key, "radio_group"),
                    "key": raw_group_key,
                    "label": humanize_fill_link_label(field.get("radioGroupLabel") or raw_group_key, fallback="Choice"),
                    "type": "radio",
                    "sourceType": "radio_group",
                    "sourceField": raw_group_key,
                    "groupKey": raw_group_key,
                    "options": [],
                    "visible": True,
                    "required": False,
                    "order": len(questions),
                }
                radio_groups[normalized_group_key] = group
                questions.append(group)

            option_key = (
                _coerce_text_answer(field.get("radioOptionKey"))
                or _coerce_text_answer(field.get("exportValue"))
                or _coerce_text_answer(field.get("name"))
            )
            option_label = (
                _coerce_text_answer(field.get("radioOptionLabel"))
                or _coerce_text_answer(field.get("optionLabel"))
                or option_key
            )
            normalized_option_key = normalize_fill_link_key(option_key or option_label)
            if not normalized_option_key:
                continue
            if any(normalize_fill_link_key(option.get("key")) == normalized_option_key for option in group["options"]):
                continue
            group["options"].append(
                {
                    "key": option_key or normalized_option_key,
                    "label": humanize_fill_link_label(option_label, fallback="Option"),
                }
            )
            continue

        if field_type != "checkbox":
            source_field = (field.get("name") or "").strip()
            normalized_key = normalize_fill_link_key(source_field)
            if not source_field or not normalized_key or normalized_key in seen_text_keys:
                continue
            seen_text_keys.add(normalized_key)
            question_type = _infer_text_question_type(field_type, source_field)
            questions.append(
                {
                    "id": _default_fill_link_question_id(source_field, "pdf_field"),
                    "key": source_field,
                    "label": humanize_fill_link_label(source_field),
                    "type": question_type,
                    "sourceType": "pdf_field",
                    "sourceField": source_field,
                    "visible": True,
                    "required": False,
                    "order": len(questions),
                }
            )
            continue

        raw_group_key = (field.get("groupKey") or field.get("name") or "").strip()
        normalized_group_key = normalize_fill_link_key(raw_group_key)
        if not raw_group_key or not normalized_group_key:
            continue
        rule = rule_map.get(normalized_group_key)
        answer_key = (rule.get("databaseField") or raw_group_key).strip() if isinstance(rule, dict) else raw_group_key
        group = checkbox_groups.get(normalized_group_key)
        if group is None:
            label_source = field.get("groupLabel") or (rule.get("databaseField") if isinstance(rule, dict) else None) or raw_group_key
            group = {
                "id": _default_fill_link_question_id(answer_key, "checkbox_group"),
                "key": answer_key,
                "label": humanize_fill_link_label(label_source, fallback="Choice"),
                "type": "radio",
                "sourceType": "checkbox_group",
                "groupKey": raw_group_key,
                "options": [],
                "operation": rule.get("operation") if isinstance(rule, dict) else None,
                "visible": True,
                "required": False,
                "order": len(questions),
            }
            checkbox_groups[normalized_group_key] = group
            questions.append(group)

        option_key = (field.get("optionKey") or field.get("name") or "").strip()
        option_label = (field.get("optionLabel") or option_key).strip()
        normalized_option_key = normalize_fill_link_key(option_key or option_label)
        if not normalized_option_key:
            continue
        if any(normalize_fill_link_key(option.get("key")) == normalized_option_key for option in group["options"]):
            continue
        group["options"].append(
            {
                "key": option_key or normalized_option_key,
                "label": humanize_fill_link_label(option_label, fallback="Option"),
            }
        )

    for question in questions:
        if question.get("groupKey"):
            options = question.get("options") if isinstance(question.get("options"), list) else []
            question["type"] = _resolve_checkbox_question_type(len(options), question.get("operation"))
            if question["type"] == "boolean":
                question.pop("options", None)
    return _ensure_fill_link_identifier_question(questions)


def _dedupe_fill_link_options(options: Any) -> List[Dict[str, Any]]:
    if not isinstance(options, list):
        return []
    deduped: List[Dict[str, Any]] = []
    seen_option_keys: set[str] = set()
    for option in options:
        normalized = _normalize_fill_link_option(option)
        if not normalized:
            continue
        normalized_option_key = normalize_fill_link_key(normalized.get("key"))
        if not normalized_option_key or normalized_option_key in seen_option_keys:
            continue
        seen_option_keys.add(normalized_option_key)
        deduped.append(normalized)
    return deduped


def _merge_fill_link_question_type(left_type: str, right_type: str) -> str:
    normalized = {_normalize_question_type(left_type), _normalize_question_type(right_type)}
    if "multi_select" in normalized:
        return "multi_select"
    if "select" in normalized:
        return "select"
    if "radio" in normalized:
        return "radio"
    if normalized == {"date"}:
        return "date"
    if "boolean" in normalized and len(normalized) == 1:
        return "boolean"
    return "text"


def _merge_fill_link_question(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(existing)
    merged["label"] = _coerce_text_answer(existing.get("label")) or _coerce_text_answer(incoming.get("label")) or "Field"
    merged["type"] = _merge_fill_link_question_type(
        _coerce_text_answer(existing.get("type")) or "text",
        _coerce_text_answer(incoming.get("type")) or "text",
    )
    merged["id"] = (
        _coerce_text_answer(existing.get("id"))
        or _coerce_text_answer(incoming.get("id"))
        or _default_fill_link_question_id(existing.get("key") or incoming.get("key"), existing.get("sourceType") or incoming.get("sourceType"))
    )
    merged["sourceType"] = _coerce_text_answer(existing.get("sourceType")) or _coerce_text_answer(incoming.get("sourceType")) or "pdf_field"
    merged["requiredForRespondentIdentity"] = bool(
        existing.get("requiredForRespondentIdentity") or incoming.get("requiredForRespondentIdentity")
    )
    merged["required"] = bool(existing.get("required") or incoming.get("required"))
    merged["visible"] = existing.get("visible") is not False or incoming.get("visible") is not False
    if not merged.get("sourceField") and incoming.get("sourceField"):
        merged["sourceField"] = incoming.get("sourceField")
    if not merged.get("groupKey") and incoming.get("groupKey"):
        merged["groupKey"] = incoming.get("groupKey")
    if not merged.get("operation") and incoming.get("operation"):
        merged["operation"] = incoming.get("operation")
    existing_order = _normalize_positive_int(existing.get("order"))
    incoming_order = _normalize_positive_int(incoming.get("order"))
    if existing_order is not None or incoming_order is not None:
        merged["order"] = min(
            value
            for value in [existing_order, incoming_order]
            if value is not None
        )
    merged_options = _dedupe_fill_link_options(
        [*(_dedupe_fill_link_options(existing.get("options"))), *(_dedupe_fill_link_options(incoming.get("options")))]
    )
    if merged_options:
        merged["options"] = merged_options
    elif "options" in merged:
        merged.pop("options", None)
    if merged.get("synthetic") or incoming.get("synthetic"):
        merged["synthetic"] = True
    return merged


def merge_fill_link_questions(question_sets: Iterable[Iterable[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Merge multiple template question lists into one respondent schema.

    Complexity is O(n + m) over questions and option entries because each
    normalized question key is merged once and option keys are deduped through
    hash-set lookups.
    """
    merged: List[Dict[str, Any]] = []
    question_index_by_key: Dict[str, int] = {}

    for questions in question_sets:
        for question in questions:
            if not isinstance(question, dict):
                continue
            key = _coerce_text_answer(question.get("key"))
            normalized_key = normalize_fill_link_key(key)
            if not key or not normalized_key:
                continue
            normalized_question = dict(question)
            normalized_question["key"] = key
            normalized_question["label"] = humanize_fill_link_label(question.get("label") or key)
            options = _dedupe_fill_link_options(question.get("options"))
            if options:
                normalized_question["options"] = options
            elif "options" in normalized_question:
                normalized_question.pop("options", None)
            existing_index = question_index_by_key.get(normalized_key)
            if existing_index is None:
                question_index_by_key[normalized_key] = len(merged)
                merged.append(normalized_question)
                continue
            merged[existing_index] = _merge_fill_link_question(merged[existing_index], normalized_question)

    return _ensure_fill_link_identifier_question(merged)


def build_group_fill_link_questions(template_sources: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build one merged question set from multiple template field/rule sources."""
    question_sets: List[List[Dict[str, Any]]] = []
    for source in template_sources:
        if not isinstance(source, dict):
            continue
        fields = source.get("fields")
        checkbox_rules = source.get("checkboxRules")
        next_questions = build_fill_link_questions(
            fields if isinstance(fields, list) else [],
            checkbox_rules if isinstance(checkbox_rules, list) else None,
        )
        if next_questions:
            question_sets.append(next_questions)
    return merge_fill_link_questions(question_sets)


def _normalize_fill_link_builder_question(
    question: Dict[str, Any],
    *,
    fallback_order: int,
) -> Optional[Dict[str, Any]]:
    if not isinstance(question, dict):
        return None
    source_type = normalize_fill_link_key(question.get("sourceType"))
    if not source_type:
        if question.get("synthetic"):
            source_type = "synthetic"
        elif question.get("groupKey"):
            source_type = "checkbox_group"
        elif normalize_fill_link_key(question.get("key")).startswith("custom"):
            source_type = "custom"
        else:
            source_type = "pdf_field"
    key = _coerce_text_answer(question.get("key") or question.get("sourceField"))
    if not key:
        key = _RESPONDENT_IDENTIFIER_KEY
    question_type = _normalize_question_type(question.get("type"))
    normalized: Dict[str, Any] = {
        "id": _coerce_text_answer(question.get("id")) or _default_fill_link_question_id(key, source_type),
        "key": key,
        "label": humanize_fill_link_label(question.get("label") or key),
        "type": question_type,
        "sourceType": source_type,
        "requiredForRespondentIdentity": bool(
            question.get("requiredForRespondentIdentity") or _question_supports_respondent_identity(question)
        ),
        "required": bool(question.get("required")),
        "synthetic": bool(question.get("synthetic")),
        "visible": question.get("visible") is not False,
        "order": _normalize_positive_int(question.get("order")) or fallback_order,
        "sourceField": _coerce_text_answer(question.get("sourceField")),
        "groupKey": _coerce_text_answer(question.get("groupKey")),
        "placeholder": _coerce_text_answer(question.get("placeholder")),
        "helpText": _coerce_text_answer(question.get("helpText")),
    }
    if normalized["requiredForRespondentIdentity"] and normalized["synthetic"]:
        normalized["required"] = True
    if _question_supports_text_limits(question_type):
        normalized["maxLength"] = _normalize_positive_int(question.get("maxLength"), maximum=4000)
    if _question_supports_options(question_type):
        normalized["options"] = _dedupe_fill_link_options(question.get("options"))
    return normalized


def _apply_fill_link_builder_overrides(
    base_question: Dict[str, Any],
    override_question: Dict[str, Any],
) -> Dict[str, Any]:
    next_question = dict(base_question)
    next_question["label"] = _coerce_text_answer(override_question.get("label")) or next_question.get("label")
    next_question["visible"] = override_question.get("visible") is not False
    next_question["required"] = bool(override_question.get("required"))
    next_question["order"] = _normalize_positive_int(override_question.get("order")) or next_question.get("order") or 0
    next_question["placeholder"] = _coerce_text_answer(override_question.get("placeholder"))
    next_question["helpText"] = _coerce_text_answer(override_question.get("helpText"))
    if _question_supports_text_limits(next_question.get("type")):
        next_question["maxLength"] = _normalize_positive_int(override_question.get("maxLength"), maximum=4000)
    else:
        next_question.pop("maxLength", None)
    return next_question


def _sort_fill_link_builder_questions(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sortable: List[Tuple[int, int, Dict[str, Any]]] = []
    for index, question in enumerate(questions):
        sortable.append((_normalize_positive_int(question.get("order")) or index, index, dict(question)))
    sortable.sort(key=lambda item: (item[0], item[1]))
    normalized: List[Dict[str, Any]] = []
    for index, (_, __, question) in enumerate(sortable):
        next_question = dict(question)
        next_question["order"] = index
        normalized.append(next_question)
    return normalized


def _question_is_signing_ceremony_managed(question: Dict[str, Any]) -> bool:
    candidates = [
        normalize_fill_link_key(question.get("type")),
        normalize_fill_link_key(question.get("key")),
        normalize_fill_link_key(question.get("sourceField")),
        normalize_fill_link_key(question.get("label")),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if (
            candidate == "signature"
            or candidate.endswith("_signature")
            or candidate.startswith("signature_")
            or "_signature_" in candidate
        ):
            return True
    return False


def build_fill_link_web_form_schema(
    default_questions: List[Dict[str, Any]],
    *,
    require_all_fields: bool = False,
    web_form_config: Optional[Dict[str, Any]] = None,
    allow_custom_questions: bool = True,
    exclude_signing_questions: bool = False,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    normalized_default_questions: List[Dict[str, Any]] = []
    for index, default_question in enumerate(_ensure_fill_link_identifier_question(default_questions)):
        normalized_question = _normalize_fill_link_builder_question(default_question, fallback_order=index)
        if normalized_question is None:
            continue
        normalized_default_questions.append(normalized_question)
    normalized_defaults = _sort_fill_link_builder_questions(normalized_default_questions)
    default_by_id = {
        normalize_fill_link_key(question.get("id")): question
        for question in normalized_defaults
        if normalize_fill_link_key(question.get("id"))
    }
    default_by_key = {
        normalize_fill_link_key(question.get("key")): question
        for question in normalized_defaults
        if normalize_fill_link_key(question.get("key"))
    }

    incoming_questions = web_form_config.get("questions") if isinstance(web_form_config, dict) else None
    stored_questions: List[Dict[str, Any]] = []
    seen_default_keys: set[str] = set()
    seen_custom_ids: set[str] = set()

    if isinstance(incoming_questions, list):
        for index, raw_question in enumerate(incoming_questions):
            normalized_question = _normalize_fill_link_builder_question(raw_question, fallback_order=index)
            if not normalized_question:
                continue
            if normalized_question.get("sourceType") == "custom":
                if not allow_custom_questions:
                    raise ValueError("Custom web-form questions are currently supported only for template Fill By Link.")
                normalized_id = normalize_fill_link_key(normalized_question.get("id"))
                if normalized_id and normalized_id in seen_custom_ids:
                    continue
                if normalized_id:
                    seen_custom_ids.add(normalized_id)
                stored_questions.append(normalized_question)
                continue

            matched_default = (
                default_by_id.get(normalize_fill_link_key(normalized_question.get("id")))
                or default_by_key.get(normalize_fill_link_key(normalized_question.get("key")))
                or default_by_key.get(normalize_fill_link_key(normalized_question.get("sourceField")))
            )
            if not matched_default:
                continue
            seen_default_keys.add(normalize_fill_link_key(matched_default.get("key")))
            stored_questions.append(_apply_fill_link_builder_overrides(matched_default, normalized_question))
    else:
        stored_questions = [dict(question) for question in normalized_defaults]

    for default_question in normalized_defaults:
        normalized_key = normalize_fill_link_key(default_question.get("key"))
        if normalized_key in seen_default_keys:
            continue
        stored_questions.append(dict(default_question))

    stored_questions = _sort_fill_link_builder_questions(
        _ensure_fill_link_identifier_question(stored_questions)
    )

    default_text_max_length = _normalize_positive_int(
        web_form_config.get("defaultTextMaxLength") if isinstance(web_form_config, dict) else None,
        maximum=4000,
    )
    published_questions: List[Dict[str, Any]] = []
    for question in stored_questions:
        if question.get("visible") is False:
            continue
        if exclude_signing_questions and _question_is_signing_ceremony_managed(question):
            continue
        question_type = _normalize_question_type(question.get("type"))
        next_question = dict(question)
        next_question["type"] = question_type
        next_question["required"] = bool(
            require_all_fields
            or question.get("required")
            or (question.get("synthetic") and question.get("requiredForRespondentIdentity"))
        )
        next_question["visible"] = True
        next_question["order"] = len(published_questions)
        if _question_supports_text_limits(question_type):
            next_question["maxLength"] = _normalize_positive_int(
                question.get("maxLength"),
                maximum=4000,
            ) or default_text_max_length
        else:
            next_question.pop("maxLength", None)
        if _question_supports_options(question_type):
            options = _dedupe_fill_link_options(question.get("options"))
            if not options:
                label = humanize_fill_link_label(question.get("label") or question.get("key"))
                raise ValueError(f"{label} needs at least one option before publishing.")
            next_question["options"] = options
        else:
            next_question.pop("options", None)
        if _question_is_boolean(question_type):
            next_question.pop("options", None)
            next_question.pop("maxLength", None)
        published_questions.append(next_question)

    if not any(question.get("requiredForRespondentIdentity") for question in published_questions):
        synthetic_question = _normalize_fill_link_builder_question(
            {
                "id": _default_fill_link_question_id(_RESPONDENT_IDENTIFIER_KEY, "synthetic"),
                "key": _RESPONDENT_IDENTIFIER_KEY,
                "label": _RESPONDENT_IDENTIFIER_LABEL,
                "type": "text",
                "sourceType": "synthetic",
                "required": True,
                "requiredForRespondentIdentity": True,
                "synthetic": True,
                "visible": True,
                "maxLength": default_text_max_length,
                "order": 0,
            },
            fallback_order=0,
        )
        if synthetic_question:
            published_questions = _sort_fill_link_builder_questions([synthetic_question, *published_questions])

    stored_config = {
        "schemaVersion": _FILL_LINK_WEB_FORM_SCHEMA_VERSION,
        "introText": _coerce_text_answer(web_form_config.get("introText")) if isinstance(web_form_config, dict) else None,
        "defaultTextMaxLength": default_text_max_length,
        "questions": stored_questions,
    }
    return stored_config, published_questions


def _coerce_boolean_answer(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    if isinstance(value, str):
        normalized = normalize_fill_link_key(value)
        if normalized in _KNOWN_BOOLEAN_TRUE:
            return True
        if normalized in _KNOWN_BOOLEAN_FALSE:
            return False
    return None


def _coerce_text_answer(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, list):
        for item in value:
            text = _coerce_text_answer(item)
            if text:
                return text
        return None
    text = str(value).strip()
    return text or None


def _coerce_multi_value_answer(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        values = [str(item).strip() for item in value]
    else:
        raw = str(value).strip()
        if not raw:
            return []
        values = [part.strip() for part in re.split(r"[,;|/]+", raw)]
    deduped: list[str] = []
    for entry in values:
        if not entry or entry in deduped:
            continue
        deduped.append(entry)
    return deduped


def _resolve_allowed_option_keys(question: Dict[str, Any]) -> List[str]:
    options = question.get("options")
    if not isinstance(options, list):
        return []
    allowed: list[str] = []
    for option in options:
        if not isinstance(option, dict):
            continue
        option_key = _coerce_text_answer(option.get("key"))
        if option_key and option_key not in allowed:
            allowed.append(option_key)
    return allowed


def _answer_size_error(label: str, *, max_chars: int) -> ValueError:
    return ValueError(f"{label} is too long. Limit {max_chars} characters.")


def coerce_fill_link_answers(
    answers: Optional[Dict[str, Any]],
    questions: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    payload = answers if isinstance(answers, dict) else {}
    limits = resolve_fill_link_answer_limits()
    normalized: Dict[str, Any] = {}
    total_chars = 0
    for question in questions:
        if not isinstance(question, dict):
            continue
        key = (question.get("key") or "").strip()
        if not key or key not in payload:
            continue
        label = humanize_fill_link_label(question.get("label") or key)
        question_type = _normalize_question_type(question.get("type"))
        raw_value = payload.get(key)
        max_chars = _normalize_positive_int(question.get("maxLength"), maximum=limits.max_value_chars) or limits.max_value_chars
        if question_type == "boolean":
            coerced = _coerce_boolean_answer(raw_value)
            if coerced is not None:
                normalized[key] = coerced
            continue
        if question_type in {"radio", "select"}:
            coerced_text = _coerce_text_answer(raw_value)
            if coerced_text is None:
                continue
            if len(coerced_text) > max_chars:
                raise _answer_size_error(label, max_chars=max_chars)
            allowed_options = _resolve_allowed_option_keys(question)
            if allowed_options and coerced_text not in allowed_options:
                raise ValueError(f"{label} contains an unsupported option.")
            total_chars += len(coerced_text)
            normalized[key] = coerced_text
            continue
        if question_type == "multi_select":
            coerced = _coerce_multi_value_answer(raw_value)
            if not coerced:
                continue
            if len(coerced) > limits.max_multi_select_values:
                raise ValueError(f"{label} has too many selections.")
            allowed_options = _resolve_allowed_option_keys(question)
            for entry in coerced:
                if len(entry) > max_chars:
                    raise _answer_size_error(label, max_chars=max_chars)
                if allowed_options and entry not in allowed_options:
                    raise ValueError(f"{label} contains an unsupported option.")
                total_chars += len(entry)
            normalized[key] = coerced
            continue
        coerced_text = _coerce_text_answer(raw_value)
        if coerced_text is None:
            continue
        if len(coerced_text) > max_chars:
            raise _answer_size_error(label, max_chars=max_chars)
        total_chars += len(coerced_text)
        normalized[key] = coerced_text
    if total_chars > limits.max_total_chars:
        raise ValueError("Response is too large. Shorten one or more answers and try again.")
    return normalized


def list_missing_required_fill_link_questions(
    answers: Optional[Dict[str, Any]],
    questions: Iterable[Dict[str, Any]],
    *,
    require_all_fields: bool = False,
) -> List[str]:
    """Return respondent-facing labels for required Fill By Link questions that were left blank.

    Complexity is O(n) over the derived question list. The answers payload is
    already key-addressable, so each question is validated once with type-aware
    checks instead of scanning field-level data structures repeatedly.
    """
    payload = answers if isinstance(answers, dict) else {}
    missing: list[str] = []

    for question in questions:
        if not isinstance(question, dict):
            continue
        key = (question.get("key") or "").strip()
        if not key:
            continue
        if not (require_all_fields or bool(question.get("required"))):
            continue
        label = humanize_fill_link_label(question.get("label") or key)
        question_type = _normalize_question_type(question.get("type"))
        raw_value = payload.get(key)

        if question_type == "boolean":
            if key not in payload or _coerce_boolean_answer(raw_value) is None:
                missing.append(label)
            continue
        if question_type == "multi_select":
            if not _coerce_multi_value_answer(raw_value):
                missing.append(label)
            continue
        if question_type in {"radio", "select"}:
            if _coerce_text_answer(raw_value) is None:
                missing.append(label)
            continue
        if _coerce_text_answer(raw_value) is None:
            missing.append(label)

    return missing


def format_missing_fill_link_questions_message(labels: Iterable[str]) -> str:
    deduped: list[str] = []
    for label in labels:
        text = str(label or "").strip()
        if not text or text in deduped:
            continue
        deduped.append(text)
    if not deduped:
        return "All fields are required for this form."
    if len(deduped) <= 3:
        return f"All fields are required. Missing: {', '.join(deduped)}."
    return f"All fields are required. Missing: {', '.join(deduped[:3])}, and {len(deduped) - 3} more."


def derive_fill_link_respondent_label(answers: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    preferred_keys = [
        _RESPONDENT_IDENTIFIER_KEY,
        "full_name",
        "name",
        "patient_name",
        "respondent_name",
    ]
    for key in preferred_keys:
        if key in answers:
            text = _coerce_text_answer(answers.get(key))
            if text:
                return text, None
    first_name = _coerce_text_answer(answers.get("first_name"))
    last_name = _coerce_text_answer(answers.get("last_name"))
    if first_name or last_name:
        full_name = " ".join(part for part in [first_name, last_name] if part)
        return full_name, None
    email = _coerce_text_answer(answers.get("email") or answers.get("email_address"))
    if email:
        return email, None
    phone = _coerce_text_answer(answers.get("phone") or answers.get("mobile_phone"))
    if phone:
        return phone, None
    keys = list(answers.keys())
    if keys:
        preview = _coerce_text_answer(answers.get(keys[0]))
        if preview:
            return preview, None
    return "Response", None


def respondent_identifier_required_message() -> str:
    return "Enter a respondent name or ID before submitting."


def has_fill_link_respondent_identifier(
    answers: Optional[Dict[str, Any]],
    questions: Iterable[Dict[str, Any]],
) -> bool:
    payload = answers if isinstance(answers, dict) else {}
    for question in questions:
        if not isinstance(question, dict) or not _question_supports_respondent_identity(question):
            continue
        key = (question.get("key") or "").strip()
        if not key:
            continue
        question_type = normalize_fill_link_key(question.get("type")) or "text"
        raw_value = payload.get(key)
        if question_type == "boolean":
            continue
        if question_type == "multi_select":
            if _coerce_multi_value_answer(raw_value):
                return True
            continue
        if _coerce_text_answer(raw_value):
            return True
    return False


def build_fill_link_search_text(answers: Dict[str, Any], respondent_label: str) -> str:
    fragments: list[str] = [respondent_label]
    for key, value in answers.items():
        fragments.append(str(key))
        if isinstance(value, list):
            fragments.extend(str(entry) for entry in value)
        else:
            fragments.append(str(value))
    return " ".join(fragment for fragment in fragments if fragment).strip().lower()


def fill_link_public_status_message(status: Optional[str], closed_reason: Optional[str]) -> Optional[str]:
    normalized_status = normalize_fill_link_key(status)
    normalized_reason = normalize_fill_link_key(closed_reason)
    if normalized_status == "active":
        return None
    if normalized_reason == "response_limit":
        return "This link has reached its response limit."
    if normalized_reason == "downgrade_retention":
        return "This link is no longer available because its saved form is queued for deletion after the owner's downgrade."
    if normalized_reason == "downgrade_link_limit":
        return "This link is no longer active because free accounts can keep only one active Fill By Link."
    if normalized_reason == "template_deleted":
        return "This link is no longer available because the template was removed."
    if normalized_reason == "group_deleted":
        return "This link is no longer available because the group was removed."
    if normalized_reason == "group_updated":
        return "This link is no longer available because the group changed. Ask the owner for a refreshed link."
    if normalized_reason == "owner_closed":
        return "This link has been closed by the owner."
    return "This link is no longer accepting responses."
