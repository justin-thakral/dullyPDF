"""Cloud Run worker for async OpenAI rename jobs."""

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
from backend.ai.rename_pipeline import run_openai_rename_on_pdf
from backend.ai.schema_mapping import build_allowlist_payload, validate_payload_size
from backend.api.schemas import TemplateOverlayField
from backend.env_utils import env_truthy, env_value, int_env
from backend.firebaseDB.firebase_service import RequestUser
from backend.firebaseDB.openai_job_database import (
    get_openai_job,
    update_openai_job,
)
from backend.firebaseDB.schema_database import get_schema
from backend.logging_config import get_logger
from backend.services.credit_refund_service import attempt_credit_refund
from backend.services.mapping_service import template_fields_to_rename_fields
from backend.services.pdf_service import get_pdf_page_count
from backend.services.task_auth_service import resolve_task_audiences, verify_internal_oidc_token
from backend.sessions.session_store import (
    get_session_entry as _get_session_entry,
    update_session_entry as _update_session_entry,
)
from backend.time_utils import now_iso

from .status import (
    OPENAI_JOB_STATUS_COMPLETE,
    OPENAI_JOB_STATUS_FAILED,
    OPENAI_JOB_STATUS_QUEUED,
    OPENAI_JOB_STATUS_RUNNING,
)


def _is_prod() -> bool:
    return env_value("ENV").lower() in {"prod", "production"}


logger = get_logger(__name__)


def _allow_unauthenticated() -> bool:
    if not env_truthy("OPENAI_RENAME_ALLOW_UNAUTHENTICATED"):
        return False
    if _is_prod():
        logger.warning("OPENAI_RENAME_ALLOW_UNAUTHENTICATED is ignored in prod.")
        return False
    env_name = env_value("ENV").lower()
    if env_name not in {"dev", "development", "local", "test"}:
        logger.warning(
            "OPENAI_RENAME_ALLOW_UNAUTHENTICATED is ignored for ENV=%s.",
            env_name or "unset",
        )
        return False
    return True


_ALLOW_UNAUTHENTICATED = _allow_unauthenticated()

app = FastAPI(title="DullyPDF OpenAI Rename Worker")


class RenameJobRequest(BaseModel):
    jobId: str = Field(..., min_length=1)
    requestId: Optional[str] = None
    sessionId: str = Field(..., min_length=1)
    schemaId: Optional[str] = None
    templateFields: Optional[List[Dict[str, Any]]] = None
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
    value = int_env("OPENAI_RENAME_TASKS_MAX_ATTEMPTS", int_env("OPENAI_TASKS_MAX_ATTEMPTS", 0))
    return value if value > 0 else None


def _should_finalize_failure(retry_count: int) -> bool:
    max_attempts = _max_task_attempts()
    if not max_attempts:
        return False
    # Cloud Tasks retry count is zero-based.
    return retry_count >= max_attempts - 1


def _retry_headers() -> Dict[str, str]:
    retry_after = int_env("OPENAI_RENAME_RETRY_AFTER_SECONDS", int_env("OPENAI_TASK_RETRY_AFTER_SECONDS", 5))
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


def _bind_payload_to_job(payload: RenameJobRequest, job: Dict[str, Any]) -> RenameJobRequest:
    trusted_user_id = str(job.get("user_id") or "").strip()
    if not trusted_user_id:
        raise ValueError("Rename job metadata is incomplete")
    if payload.userId != trusted_user_id:
        raise ValueError("Rename job user mismatch")

    stored_session_id = str(job.get("session_id") or "").strip()
    if stored_session_id and payload.sessionId != stored_session_id:
        raise ValueError("Rename job session mismatch")

    stored_schema_id = str(job.get("schema_id") or "").strip() or None
    if stored_schema_id and payload.schemaId and payload.schemaId != stored_schema_id:
        raise ValueError("Rename job schema mismatch")

    stored_credit_breakdown = job.get("credit_breakdown")
    if not isinstance(stored_credit_breakdown, dict):
        stored_credit_breakdown = payload.creditBreakdown

    return payload.model_copy(
        update={
            "requestId": str(job.get("request_id") or "").strip() or payload.requestId or payload.jobId,
            "sessionId": stored_session_id or payload.sessionId,
            "schemaId": stored_schema_id or payload.schemaId,
            "userId": trusted_user_id,
            "userRole": str(job.get("user_role") or "").strip() or payload.userRole,
            "credits": int(job.get("credits") or payload.credits or 0),
            "creditsCharged": bool(job.get("credits_charged")) if "credits_charged" in job else payload.creditsCharged,
            "creditBreakdown": stored_credit_breakdown,
        }
    )


