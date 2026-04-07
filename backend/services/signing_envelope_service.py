"""Signing envelope orchestration: turn advancement and completion cascade."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, Optional

import backend.firebaseDB.signing_database as signing_database_module
from backend.firebaseDB.signing_database import (
    get_signing_envelope,
    increment_envelope_completed_count,
    list_signing_events_for_request,
    list_signing_requests_for_envelope,
    update_signing_envelope,
    _update_public_signing_request,
    ENVELOPE_STATUS_COMPLETED,
    ENVELOPE_STATUS_PARTIAL,
    SIGNING_MODE_SEQUENTIAL,
    SIGNING_REQUESTS_COLLECTION,
)
from backend.logging_config import get_logger
from backend.services.signing_invite_service import (
    SIGNING_INVITE_METHOD_EMAIL,
    deliver_signing_invite_for_request,
    resolve_signing_invite_event_type,
)
from backend.services.signing_provenance_service import record_signing_provenance_event
from backend.services.signing_service import (
    SIGNING_STATUS_COMPLETED,
    SIGNING_STATUS_DRAFT,
    SIGNING_STATUS_SENT,
    resolve_signing_public_link_version,
    build_signing_audit_manifest_object_path,
    build_signing_audit_receipt_object_path,
    build_signing_signed_pdf_object_path,
    resolve_signing_retention_until,
    sha256_hex_for_bytes,
)
from backend.time_utils import now_iso


logger = get_logger(__name__)


def advance_envelope_after_signer_completion(completed_request) -> None:
    """Synchronous wrapper for non-async callers such as unit tests."""
    import asyncio

    asyncio.run(async_advance_envelope_after_signer_completion(completed_request))


async def async_advance_envelope_after_signer_completion(completed_request) -> None:
    """Called after a single signer's ceremony completes.

    If the request belongs to an envelope:
    - Increments the envelope's completed signer count.
    - If all signers have completed, marks the envelope completed.
    - If sequential and more signers remain, activates the next signer's turn
      and delivers their signing invite.
    """
    envelope_id = getattr(completed_request, "envelope_id", None)
    if not envelope_id:
        return

    new_count = increment_envelope_completed_count(envelope_id)
    envelope = get_signing_envelope(envelope_id)
    if envelope is None:
        logger.warning("Envelope %s not found during advancement", envelope_id)
        return

    if new_count >= envelope.signer_count:
        await _complete_envelope(envelope)
        return

    if envelope.signing_mode == SIGNING_MODE_SEQUENTIAL:
        await _activate_next_signer(envelope, completed_order=completed_request.signer_order)

    if envelope.status not in {ENVELOPE_STATUS_COMPLETED, ENVELOPE_STATUS_PARTIAL}:
        update_signing_envelope(envelope_id, {"status": ENVELOPE_STATUS_PARTIAL})


async def _complete_envelope(envelope) -> None:
    """Render the combined signed PDF with all signers' signatures, then mark completed."""
    completed_at = now_iso()
    child_requests = list_signing_requests_for_envelope(envelope.id)
    completed_requests = sorted(
        [r for r in child_requests if r.status == SIGNING_STATUS_COMPLETED],
        key=lambda r: r.signer_order,
    )

    if not completed_requests:
        logger.warning("Envelope %s has no completed requests", envelope.id)
        update_signing_envelope(envelope.id, {
            "status": ENVELOPE_STATUS_COMPLETED,
            "completed_at": completed_at,
        })
        return

    try:
        await _generate_envelope_artifacts(envelope, completed_requests, completed_at)
    except Exception as exc:
        logger.error(
            "Envelope %s artifact generation failed: %s",
            envelope.id,
            exc,
            exc_info=True,
        )
        update_signing_envelope(envelope.id, {
            "status": ENVELOPE_STATUS_PARTIAL,
            "completed_at": None,
            "signed_pdf_bucket_path": None,
            "signed_pdf_sha256": None,
            "audit_manifest_bucket_path": None,
            "audit_manifest_sha256": None,
            "audit_receipt_bucket_path": None,
            "audit_receipt_sha256": None,
        })


