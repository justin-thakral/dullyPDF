"""Signing invite email helpers.

The signing data model remains one-request-per-signer, so invite delivery is
handled one recipient at a time. The send route can call this helper in a
simple sequential loop for O(recipient_count) work, which keeps Gmail API
traffic predictable and makes it easy to record per-request delivery state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlsplit

from backend.firebaseDB.signing_database import mark_signing_request_invite_delivery
from backend.env_utils import env_value as _env_value
from backend.logging_config import get_logger
from backend.time_utils import now_iso

from .app_config import is_prod, resolve_cors_origins
from .email_service import get_gmail_access_token, send_gmail_message
from .signing_service import (
    SIGNING_EVENT_INVITE_FAILED,
    SIGNING_EVENT_INVITE_SENT,
    SIGNING_EVENT_INVITE_SKIPPED,
    SIGNING_INVITE_METHOD_EMAIL,
    SIGNING_SIGNER_CONTACT_METHOD_EMAIL,
    build_signing_public_path,
    resolve_signing_signer_contact_method,
    resolve_signing_public_link_version,
)


logger = get_logger(__name__)

_DEFAULT_PROD_SIGNING_ORIGIN = "https://dullypdf.com"

SIGNING_INVITE_DELIVERY_PENDING = "pending"
SIGNING_INVITE_DELIVERY_SENT = "sent"
SIGNING_INVITE_DELIVERY_FAILED = "failed"
SIGNING_INVITE_DELIVERY_SKIPPED = "skipped"
SIGNING_INVITE_DELIVERY_REDIRECTED = "redirected"
SIGNING_INVITE_PROVIDER_GMAIL_API = "gmail_api"


@dataclass(frozen=True)
class SigningInviteDeliveryResult:
    delivery_status: str
    attempted_at: str
    sent_at: Optional[str] = None
    provider: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    invite_message_id: Optional[str] = None


@dataclass(frozen=True)
class SigningInviteAttemptResult:
    record: object
    delivery: SigningInviteDeliveryResult


def resolve_signing_invite_event_type(delivery_status: Optional[str]) -> Optional[str]:
    normalized_status = str(delivery_status or "").strip().lower()
    if normalized_status == SIGNING_INVITE_DELIVERY_SENT:
        return SIGNING_EVENT_INVITE_SENT
    if normalized_status == SIGNING_INVITE_DELIVERY_FAILED:
        return SIGNING_EVENT_INVITE_FAILED
    if normalized_status == SIGNING_INVITE_DELIVERY_SKIPPED:
        return SIGNING_EVENT_INVITE_SKIPPED
    return None


def _resolve_normalized_request_origin(value: Optional[str]) -> Optional[str]:
    candidate = str(value or "").strip()
    if not candidate:
        return None
    parsed = urlsplit(candidate)
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname or ""
    if scheme not in {"http", "https"} or not hostname:
        return None
    port = f":{parsed.port}" if parsed.port else ""
    return f"{scheme}://{hostname.lower()}{port}"


def _request_origin_is_allowlisted(origin: Optional[str]) -> bool:
    normalized_origin = _resolve_normalized_request_origin(origin)
    if not normalized_origin:
        return False
    return normalized_origin in resolve_cors_origins()


def resolve_signing_invite_origin(*, request_origin: Optional[str] = None) -> str:
    if not is_prod():
        normalized_request_origin = _resolve_normalized_request_origin(request_origin)
        if normalized_request_origin and _request_origin_is_allowlisted(normalized_request_origin):
            return normalized_request_origin
    explicit = (_env_value("SIGNING_APP_ORIGIN") or "").strip().rstrip("/")
    if explicit:
        normalized = _normalize_signing_invite_origin(explicit, require_https=is_prod())
        if is_prod() and normalized != _DEFAULT_PROD_SIGNING_ORIGIN:
            raise RuntimeError("SIGNING_APP_ORIGIN must match the canonical production origin https://dullypdf.com")
        return normalized
    if is_prod():
        return _DEFAULT_PROD_SIGNING_ORIGIN
    return _normalize_signing_invite_origin("http://localhost:5173", require_https=False)


def _normalize_signing_invite_origin(value: str, *, require_https: bool) -> str:
    candidate = str(value or "").strip().rstrip("/")
    parsed = urlsplit(candidate)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise RuntimeError("SIGNING_APP_ORIGIN must be a valid http or https origin")
    if require_https and scheme != "https":
        raise RuntimeError("SIGNING_APP_ORIGIN must use https in production")
    if parsed.username or parsed.password:
        raise RuntimeError("SIGNING_APP_ORIGIN must not include user credentials")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise RuntimeError("SIGNING_APP_ORIGIN must be an origin only and cannot include a path, query, or fragment")
    hostname = parsed.hostname or ""
    if not hostname:
        raise RuntimeError("SIGNING_APP_ORIGIN must include a hostname")
    port = f":{parsed.port}" if parsed.port else ""
    return f"{scheme}://{hostname.lower()}{port}"


def resolve_signing_invite_sender() -> Optional[str]:
    return (
        (_env_value("SIGNING_FROM_EMAIL") or "").strip()
        or (_env_value("CONTACT_FROM_EMAIL") or "").strip()
        or (_env_value("CONTACT_TO_EMAIL") or "").strip()
        or None
    )


def build_signing_public_app_url(public_path: str, *, request_origin: Optional[str] = None) -> str:
    normalized_path = f"/{str(public_path or '').strip().lstrip('/')}"
    return f"{resolve_signing_invite_origin(request_origin=request_origin)}{normalized_path}"


def build_signing_invite_url(public_path: str, *, request_origin: Optional[str] = None) -> str:
    return build_signing_public_app_url(public_path, request_origin=request_origin)


def build_signing_invite_subject(*, document_name: str) -> str:
    title = str(document_name or "").strip() or "DullyPDF document"
    return f"Signature request: {title}"


def build_signing_invite_body(
    *,
    signer_name: str,
    document_name: str,
    signing_url: str,
    sender_email: Optional[str],
) -> str:
    greeting_name = str(signer_name or "").strip() or "there"
    source_name = str(document_name or "").strip() or "a DullyPDF document"
    sender_line = f"\nSender: {sender_email}" if str(sender_email or "").strip() else ""
    return (
        f"Hello {greeting_name},\n\n"
        f"You have been asked to review and sign {source_name} through DullyPDF.\n\n"
        f"Open the signing request:\n{signing_url}\n"
        f"{sender_line}\n\n"
        "If you prefer paper or manual handling instead of signing electronically, "
        "open the request and use the manual fallback option or contact the sender.\n\n"
        "This link opens the exact immutable PDF version that will be tied to your signature."
    ).strip()


async def send_signing_invite_email(
    *,
    signer_email: str,
    signer_name: str,
    document_name: str,
    public_path: str,
    sender_email: Optional[str] = None,
    request_origin: Optional[str] = None,
) -> SigningInviteDeliveryResult:
    attempted_at = now_iso()
    recipient = str(signer_email or "").strip()
    from_email = resolve_signing_invite_sender()
    if not recipient or not from_email:
        return SigningInviteDeliveryResult(
            delivery_status=SIGNING_INVITE_DELIVERY_SKIPPED,
            attempted_at=attempted_at,
            error_code="email_routing_unavailable",
            error_message="Signing invite email routing is not configured.",
        )

    try:
        access_token = await get_gmail_access_token()
    except Exception as exc:
        if is_prod():
            logger.exception("Signing invite email unavailable in production")
            return SigningInviteDeliveryResult(
                delivery_status=SIGNING_INVITE_DELIVERY_FAILED,
                attempted_at=attempted_at,
                provider=SIGNING_INVITE_PROVIDER_GMAIL_API,
                error_code="gmail_not_configured",
                error_message="Signing invite email is not configured.",
            )
        logger.warning("Signing invite email skipped outside production because Gmail API is not configured.")
        return SigningInviteDeliveryResult(
            delivery_status=SIGNING_INVITE_DELIVERY_SKIPPED,
            attempted_at=attempted_at,
            provider=SIGNING_INVITE_PROVIDER_GMAIL_API,
            error_code="gmail_not_configured",
            error_message="Signing invite email skipped because Gmail API is not configured in this environment.",
        )

    try:
        message_id = await send_gmail_message(
            to_email=recipient,
            from_email=from_email,
            subject=build_signing_invite_subject(document_name=document_name),
            body=build_signing_invite_body(
                signer_name=signer_name,
                document_name=document_name,
                signing_url=build_signing_invite_url(public_path, request_origin=request_origin),
                sender_email=sender_email,
            ),
            access_token=access_token,
            reply_to={"email": sender_email, "name": sender_email} if str(sender_email or "").strip() else None,
            failure_context="Gmail API signing invite send",
            failure_detail="Failed to send signing invite email",
        )
    except Exception:
        logger.exception("Signing invite delivery failed for %s", recipient)
        return SigningInviteDeliveryResult(
            delivery_status=SIGNING_INVITE_DELIVERY_FAILED,
            attempted_at=attempted_at,
            provider=SIGNING_INVITE_PROVIDER_GMAIL_API,
            error_code="gmail_send_failed",
            error_message="Failed to deliver the signing invite email.",
        )

    sent_at = now_iso()
    return SigningInviteDeliveryResult(
        delivery_status=SIGNING_INVITE_DELIVERY_SENT,
        attempted_at=attempted_at,
        sent_at=sent_at,
        provider=SIGNING_INVITE_PROVIDER_GMAIL_API,
        error_message=None,
        invite_message_id=message_id,
    )


async def deliver_signing_invite_for_request(
    *,
    record,
    user_id: str,
    sender_email: Optional[str] = None,
    request_origin: Optional[str] = None,
) -> SigningInviteAttemptResult:
    try:
        signer_contact_method = resolve_signing_signer_contact_method(record)
    except ValueError:
        signer_contact_method = None
    if signer_contact_method != SIGNING_SIGNER_CONTACT_METHOD_EMAIL:
        delivery = SigningInviteDeliveryResult(
            delivery_status=SIGNING_INVITE_DELIVERY_FAILED,
            attempted_at=now_iso(),
            error_code="unsupported_signer_contact_method",
            error_message="This signer contact method is not supported for invite delivery.",
        )
        updated_record = mark_signing_request_invite_delivery(
            record.id,
            user_id,
            delivery_status=delivery.delivery_status,
            sender_email=sender_email,
            invite_method=getattr(record, "invite_method", None),
            invite_provider=None,
            attempted_at=delivery.attempted_at,
            sent_at=delivery.sent_at,
            delivery_error=delivery.error_message,
            delivery_error_code=delivery.error_code,
            invite_message_id=delivery.invite_message_id,
        )
        return SigningInviteAttemptResult(record=updated_record or record, delivery=delivery)
    delivery = await send_signing_invite_email(
        signer_email=record.signer_email,
        signer_name=record.signer_name,
        document_name=record.source_document_name,
        public_path=build_signing_public_path(record.id, resolve_signing_public_link_version(record)),
        sender_email=sender_email,
        request_origin=request_origin,
    )
    updated_record = mark_signing_request_invite_delivery(
        record.id,
        user_id,
        delivery_status=delivery.delivery_status,
        sender_email=sender_email,
        invite_method=SIGNING_INVITE_METHOD_EMAIL,
        invite_provider=delivery.provider,
        attempted_at=delivery.attempted_at,
        sent_at=delivery.sent_at,
        delivery_error=delivery.error_message,
        delivery_error_code=delivery.error_code,
        invite_message_id=delivery.invite_message_id,
    )
    return SigningInviteAttemptResult(
        record=updated_record or record,
        delivery=delivery,
    )
