"""OpenAI rename and schema mapping endpoints."""

from __future__ import annotations

import uuid
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Request

from backend.ai.credit_pricing import (
    OPENAI_CREDIT_OPERATION_REMAP,
    OPENAI_CREDIT_OPERATION_RENAME,
    OPENAI_CREDIT_OPERATION_RENAME_REMAP,
    compute_credit_pricing,
)
from backend.ai.rename_pipeline import run_openai_rename_on_pdf
from backend.ai.openai_usage import build_openai_usage_summary
from backend.ai.schema_mapping import (
    build_allowlist_payload,
    call_openai_schema_mapping_chunked,
    validate_payload_size,
)
from backend.ai.status import (
    OPENAI_JOB_STATUS_COMPLETE,
    OPENAI_JOB_STATUS_FAILED,
    OPENAI_JOB_STATUS_QUEUED,
    OPENAI_JOB_TYPE_REMAP,
    OPENAI_JOB_TYPE_RENAME,
)
from backend.ai.tasks import (
    enqueue_openai_remap_task,
    enqueue_openai_rename_task,
    resolve_openai_remap_profile,
    resolve_openai_rename_profile,
    resolve_openai_task_config,
)
from backend.api.schemas import RenameFieldsRequest, SchemaMappingRequest
from backend.firebaseDB.openai_job_database import (
    create_openai_job,
    get_openai_job,
    update_openai_job,
)
from backend.firebaseDB.user_database import (
    ROLE_GOD,
    consume_openai_credits,
    ensure_user,
    normalize_role,
)
from backend.firebaseDB.template_database import get_template
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
from backend.services.app_config import (
    resolve_openai_remap_mode,
    resolve_openai_rename_mode,
)
from backend.services.auth_service import require_user
from backend.services.credit_refund_service import attempt_credit_refund
from backend.logging_config import get_logger
from backend.services.mapping_service import build_schema_mapping_payload, template_fields_to_rename_fields
from backend.services.pdf_service import get_pdf_page_count
from backend.time_utils import now_iso

router = APIRouter()
logger = get_logger(__name__)


