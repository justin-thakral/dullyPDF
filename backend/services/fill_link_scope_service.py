"""Validate that Fill By Link records still point at a live backing scope."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from backend.firebaseDB.fill_link_database import FillLinkRecord, close_fill_link
from backend.firebaseDB.group_database import get_group
from backend.firebaseDB.template_database import get_template


@dataclass(frozen=True)
class FillLinkScopeValidationResult:
    valid: bool
    closed_reason: Optional[str] = None


def _build_closed_scope_preview(
    record: FillLinkRecord,
    *,
    closed_reason: Optional[str],
) -> FillLinkRecord:
    payload = {
        **record.__dict__,
        "status": "closed",
        "closed_reason": (closed_reason or "owner_closed"),
    }
    return FillLinkRecord(**payload)


def _dedupe_template_ids(template_ids: Optional[Iterable[str]]) -> list[str]:
    deduped: list[str] = []
    for raw in template_ids or []:
        template_id = str(raw or "").strip()
        if not template_id or template_id in deduped:
            continue
        deduped.append(template_id)
    return deduped


def validate_fill_link_scope(
    user_id: str,
    *,
    scope_type: str,
    template_id: Optional[str] = None,
    group_id: Optional[str] = None,
    template_ids: Optional[Iterable[str]] = None,
) -> FillLinkScopeValidationResult:
    """Verify that the scope still exists and still matches the link schema source.

    Group validation is linear in the number of grouped templates because each
    template id must still resolve to a live saved form before the public form
    can safely accept submissions.
    """
    normalized_user_id = str(user_id or "").strip()
    normalized_scope = str(scope_type or "template").strip().lower() or "template"
    normalized_template_id = str(template_id or "").strip() or None
    normalized_group_id = str(group_id or "").strip() or None
    normalized_template_ids = _dedupe_template_ids(template_ids)

    if not normalized_user_id:
        return FillLinkScopeValidationResult(valid=False, closed_reason="template_deleted")

    if normalized_scope == "group":
        if not normalized_group_id:
            return FillLinkScopeValidationResult(valid=False, closed_reason="group_deleted")
        group = get_group(normalized_group_id, normalized_user_id)
        if not group:
            return FillLinkScopeValidationResult(valid=False, closed_reason="group_deleted")
        current_template_ids = _dedupe_template_ids(group.template_ids)
        if current_template_ids != normalized_template_ids:
            return FillLinkScopeValidationResult(valid=False, closed_reason="group_updated")
        for current_template_id in current_template_ids:
            if not get_template(current_template_id, normalized_user_id):
                return FillLinkScopeValidationResult(valid=False, closed_reason="template_deleted")
        return FillLinkScopeValidationResult(valid=True)

    if not normalized_template_id:
        return FillLinkScopeValidationResult(valid=False, closed_reason="template_deleted")
    if not get_template(normalized_template_id, normalized_user_id):
        return FillLinkScopeValidationResult(valid=False, closed_reason="template_deleted")
    return FillLinkScopeValidationResult(valid=True)


def close_fill_link_if_scope_invalid(record: Optional[FillLinkRecord]) -> Optional[FillLinkRecord]:
    if not record:
        return None
    if record.status != "active":
        return record
    validation = validate_fill_link_scope(
        record.user_id,
        scope_type=record.scope_type,
        template_id=record.template_id,
        group_id=record.group_id,
        template_ids=record.template_ids,
    )
    if validation.valid:
        return record
    closed_preview = _build_closed_scope_preview(record, closed_reason=validation.closed_reason)
    return close_fill_link(
        record.id,
        record.user_id,
        closed_reason=validation.closed_reason or "owner_closed",
    ) or closed_preview


def preview_fill_link_if_scope_invalid(record: Optional[FillLinkRecord]) -> Optional[FillLinkRecord]:
    if not record:
        return None
    if record.status != "active":
        return record
    validation = validate_fill_link_scope(
        record.user_id,
        scope_type=record.scope_type,
        template_id=record.template_id,
        group_id=record.group_id,
        template_ids=record.template_ids,
    )
    if validation.valid:
        return record
    return _build_closed_scope_preview(record, closed_reason=validation.closed_reason)
