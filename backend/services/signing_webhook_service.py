"""Best-effort outbound webhook delivery for signing lifecycle events."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from typing import Any, Dict, Iterable, Optional
from uuid import uuid4

import httpx

from backend.env_utils import env_value as _env_value, int_env as _int_env
from backend.logging_config import get_logger
from backend.services.signing_service import (
    SIGNING_EVENT_COMPLETED,
    SIGNING_EVENT_CONSENT_ACCEPTED,
    SIGNING_EVENT_CONSENT_WITHDRAWN,
    SIGNING_EVENT_INVITE_FAILED,
    SIGNING_EVENT_INVITE_SENT,
    SIGNING_EVENT_LINK_REISSUED,
    SIGNING_EVENT_LINK_REVOKED,
    SIGNING_EVENT_MANUAL_FALLBACK_REQUESTED,
    SIGNING_EVENT_MANUAL_LINK_SHARED,
    SIGNING_EVENT_OPENED,
    SIGNING_EVENT_REQUEST_CREATED,
    SIGNING_EVENT_REQUEST_SENT,
    SIGNING_EVENT_REVIEW_CONFIRMED,
    SIGNING_EVENT_SIGNATURE_ADOPTED,
    build_signing_public_path,
    build_signing_validation_path,
    resolve_document_category_label,
    resolve_signing_public_link_version,
    resolve_signing_signer_auth_method,
    resolve_signing_signer_contact_method,
)
from backend.time_utils import now_iso


logger = get_logger(__name__)

DEFAULT_SIGNING_WEBHOOK_EVENT_TYPES = frozenset(
    {
        SIGNING_EVENT_REQUEST_CREATED,
        SIGNING_EVENT_REQUEST_SENT,
        SIGNING_EVENT_INVITE_SENT,
        SIGNING_EVENT_INVITE_FAILED,
        SIGNING_EVENT_OPENED,
        SIGNING_EVENT_REVIEW_CONFIRMED,
        SIGNING_EVENT_CONSENT_ACCEPTED,
        SIGNING_EVENT_CONSENT_WITHDRAWN,
        SIGNING_EVENT_MANUAL_FALLBACK_REQUESTED,
        SIGNING_EVENT_SIGNATURE_ADOPTED,
        SIGNING_EVENT_COMPLETED,
        SIGNING_EVENT_LINK_REVOKED,
        SIGNING_EVENT_LINK_REISSUED,
        SIGNING_EVENT_MANUAL_LINK_SHARED,
    }
)


def _resolve_signing_webhook_urls() -> list[str]:
    raw = (
        str(_env_value("SIGNING_WEBHOOK_URLS") or "").strip()
        or str(_env_value("SIGNING_WEBHOOK_URL") or "").strip()
    )
    if not raw:
        return []
    candidates = [segment.strip() for segment in raw.replace(";", ",").split(",")]
    urls = [candidate for candidate in candidates if candidate.lower().startswith(("http://", "https://"))]
    return list(dict.fromkeys(urls))


def _resolve_signing_webhook_timeout_seconds() -> float:
    return float(max(1, _int_env("SIGNING_WEBHOOK_TIMEOUT_SECONDS", 8)))


def _resolve_signing_webhook_secret() -> Optional[str]:
    secret = str(_env_value("SIGNING_WEBHOOK_SECRET") or "").strip()
    return secret or None


def _resolve_enabled_signing_webhook_event_types() -> set[str]:
    raw = str(_env_value("SIGNING_WEBHOOK_EVENT_TYPES") or "").strip()
    if not raw:
        return set(DEFAULT_SIGNING_WEBHOOK_EVENT_TYPES)
    parts = {segment.strip().lower() for segment in raw.replace(";", ",").split(",")}
    parts.discard("")
    if not parts:
        return set(DEFAULT_SIGNING_WEBHOOK_EVENT_TYPES)
    if parts & {"all", "*"}:
        return set(DEFAULT_SIGNING_WEBHOOK_EVENT_TYPES)
    return parts


def signing_webhooks_enabled_for_event(event_type: Optional[str]) -> bool:
    normalized_event_type = str(event_type or "").strip().lower()
    return bool(normalized_event_type) and bool(_resolve_signing_webhook_urls()) and (
        normalized_event_type in _resolve_enabled_signing_webhook_event_types()
    )


def build_signing_webhook_payload(
    record,
    *,
    event_type: str,
    details: Optional[Dict[str, Any]] = None,
    occurred_at: Optional[str] = None,
) -> Dict[str, Any]:
    public_link_available = getattr(record, "status", None) in {"sent", "completed"}
    public_link_version = resolve_signing_public_link_version(record)
    return {
        "id": uuid4().hex,
        "type": str(event_type or "").strip().lower(),
        "occurredAt": occurred_at or now_iso(),
        "request": {
            "id": record.id,
            "title": getattr(record, "title", None),
            "status": getattr(record, "status", None),
            "mode": getattr(record, "mode", None),
            "signatureMode": getattr(record, "signature_mode", None),
            "sourceType": getattr(record, "source_type", None),
            "sourceId": getattr(record, "source_id", None),
            "sourceLinkId": getattr(record, "source_link_id", None),
            "sourceRecordLabel": getattr(record, "source_record_label", None),
            "sourceDocumentName": getattr(record, "source_document_name", None),
            "sourceVersion": getattr(record, "source_version", None),
            "documentCategory": getattr(record, "document_category", None),
            "documentCategoryLabel": resolve_document_category_label(getattr(record, "document_category", None)),
            "ownerUserId": getattr(record, "user_id", None),
            "signerName": getattr(record, "signer_name", None),
            "signerEmail": getattr(record, "signer_email", None),
            "signerContactMethod": resolve_signing_signer_contact_method(record),
            "signerAuthMethod": resolve_signing_signer_auth_method(record),
            "verificationRequired": bool(getattr(record, "verification_required", False)),
            "verificationMethod": getattr(record, "verification_method", None),
            "inviteMethod": getattr(record, "invite_method", None),
            "inviteDeliveryStatus": getattr(record, "invite_delivery_status", None),
            "manualFallbackEnabled": bool(getattr(record, "manual_fallback_enabled", False)),
            "publicLinkVersion": public_link_version,
            "publicPath": build_signing_public_path(record.id, public_link_version) if public_link_available else None,
            "validationPath": build_signing_validation_path(record.id),
            "createdAt": getattr(record, "created_at", None),
            "sentAt": getattr(record, "sent_at", None),
            "completedAt": getattr(record, "completed_at", None),
            "invalidatedAt": getattr(record, "invalidated_at", None),
            "invalidationReason": getattr(record, "invalidation_reason", None),
        },
        "artifacts": {
            "sourcePdfAvailable": bool(getattr(record, "source_pdf_bucket_path", None)),
            "signedPdfAvailable": bool(getattr(record, "signed_pdf_bucket_path", None)),
            "auditManifestAvailable": bool(getattr(record, "audit_manifest_bucket_path", None)),
            "auditReceiptAvailable": bool(getattr(record, "audit_receipt_bucket_path", None)),
        },
        "details": dict(details or {}),
    }


def build_signing_webhook_headers(*, payload_bytes: bytes, timestamp: str) -> Dict[str, str]:
    secret = _resolve_signing_webhook_secret()
    signature = ""
    if secret:
        signature = hmac.new(
            secret.encode("utf-8"),
            f"{timestamp}.{payload_bytes.decode('utf-8')}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    return {
        "Content-Type": "application/json",
        "User-Agent": "DullyPDF-Signing-Webhooks/1.0",
        "X-Dully-Signature": f"t={timestamp},v1={signature}" if signature else f"t={timestamp}",
    }


async def emit_signing_webhook_event(
    record,
    *,
    event_type: str,
    details: Optional[Dict[str, Any]] = None,
    occurred_at: Optional[str] = None,
) -> None:
    if not signing_webhooks_enabled_for_event(event_type):
        return
    urls = _resolve_signing_webhook_urls()
    timestamp = str(occurred_at or now_iso())
    payload = build_signing_webhook_payload(
        record,
        event_type=event_type,
        details=details,
        occurred_at=occurred_at,
    )
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    headers = build_signing_webhook_headers(payload_bytes=payload_bytes, timestamp=timestamp)
    timeout = _resolve_signing_webhook_timeout_seconds()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            for url in urls:
                response = await client.post(url, content=payload_bytes, headers=headers)
                if response.status_code >= 400:
                    logger.warning(
                        "Signing webhook delivery failed.",
                        extra={
                            "signingWebhookUrl": url,
                            "signingEventType": event_type,
                            "signingRequestId": getattr(record, "id", None),
                            "statusCode": response.status_code,
                        },
                    )
    except Exception:
        logger.warning(
            "Signing webhook delivery raised an exception.",
            exc_info=True,
            extra={
                "signingEventType": event_type,
                "signingRequestId": getattr(record, "id", None),
            },
        )


def dispatch_signing_webhook_event(
    record,
    *,
    event_type: str,
    details: Optional[Dict[str, Any]] = None,
    occurred_at: Optional[str] = None,
) -> None:
    if not signing_webhooks_enabled_for_event(event_type):
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            asyncio.run(
                emit_signing_webhook_event(
                    record,
                    event_type=event_type,
                    details=details,
                    occurred_at=occurred_at,
                )
            )
        except Exception:
            logger.warning(
                "Signing webhook dispatch failed outside an active event loop.",
                exc_info=True,
                extra={"signingEventType": event_type, "signingRequestId": getattr(record, "id", None)},
            )
        return

    loop.create_task(
        emit_signing_webhook_event(
            record,
            event_type=event_type,
            details=details,
            occurred_at=occurred_at,
        )
    )
