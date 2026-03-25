"""Authenticated owner endpoints for published API Fill templates."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Query

from backend.api.schemas import TemplateApiEndpointPublishRequest
from backend.firebaseDB.template_api_endpoint_database import (
    count_active_template_api_endpoints,
    create_template_api_endpoint,
    create_template_api_endpoint_event,
    get_active_template_api_endpoint_for_template,
    get_template_api_endpoint,
    get_template_api_monthly_usage,
    list_template_api_endpoints,
    list_template_api_endpoint_events,
    update_template_api_endpoint,
)
from backend.firebaseDB.template_database import get_template
from backend.firebaseDB.user_database import get_user_profile, normalize_role
from backend.services.auth_service import require_user
from backend.services.limits_service import (
    resolve_template_api_active_limit,
    resolve_template_api_max_pages,
    resolve_template_api_requests_monthly_limit,
)
from backend.services.template_api_service import (
    build_template_api_key_prefix,
    build_template_api_schema,
    build_template_api_snapshot,
    generate_template_api_secret,
    hash_template_api_secret,
)
from backend.time_utils import now_iso


router = APIRouter()


def _serialize_endpoint(record) -> Dict[str, Any]:
    return {
        "id": record.id,
        "templateId": record.template_id,
        "templateName": record.template_name,
        "status": record.status,
        "snapshotVersion": record.snapshot_version,
        "keyPrefix": record.key_prefix,
        "createdAt": record.created_at,
        "updatedAt": record.updated_at,
        "publishedAt": record.published_at,
        "lastUsedAt": record.last_used_at,
        "usageCount": record.usage_count,
        "currentUsageMonth": record.current_usage_month,
        "currentMonthUsageCount": record.current_month_usage_count,
        "authFailureCount": record.auth_failure_count,
        "validationFailureCount": record.validation_failure_count,
        "suspiciousFailureCount": record.suspicious_failure_count,
        "lastFailureAt": record.last_failure_at,
        "lastFailureReason": record.last_failure_reason,
        "auditEventCount": record.audit_event_count,
        "fillPath": f"/api/v1/fill/{record.id}.pdf",
        "schemaPath": f"/api/template-api-endpoints/{record.id}/schema",
    }


def _resolve_role_for_user(user) -> str:
    profile = get_user_profile(user.app_user_id)
    return normalize_role(profile.role if profile else user.role)


def _build_owner_limit_summary(*, user_id: str, role: str, current_endpoint=None) -> Dict[str, Any]:
    monthly_usage = get_template_api_monthly_usage(user_id)
    active_count = count_active_template_api_endpoints(user_id)
    template_page_count = 0
    if current_endpoint is not None and isinstance(current_endpoint.snapshot, dict):
        template_page_count = max(0, int(current_endpoint.snapshot.get("pageCount") or 0))
    return {
        "activeEndpointsMax": resolve_template_api_active_limit(role),
        "activeEndpointsUsed": active_count,
        "requestsPerMonthMax": resolve_template_api_requests_monthly_limit(role),
        "requestsThisMonth": monthly_usage.request_count if monthly_usage is not None else 0,
        "requestUsageMonth": monthly_usage.month_key if monthly_usage is not None else None,
        "maxPagesPerRequest": resolve_template_api_max_pages(role),
        "templatePageCount": template_page_count,
    }


def _build_event_summary(event_type: str, outcome: str) -> str:
    normalized_event = str(event_type or "").strip()
    normalized_outcome = str(outcome or "success").strip() or "success"
    mapping = {
        "published": "Endpoint published",
        "republished": "Snapshot republished",
        "rotated": "API key rotated",
        "revoked": "Endpoint revoked",
        "fill_succeeded": "PDF generated",
        "fill_validation_failed": "Invalid fill payload rejected",
        "fill_auth_failed": "Invalid API key rejected",
        "fill_rate_limited": "Rate limit blocked a request",
        "fill_quota_blocked": "Plan quota blocked a request",
    }
    base = mapping.get(normalized_event, normalized_event.replace("_", " ").strip().title() or "Activity")
    if normalized_outcome == "error":
        return f"{base} with an error"
    if normalized_outcome == "denied":
        return f"{base} (denied)"
    return base


def _serialize_event(record) -> Dict[str, Any]:
    return {
        "id": record.id,
        "eventType": record.event_type,
        "outcome": record.outcome,
        "createdAt": record.created_at,
        "snapshotVersion": record.snapshot_version,
        "summary": _build_event_summary(record.event_type, record.outcome),
        "metadata": record.metadata,
    }


def _build_owner_details_payload(record, *, role: str, include_schema: bool = True) -> Dict[str, Any]:
    snapshot = dict(record.snapshot or {})
    payload: Dict[str, Any] = {
        "endpoint": _serialize_endpoint(record),
        "limits": _build_owner_limit_summary(user_id=record.user_id, role=role, current_endpoint=record),
        "recentEvents": [_serialize_event(event) for event in list_template_api_endpoint_events(record.id, user_id=record.user_id)],
    }
    if include_schema:
        if not snapshot:
            raise HTTPException(status_code=404, detail="API Fill snapshot is missing")
        payload["schema"] = build_template_api_schema(snapshot)
    return payload


def _resolve_template_or_404(template_id: str, user_id: str):
    template = get_template(template_id, user_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Saved form not found")
    return template


def _build_snapshot_or_400(template, *, export_mode: str) -> Dict[str, Any]:
    try:
        return build_template_api_snapshot(template, export_mode=export_mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _resolve_endpoint_or_404(endpoint_id: str, user_id: str):
    record = get_template_api_endpoint(endpoint_id, user_id)
    if record is None:
        raise HTTPException(status_code=404, detail="API Fill endpoint not found")
    return record


@router.get("/api/template-api-endpoints")
async def list_owner_template_api_endpoints(
    templateId: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """List API Fill endpoints owned by the current user."""
    user = require_user(authorization)
    endpoints = list_template_api_endpoints(user.app_user_id, template_id=templateId)
    role = _resolve_role_for_user(user)
    return {
        "endpoints": [_serialize_endpoint(record) for record in endpoints],
        "limits": _build_owner_limit_summary(user_id=user.app_user_id, role=role),
    }


@router.post("/api/template-api-endpoints")
async def publish_template_api_endpoint(
    payload: TemplateApiEndpointPublishRequest,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Publish or republish a saved form into a frozen API Fill snapshot."""
    user = require_user(authorization)
    role = _resolve_role_for_user(user)
    template = _resolve_template_or_404(payload.templateId, user.app_user_id)
    existing = get_active_template_api_endpoint_for_template(template.id, user.app_user_id)
    if existing is None:
        active_limit = resolve_template_api_active_limit(role)
        if active_limit <= 0:
            raise HTTPException(status_code=403, detail="API Fill is unavailable on the current plan.")
        if count_active_template_api_endpoints(user.app_user_id) >= active_limit:
            raise HTTPException(status_code=409, detail=f"Your plan allows up to {active_limit} active API Fill endpoints.")
    snapshot = _build_snapshot_or_400(template, export_mode=payload.exportMode)
    template_page_count = max(0, int(snapshot.get("pageCount") or 0))
    max_pages = resolve_template_api_max_pages(role)
    if template_page_count > max_pages:
        raise HTTPException(
            status_code=403,
            detail=f"API Fill templates are limited to {max_pages} pages on your plan (got {template_page_count}).",
        )
    if existing is not None:
        updated = update_template_api_endpoint(
            existing.id,
            user.app_user_id,
            template_name=template.name,
            snapshot=snapshot,
            snapshot_version=existing.snapshot_version + 1,
            published_at=now_iso(),
            status="active",
        )
        if updated is None:
            raise HTTPException(status_code=500, detail="Failed to republish API Fill endpoint")
        create_template_api_endpoint_event(
            endpoint_id=updated.id,
            user_id=updated.user_id,
            template_id=updated.template_id,
            event_type="republished",
            snapshot_version=updated.snapshot_version,
            metadata={
                "exportMode": snapshot.get("defaultExportMode"),
                "pageCount": snapshot.get("pageCount"),
            },
        )
        updated = _resolve_endpoint_or_404(updated.id, user.app_user_id)
        payload_result = {
            "created": False,
            "secret": None,
            **_build_owner_details_payload(updated, role=role),
        }
        return payload_result

    secret = generate_template_api_secret()
    created = create_template_api_endpoint(
        user_id=user.app_user_id,
        template_id=template.id,
        template_name=template.name,
        key_prefix=build_template_api_key_prefix(secret),
        secret_hash=hash_template_api_secret(secret),
        snapshot=snapshot,
    )
    create_template_api_endpoint_event(
        endpoint_id=created.id,
        user_id=created.user_id,
        template_id=created.template_id,
        event_type="published",
        snapshot_version=created.snapshot_version,
        metadata={
            "exportMode": snapshot.get("defaultExportMode"),
            "pageCount": snapshot.get("pageCount"),
        },
    )
    created = _resolve_endpoint_or_404(created.id, user.app_user_id)
    return {
        "created": True,
        "secret": secret,
        **_build_owner_details_payload(created, role=role),
    }