def _refund_credits(payload: RenameJobRequest) -> None:
    if not payload.creditsCharged:
        return
    credits = int(payload.credits or 0)
    if credits <= 0:
        return
    attempt_credit_refund(
        user_id=payload.userId,
        role=payload.userRole,
        credits=credits,
        source="rename.worker",
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
        source="rename.worker",
        request_id=str(job.get("request_id") or "").strip() or job_id,
        job_id=job_id,
        credit_breakdown=credit_breakdown,
    )


def _finish_failure(
    payload: RenameJobRequest,
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
        raise HTTPException(status_code=401, detail="Missing rename worker auth token")
    token = raw.split(" ", 1)[1].strip()
    decoded = verify_internal_oidc_token(
        token,
        audiences=resolve_task_audiences(
            audience_envs=[
                "OPENAI_RENAME_TASKS_AUDIENCE",
                "OPENAI_RENAME_TASKS_AUDIENCE_LIGHT",
                "OPENAI_RENAME_TASKS_AUDIENCE_HEAVY",
            ],
            service_url_envs=[
                "OPENAI_RENAME_SERVICE_URL",
                "OPENAI_RENAME_SERVICE_URL_LIGHT",
                "OPENAI_RENAME_SERVICE_URL_HEAVY",
            ],
        ),
        missing_audience_detail="Rename worker audience is not configured",
        invalid_token_detail="Invalid rename worker auth token",
    )

    allowed_email = env_value("OPENAI_RENAME_CALLER_SERVICE_ACCOUNT")
    if _is_prod() and not allowed_email:
        raise HTTPException(status_code=500, detail="Rename worker caller service account is not configured")
    if allowed_email and decoded.get("email") != allowed_email:
        raise HTTPException(status_code=403, detail="Rename worker caller not allowed")
    return decoded


def _parse_template_fields(raw_fields: Optional[List[Dict[str, Any]]]) -> List[TemplateOverlayField]:
    parsed: List[TemplateOverlayField] = []
    for raw in raw_fields or []:
        try:
            parsed.append(TemplateOverlayField.model_validate(raw))
        except Exception:
            continue
    return parsed


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/internal/rename")
async def run_rename_job(
    payload: RenameJobRequest,
    authorization: Optional[str] = Header(default=None),
    x_cloud_tasks_taskretrycount: Optional[str] = Header(
        default=None,
        alias="X-CloudTasks-TaskRetryCount",
    ),
) -> Dict[str, Any]:
    try:
        _require_internal_auth(authorization)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Rename worker request rejected"
        logger.warning("Rename job %s rejected before start: %s", payload.jobId, detail)
        return _reject_job_request(payload.jobId, str(detail))

    job = get_openai_job(payload.jobId)
    if not job:
        logger.warning("Rename job %s rejected: metadata not found", payload.jobId)
        return _reject_job_request(payload.jobId, "Rename job metadata not found")

    status = str(job.get("status") or "").strip().lower()
    if status == OPENAI_JOB_STATUS_COMPLETE:
        return {"jobId": payload.jobId, "status": OPENAI_JOB_STATUS_COMPLETE}
    if status == OPENAI_JOB_STATUS_FAILED:
        return {
            "jobId": payload.jobId,
            "status": OPENAI_JOB_STATUS_FAILED,
            "error": job.get("error") or "Rename job failed",
        }

    try:
        payload = _bind_payload_to_job(payload, job)
    except ValueError as exc:
        logger.warning("Rename job %s rejected: %s", payload.jobId, exc)
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
        user = RequestUser(
            uid=payload.userId,
            app_user_id=payload.userId,
            role=payload.userRole,
        )
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

        parsed_template_fields = _parse_template_fields(payload.templateFields)
        rename_fields: List[Dict[str, Any]]
        if parsed_template_fields:
            rename_fields = template_fields_to_rename_fields(parsed_template_fields)
        else:
            rename_fields = list(entry.get("fields") or [])
        if not rename_fields:
            raise HTTPException(status_code=400, detail="No fields available for rename")

        schema_id = payload.schemaId or (job.get("schema_id") or None)
        database_fields: Optional[List[str]] = None
        if schema_id:
            schema = get_schema(schema_id, payload.userId)
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

        page_count = entry.get("page_count") or get_pdf_page_count(pdf_bytes)
        rename_report, renamed_fields = run_openai_rename_on_pdf(
            pdf_bytes=pdf_bytes,
            pdf_name=entry.get("source_pdf") or "document.pdf",
            fields=rename_fields,
            database_fields=database_fields,
            openai_max_retries=_worker_openai_max_retries(),
        )
        attempt_usage_events = coerce_usage_events(rename_report.get("usageByPage"))
        usage_events = merge_usage_events(
            usage_events,
            attempt_usage_events,
            attempt=attempt_count,
        )
        report_model = rename_report.get("model")
        usage_summary = build_openai_usage_summary(
            usage_events,
            model=report_model if isinstance(report_model, str) else None,
        )

        checkbox_rules = rename_report.get("checkboxRules") or []
        entry["fields"] = renamed_fields
        entry["renames"] = rename_report
        entry["checkboxRules"] = checkbox_rules
        entry["checkboxHints"] = []
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

        resolved_request_id = (
            payload.requestId
            or str(job.get("request_id") or "").strip()
            or payload.jobId
        )
        result = {
            "success": True,
            "requestId": resolved_request_id,
            "sessionId": payload.sessionId,
            "schemaId": schema_id,
            "renames": rename_report,
            "fields": renamed_fields,
            "checkboxRules": checkbox_rules,
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
            "fieldCount": len(renamed_fields),
            "openaiUsage": usage_summary,
        }
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Rename job rejected"
        if exc.status_code < 500 or _should_finalize_failure(retry_count):
            logger.warning("Rename job %s failed: %s", payload.jobId, detail)
            return _finish_failure(
                payload,
                str(detail),
                openai_usage_events=usage_events,
                openai_usage_summary=usage_summary,
                attempt_count=attempt_count,
            )
        raise HTTPException(
            status_code=500,
            detail="Rename worker failed; retrying",
            headers=_retry_headers(),
        ) from exc
    except Exception as exc:
        if is_insufficient_quota_error(exc):
            message = f"OpenAI insufficient_quota: {exc}"
            logger.warning("Rename job %s terminal failure: %s", payload.jobId, message)
            return _finish_failure(
                payload,
                message,
                openai_usage_events=usage_events,
                openai_usage_summary=usage_summary,
                attempt_count=attempt_count,
            )
        logger.exception("Rename job %s failed: %s", payload.jobId, exc)
        if _should_finalize_failure(retry_count):
            message = f"Rename failed after {retry_count + 1} attempts: {exc}"
            return _finish_failure(
                payload,
                message,
                openai_usage_events=usage_events,
                openai_usage_summary=usage_summary,
                attempt_count=attempt_count,
            )
        raise HTTPException(
            status_code=500,
            detail="Rename worker failed; retrying",
            headers=_retry_headers(),
        ) from exc