def _resolve_user_from_request(request: Request, authorization: Optional[str]):
    auth_payload = getattr(request.state, "preverified_auth_payload", None)
    if auth_payload is None:
        return require_user(authorization)
    try:
        return ensure_user(auth_payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to synchronize user profile") from exc


def _safe_positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _normalize_credit_breakdown(raw: Any) -> Dict[str, int]:
    payload = raw if isinstance(raw, dict) else {}
    normalized: Dict[str, int] = {}
    for key in ("base", "monthly", "refill"):
        try:
            value = int(payload.get(key, 0))
        except (TypeError, ValueError):
            value = 0
        normalized[key] = value if value > 0 else 0
    return normalized


def _coerce_consume_result(raw: Any) -> tuple[int, bool, Dict[str, int]]:
    def _to_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    if isinstance(raw, tuple):
        if len(raw) >= 3:
            remaining = _to_int(raw[0], 0)
            allowed = bool(raw[1])
            return remaining, allowed, _normalize_credit_breakdown(raw[2])
        if len(raw) >= 2:
            remaining = _to_int(raw[0], 0)
            allowed = bool(raw[1])
            return remaining, allowed, {"base": 0, "monthly": 0, "refill": 0}
    raise RuntimeError("Invalid consume_openai_credits result")


def _refund_credits_if_charged(
    *,
    user_id: str,
    role: str,
    credits: int,
    charged: bool,
    source: str,
    request_id: Optional[str] = None,
    job_id: Optional[str] = None,
    credit_breakdown: Optional[Dict[str, int]] = None,
) -> None:
    if not charged:
        return
    success = attempt_credit_refund(
        user_id=user_id,
        role=role,
        credits=credits,
        source=source,
        request_id=request_id,
        job_id=job_id,
        credit_breakdown=credit_breakdown,
    )
    if not success:
        logger.error(
            "Credit refund did not complete immediately (source=%s, user_id=%s, request_id=%s, job_id=%s).",
            source,
            user_id,
            request_id or "",
            job_id or "",
        )


def _task_mode_enabled(mode: str) -> bool:
    return (mode or "").strip().lower() == "tasks"


def _coerce_positive_int(value: Any) -> Optional[int]:
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        return None
    return resolved if resolved > 0 else None


def _resolve_template_metadata_page_count(template: Any) -> Optional[int]:
    metadata = getattr(template, "metadata", None)
    if not isinstance(metadata, dict):
        return None

    for key in ("page_count", "pageCount", "pdf_page_count", "pdfPageCount", "num_pages", "numPages"):
        page_count = _coerce_positive_int(metadata.get(key))
        if page_count is not None:
            return page_count

    nested_pdf = metadata.get("pdf")
    if isinstance(nested_pdf, dict):
        for key in ("page_count", "pageCount", "num_pages", "numPages", "pages"):
            page_count = _coerce_positive_int(nested_pdf.get(key))
            if page_count is not None:
                return page_count
    return None


def _serialize_template_fields(payload_fields) -> Optional[List[Dict[str, Any]]]:
    if not payload_fields:
        return None
    serialized: List[Dict[str, Any]] = []
    for field in payload_fields:
        try:
            serialized.append(field.model_dump())
        except Exception:
            continue
    return serialized or None


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

    window_seconds = _safe_positive_int_env("OPENAI_RENAME_RATE_LIMIT_WINDOW_SECONDS", 60)
    user_rate = _safe_positive_int_env("OPENAI_RENAME_RATE_LIMIT_PER_USER", 6)

    if not check_rate_limit(f"rename:user:{user.app_user_id}", limit=user_rate, window_seconds=window_seconds):
        raise HTTPException(status_code=429, detail="Rate limit exceeded for user")

    page_count = _coerce_positive_int(entry.get("page_count"))
    if page_count is None:
        page_count = _coerce_positive_int(get_pdf_page_count(pdf_bytes))
    if page_count is None:
        raise HTTPException(status_code=400, detail="Unable to determine document page count for credit pricing")

    credit_operation = OPENAI_CREDIT_OPERATION_RENAME_REMAP if schema_id else OPENAI_CREDIT_OPERATION_RENAME
    credit_pricing = compute_credit_pricing(credit_operation, page_count=page_count)
    credits_required = credit_pricing.total_credits

    remaining, allowed, credit_breakdown = _coerce_consume_result(
        consume_openai_credits(
            user.app_user_id,
            credits=credits_required,
            role=user.role,
            include_breakdown=True,
        )
    )
    if not allowed:
        raise HTTPException(
            status_code=402,
            detail=f"OpenAI credits exhausted (remaining={remaining}, required={credits_required})",
        )
    credits_charged = normalize_role(user.role) != ROLE_GOD

    request_id = uuid.uuid4().hex
    try:
        record_openai_rename_request(
            request_id=request_id,
            user_id=user.app_user_id,
            session_id=payload.sessionId,
            schema_id=schema_id,
        )
    except Exception as exc:
        _refund_credits_if_charged(
            user_id=user.app_user_id,
            role=user.role,
            credits=credits_required,
            charged=credits_charged,
            source="rename.request_log",
            request_id=request_id,
            credit_breakdown=credit_breakdown,
        )
        status_code = getattr(exc, "status_code", None) or 500
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    if _task_mode_enabled(resolve_openai_rename_mode()):
        profile = resolve_openai_rename_profile(page_count)
        task_config = resolve_openai_task_config("rename", profile)
        serialized_template_fields = _serialize_template_fields(payload.templateFields)

        try:
            create_openai_job(
                job_id=request_id,
                request_id=request_id,
                job_type=OPENAI_JOB_TYPE_RENAME,
                user_id=user.app_user_id,
                session_id=payload.sessionId,
                schema_id=schema_id,
                status=OPENAI_JOB_STATUS_QUEUED,
                profile=task_config.get("profile"),
                queue=task_config.get("queue"),
                service_url=task_config.get("service_url"),
                page_count=page_count,
                template_field_count=len(rename_fields),
                credits=credits_required,
                credit_pricing=credit_pricing.to_dict(),
                credits_charged=credits_charged,
                credit_breakdown=credit_breakdown,
                user_role=user.role,
            )
            task_name = enqueue_openai_rename_task(
                {
                    "jobId": request_id,
                    "requestId": request_id,
                    "sessionId": payload.sessionId,
                    "schemaId": schema_id,
                    "templateFields": serialized_template_fields,
                    "userId": user.app_user_id,
                    "userRole": user.role,
                    "pageCount": page_count,
                    "credits": credits_required,
                    "creditPricing": credit_pricing.to_dict(),
                    "creditsCharged": credits_charged,
                    "creditBreakdown": credit_breakdown,
                },
                profile=profile,
            )
            update_openai_job(job_id=request_id, task_name=task_name)
        except Exception as exc:
            _refund_credits_if_charged(
                user_id=user.app_user_id,
                role=user.role,
                credits=credits_required,
                charged=credits_charged,
                source="rename.enqueue",
                request_id=request_id,
                job_id=request_id,
                credit_breakdown=credit_breakdown,
            )
            update_openai_job(
                job_id=request_id,
                status=OPENAI_JOB_STATUS_FAILED,
                error=str(exc),
                completed_at=now_iso(),
            )
            raise HTTPException(status_code=500, detail="Failed to enqueue rename job") from exc

        return {
            "success": True,
            "requestId": request_id,
            "jobId": request_id,
            "sessionId": payload.sessionId,
            "schemaId": schema_id,
            "status": OPENAI_JOB_STATUS_QUEUED,
            "pageCount": page_count,
            "creditPricing": credit_pricing.to_dict(),
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }

    try:
        rename_report, renamed_fields = run_openai_rename_on_pdf(
            pdf_bytes=pdf_bytes,
            pdf_name=entry.get("source_pdf") or "document.pdf",
            fields=rename_fields,
            database_fields=database_fields,
        )
    except Exception as exc:
        _refund_credits_if_charged(
            user_id=user.app_user_id,
            role=user.role,
            credits=credits_required,
            charged=credits_charged,
            source="rename.sync_openai",
            request_id=request_id,
            credit_breakdown=credit_breakdown,
        )
        status_code = getattr(exc, "status_code", None) or 500
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    checkbox_rules = rename_report.get("checkboxRules") or []
    entry["fields"] = renamed_fields
    entry["renames"] = rename_report
    entry["checkboxRules"] = checkbox_rules
    # Rename does not emit checkbox hints, so clear any previous hints to avoid stale
    # Search & Fill behavior after reruns on the same session.
    entry["checkboxHints"] = []
    # Text transform rules are produced by schema mapping, not rename.
    # Clear stale rules on rename reruns because field names may have changed.
    entry["textTransformRules"] = []
    entry["page_count"] = page_count
    _update_session_entry(
        payload.sessionId,
        entry,
        persist_fields=True,
        persist_renames=True,
        persist_checkbox_rules=True,
        persist_checkbox_hints=True,
        persist_text_transform_rules=True,
    )

    return {
        "success": True,
        "requestId": request_id,
        "sessionId": payload.sessionId,
        "schemaId": schema_id,
        "renames": rename_report,
        "fields": renamed_fields,
        "checkboxRules": checkbox_rules,
        "pageCount": page_count,
        "creditPricing": credit_pricing.to_dict(),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


@router.get("/api/renames/ai/{job_id}")
async def get_rename_job_status(
    request: Request,
    job_id: str,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    user = _resolve_user_from_request(request, authorization)
    job = get_openai_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Rename job not found")
    if str(job.get("job_type") or "") != OPENAI_JOB_TYPE_RENAME:
        raise HTTPException(status_code=404, detail="Rename job not found")
    if str(job.get("user_id") or "") != user.app_user_id:
        raise HTTPException(status_code=403, detail="Rename job access denied")

    status = str(job.get("status") or OPENAI_JOB_STATUS_FAILED).strip().lower()
    response: Dict[str, Any] = {
        "success": status == OPENAI_JOB_STATUS_COMPLETE,
        "jobId": job_id,
        "requestId": job.get("request_id") or job_id,
        "status": status,
        "sessionId": job.get("session_id"),
        "schemaId": job.get("schema_id"),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }
    if status == OPENAI_JOB_STATUS_FAILED:
        response["error"] = job.get("error") or "Rename job failed"
    result = job.get("result")
    if isinstance(result, dict):
        response["result"] = result
        if status == OPENAI_JOB_STATUS_COMPLETE:
            response.update(result)
    openai_usage = job.get("openai_usage_summary")
    if isinstance(openai_usage, dict):
        response["openaiUsage"] = openai_usage
    openai_usage_events = job.get("openai_usage_events")
    if isinstance(openai_usage_events, list):
        response["openaiUsageEvents"] = openai_usage_events
    attempt_count = job.get("attempt_count")
    if isinstance(attempt_count, int):
        response["attemptCount"] = attempt_count
    return response


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
    window_seconds = _safe_positive_int_env("OPENAI_SCHEMA_RATE_LIMIT_WINDOW_SECONDS", 60)
    user_rate = _safe_positive_int_env("OPENAI_SCHEMA_RATE_LIMIT_PER_USER", 10)

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

    page_count = _coerce_positive_int((session_entry or {}).get("page_count"))
    if page_count is None:
        page_count = _resolve_template_metadata_page_count(template)
    if page_count is None:
        raise HTTPException(status_code=400, detail="Unable to determine document page count for credit pricing")

    credit_pricing = compute_credit_pricing(
        OPENAI_CREDIT_OPERATION_REMAP,
        page_count=page_count,
    )
    credits_required = credit_pricing.total_credits

    remaining, allowed, credit_breakdown = _coerce_consume_result(
        consume_openai_credits(
            user.app_user_id,
            credits=credits_required,
            role=user.role,
            include_breakdown=True,
        )
    )
    if not allowed:
        raise HTTPException(
            status_code=402,
            detail=f"OpenAI credits exhausted (remaining={remaining}, required={credits_required})",
        )
    credits_charged = normalize_role(user.role) != ROLE_GOD

    request_id = uuid.uuid4().hex
    try:
        record_openai_request(
            request_id=request_id,
            user_id=user.app_user_id,
            schema_id=schema.id,
            template_id=payload.templateId,
        )
    except Exception as exc:
        _refund_credits_if_charged(
            user_id=user.app_user_id,
            role=user.role,
            credits=credits_required,
            charged=credits_charged,
            source="remap.request_log",
            request_id=request_id,
            credit_breakdown=credit_breakdown,
        )
        status_code = getattr(exc, "status_code", None) or 500
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    if _task_mode_enabled(resolve_openai_remap_mode()):
        profile = resolve_openai_remap_profile(len(template_fields))
        task_config = resolve_openai_task_config("remap", profile)
        try:
            create_openai_job(
                job_id=request_id,
                request_id=request_id,
                job_type=OPENAI_JOB_TYPE_REMAP,
                user_id=user.app_user_id,
                session_id=payload.sessionId,
                schema_id=schema.id,
                template_id=payload.templateId,
                status=OPENAI_JOB_STATUS_QUEUED,
                profile=task_config.get("profile"),
                queue=task_config.get("queue"),
                service_url=task_config.get("service_url"),
                page_count=page_count,
                template_field_count=len(template_fields),
                credits=credits_required,
                credit_pricing=credit_pricing.to_dict(),
                credits_charged=credits_charged,
                credit_breakdown=credit_breakdown,
                user_role=user.role,
            )
            task_name = enqueue_openai_remap_task(
                {
                    "jobId": request_id,
                    "requestId": request_id,
                    "schemaId": schema.id,
                    "templateId": payload.templateId,
                    "templateFields": template_fields,
                    "sessionId": payload.sessionId,
                    "userId": user.app_user_id,
                    "userRole": user.role,
                    "pageCount": page_count,
                    "credits": credits_required,
                    "creditPricing": credit_pricing.to_dict(),
                    "creditsCharged": credits_charged,
                    "creditBreakdown": credit_breakdown,
                },
                profile=profile,
            )
            update_openai_job(job_id=request_id, task_name=task_name)
        except Exception as exc:
            _refund_credits_if_charged(
                user_id=user.app_user_id,
                role=user.role,
                credits=credits_required,
                charged=credits_charged,
                source="remap.enqueue",
                request_id=request_id,
                job_id=request_id,
                credit_breakdown=credit_breakdown,
            )
            update_openai_job(
                job_id=request_id,
                status=OPENAI_JOB_STATUS_FAILED,
                error=str(exc),
                completed_at=now_iso(),
            )
            raise HTTPException(status_code=500, detail="Failed to enqueue schema mapping job") from exc

        return {
            "success": True,
            "requestId": request_id,
            "jobId": request_id,
            "schemaId": schema.id,
            "status": OPENAI_JOB_STATUS_QUEUED,
            "pageCount": page_count,
            "creditPricing": credit_pricing.to_dict(),
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }

    try:
        openai_usage_events: List[Dict[str, Any]] = []
        ai_response = call_openai_schema_mapping_chunked(
            allowlist_payload,
            usage_collector=openai_usage_events,
        )
        openai_usage_summary = build_openai_usage_summary(openai_usage_events)
    except ValueError as exc:
        _refund_credits_if_charged(
            user_id=user.app_user_id,
            role=user.role,
            credits=credits_required,
            charged=credits_charged,
            source="remap.sync_openai",
            request_id=request_id,
            credit_breakdown=credit_breakdown,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        _refund_credits_if_charged(
            user_id=user.app_user_id,
            role=user.role,
            credits=credits_required,
            charged=credits_charged,
            source="remap.sync_openai",
            request_id=request_id,
            credit_breakdown=credit_breakdown,
        )
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
        persist_text_rules = False
        if isinstance(mapping_results, dict):
            # Persist explicit arrays (including empty arrays) so newer mapping results
            # can clear stale checkbox behavior from prior runs.
            checkbox_rules = list(mapping_results.get("checkboxRules") or [])
            session_entry["checkboxRules"] = checkbox_rules
            persist_rules = True
            checkbox_hints = list(mapping_results.get("checkboxHints") or [])
            session_entry["checkboxHints"] = checkbox_hints
            persist_hints = True
            text_transform_rules = list(mapping_results.get("textTransformRules") or [])
            session_entry["textTransformRules"] = text_transform_rules
            persist_text_rules = True
        _update_session_entry(
            payload.sessionId,
            session_entry,
            persist_checkbox_rules=persist_rules,
            persist_checkbox_hints=persist_hints,
            persist_text_transform_rules=persist_text_rules,
        )
    return {
        "success": True,
        "requestId": request_id,
        "schemaId": schema.id,
        "mappingResults": mapping_results,
        "pageCount": page_count,
        "creditPricing": credit_pricing.to_dict(),
        "openaiUsage": openai_usage_summary,
        "openaiUsageEvents": openai_usage_events,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


@router.get("/api/schema-mappings/ai/{job_id}")
async def get_schema_mapping_job_status(
    request: Request,
    job_id: str,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    user = _resolve_user_from_request(request, authorization)
    job = get_openai_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Schema mapping job not found")
    if str(job.get("job_type") or "") != OPENAI_JOB_TYPE_REMAP:
        raise HTTPException(status_code=404, detail="Schema mapping job not found")
    if str(job.get("user_id") or "") != user.app_user_id:
        raise HTTPException(status_code=403, detail="Schema mapping job access denied")

    status = str(job.get("status") or OPENAI_JOB_STATUS_FAILED).strip().lower()
    response: Dict[str, Any] = {
        "success": status == OPENAI_JOB_STATUS_COMPLETE,
        "jobId": job_id,
        "requestId": job.get("request_id") or job_id,
        "status": status,
        "schemaId": job.get("schema_id"),
        "sessionId": job.get("session_id"),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }
    if status == OPENAI_JOB_STATUS_FAILED:
        response["error"] = job.get("error") or "Schema mapping job failed"
    result = job.get("result")
    if isinstance(result, dict):
        response["result"] = result
        if status == OPENAI_JOB_STATUS_COMPLETE:
            response.update(result)
    openai_usage = job.get("openai_usage_summary")
    if isinstance(openai_usage, dict):
        response["openaiUsage"] = openai_usage
    openai_usage_events = job.get("openai_usage_events")
    if isinstance(openai_usage_events, list):
        response["openaiUsageEvents"] = openai_usage_events
    attempt_count = job.get("attempt_count")
    if isinstance(attempt_count, int):
        response["attemptCount"] = attempt_count
    return response