async def _generate_envelope_artifacts(envelope, completed_requests, completed_at: str) -> None:
    """Load source PDF, render all signers' signatures, seal, upload, and update records."""
    from backend.firebaseDB.storage_service import (
        build_signing_bucket_uri,
        download_storage_bytes,
    )
    from backend.services.signing_audit_service import build_signing_audit_bundle
    from backend.services.signing_pdf_digital_service import async_apply_digital_pdf_signature
    from backend.services.signing_storage_service import (
        promote_signing_staged_object,
        resolve_signing_storage_read_bucket_path,
        upload_signing_staging_json_for_final,
        upload_signing_staging_pdf_bytes_for_final,
    )
    from backend.services.signing_pdf_service import build_signed_pdf

    source_bucket_path = envelope.source_pdf_bucket_path
    if not source_bucket_path:
        first_with_source = next((r for r in completed_requests if r.source_pdf_bucket_path), None)
        if first_with_source:
            source_bucket_path = first_with_source.source_pdf_bucket_path
    if not source_bucket_path:
        raise ValueError("No source PDF bucket path found for envelope")

    readable_path = resolve_signing_storage_read_bucket_path(
        source_bucket_path,
        retain_until=completed_requests[0].retention_until if completed_requests else None,
    )
    pdf_bytes = download_storage_bytes(readable_path)

    # Render each signer's anchors onto the PDF in order
    total_applied = 0
    for request in completed_requests:
        render_result = build_signed_pdf(
            source_pdf_bytes=pdf_bytes,
            anchors=request.anchors or [],
            adopted_name=request.signature_adopted_name or request.signer_name,
            completed_at=request.completed_at or completed_at,
            signature_adopted_mode=getattr(request, "signature_adopted_mode", None),
            signature_image_data_url=getattr(request, "signature_adopted_image_data_url", None),
        )
        pdf_bytes = render_result.pdf_bytes
        total_applied += render_result.applied_anchor_count

    # Apply single digital seal
    first_signer = completed_requests[0]
    signer_names = ", ".join(r.signature_adopted_name or r.signer_name for r in completed_requests)

    digitally_signed = await async_apply_digital_pdf_signature(
        pdf_bytes=pdf_bytes,
        signer_name=signer_names,
        source_document_name=envelope.source_document_name,
    )

    shared_retention_until = (
        str(next((request.retention_until for request in completed_requests if request.retention_until), "") or "").strip()
        or resolve_signing_retention_until(completed_at)
    )
    signed_pdf_sha256 = sha256_hex_for_bytes(digitally_signed.pdf_bytes)

    signed_pdf_object_path = build_signing_signed_pdf_object_path(
        user_id=envelope.user_id,
        request_id=envelope.id,
        source_document_name=envelope.source_document_name,
    )
    signed_pdf_bucket_path = build_signing_bucket_uri(signed_pdf_object_path)

    upload_signing_staging_pdf_bytes_for_final(
        digitally_signed.pdf_bytes,
        signed_pdf_object_path,
    )
    promote_signing_staged_object(signed_pdf_bucket_path, retain_until=shared_retention_until)

    envelope_events = _collect_envelope_events(completed_requests)
    request_audit_artifacts: list[Dict[str, Any]] = []
    for request in completed_requests:
        audit_manifest_object_path = build_signing_audit_manifest_object_path(
            user_id=envelope.user_id,
            request_id=request.id,
            source_document_name=envelope.source_document_name,
        )
        audit_manifest_bucket_path = build_signing_bucket_uri(audit_manifest_object_path)
        audit_receipt_object_path = build_signing_audit_receipt_object_path(
            user_id=envelope.user_id,
            request_id=request.id,
            source_document_name=envelope.source_document_name,
        )
        audit_receipt_bucket_path = build_signing_bucket_uri(audit_receipt_object_path)
        completed_record = replace(
            request,
            status=SIGNING_STATUS_COMPLETED,
            completed_at=request.completed_at or completed_at,
            source_pdf_bucket_path=request.source_pdf_bucket_path or source_bucket_path,
            source_pdf_sha256=request.source_pdf_sha256 or envelope.source_pdf_sha256,
            public_app_origin=getattr(request, "public_app_origin", None) or getattr(envelope, "public_app_origin", None),
            signed_pdf_bucket_path=signed_pdf_bucket_path,
            signed_pdf_sha256=signed_pdf_sha256,
            signed_pdf_digital_signature_method=digitally_signed.signature_info.signature_method,
            signed_pdf_digital_signature_algorithm=digitally_signed.signature_info.signature_algorithm,
            signed_pdf_digital_signature_field_name=digitally_signed.signature_info.field_name,
            signed_pdf_digital_signature_subfilter=digitally_signed.signature_info.subfilter,
            signed_pdf_digital_signature_timestamped=digitally_signed.signature_info.timestamped,
            signed_pdf_digital_certificate_subject=digitally_signed.signature_info.certificate_subject,
            signed_pdf_digital_certificate_issuer=digitally_signed.signature_info.certificate_issuer,
            signed_pdf_digital_certificate_serial_number=digitally_signed.signature_info.certificate_serial_number,
            signed_pdf_digital_certificate_fingerprint_sha256=digitally_signed.signature_info.certificate_fingerprint_sha256,
            audit_manifest_bucket_path=audit_manifest_bucket_path,
            audit_receipt_bucket_path=audit_receipt_bucket_path,
            artifacts_generated_at=completed_at,
            retention_until=shared_retention_until,
        )
        audit_bundle = build_signing_audit_bundle(
            record=completed_record,
            events=envelope_events,
            signed_pdf_sha256=signed_pdf_sha256,
            signed_pdf_bucket_path=signed_pdf_bucket_path,
            source_pdf_bucket_path=completed_record.source_pdf_bucket_path or source_bucket_path,
            signed_pdf_page_count=render_result.page_count,
            applied_anchor_count=total_applied,
        )
        request_audit_artifacts.append(
            {
                "request": request,
                "audit_manifest_object_path": audit_manifest_object_path,
                "audit_manifest_bucket_path": audit_manifest_bucket_path,
                "audit_receipt_object_path": audit_receipt_object_path,
                "audit_receipt_bucket_path": audit_receipt_bucket_path,
                "audit_bundle": audit_bundle,
            }
        )

    for artifact in request_audit_artifacts:
        upload_signing_staging_json_for_final(
            artifact["audit_bundle"].envelope_payload,
            artifact["audit_manifest_object_path"],
        )
        upload_signing_staging_pdf_bytes_for_final(
            artifact["audit_bundle"].receipt_pdf_bytes,
            artifact["audit_receipt_object_path"],
        )

    for artifact in request_audit_artifacts:
        retain_until = artifact["audit_bundle"].retention_until
        promote_signing_staged_object(artifact["audit_manifest_bucket_path"], retain_until=retain_until)
        promote_signing_staged_object(artifact["audit_receipt_bucket_path"], retain_until=retain_until)

    canonical_audit = request_audit_artifacts[0] if request_audit_artifacts else None
    update_signing_envelope(envelope.id, {
        "status": ENVELOPE_STATUS_COMPLETED,
        "completed_at": completed_at,
        "signed_pdf_bucket_path": signed_pdf_bucket_path,
        "signed_pdf_sha256": signed_pdf_sha256,
        "audit_manifest_bucket_path": (
            canonical_audit["audit_manifest_bucket_path"]
            if canonical_audit is not None
            else None
        ),
        "audit_manifest_sha256": (
            canonical_audit["audit_bundle"].envelope_sha256
            if canonical_audit is not None
            else None
        ),
        "audit_receipt_bucket_path": (
            canonical_audit["audit_receipt_bucket_path"]
            if canonical_audit is not None
            else None
        ),
        "audit_receipt_sha256": (
            canonical_audit["audit_bundle"].receipt_pdf_sha256
            if canonical_audit is not None
            else None
        ),
    })

    firestore_client = signing_database_module.get_firestore_client()
    shared_request_updates = {
        "signed_pdf_bucket_path": signed_pdf_bucket_path,
        "signed_pdf_sha256": signed_pdf_sha256,
        "signed_pdf_digital_signature_method": digitally_signed.signature_info.signature_method,
        "signed_pdf_digital_signature_algorithm": digitally_signed.signature_info.signature_algorithm,
        "signed_pdf_digital_signature_field_name": digitally_signed.signature_info.field_name,
        "signed_pdf_digital_signature_subfilter": digitally_signed.signature_info.subfilter,
        "signed_pdf_digital_signature_timestamped": digitally_signed.signature_info.timestamped,
        "signed_pdf_digital_certificate_subject": digitally_signed.signature_info.certificate_subject,
        "signed_pdf_digital_certificate_issuer": digitally_signed.signature_info.certificate_issuer,
        "signed_pdf_digital_certificate_serial_number": digitally_signed.signature_info.certificate_serial_number,
        "signed_pdf_digital_certificate_fingerprint_sha256": digitally_signed.signature_info.certificate_fingerprint_sha256,
        "artifacts_generated_at": completed_at,
        "updated_at": completed_at,
    }
    for artifact in request_audit_artifacts:
        request = artifact["request"]
        audit_bundle = artifact["audit_bundle"]
        doc_ref = firestore_client.collection(SIGNING_REQUESTS_COLLECTION).document(request.id)
        doc_ref.set({
            **shared_request_updates,
            "audit_manifest_bucket_path": artifact["audit_manifest_bucket_path"],
            "audit_manifest_sha256": audit_bundle.envelope_sha256,
            "audit_receipt_bucket_path": artifact["audit_receipt_bucket_path"],
            "audit_receipt_sha256": audit_bundle.receipt_pdf_sha256,
            "audit_signature_method": audit_bundle.signature.get("method"),
            "audit_signature_algorithm": audit_bundle.signature.get("algorithm"),
            "audit_kms_key_resource_name": audit_bundle.signature.get("keyResourceName"),
            "audit_kms_key_version_name": audit_bundle.signature.get("keyVersionName"),
            "retention_until": audit_bundle.retention_until,
        }, merge=True)

    logger.info(
        "Envelope %s artifacts generated: %d signers, %d anchors applied, signed PDF %s",
        envelope.id,
        len(completed_requests),
        total_applied,
        signed_pdf_sha256[:16],
    )


