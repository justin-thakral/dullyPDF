"""OpenAI rename and schema mapping endpoints."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Request

from backend.ai.rename_pipeline import run_openai_rename_on_pdf
from backend.ai.schema_mapping import (
    build_allowlist_payload,
    call_openai_schema_mapping_chunked,
    validate_payload_size,
)
from backend.api.schemas import RenameFieldsRequest, SchemaMappingRequest
from backend.firebaseDB.app_database import (
    ROLE_GOD,
    consume_openai_credits,
    ensure_user,
    get_template,
    normalize_role,
    refund_openai_credits,
)
from backend.firebaseDB.schema_database import (
    get_schema,
    record_openai_rename_request,
    record_openai_request,
)
from backend.security.rate_limit import check_rate_limit
from backend.sessions.session_store import (
    get_session_entry as _get_session_entry,
    update_session_entry as _update_session_entry,
)
from backend.services.auth_service import require_user
from backend.services.mapping_service import build_schema_mapping_payload, template_fields_to_rename_fields
from backend.services.pdf_service import get_pdf_page_count

router = APIRouter()


def _resolve_user_from_request(request: Request, authorization: Optional[str]):
    auth_payload = getattr(request.state, "preverified_auth_payload", None)
    if auth_payload is None:
        return require_user(authorization)
    try:
        return ensure_user(auth_payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to synchronize user profile") from exc


@router.post("/api/renames/ai")
async def rename_fields_ai(
    request: Request,
    payload: RenameFieldsRequest,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Run OpenAI rename using cached PDF bytes and overlay tags."""
    user = _resolve_user_from_request(request, authorization)

    entry = _get_session_entry(
        payload.sessionId,
        user,
        include_result=False,
        include_renames=False,
        include_checkbox_rules=False,
        force_l2=True,
    )
    pdf_bytes = entry.get("pdf_bytes")
    if not pdf_bytes:
        raise HTTPException(status_code=404, detail="Session PDF not found")

    rename_fields: List[Dict[str, Any]]
    if payload.templateFields:
        rename_fields = template_fields_to_rename_fields(payload.templateFields)
    else:
        rename_fields = list(entry.get("fields") or [])
    if not rename_fields:
        raise HTTPException(status_code=400, detail="No fields available for rename")

    database_fields: Optional[List[str]] = None
    schema_id: Optional[str] = None
    if payload.schemaId:
        schema = get_schema(payload.schemaId, user.app_user_id)
        if not schema:
            raise HTTPException(status_code=404, detail="Schema not found")
        allowlist = build_allowlist_payload(schema.fields, [])
        schema_fields = allowlist.get("schemaFields") or []
        if not schema_fields:
            raise HTTPException(status_code=400, detail="Schema fields are required for rename")
        try:
            validate_payload_size(allowlist)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        database_fields = [field.get("name") for field in schema_fields if field.get("name")]
        schema_id = schema.id

    try:
        window_seconds = int(os.getenv("OPENAI_RENAME_RATE_LIMIT_WINDOW_SECONDS", "60"))
    except ValueError:
        window_seconds = 60
    try:
        user_rate = int(os.getenv("OPENAI_RENAME_RATE_LIMIT_PER_USER", "6"))
    except ValueError:
        user_rate = 6

    if not check_rate_limit(f"rename:user:{user.app_user_id}", limit=user_rate, window_seconds=window_seconds):
        raise HTTPException(status_code=429, detail="Rate limit exceeded for user")

    credits_required = 2 if schema_id else 1
    page_count = entry.get("page_count") or get_pdf_page_count(pdf_bytes)
    remaining, allowed = consume_openai_credits(
        user.app_user_id,
        credits=credits_required,
        role=user.role,
    )
    if not allowed:
        raise HTTPException(
            status_code=402,
            detail=f"OpenAI credits exhausted (remaining={remaining}, required={credits_required})",
        )
    credits_charged = normalize_role(user.role) != ROLE_GOD

    request_id = uuid.uuid4().hex
    record_openai_rename_request(
        request_id=request_id,
        user_id=user.app_user_id,
        session_id=payload.sessionId,
        schema_id=schema_id,
    )

    try:
        rename_report, renamed_fields = run_openai_rename_on_pdf(
            pdf_bytes=pdf_bytes,
            pdf_name=entry.get("source_pdf") or "document.pdf",
            fields=rename_fields,
            database_fields=database_fields,
        )
    except Exception as exc:
        if credits_charged:
            try:
                refund_openai_credits(
                    user.app_user_id,
                    credits=credits_required,
                    role=user.role,
                )
            except Exception:
                pass
        status_code = getattr(exc, "status_code", None) or 500
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    checkbox_rules = rename_report.get("checkboxRules") or []
    entry["fields"] = renamed_fields
    entry["renames"] = rename_report
    entry["checkboxRules"] = checkbox_rules
    entry["page_count"] = page_count
    _update_session_entry(
        payload.sessionId,
        entry,
        persist_fields=True,
        persist_renames=True,
        persist_checkbox_rules=True,
    )

    return {
        "success": True,
        "requestId": request_id,
        "sessionId": payload.sessionId,
        "schemaId": schema_id,
        "renames": rename_report,
        "fields": renamed_fields,
        "checkboxRules": checkbox_rules,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


@router.post("/api/schema-mappings/ai")
async def map_schema_ai(
    request: Request,
    payload: SchemaMappingRequest,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Run OpenAI mapping using schema metadata + template overlay tags."""
    user = _resolve_user_from_request(request, authorization)
    schema = get_schema(payload.schemaId, user.app_user_id)
    if not schema:
        raise HTTPException(status_code=404, detail="Schema not found")

    template = None
    if payload.templateId:
        template = get_template(payload.templateId, user.app_user_id)
        if not template:
            raise HTTPException(status_code=403, detail="Template access denied")
    if not payload.sessionId and not template:
        raise HTTPException(status_code=400, detail="sessionId or templateId is required")

    template_fields = [field.model_dump() for field in payload.templateFields]
    if not template_fields:
        raise HTTPException(status_code=400, detail="templateFields is required")

    allowlist_payload = build_allowlist_payload(schema.fields, template_fields)
    template_tags = allowlist_payload.get("templateTags") or []
    if not template_tags:
        raise HTTPException(status_code=400, detail="No valid template tags provided")
    try:
        window_seconds = int(os.getenv("OPENAI_SCHEMA_RATE_LIMIT_WINDOW_SECONDS", "60"))
    except ValueError:
        window_seconds = 60
    try:
        user_rate = int(os.getenv("OPENAI_SCHEMA_RATE_LIMIT_PER_USER", "10"))
    except ValueError:
        user_rate = 10

    if not check_rate_limit(f"user:{user.app_user_id}", limit=user_rate, window_seconds=window_seconds):
        raise HTTPException(status_code=429, detail="Rate limit exceeded for user")

    session_entry = None
    if payload.sessionId:
        session_entry = _get_session_entry(
            payload.sessionId,
            user,
            include_pdf_bytes=False,
            include_fields=False,
            include_result=False,
            include_renames=False,
            include_checkbox_rules=False,
        )
    credits_required = 1
    remaining, allowed = consume_openai_credits(
        user.app_user_id,
        credits=credits_required,
        role=user.role,
    )
    if not allowed:
        raise HTTPException(
            status_code=402,
            detail=f"OpenAI credits exhausted (remaining={remaining}, required={credits_required})",
        )
    credits_charged = normalize_role(user.role) != ROLE_GOD

    request_id = uuid.uuid4().hex
    record_openai_request(
        request_id=request_id,
        user_id=user.app_user_id,
        schema_id=schema.id,
        template_id=payload.templateId,
    )

    try:
        ai_response = call_openai_schema_mapping_chunked(allowlist_payload)
    except ValueError as exc:
        if credits_charged:
            try:
                refund_openai_credits(user.app_user_id, credits=credits_required, role=user.role)
            except Exception:
                pass
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        if credits_charged:
            try:
                refund_openai_credits(user.app_user_id, credits=credits_required, role=user.role)
            except Exception:
                pass
        status_code = getattr(exc, "status_code", None) or 500
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    mapping_results = build_schema_mapping_payload(
        allowlist_payload.get("schemaFields") or [],
        allowlist_payload.get("templateTags") or [],
        ai_response,
    )
    if session_entry and payload.sessionId:
        persist_rules = False
        persist_hints = False
        if isinstance(mapping_results, dict):
            checkbox_rules = list(mapping_results.get("checkboxRules") or [])
            if checkbox_rules:
                session_entry["checkboxRules"] = checkbox_rules
                persist_rules = True
            checkbox_hints = list(mapping_results.get("checkboxHints") or [])
            if checkbox_hints:
                session_entry["checkboxHints"] = checkbox_hints
                persist_hints = True
        _update_session_entry(
            payload.sessionId,
            session_entry,
            persist_checkbox_rules=persist_rules,
            persist_checkbox_hints=persist_hints,
        )
    return {
        "success": True,
        "requestId": request_id,
        "schemaId": schema.id,
        "mappingResults": mapping_results,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }
