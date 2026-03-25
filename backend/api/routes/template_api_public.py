"""Public API Fill routes for published saved-template endpoints."""

from __future__ import annotations

import os
from pathlib import Path
import hashlib
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from fastapi.responses import FileResponse

from backend.api.schemas import TemplateApiFillRequest
from backend.firebaseDB.template_api_endpoint_database import (
    create_template_api_endpoint_event,
    get_template_api_endpoint_public,
    get_template_api_monthly_usage,
    get_template_api_endpoint_for_secret,
    record_template_api_endpoint_failure,
    record_template_api_endpoint_use,
)
from backend.firebaseDB.user_database import get_user_profile, normalize_role
from backend.security.rate_limit import check_rate_limit
from backend.services.app_config import resolve_stream_cors_headers
from backend.services.contact_service import resolve_client_ip
from backend.services.pdf_service import cleanup_paths
from backend.services.limits_service import (
    resolve_template_api_active_limit,
    resolve_template_api_max_pages,
    resolve_template_api_requests_monthly_limit,
)
from backend.services.template_api_service import (
    build_template_api_key_prefix,
    build_template_api_schema,
    materialize_template_api_snapshot,
    parse_template_api_basic_secret,
    resolve_template_api_request_data,
    verify_template_api_secret,
)


router = APIRouter()


def _resolve_public_rate_limits(prefix: str) -> tuple[int, int, int]:
    window_seconds = max(1, int(os.getenv(f"{prefix}_WINDOW_SECONDS", "60") or "60"))
    per_ip = max(1, int(os.getenv(f"{prefix}_PER_IP", "60") or "60"))
    per_endpoint = max(1, int(os.getenv(f"{prefix}_PER_ENDPOINT", "120") or "120"))
    global_limit = max(0, int(os.getenv(f"{prefix}_GLOBAL", "600") or "600"))
    return window_seconds, per_ip, per_endpoint, global_limit


def _check_public_rate_limits(
    *,
    scope: str,
    client_ip: str,
    window_seconds: int,
    per_ip: int,
    global_limit: int,
) -> bool:
    if global_limit > 0:
        global_allowed = check_rate_limit(
            f"{scope}:global",
            limit=global_limit,
            window_seconds=window_seconds,
            fail_closed=True,
        )
        if not global_allowed:
            return False
    return check_rate_limit(
        f"{scope}:{client_ip}",
        limit=per_ip,
        window_seconds=window_seconds,
        fail_closed=True,
    )


def _check_endpoint_rate_limit(
    *,
    scope: str,
    endpoint_id: str,
    window_seconds: int,
    per_endpoint: int,
) -> bool:
    return check_rate_limit(
        f"{scope}:endpoint:{endpoint_id}",
        limit=per_endpoint,
        window_seconds=window_seconds,
        fail_closed=True,
    )


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="A valid API Fill key is required.",
        headers={"WWW-Authenticate": 'Basic realm="API Fill"'},
    )


def _serialize_public_endpoint(record) -> Dict[str, Any]:
    return {
        "id": record.id,
        "templateName": record.template_name,
        "status": record.status,
        "snapshotVersion": record.snapshot_version,
        "fillPath": f"/api/v1/fill/{record.id}.pdf",
        "schemaPath": f"/api/v1/fill/{record.id}/schema",
    }