def _collect_envelope_events(completed_requests) -> list[Dict[str, Any]]:
    """Aggregate child-request events into one deterministic envelope timeline."""
    normalized_events: list[Dict[str, Any]] = []
    for request in completed_requests:
        for event in list_signing_events_for_request(request.id):
            event_details = dict(getattr(event, "details", {}) or {})
            event_details.setdefault("requestId", request.id)
            event_details.setdefault("signerOrder", getattr(request, "signer_order", None))
            event_details.setdefault("signerEmail", getattr(request, "signer_email", None))
            event_details.setdefault("signerName", getattr(request, "signer_name", None))
            normalized_events.append(
                {
                    "eventType": getattr(event, "event_type", None),
                    "sessionId": getattr(event, "session_id", None),
                    "linkTokenId": getattr(event, "link_token_id", None),
                    "clientIp": getattr(event, "client_ip", None),
                    "userAgent": getattr(event, "user_agent", None),
                    "occurredAt": getattr(event, "occurred_at", None),
                    "details": event_details,
                }
            )
    return sorted(
        normalized_events,
        key=lambda entry: (
            str(entry.get("occurredAt") or ""),
            str((entry.get("details") or {}).get("requestId") or ""),
            str(entry.get("eventType") or ""),
        ),
    )


async def _activate_next_signer(envelope, *, completed_order: int) -> None:
    """Find the next unactivated signer and send them their invite."""
    child_requests = list_signing_requests_for_envelope(envelope.id)
    next_request = None
    for req in child_requests:
        if req.signer_order > completed_order and not getattr(req, "turn_activated_at", None):
            if req.status in {SIGNING_STATUS_DRAFT, SIGNING_STATUS_SENT}:
                next_request = req
                break

    if next_request is None:
        logger.info("No next signer found for envelope %s after order %d", envelope.id, completed_order)
        return

    activation_time = now_iso()
    activated_request = _update_public_signing_request(
        next_request.id,
        allowed_statuses={SIGNING_STATUS_DRAFT, SIGNING_STATUS_SENT},
        updates={"turn_activated_at": activation_time},
    )
    active_request = activated_request or next_request

    if active_request.status == SIGNING_STATUS_SENT:
        await _deliver_next_signer_invite(envelope, active_request)
    else:
        logger.info(
            "Next signer %s (order %d) in envelope %s is still in draft status; "
            "invite will be sent when their request transitions to sent.",
            active_request.signer_email,
            active_request.signer_order,
            envelope.id,
        )


