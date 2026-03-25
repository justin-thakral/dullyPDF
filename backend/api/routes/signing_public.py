"""Public signer ceremony endpoints."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from backend.api.schemas import (
    PublicSigningAdoptSignatureRequest,
    PublicSigningCompleteRequest,
    PublicSigningConsentRequest,
    PublicSigningManualFallbackRequest,
    PublicSigningReviewRequest,
)
from backend.firebaseDB.signing_database import (
    complete_signing_request,
    create_signing_session,
    get_signing_request_by_public_token,
    get_signing_session_for_request,
    list_signing_events_for_request,
    mark_signing_request_consented,
    mark_signing_request_manual_fallback_requested,
    mark_signing_request_opened,
    mark_signing_request_reviewed,
    mark_signing_request_signature_adopted,
    record_signing_event,
    touch_signing_session,
)
from backend.firebaseDB.storage_service import (
    build_signing_bucket_uri,
    delete_storage_object,
    download_storage_bytes,
    is_gcs_path,
    stream_pdf,
    upload_signing_json,
    upload_signing_pdf_bytes,
)
from backend.security.rate_limit import check_rate_limit
from backend.services.app_config import resolve_stream_cors_headers
from backend.services.contact_service import resolve_client_ip
from backend.services.pdf_service import safe_pdf_download_filename
from backend.services.signing_audit_service import build_signing_audit_bundle
from backend.services.signing_pdf_service import build_signed_pdf
from backend.services.signing_service import (
    SIGNING_ARTIFACT_AUDIT_RECEIPT,
    SIGNING_ARTIFACT_SIGNED_PDF,
    SIGNATURE_MODE_CONSUMER,
    SIGNING_EVENT_COMPLETED,
    SIGNING_EVENT_CONSENT_ACCEPTED,
    SIGNING_EVENT_MANUAL_FALLBACK_REQUESTED,
    SIGNING_EVENT_OPENED,
    SIGNING_EVENT_REVIEW_CONFIRMED,
    SIGNING_EVENT_SESSION_STARTED,
    SIGNING_EVENT_SIGNATURE_ADOPTED,
    SIGNING_STATUS_COMPLETED,
    SIGNING_STATUS_SENT,
    build_signing_audit_manifest_object_path,
    build_signing_audit_receipt_object_path,
    build_signing_link_token_id,
    build_signing_public_session_token,
    build_signing_signed_pdf_object_path,
    normalize_signing_user_agent,
    parse_signing_public_session_token,
    resolve_document_category_label,
    resolve_signing_action_rate_limits,
    resolve_signing_document_rate_limits,
    resolve_signing_public_status_message,
    resolve_signing_session_ttl_seconds,
    resolve_signing_view_rate_limits,
    serialize_signing_ceremony_state,
    sha256_hex_for_bytes,
    validate_adopted_signature_name,
    validate_public_signing_actionable_record,
    validate_public_signing_adoptable_record,
    validate_public_signing_completable_record,
    validate_public_signing_reviewable_record,
)
from backend.time_utils import now_iso


router = APIRouter()


def _cleanup_completion_uploads(bucket_paths: list[str]) -> None:
    """Best-effort cleanup for artifacts uploaded before a completion race/failure.

    Completion generates multiple artifacts. If the final Firestore completion transition loses a race after some
    uploads already succeeded, remove those orphaned objects so later audit/export flows do not accumulate dead
    artifacts. Cleanup remains O(k) in the number of uploaded artifacts, where k is bounded to three.
    """

    for bucket_path in bucket_paths:
        try:
            delete_storage_object(bucket_path)
        except Exception:
            # Cleanup is best-effort because the original completion error is the primary signal to the caller.
            pass


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


def _serialize_public_request(record, *, token: str) -> Dict[str, Any]:
    return {
        "id": record.id,
        "title": record.title,
        "mode": record.mode,
        "signatureMode": record.signature_mode,
        "status": record.status,
        "statusMessage": resolve_signing_public_status_message(record.status, record.invalidation_reason),
        "sourceDocumentName": record.source_document_name,
        "sourcePdfSha256": record.source_pdf_sha256,
        "sourceVersion": record.source_version,
        "documentCategory": record.document_category,
        "documentCategoryLabel": resolve_document_category_label(record.document_category),
        "manualFallbackEnabled": record.manual_fallback_enabled,
        "signerName": record.signer_name,
        "anchors": record.anchors,
        "disclosureVersion": record.disclosure_version,
        "documentPath": f"/api/signing/public/{token}/document",
        "artifacts": {
            "signedPdf": {
                "available": bool(record.signed_pdf_bucket_path),
                "sha256": record.signed_pdf_sha256,
                "downloadPath": (
                    f"/api/signing/public/{token}/artifacts/{SIGNING_ARTIFACT_SIGNED_PDF}"
                    if record.signed_pdf_bucket_path
                    else None
                ),
                "generatedAt": record.artifacts_generated_at,
            },
            "auditReceipt": {
                "available": bool(record.audit_receipt_bucket_path),
                "sha256": record.audit_receipt_sha256,
                "downloadPath": (
                    f"/api/signing/public/{token}/artifacts/{SIGNING_ARTIFACT_AUDIT_RECEIPT}"
                    if record.audit_receipt_bucket_path
                    else None
                ),
                "generatedAt": record.artifacts_generated_at,
            },
        },
        "createdAt": record.created_at,
        "sentAt": record.sent_at,
        "completedAt": record.completed_at,
        "invalidatedAt": record.invalidated_at,
        "invalidationReason": record.invalidation_reason,
        **serialize_signing_ceremony_state(record),
    }


def _serialize_public_session(session, *, session_token: str) -> Dict[str, Any]:
    return {
        "id": session.id,
        "token": session_token,
        "expiresAt": session.expires_at,
    }


def _resolve_public_artifact(record, *, token: str, artifact_key: str) -> tuple[str, str, str]:
    if record.status != SIGNING_STATUS_COMPLETED:
        raise HTTPException(status_code=409, detail="Signed artifacts are available only after the request is completed.")
    if artifact_key == SIGNING_ARTIFACT_SIGNED_PDF and record.signed_pdf_bucket_path:
        filename = safe_pdf_download_filename(f"{record.source_document_name or 'document'}-signed", "signed-document")
        return record.signed_pdf_bucket_path, "application/pdf", filename
    if artifact_key == SIGNING_ARTIFACT_AUDIT_RECEIPT and record.audit_receipt_bucket_path:
        filename = safe_pdf_download_filename(f"{record.source_document_name or 'document'}-audit-receipt", "audit-receipt")
        return record.audit_receipt_bucket_path, "application/pdf", filename
    raise HTTPException(status_code=404, detail="Signing artifact is not available.")


def _get_public_record_or_404(token: str):
    record = get_signing_request_by_public_token(token)
    if record is None:
        raise HTTPException(status_code=404, detail="Signing request not found")
    return record


def _require_public_transition_applied(
    updated_record,
    *,
    expected_status: str,
    required_fields: tuple[str, ...] = (),
):
    """Reject stale action responses when the Firestore state no longer matches the attempted transition.

    Public signer actions are multi-step and can be retried or race with a second tab. The database helper
    returns the current record snapshot even when the status precondition no longer matches, so callers need
    to verify that the expected status/fields actually exist before recording success events. This keeps the
    audit trail O(1) per accepted action instead of appending misleading duplicate events from stale retries.
    """

    if updated_record is None:
        raise HTTPException(status_code=409, detail="This signing request changed before the action could be saved. Reload and try again.")
    if str(updated_record.status or "").strip().lower() != expected_status:
        raise HTTPException(
            status_code=409,
            detail=resolve_signing_public_status_message(updated_record.status, updated_record.invalidation_reason),
        )
    for field_name in required_fields:
        if not getattr(updated_record, field_name, None):
            raise HTTPException(
                status_code=409,
                detail="This signing request changed before the action could be saved. Reload and try again.",
            )
    return updated_record


def _session_header_value(value: Optional[str]) -> str:
    return str(value or "").strip()


def _require_public_signing_session(
    *,
    token: str,
    x_signing_session: Optional[str],
    request: Request,
):
    record = _get_public_record_or_404(token)
    try:
        validate_public_signing_actionable_record(record)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    session_header = _session_header_value(x_signing_session)
    if not session_header:
        raise HTTPException(status_code=401, detail="Signing session is required. Reload the page and try again.")
    parsed = parse_signing_public_session_token(session_header)
    if parsed is None:
        raise HTTPException(status_code=401, detail="Signing session expired. Reload the page and try again.")
    request_id, session_id, _expires_at_epoch = parsed
    if request_id != record.id:
        raise HTTPException(status_code=401, detail="Signing session does not match this request.")
    session = get_signing_session_for_request(session_id, record.id)
    if session is None:
        raise HTTPException(status_code=401, detail="Signing session was not found. Reload the page and try again.")
    client_ip = resolve_client_ip(request)
    user_agent = normalize_signing_user_agent(request.headers.get("user-agent"))
    touch_signing_session(session.id, client_ip=client_ip, user_agent=user_agent)
    return record, session, client_ip, user_agent


@router.get("/api/signing/public/{token}")
async def get_public_signing_request(token: str, request: Request) -> Dict[str, Any]:
    client_ip = resolve_client_ip(request)
    window_seconds, per_ip, global_limit = resolve_signing_view_rate_limits()
    allowed = _check_public_rate_limits(
        scope="signing_view",
        client_ip=client_ip,
        window_seconds=window_seconds,
        per_ip=per_ip,
        global_limit=global_limit,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many signing page loads. Please wait and try again.")
    record = _get_public_record_or_404(token)
    return {"request": _serialize_public_request(record, token=token)}


@router.post("/api/signing/public/{token}/bootstrap")
async def start_public_signing_session(token: str, request: Request) -> Dict[str, Any]:
    client_ip = resolve_client_ip(request)
    window_seconds, per_ip, global_limit = resolve_signing_action_rate_limits()
    allowed = _check_public_rate_limits(
        scope="signing_bootstrap",
        client_ip=client_ip,
        window_seconds=window_seconds,
        per_ip=per_ip,
        global_limit=global_limit,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many signing session starts. Please wait and try again.")

    record = _get_public_record_or_404(token)
    if record.status != SIGNING_STATUS_SENT:
        raise HTTPException(
            status_code=409,
            detail=resolve_signing_public_status_message(record.status, record.invalidation_reason),
        )
    try:
        validate_public_signing_actionable_record(record)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    ttl_seconds = resolve_signing_session_ttl_seconds()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    token_id = build_signing_link_token_id(token)
    user_agent = normalize_signing_user_agent(request.headers.get("user-agent"))
    session = create_signing_session(
        record.id,
        link_token_id=token_id,
        client_ip=client_ip,
        user_agent=user_agent,
        expires_at=expires_at.isoformat(),
    )
    updated_record = mark_signing_request_opened(
        record.id,
        session_id=session.id,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    updated_record = _require_public_transition_applied(
        updated_record,
        expected_status=SIGNING_STATUS_SENT,
        required_fields=("opened_at",),
    )
    record_signing_event(
        updated_record.id,
        event_type=SIGNING_EVENT_SESSION_STARTED,
        session_id=session.id,
        link_token_id=token_id,
        client_ip=client_ip,
        user_agent=user_agent,
        details={"status": updated_record.status},
    )
    record_signing_event(
        updated_record.id,
        event_type=SIGNING_EVENT_OPENED,
        session_id=session.id,
        link_token_id=token_id,
        client_ip=client_ip,
        user_agent=user_agent,
        details={
            "documentCategory": updated_record.document_category,
            "sourceVersion": updated_record.source_version,
        },
    )
    session_token = build_signing_public_session_token(
        updated_record.id,
        session.id,
        int(expires_at.timestamp()),
    )
    return {
        "request": _serialize_public_request(updated_record, token=token),
        "session": _serialize_public_session(session, session_token=session_token),
    }


@router.get("/api/signing/public/{token}/document")
async def get_public_signing_document(token: str, request: Request):
    client_ip = resolve_client_ip(request)
    window_seconds, per_ip, global_limit = resolve_signing_document_rate_limits()
    allowed = _check_public_rate_limits(
        scope="signing_document",
        client_ip=client_ip,
        window_seconds=window_seconds,
        per_ip=per_ip,
        global_limit=global_limit,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many document loads. Please wait and try again.")

    record = _get_public_record_or_404(token)
    if record.status not in {SIGNING_STATUS_SENT, SIGNING_STATUS_COMPLETED}:
        raise HTTPException(
            status_code=409,
            detail=resolve_signing_public_status_message(record.status, record.invalidation_reason),
        )
    if not record.source_pdf_bucket_path or not is_gcs_path(record.source_pdf_bucket_path):
        raise HTTPException(status_code=404, detail="Signing document is not available.")
    try:
        stream = stream_pdf(record.source_pdf_bucket_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to load signing document.") from exc

    filename = safe_pdf_download_filename(record.source_document_name or "signing-document", "signing-document")
    headers = {"Content-Disposition": f'inline; filename="{filename}"'}
    headers.update(resolve_stream_cors_headers(request.headers.get("origin")))
    return StreamingResponse(stream, media_type="application/pdf", headers=headers)


@router.get("/api/signing/public/{token}/artifacts/{artifact_key}")
async def get_public_signing_artifact(token: str, artifact_key: str, request: Request):
    client_ip = resolve_client_ip(request)
    window_seconds, per_ip, global_limit = resolve_signing_document_rate_limits()
    allowed = _check_public_rate_limits(
        scope="signing_artifact",
        client_ip=client_ip,
        window_seconds=window_seconds,
        per_ip=per_ip,
        global_limit=global_limit,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many artifact downloads. Please wait and try again.")
    record = _get_public_record_or_404(token)
    bucket_path, media_type, filename = _resolve_public_artifact(record, token=token, artifact_key=artifact_key)
    try:
        body = download_storage_bytes(bucket_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to load signing artifact.") from exc
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    headers.update(resolve_stream_cors_headers(request.headers.get("origin")))
    if media_type == "application/json":
        return Response(content=body, media_type=media_type, headers=headers)
    return StreamingResponse(iter([body]), media_type=media_type, headers=headers)


@router.post("/api/signing/public/{token}/review")
async def review_public_signing_request(
    token: str,
    payload: PublicSigningReviewRequest,
    request: Request,
    x_signing_session: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    if not payload.reviewConfirmed:
        raise HTTPException(status_code=400, detail="Review acknowledgment is required.")
    record, session, client_ip, user_agent = _require_public_signing_session(
        token=token,
        x_signing_session=x_signing_session,
        request=request,
    )
    try:
        validate_public_signing_reviewable_record(record)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    updated_record = mark_signing_request_reviewed(
        record.id,
        session_id=session.id,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    updated_record = _require_public_transition_applied(
        updated_record,
        expected_status=SIGNING_STATUS_SENT,
        required_fields=("reviewed_at",),
    )
    record_signing_event(
        updated_record.id,
        event_type=SIGNING_EVENT_REVIEW_CONFIRMED,
        session_id=session.id,
        link_token_id=session.link_token_id,
        client_ip=client_ip,
        user_agent=user_agent,
        details={
            "sourcePdfSha256": updated_record.source_pdf_sha256,
            "sourceVersion": updated_record.source_version,
        },
    )
    return {"request": _serialize_public_request(updated_record, token=token)}


@router.post("/api/signing/public/{token}/consent")
async def consent_public_signing_request(
    token: str,
    payload: PublicSigningConsentRequest,
    request: Request,
    x_signing_session: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    if not payload.accepted:
        raise HTTPException(status_code=400, detail="Electronic records consent is required to continue.")
    record, session, client_ip, user_agent = _require_public_signing_session(
        token=token,
        x_signing_session=x_signing_session,
        request=request,
    )
    if record.signature_mode != SIGNATURE_MODE_CONSUMER:
        raise HTTPException(status_code=400, detail="Consumer e-consent is only required for consumer signing requests.")
    updated_record = mark_signing_request_consented(
        record.id,
        session_id=session.id,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    updated_record = _require_public_transition_applied(
        updated_record,
        expected_status=SIGNING_STATUS_SENT,
        required_fields=("consented_at",),
    )
    record_signing_event(
        updated_record.id,
        event_type=SIGNING_EVENT_CONSENT_ACCEPTED,
        session_id=session.id,
        link_token_id=session.link_token_id,
        client_ip=client_ip,
        user_agent=user_agent,
        details={
            "disclosureVersion": updated_record.disclosure_version,
            "documentCategory": updated_record.document_category,
        },
    )
    return {"request": _serialize_public_request(updated_record, token=token)}


@router.post("/api/signing/public/{token}/manual-fallback")
async def request_public_signing_manual_fallback(
    token: str,
    payload: PublicSigningManualFallbackRequest,
    request: Request,
    x_signing_session: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    record, session, client_ip, user_agent = _require_public_signing_session(
        token=token,
        x_signing_session=x_signing_session,
        request=request,
    )
    if not record.manual_fallback_enabled:
        raise HTTPException(status_code=409, detail="Manual fallback is not enabled for this signing request.")
    updated_record = mark_signing_request_manual_fallback_requested(
        record.id,
        session_id=session.id,
        note=payload.note,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    updated_record = _require_public_transition_applied(
        updated_record,
        expected_status=SIGNING_STATUS_SENT,
        required_fields=("manual_fallback_requested_at",),
    )
    record_signing_event(
        updated_record.id,
        event_type=SIGNING_EVENT_MANUAL_FALLBACK_REQUESTED,
        session_id=session.id,
        link_token_id=session.link_token_id,
        client_ip=client_ip,
        user_agent=user_agent,
        details={"note": payload.note},
    )
    return {"request": _serialize_public_request(updated_record, token=token)}


@router.post("/api/signing/public/{token}/adopt-signature")
async def adopt_public_signing_signature(
    token: str,
    payload: PublicSigningAdoptSignatureRequest,
    request: Request,
    x_signing_session: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    record, session, client_ip, user_agent = _require_public_signing_session(
        token=token,
        x_signing_session=x_signing_session,
        request=request,
    )
    try:
        validate_public_signing_adoptable_record(record)
        adopted_name = validate_adopted_signature_name(payload.adoptedName)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    updated_record = mark_signing_request_signature_adopted(
        record.id,
        session_id=session.id,
        adopted_name=adopted_name,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    updated_record = _require_public_transition_applied(
        updated_record,
        expected_status=SIGNING_STATUS_SENT,
        required_fields=("signature_adopted_at", "signature_adopted_name"),
    )
    record_signing_event(
        updated_record.id,
        event_type=SIGNING_EVENT_SIGNATURE_ADOPTED,
        session_id=session.id,
        link_token_id=session.link_token_id,
        client_ip=client_ip,
        user_agent=user_agent,
        details={
            "adoptedName": adopted_name,
            "anchorCount": len(updated_record.anchors or []),
        },
    )
    return {"request": _serialize_public_request(updated_record, token=token)}


@router.post("/api/signing/public/{token}/complete")
async def complete_public_signing_request(
    token: str,
    payload: PublicSigningCompleteRequest,
    request: Request,
    x_signing_session: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    if not payload.intentConfirmed:
        raise HTTPException(status_code=400, detail="Confirm the final sign action to complete this request.")
    record, session, client_ip, user_agent = _require_public_signing_session(
        token=token,
        x_signing_session=x_signing_session,
        request=request,
    )
    try:
        validate_public_signing_completable_record(record)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not record.source_pdf_bucket_path or not is_gcs_path(record.source_pdf_bucket_path):
        raise HTTPException(status_code=409, detail="The immutable source PDF is missing for this signing request.")
    try:
        source_pdf_bytes = download_storage_bytes(record.source_pdf_bucket_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to load the immutable source PDF.") from exc

    completed_at = now_iso()
    signed_pdf_render = build_signed_pdf(
        source_pdf_bytes=source_pdf_bytes,
        anchors=record.anchors or [],
        adopted_name=record.signature_adopted_name or record.signer_name,
        completed_at=completed_at,
    )
    signed_pdf_object_path = build_signing_signed_pdf_object_path(
        user_id=record.user_id,
        request_id=record.id,
        source_document_name=record.source_document_name,
    )
    signed_pdf_bucket_path = build_signing_bucket_uri(signed_pdf_object_path)
    audit_manifest_object_path = build_signing_audit_manifest_object_path(
        user_id=record.user_id,
        request_id=record.id,
        source_document_name=record.source_document_name,
    )
    audit_manifest_bucket_path = build_signing_bucket_uri(audit_manifest_object_path)
    audit_receipt_object_path = build_signing_audit_receipt_object_path(
        user_id=record.user_id,
        request_id=record.id,
        source_document_name=record.source_document_name,
    )
    audit_receipt_bucket_path = build_signing_bucket_uri(audit_receipt_object_path)
    signed_pdf_sha256 = sha256_hex_for_bytes(signed_pdf_render.pdf_bytes)

    completed_record = replace(
        record,
        status=SIGNING_STATUS_COMPLETED,
        completed_at=completed_at,
        completed_session_id=session.id,
        completed_ip_address=client_ip,
        completed_user_agent=user_agent,
        signed_pdf_bucket_path=signed_pdf_bucket_path,
        signed_pdf_sha256=signed_pdf_sha256,
        audit_manifest_bucket_path=audit_manifest_bucket_path,
        audit_receipt_bucket_path=audit_receipt_bucket_path,
        artifacts_generated_at=completed_at,
    )
    synthetic_completed_event = {
        "eventType": SIGNING_EVENT_COMPLETED,
        "sessionId": session.id,
        "linkTokenId": session.link_token_id,
        "clientIp": client_ip,
        "userAgent": user_agent,
        "occurredAt": completed_at,
        "details": {
            "sourcePdfSha256": record.source_pdf_sha256,
            "sourceVersion": record.source_version,
            "adoptedName": record.signature_adopted_name,
            "signedPdfSha256": signed_pdf_sha256,
        },
    }
    existing_events = list_signing_events_for_request(record.id)
    audit_bundle = build_signing_audit_bundle(
        record=completed_record,
        events=[*existing_events, synthetic_completed_event],
        signed_pdf_sha256=signed_pdf_sha256,
        signed_pdf_bucket_path=signed_pdf_bucket_path,
        source_pdf_bucket_path=record.source_pdf_bucket_path,
        signed_pdf_page_count=signed_pdf_render.page_count,
        applied_anchor_count=signed_pdf_render.applied_anchor_count,
    )

    uploaded_bucket_paths: list[str] = []
    try:
        upload_signing_pdf_bytes(signed_pdf_render.pdf_bytes, signed_pdf_object_path)
        uploaded_bucket_paths.append(signed_pdf_bucket_path)
        upload_signing_json(audit_bundle.envelope_payload, audit_manifest_object_path)
        uploaded_bucket_paths.append(audit_manifest_bucket_path)
        upload_signing_pdf_bytes(audit_bundle.receipt_pdf_bytes, audit_receipt_object_path)
        uploaded_bucket_paths.append(audit_receipt_bucket_path)

        updated_record = complete_signing_request(
            record.id,
            session_id=session.id,
            client_ip=client_ip,
            user_agent=user_agent,
            completed_at=completed_at,
            artifact_updates={
                "signed_pdf_bucket_path": signed_pdf_bucket_path,
                "signed_pdf_sha256": signed_pdf_sha256,
                "audit_manifest_bucket_path": audit_manifest_bucket_path,
                "audit_manifest_sha256": audit_bundle.envelope_sha256,
                "audit_receipt_bucket_path": audit_receipt_bucket_path,
                "audit_receipt_sha256": audit_bundle.receipt_pdf_sha256,
                "audit_signature_method": audit_bundle.signature.get("method"),
                "audit_signature_algorithm": audit_bundle.signature.get("algorithm"),
                "audit_kms_key_resource_name": audit_bundle.signature.get("keyResourceName"),
                "audit_kms_key_version_name": audit_bundle.signature.get("keyVersionName"),
                "artifacts_generated_at": completed_at,
                "retention_until": audit_bundle.retention_until,
            },
        )
        updated_record = _require_public_transition_applied(
            updated_record,
            expected_status=SIGNING_STATUS_COMPLETED,
            required_fields=(
                "completed_at",
                "signed_pdf_bucket_path",
                "audit_manifest_bucket_path",
                "audit_receipt_bucket_path",
            ),
        )
    except Exception:
        _cleanup_completion_uploads(uploaded_bucket_paths)
        raise
    touch_signing_session(session.id, client_ip=client_ip, user_agent=user_agent, completed=True)
    record_signing_event(
        updated_record.id,
        event_type=SIGNING_EVENT_COMPLETED,
        session_id=session.id,
        link_token_id=session.link_token_id,
        client_ip=client_ip,
        user_agent=user_agent,
        occurred_at=completed_at,
        details={
            "sourcePdfSha256": updated_record.source_pdf_sha256,
            "sourceVersion": updated_record.source_version,
            "adoptedName": updated_record.signature_adopted_name,
            "signedPdfSha256": updated_record.signed_pdf_sha256,
            "auditManifestSha256": updated_record.audit_manifest_sha256,
            "auditReceiptSha256": updated_record.audit_receipt_sha256,
            "retentionUntil": updated_record.retention_until,
        },
    )
    return {"request": _serialize_public_request(updated_record, token=token)}