def _hash_client_ip(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _record_event(record, *, event_type: str, outcome: str = "success", metadata: Optional[Dict[str, Any]] = None) -> None:
    create_template_api_endpoint_event(
        endpoint_id=record.id,
        user_id=record.user_id,
        template_id=record.template_id,
        event_type=event_type,
        outcome=outcome,
        snapshot_version=record.snapshot_version,
        metadata=metadata,
    )


def _record_auth_failure(endpoint_id: str, *, reason: str, client_ip: str) -> None:
    record = get_template_api_endpoint_public(endpoint_id)
    if record is None:
        return
    record_template_api_endpoint_failure(
        endpoint_id,
        auth_failure=True,
        suspicious=True,
        reason=reason,
    )
    _record_event(
        record,
        event_type="fill_auth_failed",
        outcome="denied",
        metadata={"reason": reason, "clientIpHash": _hash_client_ip(client_ip)},
    )


def _resolve_owner_role(record) -> str:
    profile = get_user_profile(record.user_id)
    return normalize_role(profile.role if profile else None)


def _enforce_runtime_plan_limits(record, snapshot: Dict[str, Any]) -> None:
    role = _resolve_owner_role(record)
    if resolve_template_api_active_limit(role) <= 0:
        raise HTTPException(status_code=403, detail="API Fill is unavailable on this account's current plan.")
    max_pages = resolve_template_api_max_pages(role)
    page_count = max(0, int(snapshot.get("pageCount") or 0))
    if page_count > max_pages:
        raise HTTPException(
            status_code=403,
            detail=f"API Fill templates are limited to {max_pages} pages on this account's current plan.",
        )
    monthly_limit = resolve_template_api_requests_monthly_limit(role)
    if monthly_limit <= 0:
        raise HTTPException(status_code=403, detail="API Fill is unavailable on this account's current plan.")
    monthly_usage = get_template_api_monthly_usage(record.user_id)
    if monthly_usage is not None and monthly_usage.request_count >= monthly_limit:
        raise HTTPException(status_code=429, detail="This account has reached its monthly API Fill request limit.")


def _resolve_authenticated_endpoint(endpoint_id: str, authorization: Optional[str]):
    secret = parse_template_api_basic_secret(authorization)
    if not secret:
        raise _unauthorized()
    prefix = build_template_api_key_prefix(secret)
    record = get_template_api_endpoint_for_secret(
        endpoint_id,
        key_prefix=prefix,
    )
    if record is None:
        raise _unauthorized()
    if not record.secret_hash or not verify_template_api_secret(secret, record.secret_hash):
        raise _unauthorized()
    if record.status != "active":
        raise HTTPException(status_code=404, detail="API Fill endpoint not found.")
    snapshot = dict(record.snapshot or {})
    if not snapshot:
        raise HTTPException(status_code=404, detail="API Fill snapshot is missing.")
    return record, snapshot


@router.get("/api/v1/fill/{endpoint_id}/schema")
async def get_public_template_api_schema(
    endpoint_id: str,
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    window_seconds, per_ip, per_endpoint, global_limit = _resolve_public_rate_limits("SANDBOX_TEMPLATE_API_SCHEMA_RATE_LIMIT")
    client_ip = resolve_client_ip(request)
    allowed = _check_public_rate_limits(
        scope="template_api_schema",
        client_ip=client_ip,
        window_seconds=window_seconds,
        per_ip=per_ip,
        global_limit=global_limit,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many API Fill schema requests. Please wait and try again.")
    try:
        record, snapshot = _resolve_authenticated_endpoint(endpoint_id, authorization)
    except HTTPException as exc:
        if exc.status_code == 401:
            _record_auth_failure(endpoint_id, reason="schema_auth_failed", client_ip=client_ip)
        raise
    if not _check_endpoint_rate_limit(
        scope="template_api_schema",
        endpoint_id=endpoint_id,
        window_seconds=window_seconds,
        per_endpoint=per_endpoint,
    ):
        _record_event(
            record,
            event_type="fill_rate_limited",
            outcome="denied",
            metadata={"route": "schema", "clientIpHash": _hash_client_ip(client_ip)},
        )
        raise HTTPException(status_code=429, detail="Too many API Fill schema requests for this endpoint. Please wait and try again.")
    return {
        "endpoint": _serialize_public_endpoint(record),
        "schema": build_template_api_schema(snapshot),
    }


@router.post("/api/v1/fill/{endpoint_id}.pdf")
async def fill_public_template_api_endpoint(
    endpoint_id: str,
    payload: TemplateApiFillRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    authorization: Optional[str] = Header(default=None),
):
    window_seconds, per_ip, per_endpoint, global_limit = _resolve_public_rate_limits("SANDBOX_TEMPLATE_API_FILL_RATE_LIMIT")
    client_ip = resolve_client_ip(request)
    allowed = _check_public_rate_limits(
        scope="template_api_fill",
        client_ip=client_ip,
        window_seconds=window_seconds,
        per_ip=per_ip,
        global_limit=global_limit,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many API Fill requests. Please wait and try again.")
    try:
        record, snapshot = _resolve_authenticated_endpoint(endpoint_id, authorization)
    except HTTPException as exc:
        if exc.status_code == 401:
            _record_auth_failure(endpoint_id, reason="fill_auth_failed", client_ip=client_ip)
        raise
    if not _check_endpoint_rate_limit(
        scope="template_api_fill",
        endpoint_id=endpoint_id,
        window_seconds=window_seconds,
        per_endpoint=per_endpoint,
    ):
        _record_event(
            record,
            event_type="fill_rate_limited",
            outcome="denied",
            metadata={"route": "fill", "clientIpHash": _hash_client_ip(client_ip)},
        )
        raise HTTPException(status_code=429, detail="Too many API Fill requests for this endpoint. Please wait and try again.")
    try:
        _enforce_runtime_plan_limits(record, snapshot)
    except HTTPException as exc:
        _record_event(
            record,
            event_type="fill_quota_blocked",
            outcome="denied",
            metadata={"reason": exc.detail, "clientIpHash": _hash_client_ip(client_ip)},
        )
        raise
    try:
        normalized_data = resolve_template_api_request_data(
            snapshot,
            payload.data,
            strict=bool(payload.strict),
        )
    except HTTPException as exc:
        record_template_api_endpoint_failure(
            endpoint_id,
            validation_failure=True,
            reason=str(exc.detail),
        )
        _record_event(
            record,
            event_type="fill_validation_failed",
            outcome="error",
            metadata={"reason": str(exc.detail), "strict": bool(payload.strict)},
        )
        raise

    try:
        output_path, cleanup_targets, filename = materialize_template_api_snapshot(
            snapshot,
            data=normalized_data,
            export_mode=payload.exportMode,
            filename=payload.filename,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        record_template_api_endpoint_failure(
            endpoint_id,
            validation_failure=True,
            reason=str(exc),
        )
        _record_event(
            record,
            event_type="fill_validation_failed",
            outcome="error",
            metadata={"reason": str(exc), "strict": bool(payload.strict)},
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    updated_record = record_template_api_endpoint_use(record.id) or record
    try:
        file_size = Path(output_path).stat().st_size
    except OSError:
        file_size = None
    _record_event(
        updated_record,
        event_type="fill_succeeded",
        outcome="success",
        metadata={
            "exportMode": payload.exportMode or snapshot.get("defaultExportMode"),
            "strict": bool(payload.strict),
            "filenameProvided": bool(str(payload.filename or "").strip()),
            "clientIpHash": _hash_client_ip(client_ip),
            "responseBytes": file_size,
        },
    )
    background_tasks.add_task(cleanup_paths, cleanup_targets)
    response = FileResponse(
        str(output_path),
        media_type="application/pdf",
        filename=filename,
        background=background_tasks,
    )
    response.headers.update(resolve_stream_cors_headers(request.headers.get("origin")))
    return response
