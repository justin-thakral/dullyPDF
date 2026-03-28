"""Public Fill By Link respondent endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse

from backend.api.schemas import FillLinkPublicRetrySigningRequest, FillLinkPublicSubmitRequest
from backend.firebaseDB.fill_link_database import (
    get_fill_link_by_public_token,
    get_fill_link_response,
    submit_fill_link_response,
)
from backend.firebaseDB.user_database import get_user_profile
from backend.env_utils import int_env as _int_env
from backend.logging_config import get_logger
from backend.security.rate_limit import check_rate_limit
from backend.services.contact_service import resolve_client_ip
from backend.services.app_config import resolve_stream_cors_headers
from backend.services.fill_link_download_service import (
    build_fill_link_download_payload,
    materialize_fill_link_response_download,
    respondent_pdf_editable_enabled,
    respondent_pdf_download_enabled,
)
from backend.services.fill_link_signing_service import (
    ensure_fill_link_response_signing_request,
    resolve_fill_link_signer_identity_from_answers,
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
from backend.services.signing_consumer_consent_service import persist_consumer_disclosure_artifact
from backend.services.signing_invite_service import (
    SIGNING_INVITE_DELIVERY_FAILED,
    SIGNING_INVITE_DELIVERY_SENT,
    SIGNING_INVITE_DELIVERY_SKIPPED,
    deliver_signing_invite_for_request,
    resolve_signing_invite_event_type,
)
from backend.services.signing_provenance_service import record_signing_provenance_event
from backend.services.signing_request_limit_service import SigningRequestDocumentLimitError
from backend.services.signing_service import (
    SIGNING_EVENT_REQUEST_CREATED,
    SIGNING_EVENT_REQUEST_SENT,
    SIGNING_INVITE_METHOD_EMAIL,
    mask_signing_email,
    resolve_signing_public_link_version,
    signing_request_is_expired,
)
from backend.services.recaptcha_service import (
    recaptcha_required_for_fill_link,
    resolve_fill_link_recaptcha_action,
    verify_recaptcha_token,
)

router = APIRouter()
logger = get_logger(__name__)

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
        web_form_config = record.web_form_config if isinstance(record.web_form_config, dict) else {}
        payload["title"] = record.title
        payload["introText"] = web_form_config.get("introText")
        payload["requireAllFields"] = record.require_all_fields
        payload["respondentPdfDownloadEnabled"] = respondent_pdf_download_enabled(record)
        payload["respondentPdfEditableEnabled"] = respondent_pdf_editable_enabled(record)
        payload["postSubmitSigningEnabled"] = bool(
            isinstance(record.signing_config, dict) and record.signing_config.get("enabled")
        )
        payload["questions"] = record.questions
    return payload


def _parse_iso_datetime(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _resolve_fill_link_signing_resend_cooldown_seconds() -> int:
    return max(60, int(_int_env("FILL_LINK_SIGNING_RESEND_COOLDOWN_SECONDS", 300)))


def _resolve_resend_available_at(last_attempt_at: Any) -> str | None:
    parsed = _parse_iso_datetime(last_attempt_at)
    if parsed is None:
        return None
    return (parsed + timedelta(seconds=_resolve_fill_link_signing_resend_cooldown_seconds())).isoformat()


def _can_resend_signing_email(record) -> bool:
    if record is None or str(getattr(record, "status", "") or "").strip() != "sent":
        return False
    if signing_request_is_expired(record):
        return False
    resend_available_at = _parse_iso_datetime(_resolve_resend_available_at(getattr(record, "invite_last_attempt_at", None)))
    if resend_available_at is None:
        return True
    return resend_available_at <= datetime.now(timezone.utc)


def _resolve_fill_link_owner_email(user_id: str) -> str | None:
    profile = get_user_profile(str(user_id or "").strip())
    if profile is None:
        return None
    email = str(profile.email or "").strip()
    return email or None


def _resolve_fill_link_owner_display_name(user_id: str) -> str | None:
    profile = get_user_profile(str(user_id or "").strip())
    if profile is None:
        return None
    display_name = str(profile.display_name or "").strip()
    return display_name or None


def _serialize_post_submit_signing_payload(record, *, message: str | None = None, error_message: str | None = None) -> Dict[str, Any]:
    resend_available_at = _resolve_resend_available_at(getattr(record, "invite_last_attempt_at", None)) if record else None
    email_hint = mask_signing_email(getattr(record, "signer_email", None)) if record else None
    can_resend = bool(record) and _can_resend_signing_email(record)
    delivery_status = str(getattr(record, "invite_delivery_status", "") or "").strip() or None
    if not message and record:
        if getattr(record, "status", None) == "completed":
            message = "This response has already been signed."
        elif signing_request_is_expired(record):
            error_message = error_message or "This signing request has expired. Contact the sender for a fresh signing email."
        elif delivery_status == SIGNING_INVITE_DELIVERY_SENT and email_hint:
            message = f"We emailed the signing link to {email_hint}. Open that email to review and sign the exact PDF record."
        elif delivery_status == SIGNING_INVITE_DELIVERY_SENT:
            message = "We emailed the signing link for this response."
        elif delivery_status == SIGNING_INVITE_DELIVERY_FAILED:
            error_message = error_message or "Your response was saved, but the signing email could not be delivered. Contact the sender."
        elif delivery_status == SIGNING_INVITE_DELIVERY_SKIPPED:
            error_message = error_message or "Your response was saved, but signing email routing is unavailable right now. Contact the sender."
    return {
        "enabled": True,
        "available": bool(record),
        "requestId": getattr(record, "id", None) if record else None,
        "status": getattr(record, "status", None) if record else None,
        "deliveryStatus": delivery_status,
        "emailHint": email_hint,
        "canResend": can_resend,
        "resendAvailableAt": resend_available_at,
        "message": message,
        "errorMessage": error_message,
    }


def _serialize_retryable_post_submit_signing_failure(error_message: str) -> Dict[str, Any]:
    return {
        "enabled": True,
        "available": False,
        "requestId": None,
        "status": None,
        "deliveryStatus": None,
        "emailHint": None,
        "canResend": True,
        "resendAvailableAt": None,
        "message": None,
        "errorMessage": error_message,
    }


def _serialize_post_submit_signing_limit_failure(error_message: str) -> Dict[str, Any]:
    return {
        "enabled": True,
        "available": False,
        "requestId": None,
        "status": None,
        "deliveryStatus": None,
        "emailHint": None,
        "canResend": False,
        "resendAvailableAt": None,
        "message": None,
        "errorMessage": error_message,
    }


async def _build_post_submit_signing_payload(
    *,
    link,
    response,
    request_origin: str | None = None,
) -> Dict[str, Any]:
    snapshot = (
        response.respondent_pdf_snapshot
        if response and isinstance(response.respondent_pdf_snapshot, dict)
        else link.respondent_pdf_snapshot
        if isinstance(link.respondent_pdf_snapshot, dict)
        else None
    )
    cleanup_targets: list[Any] = []
    if snapshot is None:
        return {
            "enabled": True,
            "available": False,
            "errorMessage": "This submitted record could not be prepared for signature. Contact the sender.",
        }
    try:
        output_path, cleanup_targets, _ = materialize_fill_link_response_download(
            snapshot,
            answers=response.answers,
            export_mode="flat",
        )
        source_pdf_bytes = Path(output_path).read_bytes()
        sender_email = _resolve_fill_link_owner_email(link.user_id)
        sender_display_name = _resolve_fill_link_owner_display_name(link.user_id)
        signing_materialization = ensure_fill_link_response_signing_request(
            link=link,
            response=response,
            source_pdf_bytes=source_pdf_bytes,
            signing_config=link.signing_config,
            sender_email=sender_email,
            sender_display_name=sender_display_name,
        )
        signing_request = persist_consumer_disclosure_artifact(signing_materialization.record) or signing_materialization.record
        if signing_materialization.created_now:
            record_signing_provenance_event(
                signing_request,
                event_type=SIGNING_EVENT_REQUEST_CREATED,
                sender_email=sender_email,
                invite_method=SIGNING_INVITE_METHOD_EMAIL,
                source="fill_link_auto_send",
                response_id=response.id,
                user_agent=None,
                include_link_token=False,
                extra={
                    "statusAfter": signing_request.status if not signing_materialization.sent_now else "draft",
                    "sourceType": signing_request.source_type,
                    "sourceId": signing_request.source_id,
                },
                occurred_at=signing_request.created_at,
            )
        if signing_materialization.sent_now:
            record_signing_provenance_event(
                signing_request,
                event_type=SIGNING_EVENT_REQUEST_SENT,
                sender_email=sender_email,
                invite_method=SIGNING_INVITE_METHOD_EMAIL,
                source="fill_link_auto_send",
                response_id=response.id,
                user_agent=None,
                extra={
                    "statusBefore": "draft",
                    "statusAfter": signing_request.status,
                    "publicLinkVersion": resolve_signing_public_link_version(signing_request),
                    "expiresAt": signing_request.expires_at,
                },
                occurred_at=signing_request.sent_at,
            )
        if not _can_resend_signing_email(signing_request):
            if getattr(signing_request, "invite_delivery_status", None) != SIGNING_INVITE_DELIVERY_SENT:
                return _serialize_post_submit_signing_payload(signing_request)
            resend_available_at = _resolve_resend_available_at(getattr(signing_request, "invite_last_attempt_at", None))
            retry_message = (
                f"We already emailed the signing link to {mask_signing_email(signing_request.signer_email) or 'the signer email'}."
            )
            if resend_available_at:
                retry_message = f"{retry_message} You can resend it after {resend_available_at}."
            return _serialize_post_submit_signing_payload(signing_request, message=retry_message)
        invite_attempt = await deliver_signing_invite_for_request(
            record=signing_request,
            user_id=link.user_id,
            sender_email=sender_email,
            request_origin=request_origin,
        )
        invite_event_type = resolve_signing_invite_event_type(invite_attempt.delivery.delivery_status)
        if invite_event_type:
            record_signing_provenance_event(
                invite_attempt.record,
                event_type=invite_event_type,
                sender_email=sender_email,
                invite_method=SIGNING_INVITE_METHOD_EMAIL,
                source="fill_link_auto_send",
                response_id=response.id,
                user_agent=None,
                extra={
                    "provider": invite_attempt.delivery.provider,
                    "providerMessageId": invite_attempt.delivery.invite_message_id,
                    "deliveryStatus": invite_attempt.delivery.delivery_status,
                    "deliveryErrorCode": invite_attempt.delivery.error_code,
                    "deliveryErrorSummary": invite_attempt.delivery.error_message,
                    "publicLinkVersion": resolve_signing_public_link_version(invite_attempt.record),
                },
                occurred_at=invite_attempt.delivery.sent_at or invite_attempt.delivery.attempted_at,
            )
        if invite_attempt.delivery.delivery_status == SIGNING_INVITE_DELIVERY_SENT:
            success_message = (
                "We emailed the signing link for this response."
                if not getattr(signing_request, "invite_last_attempt_at", None)
                else "We resent the signing link for this response."
            )
            return _serialize_post_submit_signing_payload(invite_attempt.record, message=success_message)
        return _serialize_post_submit_signing_payload(invite_attempt.record)
    except SigningRequestDocumentLimitError as exc:
        return _serialize_post_submit_signing_limit_failure(exc.public_message)
    except Exception:
        logger.warning(
            "Fill By Link post-submit signing failed for link=%s response=%s",
            link.id,
            response.id,
            exc_info=True,
        )
        return _serialize_retryable_post_submit_signing_failure(
            "Your form was submitted, but the signing email is unavailable right now. Contact the sender.",
        )
    finally:
        cleanup_paths(cleanup_targets)


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
    missing_labels = list_missing_required_fill_link_questions(
        answers,
        record.questions,
        require_all_fields=record.require_all_fields,
    )
    if missing_labels:
        raise HTTPException(
            status_code=400,
            detail=format_missing_fill_link_questions_message(missing_labels),
        )
    if isinstance(record.signing_config, dict) and record.signing_config.get("enabled"):
        try:
            resolve_fill_link_signer_identity_from_answers(answers, record.signing_config)
        except ValueError as exc:
            message = str(exc)
            if "valid email address" in message or "Signer email is required" in message:
                raise HTTPException(
                    status_code=400,
                    detail="Enter a valid signer email address before continuing to the signing step.",
                ) from exc
            if "Signer name is required" in message:
                raise HTTPException(
                    status_code=400,
                    detail="Enter the signer name before continuing to the signing step.",
                ) from exc
            raise HTTPException(
                status_code=409,
                detail="This signing-enabled form is misconfigured. Contact the sender to update the signer fields.",
            ) from exc
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
    signing_payload: Dict[str, Any] | None = None
    if (
        result.response
        and isinstance((result.link or record).signing_config, dict)
        and (result.link or record).signing_config.get("enabled")
    ):
        signing_payload = await _build_post_submit_signing_payload(
            link=result.link or record,
            response=result.response,
            request_origin=request.headers.get("origin") or request.headers.get("referer"),
        )
    if signing_payload and signing_payload.get("enabled"):
        download_payload = None
    return {
        "success": True,
        "responseId": result.response.id if result.response else None,
        "respondentLabel": result.response.respondent_label if result.response else respondent_label,
        "link": _serialize_public_link(result.link or record),
        "responseDownloadAvailable": bool(download_payload and download_payload.get("enabled")),
        "responseDownloadPath": download_payload.get("downloadPath") if download_payload else None,
        "download": download_payload,
        "signing": signing_payload,
    }


@router.post("/api/fill-links/public/{token}/retry-signing")
async def retry_public_fill_link_signing(
    token: str,
    payload: FillLinkPublicRetrySigningRequest,
    request: Request,
) -> Dict[str, Any]:
    public_token = normalize_fill_link_token(token)
    window_seconds, per_ip, global_limit = resolve_fill_link_submit_rate_limits()
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

    record = close_fill_link_if_scope_invalid(get_fill_link_by_public_token(public_token))
    if not record:
        raise HTTPException(status_code=404, detail="Fill By Link not found")
    if not (isinstance(record.signing_config, dict) and record.signing_config.get("enabled")):
        raise HTTPException(status_code=409, detail="This Fill By Link does not require signature after submit.")

    response_record = get_fill_link_response(payload.responseId, record.id, record.user_id)
    if not response_record:
        raise HTTPException(status_code=404, detail="Submitted response not found.")

    signing_payload = await _build_post_submit_signing_payload(
        link=record,
        response=response_record,
        request_origin=request.headers.get("origin") or request.headers.get("referer"),
    )
    return {
        "success": bool(signing_payload.get("available")),
        "responseId": response_record.id,
        "link": _serialize_public_link(record),
        "signing": signing_payload,
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
    response.headers["Cache-Control"] = "private, no-store"
    return response
