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
from backend.firebaseDB.signing_database import (
    get_signing_request_for_user,
    list_signing_requests,
)
from backend.services.fill_link_signing_service import (
    normalize_fill_link_signing_config,
    serialize_fill_link_signing_config,
)
from backend.firebaseDB.group_database import get_group
from backend.firebaseDB.template_database import get_template
from backend.services.auth_service import require_user
from backend.services.fill_link_download_service import (
    build_template_fill_link_download_snapshot,
    respondent_pdf_editable_enabled,
    respondent_pdf_download_enabled,
)
from backend.services.fill_links_service import (
    build_group_fill_link_questions,
    build_fill_link_questions,
    build_fill_link_web_form_schema,
    build_fill_link_public_token,
)
from backend.services.fill_link_scope_service import close_fill_link_if_scope_invalid, validate_fill_link_scope
from backend.services.downgrade_retention_service import sync_user_downgrade_retention
from backend.services.limits_service import (
    resolve_fill_link_response_limit,
    resolve_fill_links_active_limit,
)
from backend.services.signing_service import (
    SIGNING_ARTIFACT_AUDIT_RECEIPT,
    SIGNING_ARTIFACT_SIGNED_PDF,
    SIGNING_ARTIFACT_SOURCE_PDF,
    build_signing_public_path,
    build_signing_validation_path,
    resolve_signing_public_link_version,
)

router = APIRouter()


def _serialize_link(record) -> Dict[str, Any]:
    public_token = build_fill_link_public_token(record.id)
    default_title = record.title or record.group_name or record.template_name or "Fill By Link"
    web_form_config = dict(record.web_form_config) if isinstance(record.web_form_config, dict) else None
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
        "respondentPdfEditableEnabled": respondent_pdf_editable_enabled(record),
        "introText": web_form_config.get("introText") if isinstance(web_form_config, dict) else None,
        "webFormConfig": web_form_config,
        "signingConfig": serialize_fill_link_signing_config(record.signing_config),
        "questions": record.questions,
    }


def _serialize_linked_signing_artifacts(record) -> Dict[str, Any]:
    return {
        "sourcePdf": {
            "available": bool(record.source_pdf_bucket_path),
            "downloadPath": (
                f"/api/signing/requests/{record.id}/artifacts/{SIGNING_ARTIFACT_SOURCE_PDF}"
                if record.source_pdf_bucket_path
                else None
            ),
        },
        "signedPdf": {
            "available": bool(record.signed_pdf_bucket_path),
            "downloadPath": (
                f"/api/signing/requests/{record.id}/artifacts/{SIGNING_ARTIFACT_SIGNED_PDF}"
                if record.signed_pdf_bucket_path
                else None
            ),
        },
        "auditReceipt": {
            "available": bool(record.audit_receipt_bucket_path),
            "downloadPath": (
                f"/api/signing/requests/{record.id}/artifacts/{SIGNING_ARTIFACT_AUDIT_RECEIPT}"
                if record.audit_receipt_bucket_path
                else None
            ),
        },
    }


def _serialize_linked_signing(record) -> Dict[str, Any]:
    public_link_version = resolve_signing_public_link_version(record)
    public_link_available = record.status in {"sent", "completed"}
    return {
        "requestId": record.id,
        "status": record.status,
        "senderEmail": getattr(record, "sender_email", None),
        "inviteMethod": getattr(record, "invite_method", None),
        "inviteProvider": getattr(record, "invite_provider", None),
        "inviteDeliveryStatus": record.invite_delivery_status,
        "inviteLastAttemptAt": record.invite_last_attempt_at,
        "inviteSentAt": record.invite_sent_at,
        "inviteDeliveryError": record.invite_delivery_error,
        "inviteDeliveryErrorCode": getattr(record, "invite_delivery_error_code", None),
        "manualLinkSharedAt": getattr(record, "manual_link_shared_at", None),
        "completedAt": record.completed_at,
        "manualFallbackRequestedAt": record.manual_fallback_requested_at,
        "publicLinkVersion": public_link_version,
        "publicLinkRevokedAt": getattr(record, "public_link_revoked_at", None),
        "publicLinkLastReissuedAt": getattr(record, "public_link_last_reissued_at", None),
        "publicPath": build_signing_public_path(record.id, public_link_version) if public_link_available else None,
        "validationPath": build_signing_validation_path(record.id),
        "artifacts": _serialize_linked_signing_artifacts(record),
    }


def _serialize_response(record, *, linked_signing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
        "signingRequestId": record.signing_request_id,
        "signingStatus": linked_signing.get("status") if isinstance(linked_signing, dict) else None,
        "signingCompletedAt": linked_signing.get("completedAt") if isinstance(linked_signing, dict) else None,
        "linkedSigning": linked_signing,
    }