@router.post("/api/template-api-endpoints/{endpoint_id}/rotate")
async def rotate_template_api_endpoint_secret(
    endpoint_id: str,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Rotate the scoped secret for an active API Fill endpoint."""
    user = require_user(authorization)
    role = _resolve_role_for_user(user)
    record = _resolve_endpoint_or_404(endpoint_id, user.app_user_id)
    if record.status != "active":
        raise HTTPException(status_code=409, detail="Only active API Fill endpoints can rotate keys.")
    secret = generate_template_api_secret()
    updated = update_template_api_endpoint(
        endpoint_id,
        user.app_user_id,
        key_prefix=build_template_api_key_prefix(secret),
        secret_hash=hash_template_api_secret(secret),
    )
    if updated is None:
        raise HTTPException(status_code=500, detail="Failed to rotate API Fill key")
    create_template_api_endpoint_event(
        endpoint_id=updated.id,
        user_id=updated.user_id,
        template_id=updated.template_id,
        event_type="rotated",
        snapshot_version=updated.snapshot_version,
        metadata={"keyPrefix": updated.key_prefix},
    )
    updated = _resolve_endpoint_or_404(updated.id, user.app_user_id)
    return {
        "secret": secret,
        **_build_owner_details_payload(updated, role=role, include_schema=False),
    }


@router.post("/api/template-api-endpoints/{endpoint_id}/revoke")
async def revoke_template_api_endpoint(
    endpoint_id: str,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Revoke an API Fill endpoint so it can no longer be used publicly."""
    user = require_user(authorization)
    role = _resolve_role_for_user(user)
    record = _resolve_endpoint_or_404(endpoint_id, user.app_user_id)
    if record.status != "revoked":
        record = update_template_api_endpoint(
            endpoint_id,
            user.app_user_id,
            status="revoked",
        )
    if record is None:
        raise HTTPException(status_code=500, detail="Failed to revoke API Fill endpoint")
    create_template_api_endpoint_event(
        endpoint_id=record.id,
        user_id=record.user_id,
        template_id=record.template_id,
        event_type="revoked",
        snapshot_version=record.snapshot_version,
    )
    record = _resolve_endpoint_or_404(record.id, user.app_user_id)
    return _build_owner_details_payload(record, role=role, include_schema=False)


@router.get("/api/template-api-endpoints/{endpoint_id}/schema")
async def get_template_api_endpoint_schema(
    endpoint_id: str,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Return the published schema for one owner-controlled API Fill endpoint."""
    user = require_user(authorization)
    role = _resolve_role_for_user(user)
    record = _resolve_endpoint_or_404(endpoint_id, user.app_user_id)
    return _build_owner_details_payload(record, role=role)
