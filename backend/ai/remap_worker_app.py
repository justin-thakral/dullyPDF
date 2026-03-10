"""Cloud Run worker for async OpenAI schema mapping jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from backend.ai.openai_client import resolve_openai_worker_max_retries
from backend.ai.openai_usage import (
    build_openai_usage_summary,
    coerce_usage_events,
    is_insufficient_quota_error,
    merge_usage_events,
)
from backend.ai.schema_mapping import (
    OPENAI_SCHEMA_MODEL,
    build_allowlist_payload,
    call_openai_schema_mapping_chunked,
)
from backend.api.schemas import TemplateOverlayField
from backend.env_utils import env_truthy, env_value, int_env
from backend.firebaseDB.firebase_service import RequestUser
from backend.firebaseDB.openai_job_database import (
    get_openai_job,
    update_openai_job,
)
from backend.firebaseDB.schema_database import get_schema
from backend.firebaseDB.template_database import get_template
from backend.logging_config import get_logger
from backend.services.credit_refund_service import attempt_credit_refund
from backend.services.mapping_service import build_schema_mapping_payload
from backend.services.task_auth_service import resolve_task_audiences, verify_internal_oidc_token
from backend.sessions.session_store import (
    get_session_entry as _get_session_entry,
    update_session_entry as _update_session_entry,
)
from backend.time_utils import now_iso

from .status import (
    OPENAI_JOB_STATUS_COMPLETE,
    OPENAI_JOB_STATUS_FAILED,
    OPENAI_JOB_STATUS_RUNNING,
)


def _is_prod() -> bool:
    return env_value("ENV").lower() in {"prod", "production"}


logger = get_logger(__name__)


def _allow_unauthenticated() -> bool:
    if not env_truthy("OPENAI_REMAP_ALLOW_UNAUTHENTICATED"):
        return False
    if _is_prod():
        logger.warning("OPENAI_REMAP_ALLOW_UNAUTHENTICATED is ignored in prod.")
        return False
    env_name = env_value("ENV").lower()
    if env_name not in {"dev", "development", "local", "test"}:
        logger.warning(
            "OPENAI_REMAP_ALLOW_UNAUTHENTICATED is ignored for ENV=%s.",
            env_name or "unset",
        )
        return False
    return True


_ALLOW_UNAUTHENTICATED = _allow_unauthenticated()

app = FastAPI(title="DullyPDF OpenAI Remap Worker")


class RemapJobRequest(BaseModel):
    jobId: str = Field(..., min_length=1)
    requestId: Optional[str] = None
    schemaId: str = Field(..., min_length=1)
    templateId: Optional[str] = None
    sessionId: Optional[str] = None
    templateFields: List[Dict[str, Any]]
    userId: str = Field(..., min_length=1)
    userRole: Optional[str] = None
    credits: int = 0
    creditsCharged: bool = False
    creditBreakdown: Optional[Dict[str, int]] = None


def _parse_retry_count(raw: Optional[str]) -> int:
    if raw is None:
        return 0
    try:
        value = int(str(raw).strip())
    except ValueError:
        return 0
    return max(0, value)


def _max_task_attempts() -> Optional[int]:
    value = int_env("OPENAI_REMAP_TASKS_MAX_ATTEMPTS", int_env("OPENAI_TASKS_MAX_ATTEMPTS", 0))
    return value if value > 0 else None


def _should_finalize_failure(retry_count: int) -> bool:
    max_attempts = _max_task_attempts()
    if not max_attempts:
        return False
    return retry_count >= max_attempts - 1


def _retry_headers() -> Dict[str, str]:
    retry_after = int_env("OPENAI_REMAP_RETRY_AFTER_SECONDS", int_env("OPENAI_TASK_RETRY_AFTER_SECONDS", 5))
    headers = {"X-Dully-Retry": "true"}
    if retry_after > 0:
        headers["Retry-After"] = str(retry_after)
    return headers


def _worker_openai_max_retries() -> int:
    return resolve_openai_worker_max_retries()


def _reject_job_request(job_id: str, message: str) -> Dict[str, Any]:
    job = get_openai_job(job_id)
    job_status = str((job or {}).get("status") or "").strip().lower()
    if job and job_status not in {OPENAI_JOB_STATUS_COMPLETE, OPENAI_JOB_STATUS_FAILED}:
        _refund_stored_job(job, job_id=job_id)
        update_openai_job(
            job_id=job_id,
            status=OPENAI_JOB_STATUS_FAILED,
            error=message,
            completed_at=now_iso(),
        )
    return {
        "jobId": job_id,
        "status": OPENAI_JOB_STATUS_FAILED,
        "error": message,
    }


def _bind_payload_to_job(payload: RemapJobRequest, job: Dict[str, Any]) -> RemapJobRequest:
    trusted_user_id = str(job.get("user_id") or "").strip()
    if not trusted_user_id:
        raise ValueError("Schema mapping job metadata is incomplete")
    if payload.userId != trusted_user_id:
        raise ValueError("Schema mapping job user mismatch")

    stored_schema_id = str(job.get("schema_id") or "").strip()
    if not stored_schema_id:
        raise ValueError("Schema mapping job metadata is incomplete")
    if payload.schemaId != stored_schema_id:
        raise ValueError("Schema mapping job schema mismatch")

    stored_session_id = str(job.get("session_id") or "").strip() or None
    if stored_session_id and payload.sessionId and payload.sessionId != stored_session_id:
        raise ValueError("Schema mapping job session mismatch")

    stored_template_id = str(job.get("template_id") or "").strip() or None
    if stored_template_id and payload.templateId and payload.templateId != stored_template_id:
        raise ValueError("Schema mapping job template mismatch")

    stored_credit_breakdown = job.get("credit_breakdown")
    if not isinstance(stored_credit_breakdown, dict):
        stored_credit_breakdown = payload.creditBreakdown

    return payload.model_copy(
        update={
            "requestId": str(job.get("request_id") or "").strip() or payload.requestId or payload.jobId,
            "schemaId": stored_schema_id,
            "templateId": stored_template_id or payload.templateId,
            "sessionId": stored_session_id or payload.sessionId,
            "userId": trusted_user_id,
            "userRole": str(job.get("user_role") or "").strip() or payload.userRole,
            "credits": int(job.get("credits") or payload.credits or 0),
            "creditsCharged": bool(job.get("credits_charged")) if "credits_charged" in job else payload.creditsCharged,
            "creditBreakdown": stored_credit_breakdown,
        }
    )


def _refund_credits(payload: RemapJobRequest) -> None:
    if not payload.creditsCharged:
        return
    credits = int(payload.credits or 0)
    if credits <= 0:
        return
    attempt_credit_refund(
        user_id=payload.userId,
        role=payload.userRole,
        credits=credits,
        source="remap.worker",
        request_id=payload.requestId,
        job_id=payload.jobId,
        credit_breakdown=payload.creditBreakdown,
    )


def _refund_stored_job(job: Dict[str, Any], *, job_id: str) -> None:
    if not bool(job.get("credits_charged")):
        return
    user_id = str(job.get("user_id") or "").strip()
    if not user_id:
        return
    try:
        credits = int(job.get("credits") or 0)
    except (TypeError, ValueError):
        credits = 0
    if credits <= 0:
        return
    credit_breakdown = job.get("credit_breakdown") if isinstance(job.get("credit_breakdown"), dict) else None
    attempt_credit_refund(
        user_id=user_id,
        role=str(job.get("user_role") or "").strip() or None,
        credits=credits,
        source="remap.worker",
        request_id=str(job.get("request_id") or "").strip() or job_id,
        job_id=job_id,
        credit_breakdown=credit_breakdown,
    )


def _finish_failure(
    payload: RemapJobRequest,
    message: str,
    *,
    openai_usage_events: Optional[List[Dict[str, Any]]] = None,
    openai_usage_summary: Optional[Dict[str, Any]] = None,
    attempt_count: Optional[int] = None,
) -> Dict[str, Any]:
    _refund_credits(payload)
    result_payload: Dict[str, Any] = {}
    if isinstance(openai_usage_summary, dict):
        result_payload["openaiUsage"] = openai_usage_summary
    if isinstance(openai_usage_events, list):
        result_payload["openaiUsageEvents"] = openai_usage_events
    update_openai_job(
        job_id=payload.jobId,
        status=OPENAI_JOB_STATUS_FAILED,
        error=message,
        result=result_payload or None,
        completed_at=now_iso(),
        openai_usage_summary=openai_usage_summary,
        openai_usage_events=openai_usage_events,
        attempt_count=attempt_count,
    )
    response: Dict[str, Any] = {
        "jobId": payload.jobId,
        "status": OPENAI_JOB_STATUS_FAILED,
        "error": message,
    }
    if isinstance(openai_usage_summary, dict):
        response["openaiUsage"] = openai_usage_summary
    return response


def _require_internal_auth(authorization: Optional[str]) -> Dict[str, Any]:
    if _ALLOW_UNAUTHENTICATED:
        return {}
    raw = (authorization or "").strip()
    if not raw.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing remap worker auth token")
    token = raw.split(" ", 1)[1].strip()
    decoded = verify_internal_oidc_token(
        token,
        audiences=resolve_task_audiences(
            audience_envs=[
                "OPENAI_REMAP_TASKS_AUDIENCE",
                "OPENAI_REMAP_TASKS_AUDIENCE_LIGHT",
                "OPENAI_REMAP_TASKS_AUDIENCE_HEAVY",
            ],
            service_url_envs=[
                "OPENAI_REMAP_SERVICE_URL",
                "OPENAI_REMAP_SERVICE_URL_LIGHT",
                "OPENAI_REMAP_SERVICE_URL_HEAVY",
            ],
        ),
        missing_audience_detail="Remap worker audience is not configured",
        invalid_token_detail="Invalid remap worker auth token",
    )

    allowed_email = env_value("OPENAI_REMAP_CALLER_SERVICE_ACCOUNT")
    if _is_prod() and not allowed_email:
        raise HTTPException(status_code=500, detail="Remap worker caller service account is not configured")
    if allowed_email and decoded.get("email") != allowed_email:
        raise HTTPException(status_code=403, detail="Remap worker caller not allowed")
    return decoded


def _parse_template_fields(raw_fields: List[Dict[str, Any]]) -> List[TemplateOverlayField]:
    parsed: List[TemplateOverlayField] = []
    for raw in raw_fields:
        try:
            parsed.append(TemplateOverlayField.model_validate(raw))
        except Exception:
            continue
    return parsed


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/internal/remap")
async def run_remap_job(
    payload: RemapJobRequest,
    authorization: Optional[str] = Header(default=None),
    x_cloud_tasks_taskretrycount: Optional[str] = Header(
        default=None,
        alias="X-CloudTasks-TaskRetryCount",
    ),
) -> Dict[str, Any]:
    try:
        _require_internal_auth(authorization)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Schema mapping worker request rejected"
        logger.warning("Schema mapping job %s rejected before start: %s", payload.jobId, detail)
        return _reject_job_request(payload.jobId, str(detail))

    job = get_openai_job(payload.jobId)
    if not job:
        logger.warning("Schema mapping job %s rejected: metadata not found", payload.jobId)
        return _reject_job_request(payload.jobId, "Schema mapping job metadata not found")

    status = str(job.get("status") or "").strip().lower()
    if status == OPENAI_JOB_STATUS_COMPLETE:
        return {"jobId": payload.jobId, "status": OPENAI_JOB_STATUS_COMPLETE}
    if status == OPENAI_JOB_STATUS_FAILED:
        return {
            "jobId": payload.jobId,
            "status": OPENAI_JOB_STATUS_FAILED,
            "error": job.get("error") or "Schema mapping job failed",
        }

    try:
        payload = _bind_payload_to_job(payload, job)
    except ValueError as exc:
        logger.warning("Schema mapping job %s rejected: %s", payload.jobId, exc)
        return _reject_job_request(payload.jobId, str(exc))

    retry_count = _parse_retry_count(x_cloud_tasks_taskretrycount)
    attempt_count = retry_count + 1
    usage_events = coerce_usage_events(job.get("openai_usage_events"))
    usage_summary = (
        dict(job.get("openai_usage_summary"))
        if isinstance(job.get("openai_usage_summary"), dict)
        else build_openai_usage_summary(usage_events)
    )

    update_openai_job(
        job_id=payload.jobId,
        status=OPENAI_JOB_STATUS_RUNNING,
        error="",
        started_at=now_iso(),
        openai_usage_summary=usage_summary,
        openai_usage_events=usage_events,
        attempt_count=attempt_count,
    )

    try:
        schema = get_schema(payload.schemaId, payload.userId)
        if not schema:
            raise HTTPException(status_code=404, detail="Schema not found")

        if payload.templateId:
            template = get_template(payload.templateId, payload.userId)
            if not template:
                raise HTTPException(status_code=403, detail="Template access denied")
        elif not payload.sessionId:
            raise HTTPException(status_code=400, detail="sessionId or templateId is required")

        parsed_template_fields = _parse_template_fields(payload.templateFields or [])
        if not parsed_template_fields:
            raise HTTPException(status_code=400, detail="templateFields is required")
        template_fields = [field.model_dump() for field in parsed_template_fields]

        allowlist_payload = build_allowlist_payload(schema.fields, template_fields)
        template_tags = allowlist_payload.get("templateTags") or []
        if not template_tags:
            raise HTTPException(status_code=400, detail="No valid template tags provided")

        session_entry = None
        if payload.sessionId:
            user = RequestUser(
                uid=payload.userId,
                app_user_id=payload.userId,
                role=payload.userRole,
            )
            session_entry = _get_session_entry(
                payload.sessionId,
                user,
                include_pdf_bytes=False,
                include_fields=False,
                include_result=False,
                include_renames=False,
                include_checkbox_rules=False,
                include_checkbox_hints=False,
            )

        attempt_usage_events: List[Dict[str, Any]] = []
        ai_response = call_openai_schema_mapping_chunked(
            allowlist_payload,
            usage_collector=attempt_usage_events,
            openai_max_retries=_worker_openai_max_retries(),
        )
        usage_events = merge_usage_events(
            usage_events,
            attempt_usage_events,
            attempt=attempt_count,
        )
        usage_summary = build_openai_usage_summary(usage_events, model=OPENAI_SCHEMA_MODEL)
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

        resolved_request_id = (
            payload.requestId
            or str(job.get("request_id") or "").strip()
            or payload.jobId
        )
        result = {
            "success": True,
            "requestId": resolved_request_id,
            "schemaId": schema.id,
            "mappingResults": mapping_results,
            "openaiUsage": usage_summary,
            "openaiUsageEvents": usage_events,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }
        update_openai_job(
            job_id=payload.jobId,
            status=OPENAI_JOB_STATUS_COMPLETE,
            error="",
            result=result,
            completed_at=now_iso(),
            openai_usage_summary=usage_summary,
            openai_usage_events=usage_events,
            attempt_count=attempt_count,
        )
        return {
            "jobId": payload.jobId,
            "status": OPENAI_JOB_STATUS_COMPLETE,
            "mappingCount": len(mapping_results.get("mappings") or []),
            "openaiUsage": usage_summary,
        }
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Schema mapping job rejected"
        if exc.status_code < 500 or _should_finalize_failure(retry_count):
            logger.warning("Schema mapping job %s failed: %s", payload.jobId, detail)
            return _finish_failure(
                payload,
                str(detail),
                openai_usage_events=usage_events,
                openai_usage_summary=usage_summary,
                attempt_count=attempt_count,
            )
        raise HTTPException(
            status_code=500,
            detail="Schema mapping worker failed; retrying",
            headers=_retry_headers(),
        ) from exc
    except ValueError as exc:
        if _should_finalize_failure(retry_count):
            return _finish_failure(
                payload,
                str(exc),
                openai_usage_events=usage_events,
                openai_usage_summary=usage_summary,
                attempt_count=attempt_count,
            )
        raise HTTPException(
            status_code=500,
            detail="Schema mapping worker failed; retrying",
            headers=_retry_headers(),
        ) from exc
    except Exception as exc:
        if is_insufficient_quota_error(exc):
            message = f"OpenAI insufficient_quota: {exc}"
            logger.warning("Schema mapping job %s terminal failure: %s", payload.jobId, message)
            return _finish_failure(
                payload,
                message,
                openai_usage_events=usage_events,
                openai_usage_summary=usage_summary,
                attempt_count=attempt_count,
            )
        logger.exception("Schema mapping job %s failed: %s", payload.jobId, exc)
        if _should_finalize_failure(retry_count):
            message = f"Schema mapping failed after {retry_count + 1} attempts: {exc}"
            return _finish_failure(
                payload,
                message,
                openai_usage_events=usage_events,
                openai_usage_summary=usage_summary,
                attempt_count=attempt_count,
            )
        raise HTTPException(
            status_code=500,
            detail="Schema mapping worker failed; retrying",
            headers=_retry_headers(),
        ) from exc