async def _deliver_next_signer_invite(envelope, request_record) -> None:
    """Send the signing invite email to the next signer in a sequential envelope."""
    try:
        invite_attempt = await deliver_signing_invite_for_request(
            record=request_record,
            user_id=envelope.user_id,
            sender_email=getattr(request_record, "sender_email", None),
            request_origin=(
                getattr(request_record, "public_app_origin", None)
                or getattr(envelope, "public_app_origin", None)
            ),
        )
        _record_envelope_invite_delivery_event(
            invite_attempt.record,
            delivery=invite_attempt.delivery,
        )
        logger.info(
            "Delivered sequential invite to %s for request %s (delivery: %s)",
            request_record.signer_email,
            request_record.id,
            getattr(invite_attempt.delivery, "delivery_status", "unknown"),
        )
    except Exception as exc:
        logger.warning(
            "Failed to deliver sequential invite to %s for request %s: %s",
            request_record.signer_email,
            request_record.id,
            exc,
        )


def _record_envelope_invite_delivery_event(record, *, delivery) -> None:
    event_type = resolve_signing_invite_event_type(getattr(delivery, "delivery_status", None))
    if not event_type:
        return
    record_signing_provenance_event(
        record,
        event_type=event_type,
        sender_email=getattr(record, "sender_email", None),
        invite_method=SIGNING_INVITE_METHOD_EMAIL,
        source="envelope_turn_advance",
        include_link_token=False,
        extra={
            "provider": getattr(delivery, "provider", None),
            "providerMessageId": getattr(delivery, "invite_message_id", None),
            "deliveryStatus": getattr(delivery, "delivery_status", None),
            "deliveryErrorCode": getattr(delivery, "error_code", None),
            "deliveryErrorSummary": getattr(delivery, "error_message", None),
            "publicLinkVersion": resolve_signing_public_link_version(record),
        },
        occurred_at=getattr(delivery, "sent_at", None) or getattr(delivery, "attempted_at", None),
    )
