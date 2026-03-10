"""Authenticated Fill By Link owner endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Query

from backend.api.schemas import FillLinkCreateRequest, FillLinkUpdateRequest
from backend.firebaseDB.fill_link_database import (
    FillLinkActiveLimitExceededError,
    close_fill_link,
    create_or_update_fill_link,
    get_fill_link,
    get_fill_link_for_group,
    get_fill_link_for_template,
    get_fill_link_response,
    update_fill_link,
    list_fill_link_responses,
    list_fill_links,
)
from backend.firebaseDB.group_database import get_group
from backend.firebaseDB.template_database import get_template
from backend.services.auth_service import require_user
from backend.services.fill_link_download_service import (
    build_template_fill_link_download_snapshot,
    respondent_pdf_download_enabled,
)
from backend.services.fill_links_service import (
    build_group_fill_link_questions,
    build_fill_link_questions,
    build_fill_link_public_token,
)
from backend.services.fill_link_scope_service import close_fill_link_if_scope_invalid, validate_fill_link_scope
from backend.services.downgrade_retention_service import sync_user_downgrade_retention
from backend.services.limits_service import (
    resolve_fill_link_response_limit,
    resolve_fill_links_active_limit,
)

router = APIRouter()


def _serialize_link(record) -> Dict[str, Any]:
    public_token = build_fill_link_public_token(record.id)
    default_title = record.title or record.group_name or record.template_name or "Fill By Link"
    return {
        "id": record.id,
        "scopeType": record.scope_type,
        "templateId": record.template_id,
        "templateName": record.template_name,
        "groupId": record.group_id,
        "groupName": record.group_name,
        "templateIds": record.template_ids,
        "title": default_title,
        "status": record.status,
        "closedReason": record.closed_reason,
        "responseCount": record.response_count,
        "maxResponses": record.max_responses,
        "createdAt": record.created_at,
        "updatedAt": record.updated_at,
        "publishedAt": record.published_at,
        "closedAt": record.closed_at,
        "publicToken": public_token,
        "publicPath": f"/respond/{public_token}",
        "canAcceptResponses": record.status == "active" and record.response_count < record.max_responses,
        "requireAllFields": record.require_all_fields,
        "respondentPdfDownloadEnabled": respondent_pdf_download_enabled(record),
        "questions": record.questions,
    }


def _serialize_response(record) -> Dict[str, Any]:
    return {
        "id": record.id,
        "linkId": record.link_id,
        "scopeType": record.scope_type,
        "templateId": record.template_id,
        "groupId": record.group_id,
        "respondentLabel": record.respondent_label,
        "respondentSecondaryLabel": record.respondent_secondary_label,
        "submittedAt": record.submitted_at,
        "answers": record.answers,
    }


def _require_template_questions(fields: List[Dict[str, Any]], checkbox_rules: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    questions = build_fill_link_questions(fields, checkbox_rules)
    if not questions:
        raise HTTPException(status_code=400, detail="No usable template fields were provided for Fill By Link.")
    return questions


def _require_group_questions(group_templates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    questions = build_group_fill_link_questions(group_templates)
    if not questions:
        raise HTTPException(status_code=400, detail="No usable group template fields were provided for Fill By Link.")
    return questions


def _normalize_group_template_sources(payload: FillLinkCreateRequest | FillLinkUpdateRequest) -> List[Dict[str, Any]]:
    group_templates = payload.groupTemplates if payload.groupTemplates is not None else []
    normalized: List[Dict[str, Any]] = []
    for template_source in group_templates:
        normalized.append(
            {
                "templateId": template_source.templateId,
                "templateName": template_source.templateName,
                "fields": [field.model_dump(exclude_none=True) for field in template_source.fields],
                "checkboxRules": list(template_source.checkboxRules or []),
            }
        )
    return normalized


def _validate_group_template_sources(
    group_template_ids: List[str],
    normalized_sources: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    source_ids: List[str] = []
    deduped_sources: List[Dict[str, Any]] = []
    for source in normalized_sources:
        template_id = str(source.get("templateId") or "").strip()
        if not template_id or template_id in source_ids:
            continue
        source_ids.append(template_id)
        deduped_sources.append(source)
    if len(source_ids) != len(group_template_ids) or sorted(source_ids) != sorted(group_template_ids):
        raise HTTPException(
            status_code=400,
            detail="Group Fill By Link must include every template in the current group.",
        )
    return deduped_sources


def _ensure_active_link_capacity(user_id: str, role: Optional[str], *, existing_link_id: Optional[str] = None) -> None:
    active_limit = resolve_fill_links_active_limit(role)
    existing_active = [
        link
        for link in list_fill_links(user_id)
        if link.status == "active" and link.id != existing_link_id
    ]
    if len(existing_active) >= active_limit:
        raise HTTPException(
            status_code=403,
            detail=f"Fill By Link limit reached ({active_limit} active links max for your tier).",
        )


def _get_retention_pending_template_ids(user) -> set[str]:
    role = str(getattr(user, "role", "") or "").strip().lower()
    if role != "base":
        return set()
    retention_summary = sync_user_downgrade_retention(user.app_user_id, create_if_missing=True)
    pending_ids = retention_summary.get("pendingDeleteTemplateIds") if isinstance(retention_summary, dict) else None
    if not isinstance(pending_ids, list):
        return set()
    return {str(template_id).strip() for template_id in pending_ids if str(template_id or "").strip()}


def _ensure_fill_link_templates_available(user, template_ids: List[str]) -> None:
    pending_template_ids = _get_retention_pending_template_ids(user)
    if not pending_template_ids:
        return
    if any(template_id in pending_template_ids for template_id in template_ids):
        raise HTTPException(
            status_code=409,
            detail=(
                "This Fill By Link cannot be published because one or more saved forms are queued for deletion "
                "after your downgrade. Reactivate Premium or update the retention selection first."
            ),
        )


def _fill_link_scope_conflict_detail(closed_reason: Optional[str]) -> str:
    normalized_reason = str(closed_reason or "").strip().lower()
    if normalized_reason == "group_deleted":
        return "This Fill By Link can no longer be activated because its workflow group was removed."
    if normalized_reason == "group_updated":
        return "This Fill By Link can no longer be activated because its workflow group changed. Refresh the link from the current group."
    return "This Fill By Link can no longer be activated because its saved form was removed."


def _resolve_template_download_snapshot(template, payload_fields: List[Dict[str, Any]]) -> Dict[str, Any]:
    try:
        return build_template_fill_link_download_snapshot(template=template, fields=payload_fields)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/fill-links")
async def list_owner_fill_links(
    templateId: Optional[str] = Query(default=None),
    groupId: Optional[str] = Query(default=None),
    scopeType: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    user = require_user(authorization)
    links = list_fill_links(
        user.app_user_id,
        template_id=(templateId or "").strip() or None,
        group_id=(groupId or "").strip() or None,
        scope_type=(scopeType or "").strip() or None,
    )
    return {"links": [_serialize_link(close_fill_link_if_scope_invalid(link) or link) for link in links]}


@router.post("/api/fill-links")
async def create_owner_fill_link(
    payload: FillLinkCreateRequest,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    user = require_user(authorization)
    scope_type = payload.scopeType or "template"
    template = None
    group = None
    template_ids: List[str] = []
    fields: List[Dict[str, Any]] = []
    questions: List[Dict[str, Any]]
    existing = None

    if scope_type == "group":
        if payload.respondentPdfDownloadEnabled:
            raise HTTPException(
                status_code=400,
                detail="Respondent PDF download is only available for template Fill By Link.",
            )
        group = get_group(payload.groupId, user.app_user_id)
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")
        template_ids = list(group.template_ids)
        for template_id in template_ids:
            if not get_template(template_id, user.app_user_id):
                raise HTTPException(status_code=404, detail="One or more saved forms were not found")
        normalized_sources = _validate_group_template_sources(
            template_ids,
            _normalize_group_template_sources(payload),
        )
        questions = _require_group_questions(normalized_sources)
        existing = get_fill_link_for_group(group.id, user.app_user_id)
    else:
        template = get_template(payload.templateId, user.app_user_id)
        if not template:
            raise HTTPException(status_code=404, detail="Saved form not found")
        template_ids = [template.id]
        fields = [field.model_dump(exclude_none=True) for field in payload.fields]
        questions = _require_template_questions(fields, payload.checkboxRules)
        existing = get_fill_link_for_template(payload.templateId, user.app_user_id)
    respondent_download_enabled = bool(payload.respondentPdfDownloadEnabled and scope_type == "template")
    respondent_download_snapshot = (
        _resolve_template_download_snapshot(template, fields)
        if respondent_download_enabled and template is not None
        else None
    )

    _ensure_fill_link_templates_available(user, template_ids)
    active_limit = resolve_fill_links_active_limit(user.role)

    if existing and existing.status != "active":
        _ensure_active_link_capacity(user.app_user_id, user.role, existing_link_id=existing.id)
    elif not existing:
        _ensure_active_link_capacity(user.app_user_id, user.role)

    max_responses = resolve_fill_link_response_limit(user.role)
    if existing and existing.response_count >= max_responses:
        raise HTTPException(status_code=409, detail="This Fill By Link has already reached its response limit.")

    try:
        record = create_or_update_fill_link(
            user.app_user_id,
            scope_type=scope_type,
            template_id=payload.templateId,
            template_name=payload.templateName or (template.name if template else None),
            group_id=payload.groupId,
            group_name=payload.groupName or (group.name if group else None),
            template_ids=template_ids,
            title=payload.title or (group.name if group else template.name),
            questions=questions,
            require_all_fields=payload.requireAllFields,
            max_responses=max_responses,
            respondent_pdf_download_enabled=respondent_download_enabled,
            respondent_pdf_snapshot=respondent_download_snapshot,
            status="active",
            closed_reason=None,
            active_limit=active_limit,
        )
    except FillLinkActiveLimitExceededError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"success": True, "link": _serialize_link(record)}


@router.get("/api/fill-links/{link_id}")
async def get_owner_fill_link(
    link_id: str,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    user = require_user(authorization)
    record = close_fill_link_if_scope_invalid(get_fill_link(link_id, user.app_user_id))
    if not record:
        raise HTTPException(status_code=404, detail="Fill By Link not found")
    return {"link": _serialize_link(record)}


@router.patch("/api/fill-links/{link_id}")
async def update_owner_fill_link(
    link_id: str,
    payload: FillLinkUpdateRequest,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    user = require_user(authorization)
    record = close_fill_link_if_scope_invalid(get_fill_link(link_id, user.app_user_id))
    if not record:
        raise HTTPException(status_code=404, detail="Fill By Link not found")

    next_questions = record.questions
    next_template_ids = list(record.template_ids)
    next_group_name = record.group_name
    next_respondent_download_enabled = bool(
        payload.respondentPdfDownloadEnabled
        if payload.respondentPdfDownloadEnabled is not None
        else record.respondent_pdf_download_enabled
    )
    next_respondent_download_snapshot = (
        dict(record.respondent_pdf_snapshot)
        if isinstance(record.respondent_pdf_snapshot, dict)
        else None
    )
    if record.scope_type == "group":
        if payload.respondentPdfDownloadEnabled:
            raise HTTPException(
                status_code=400,
                detail="Respondent PDF download is only available for template Fill By Link.",
            )
        if payload.groupName is not None:
            next_group_name = payload.groupName
        if payload.groupTemplates is not None:
            if not record.group_id:
                raise HTTPException(status_code=400, detail="Group Fill By Link is missing its group reference.")
            group = get_group(record.group_id, user.app_user_id)
            if not group:
                raise HTTPException(status_code=404, detail="Group not found")
            next_template_ids = list(group.template_ids)
            normalized_sources = _validate_group_template_sources(
                next_template_ids,
                _normalize_group_template_sources(payload),
            )
            next_questions = _require_group_questions(normalized_sources)
    elif payload.fields is not None:
        template = get_template(record.template_id, user.app_user_id) if record.template_id else None
        if not template:
            raise HTTPException(status_code=404, detail="Saved form not found")
        next_fields = [field.model_dump(exclude_none=True) for field in payload.fields]
        next_questions = _require_template_questions(
            next_fields,
            payload.checkboxRules,
        )
        next_respondent_download_snapshot = (
            _resolve_template_download_snapshot(template, next_fields)
            if next_respondent_download_enabled
            else None
        )
    elif not next_respondent_download_enabled:
        next_respondent_download_snapshot = None
    elif record.scope_type == "template" and next_respondent_download_snapshot is None:
        raise HTTPException(
            status_code=409,
            detail="Refresh the template Fill By Link schema before enabling respondent PDF download.",
        )

    next_status = payload.status or record.status
    active_limit = resolve_fill_links_active_limit(user.role)
    if next_status == "active":
        scope_validation = validate_fill_link_scope(
            user.app_user_id,
            scope_type=record.scope_type,
            template_id=record.template_id,
            group_id=record.group_id,
            template_ids=next_template_ids,
        )
        if not scope_validation.valid:
            raise HTTPException(
                status_code=409,
                detail=_fill_link_scope_conflict_detail(scope_validation.closed_reason),
            )
        _ensure_fill_link_templates_available(user, next_template_ids)
        if record.status != "active":
            _ensure_active_link_capacity(user.app_user_id, user.role, existing_link_id=record.id)
        if record.response_count >= resolve_fill_link_response_limit(user.role):
            raise HTTPException(status_code=409, detail="This Fill By Link has already reached its response limit.")

    try:
        updated = update_fill_link(
            link_id,
            user.app_user_id,
            title=payload.title,
            questions=next_questions if (payload.fields is not None or payload.groupTemplates is not None) else None,
            group_name=next_group_name if payload.groupName is not None else None,
            template_ids=next_template_ids if payload.groupTemplates is not None else None,
            require_all_fields=payload.requireAllFields,
            respondent_pdf_download_enabled=(
                next_respondent_download_enabled if record.scope_type == "template" else None
            ),
            respondent_pdf_snapshot=(
                next_respondent_download_snapshot if record.scope_type == "template" else None
            ),
            status=payload.status,
            closed_reason="owner_closed" if payload.status == "closed" else None,
            max_responses=resolve_fill_link_response_limit(user.role),
            active_limit=active_limit,
        )
    except FillLinkActiveLimitExceededError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="Fill By Link not found")
    return {"success": True, "link": _serialize_link(updated)}


@router.post("/api/fill-links/{link_id}/close")
async def close_owner_fill_link(
    link_id: str,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    user = require_user(authorization)
    record = close_fill_link(link_id, user.app_user_id, closed_reason="owner_closed")
    if not record:
        raise HTTPException(status_code=404, detail="Fill By Link not found")
    return {"success": True, "link": _serialize_link(record)}


@router.get("/api/fill-links/{link_id}/responses")
async def list_owner_fill_link_responses(
    link_id: str,
    search: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=10000),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    user = require_user(authorization)
    link = get_fill_link(link_id, user.app_user_id)
    if not link:
        raise HTTPException(status_code=404, detail="Fill By Link not found")
    responses = list_fill_link_responses(link_id, user.app_user_id, search=search, limit=limit)
    return {
        "link": _serialize_link(link),
        "responses": [_serialize_response(response) for response in responses],
    }


@router.get("/api/fill-links/{link_id}/responses/{response_id}")
async def get_owner_fill_link_response(
    link_id: str,
    response_id: str,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    user = require_user(authorization)
    response_record = get_fill_link_response(response_id, link_id, user.app_user_id)
    if not response_record:
        raise HTTPException(status_code=404, detail="Response not found")
    return {"response": _serialize_response(response_record)}
