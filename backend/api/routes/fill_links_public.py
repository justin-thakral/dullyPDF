"""Public Fill By Link respondent endpoints."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse

from backend.api.schemas import FillLinkPublicSubmitRequest
from backend.firebaseDB.fill_link_database import (
    get_fill_link_by_public_token,
    get_fill_link_response,
    submit_fill_link_response,
)
from backend.security.rate_limit import check_rate_limit
from backend.services.contact_service import resolve_client_ip
from backend.services.app_config import resolve_stream_cors_headers
from backend.services.fill_link_download_service import (
    build_fill_link_download_payload,
    materialize_fill_link_response_download,
    respondent_pdf_download_enabled,
)
from backend.services.fill_link_scope_service import (
    close_fill_link_if_scope_invalid,
    preview_fill_link_if_scope_invalid,
)
from backend.services.fill_links_service import (
    build_fill_link_search_text,
    coerce_fill_link_answers,
    derive_fill_link_respondent_label,
    format_missing_fill_link_questions_message,
    fill_link_public_status_message,
    has_fill_link_respondent_identifier,
    is_closed_reason_blocking_download,
    list_missing_required_fill_link_questions,
    normalize_fill_link_token,
    respondent_identifier_required_message,
    resolve_fill_link_download_rate_limits,
    resolve_fill_link_submit_rate_limits,
    resolve_fill_link_view_rate_limits,
)
from backend.services.pdf_service import cleanup_paths
from backend.services.recaptcha_service import (
    recaptcha_required_for_fill_link,
    resolve_fill_link_recaptcha_action,
    verify_recaptcha_token,
)

router = APIRouter()


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


def _serialize_public_link(
    record,
    *,
    include_questions: bool | None = None,
    expose_closed_reason: bool = False,
) -> Dict[str, Any]:
    is_active = record.status == "active"
    if include_questions is None:
        include_questions = is_active
    payload: Dict[str, Any] = {
        "status": record.status,
        "statusMessage": fill_link_public_status_message(
            record.status,
            record.closed_reason if expose_closed_reason else None,
        ),
    }
    if expose_closed_reason and record.closed_reason:
        payload["closedReason"] = record.closed_reason
    if include_questions:
        payload["requireAllFields"] = record.require_all_fields
        payload["respondentPdfDownloadEnabled"] = respondent_pdf_download_enabled(record)
        payload["questions"] = record.questions
    return payload


@router.get("/api/fill-links/public/{token}")
async def get_public_fill_link(token: str, request: Request) -> Dict[str, Any]:
    public_token = normalize_fill_link_token(token)
    window_seconds, per_ip, global_limit = resolve_fill_link_view_rate_limits()
    client_ip = resolve_client_ip(request)
    allowed = _check_public_rate_limits(
        scope="fill_link_view",
        client_ip=client_ip,
        window_seconds=window_seconds,
        per_ip=per_ip,
        global_limit=global_limit,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many Fill By Link page loads. Please wait and try again.")

    record = preview_fill_link_if_scope_invalid(get_fill_link_by_public_token(public_token))
    if not record:
        raise HTTPException(status_code=404, detail="Fill By Link not found")
    return {"link": _serialize_public_link(record)}


@router.post("/api/fill-links/public/{token}/submit")
async def submit_public_fill_link(
    token: str,
    payload: FillLinkPublicSubmitRequest,
    request: Request,
) -> Dict[str, Any]:
    public_token = normalize_fill_link_token(token)
    window_seconds, per_ip, global_limit = resolve_fill_link_submit_rate_limits()
    action = resolve_fill_link_recaptcha_action()
    client_ip = resolve_client_ip(request)
    allowed = _check_public_rate_limits(
        scope="fill_link_submit",
        client_ip=client_ip,
        window_seconds=window_seconds,
        per_ip=per_ip,
        global_limit=global_limit,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many Fill By Link submissions. Please wait and try again.")

    await verify_recaptcha_token(
        payload.recaptchaToken,
        action,
        request,
        required=recaptcha_required_for_fill_link(),
    )

    record = close_fill_link_if_scope_invalid(get_fill_link_by_public_token(public_token))
    if not record:
        raise HTTPException(status_code=404, detail="Fill By Link not found")
    normalized_attempt_id = (payload.attemptId or "").strip()
    if record.status != "active" and not normalized_attempt_id:
        link_payload = _serialize_public_link(record)
        raise HTTPException(
            status_code=409,
            detail=link_payload.get("statusMessage") or "This link is no longer accepting responses.",
        )

    try:
        answers = coerce_fill_link_answers(payload.answers, record.questions)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not answers:
        raise HTTPException(status_code=400, detail="At least one response is required.")
    if not has_fill_link_respondent_identifier(answers, record.questions):
        raise HTTPException(status_code=400, detail=respondent_identifier_required_message())
    if record.require_all_fields:
        missing_labels = list_missing_required_fill_link_questions(answers, record.questions)
        if missing_labels:
            raise HTTPException(
                status_code=400,
                detail=format_missing_fill_link_questions_message(missing_labels),
            )
    respondent_label, respondent_secondary_label = derive_fill_link_respondent_label(answers)
    search_text = build_fill_link_search_text(answers, respondent_label)
    result = submit_fill_link_response(
        public_token,
        answers=answers,
        attempt_id=normalized_attempt_id or None,
        respondent_label=respondent_label,
        respondent_secondary_label=respondent_secondary_label,
        search_text=search_text,
    )
    if result.status == "not_found":
        raise HTTPException(status_code=404, detail="Fill By Link not found")
    if result.status in {"closed", "limit_reached"}:
        link_payload = _serialize_public_link(result.link or record)
        raise HTTPException(
            status_code=409,
            detail=link_payload.get("statusMessage") or "This link is no longer accepting responses.",
        )
    response_snapshot = (
        result.response.respondent_pdf_snapshot
        if result.response and isinstance(result.response.respondent_pdf_snapshot, dict)
        else None
    )
    download_payload = (
        build_fill_link_download_payload(
            result.link or record,
            token=public_token,
            response_id=result.response.id,
            snapshot=response_snapshot,
            enabled=bool(response_snapshot) or respondent_pdf_download_enabled(result.link or record),
        )
        if result.response
        else None
    )
    return {
        "success": True,
        "responseId": result.response.id if result.response else None,
        "respondentLabel": result.response.respondent_label if result.response else respondent_label,
        "link": _serialize_public_link(result.link or record),
        "responseDownloadAvailable": bool(download_payload and download_payload.get("enabled")),
        "responseDownloadPath": download_payload.get("downloadPath") if download_payload else None,
        "download": download_payload,
    }


@router.get("/api/fill-links/public/{token}/responses/{response_id}/download")
async def download_public_fill_link_response(
    token: str,
    response_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
):
    public_token = normalize_fill_link_token(token)
    window_seconds, per_ip, global_limit = resolve_fill_link_download_rate_limits()
    client_ip = resolve_client_ip(request)
    allowed = _check_public_rate_limits(
        scope="fill_link_download",
        client_ip=client_ip,
        window_seconds=window_seconds,
        per_ip=per_ip,
        global_limit=global_limit,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many Fill By Link downloads. Please wait and try again.")

    record = preview_fill_link_if_scope_invalid(get_fill_link_by_public_token(public_token))
    if not record:
        raise HTTPException(status_code=404, detail="Fill By Link not found")
    if record.scope_type != "template":
        raise HTTPException(
            status_code=409,
            detail="Respondent PDF download is only available for template Fill By Link.",
        )
    if not respondent_pdf_download_enabled(record):
        raise HTTPException(status_code=404, detail="Respondent PDF download is not available for this link.")
    if is_closed_reason_blocking_download(record.closed_reason):
        raise HTTPException(status_code=409, detail="This respondent PDF is no longer available.")

    response_record = get_fill_link_response(response_id, record.id, record.user_id)
    if not response_record:
        raise HTTPException(status_code=404, detail="Response not found")
    snapshot = (
        response_record.respondent_pdf_snapshot
        if isinstance(response_record.respondent_pdf_snapshot, dict)
        else record.respondent_pdf_snapshot if isinstance(record.respondent_pdf_snapshot, dict) else None
    )
    if not snapshot:
        raise HTTPException(status_code=404, detail="Respondent PDF download is not available for this link.")

    try:
        output_path, cleanup_targets, filename = materialize_fill_link_response_download(
            snapshot,
            answers=response_record.answers,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to generate respondent PDF.") from exc

    background_tasks.add_task(cleanup_paths, cleanup_targets)
    response = FileResponse(
        str(output_path),
        media_type="application/pdf",
        filename=filename,
        background=background_tasks,
    )
    response.headers.update(resolve_stream_cors_headers(request.headers.get("origin")))
    return response