def _normalize_web_form_config(
    payload: FillLinkCreateRequest | FillLinkUpdateRequest,
) -> Optional[Dict[str, Any]]:
    if payload.webFormConfig is None:
        return None
    return payload.webFormConfig.model_dump(exclude_none=True)


def _normalize_signing_config(
    payload: FillLinkCreateRequest | FillLinkUpdateRequest,
    *,
    scope_type: str,
    questions: List[Dict[str, Any]],
    fields: List[Dict[str, Any]],
    sender_display_name: Optional[str] = None,
    sender_email: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    raw_config = payload.signingConfig.model_dump(exclude_none=True) if payload.signingConfig is not None else None
    try:
        return normalize_fill_link_signing_config(
            raw_config,
            scope_type=scope_type,
            questions=questions,
            fields=fields,
            sender_display_name=sender_display_name,
            sender_email=sender_email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _post_submit_signing_requested(
    payload: FillLinkCreateRequest | FillLinkUpdateRequest,
    *,
    fallback_config: Optional[Dict[str, Any]] = None,
) -> bool:
    if payload.signingConfig is not None:
        raw_config = payload.signingConfig.model_dump(exclude_none=True)
        return bool(isinstance(raw_config, dict) and raw_config.get("enabled"))
    return bool(isinstance(fallback_config, dict) and fallback_config.get("enabled"))


def _build_template_web_form_schema(
    fields: List[Dict[str, Any]],
    *,
    checkbox_rules: Optional[List[Dict[str, Any]]] = None,
    web_form_config: Optional[Dict[str, Any]] = None,
    require_all_fields: bool = False,
    exclude_signing_questions: bool = False,
) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    default_questions = build_fill_link_questions(fields, checkbox_rules)
    try:
        stored_config, published_questions = build_fill_link_web_form_schema(
            default_questions,
            require_all_fields=require_all_fields,
            web_form_config=web_form_config,
            allow_custom_questions=True,
            exclude_signing_questions=exclude_signing_questions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not published_questions:
        raise HTTPException(status_code=400, detail="Add at least one visible template web-form question before publishing Fill By Link.")
    return stored_config, published_questions


def _build_group_web_form_schema(
    group_templates: List[Dict[str, Any]],
    *,
    web_form_config: Optional[Dict[str, Any]] = None,
    require_all_fields: bool = False,
) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    default_questions = build_group_fill_link_questions(group_templates)
    try:
        stored_config, published_questions = build_fill_link_web_form_schema(
            default_questions,
            require_all_fields=require_all_fields,
            web_form_config=web_form_config,
            allow_custom_questions=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not published_questions:
        raise HTTPException(status_code=400, detail="No usable group template fields were provided for Fill By Link.")
    return stored_config, published_questions


def _build_web_form_schema_from_default_questions(
    default_questions: List[Dict[str, Any]],
    *,
    web_form_config: Optional[Dict[str, Any]] = None,
    require_all_fields: bool = False,
    allow_custom_questions: bool = True,
    exclude_signing_questions: bool = False,
) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    try:
        stored_config, published_questions = build_fill_link_web_form_schema(
            default_questions,
            require_all_fields=require_all_fields,
            web_form_config=web_form_config,
            allow_custom_questions=allow_custom_questions,
            exclude_signing_questions=exclude_signing_questions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not published_questions:
        raise HTTPException(status_code=400, detail="Add at least one visible web-form question before publishing Fill By Link.")
    return stored_config, published_questions


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


def _resolve_template_download_snapshot(
    template,
    payload_fields: List[Dict[str, Any]],
    *,
    editable: bool = False,
) -> Dict[str, Any]:
    try:
        return build_template_fill_link_download_snapshot(
            template=template,
            fields=payload_fields,
            export_mode="editable" if editable else "flat",
        )
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
    web_form_config = _normalize_web_form_config(payload)
    stored_web_form_config: Dict[str, Any]
    questions: List[Dict[str, Any]]
    signing_config: Optional[Dict[str, Any]] = None
    existing = None

    if scope_type == "group":
        if payload.respondentPdfDownloadEnabled:
            raise HTTPException(
                status_code=400,
                detail="Respondent PDF download is only available for template Fill By Link.",
            )
        if payload.respondentPdfEditableEnabled:
            raise HTTPException(
                status_code=400,
                detail="Editable respondent PDF download is only available for template Fill By Link.",
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
        stored_web_form_config, questions = _build_group_web_form_schema(
            normalized_sources,
            web_form_config=web_form_config,
            require_all_fields=payload.requireAllFields,
        )
        signing_config = _normalize_signing_config(
            payload,
            scope_type=scope_type,
            questions=questions,
            fields=[],
            sender_display_name=user.display_name,
            sender_email=user.email,
        )
        existing = get_fill_link_for_group(group.id, user.app_user_id)
    else:
        template = get_template(payload.templateId, user.app_user_id)
        if not template:
            raise HTTPException(status_code=404, detail="Saved form not found")
        template_ids = [template.id]
        fields = [field.model_dump(exclude_none=True) for field in payload.fields]
        stored_web_form_config, questions = _build_template_web_form_schema(
            fields,
            checkbox_rules=payload.checkboxRules,
            web_form_config=web_form_config,
            require_all_fields=payload.requireAllFields,
            exclude_signing_questions=_post_submit_signing_requested(payload),
        )
        signing_config = _normalize_signing_config(
            payload,
            scope_type=scope_type,
            questions=questions,
            fields=fields,
            sender_display_name=user.display_name,
            sender_email=user.email,
        )
        existing = get_fill_link_for_template(payload.templateId, user.app_user_id)
    signing_enabled = bool(isinstance(signing_config, dict) and signing_config.get("enabled"))
    respondent_download_enabled = bool(payload.respondentPdfDownloadEnabled and scope_type == "template")
    respondent_download_editable_enabled = bool(
        respondent_download_enabled
        and payload.respondentPdfEditableEnabled
        and scope_type == "template"
        and not signing_enabled
    )
    needs_template_snapshot = bool(
        scope_type == "template" and template is not None and (respondent_download_enabled or signing_config)
    )
    respondent_download_snapshot = (
        _resolve_template_download_snapshot(template, fields, editable=respondent_download_editable_enabled)
        if needs_template_snapshot
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
            web_form_config=stored_web_form_config,
            signing_config=signing_config,
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
    next_web_form_config = dict(record.web_form_config) if isinstance(record.web_form_config, dict) else None
    next_signing_config = dict(record.signing_config) if isinstance(record.signing_config, dict) else None
    next_respondent_download_enabled = bool(
        payload.respondentPdfDownloadEnabled
        if payload.respondentPdfDownloadEnabled is not None
        else record.respondent_pdf_download_enabled
    )
    next_respondent_download_editable_enabled = bool(
        payload.respondentPdfEditableEnabled
        if payload.respondentPdfEditableEnabled is not None
        else respondent_pdf_editable_enabled(record)
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
        if payload.respondentPdfEditableEnabled:
            raise HTTPException(
                status_code=400,
                detail="Editable respondent PDF download is only available for template Fill By Link.",
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
            next_web_form_config, next_questions = _build_group_web_form_schema(
                normalized_sources,
                web_form_config=_normalize_web_form_config(payload) or next_web_form_config,
                require_all_fields=(
                    payload.requireAllFields
                    if payload.requireAllFields is not None
                    else record.require_all_fields
                ),
            )
            next_signing_config = _normalize_signing_config(
                payload,
                scope_type=record.scope_type,
                questions=next_questions,
                fields=[],
                sender_display_name=user.display_name,
                sender_email=user.email,
            ) if payload.signingConfig is not None else next_signing_config
        elif payload.webFormConfig is not None:
            default_questions = (
                next_web_form_config.get("questions")
                if isinstance(next_web_form_config, dict) and isinstance(next_web_form_config.get("questions"), list)
                else record.questions
            )
            next_web_form_config, next_questions = _build_web_form_schema_from_default_questions(
                default_questions if isinstance(default_questions, list) else [],
                web_form_config=_normalize_web_form_config(payload),
                require_all_fields=(
                    payload.requireAllFields
                    if payload.requireAllFields is not None
                    else record.require_all_fields
                ),
                allow_custom_questions=False,
            )
        elif payload.signingConfig is not None:
            next_signing_config = _normalize_signing_config(
                payload,
                scope_type=record.scope_type,
                questions=next_questions,
                fields=[],
                sender_display_name=user.display_name,
                sender_email=user.email,
            )
    elif payload.fields is not None or payload.webFormConfig is not None:
        template = get_template(record.template_id, user.app_user_id) if record.template_id else None
        if not template:
            raise HTTPException(status_code=404, detail="Saved form not found")
        exclude_signing_questions = _post_submit_signing_requested(
            payload,
            fallback_config=next_signing_config,
        )
        if payload.fields is not None:
            next_fields = [field.model_dump(exclude_none=True) for field in payload.fields]
            next_web_form_config, next_questions = _build_template_web_form_schema(
                next_fields,
                checkbox_rules=payload.checkboxRules,
                web_form_config=_normalize_web_form_config(payload) or next_web_form_config,
                require_all_fields=(
                    payload.requireAllFields
                    if payload.requireAllFields is not None
                    else record.require_all_fields
                ),
                exclude_signing_questions=exclude_signing_questions,
            )
            next_respondent_download_snapshot = (
                _resolve_template_download_snapshot(
                    template,
                    next_fields,
                    editable=next_respondent_download_enabled and next_respondent_download_editable_enabled,
                )
                if (next_respondent_download_enabled or next_signing_config)
                else None
            )
            if payload.signingConfig is not None:
                next_signing_config = _normalize_signing_config(
                    payload,
                    scope_type=record.scope_type,
                    questions=next_questions,
                    fields=next_fields,
                    sender_display_name=user.display_name,
                    sender_email=user.email,
                )
        else:
            default_questions = (
                next_web_form_config.get("questions")
                if isinstance(next_web_form_config, dict) and isinstance(next_web_form_config.get("questions"), list)
                else record.questions
            )
            next_web_form_config, next_questions = _build_web_form_schema_from_default_questions(
                default_questions if isinstance(default_questions, list) else [],
                web_form_config=_normalize_web_form_config(payload),
                require_all_fields=(
                    payload.requireAllFields
                    if payload.requireAllFields is not None
                    else record.require_all_fields
                ),
                allow_custom_questions=True,
                exclude_signing_questions=exclude_signing_questions,
            )
            if not next_respondent_download_enabled:
                next_respondent_download_snapshot = (
                    next_respondent_download_snapshot if next_signing_config else None
                )
            if payload.signingConfig is not None:
                next_signing_config = _normalize_signing_config(
                    payload,
                    scope_type=record.scope_type,
                    questions=next_questions,
                    fields=(
                        next_respondent_download_snapshot.get("fields")
                        if isinstance(next_respondent_download_snapshot, dict)
                        and isinstance(next_respondent_download_snapshot.get("fields"), list)
                        else []
                    ),
                    sender_display_name=user.display_name,
                    sender_email=user.email,
                )
                if next_signing_config and next_respondent_download_snapshot is None:
                    raise HTTPException(
                        status_code=409,
                        detail="Refresh the template Fill By Link schema before enabling post-submit signing.",
                    )
    elif not next_respondent_download_enabled and not next_signing_config:
        next_respondent_download_snapshot = None
    elif record.scope_type == "template" and next_respondent_download_snapshot is None:
        raise HTTPException(
            status_code=409,
            detail="Refresh the template Fill By Link schema before enabling respondent PDF download or signing.",
        )
    elif (
        record.scope_type == "template"
        and isinstance(next_respondent_download_snapshot, dict)
        and (next_respondent_download_enabled or next_signing_config)
    ):
        next_signing_enabled = bool(isinstance(next_signing_config, dict) and next_signing_config.get("enabled"))
        if next_signing_enabled:
            next_respondent_download_editable_enabled = False
        next_respondent_download_snapshot["downloadMode"] = (
            "editable"
            if next_respondent_download_enabled and next_respondent_download_editable_enabled and not next_signing_enabled
            else "flat"
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
            questions=(
                next_questions
                if (payload.fields is not None or payload.groupTemplates is not None or payload.webFormConfig is not None)
                else None
            ),
            group_name=next_group_name if payload.groupName is not None else None,
            template_ids=next_template_ids if payload.groupTemplates is not None else None,
            require_all_fields=payload.requireAllFields,
            web_form_config=(
                next_web_form_config
                if (payload.fields is not None or payload.groupTemplates is not None or payload.webFormConfig is not None)
                else None
            ),
            signing_config=next_signing_config if payload.signingConfig is not None else None,
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
    signing_records_by_id: Dict[str, Any] = {}
    signing_request_ids = [response.signing_request_id for response in responses if response.signing_request_id]
    if signing_request_ids:
        request_id_set = set(signing_request_ids)
        signing_records_by_id = {
            record.id: record
            for record in list_signing_requests(user.app_user_id)
            if record.id in request_id_set
        }
    return {
        "link": _serialize_link(link),
        "responses": [
            _serialize_response(
                response,
                linked_signing=(
                    _serialize_linked_signing(signing_records_by_id[response.signing_request_id])
                    if response.signing_request_id and response.signing_request_id in signing_records_by_id
                    else None
                ),
            )
            for response in responses
        ],
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
    linked_signing = None
    if response_record.signing_request_id:
        signing_record = get_signing_request_for_user(response_record.signing_request_id, user.app_user_id)
        if signing_record:
            linked_signing = _serialize_linked_signing(signing_record)
    return {"response": _serialize_response(response_record, linked_signing=linked_signing)}
