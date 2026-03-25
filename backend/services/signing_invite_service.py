"""Signing invite email helpers.

The signing data model remains one-request-per-signer, so invite delivery is
handled one recipient at a time. The send route can call this helper in a
simple sequential loop for O(recipient_count) work, which keeps Gmail API
traffic predictable and makes it easy to record per-request delivery state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from backend.env_utils import env_value as _env_value
from backend.logging_config import get_logger
from backend.time_utils import now_iso

from .app_config import is_prod
from .email_service import get_gmail_access_token, send_gmail_message


logger = get_logger(__name__)

SIGNING_INVITE_DELIVERY_PENDING = "pending"
SIGNING_INVITE_DELIVERY_SENT = "sent"
SIGNING_INVITE_DELIVERY_FAILED = "failed"
SIGNING_INVITE_DELIVERY_SKIPPED = "skipped"
SIGNING_INVITE_DELIVERY_REDIRECTED = "redirected"


@dataclass(frozen=True)
class SigningInviteDeliveryResult:
    delivery_status: str
    attempted_at: str
    sent_at: Optional[str] = None
    error_message: Optional[str] = None


def resolve_signing_invite_origin() -> str:
    explicit = (_env_value("SIGNING_APP_ORIGIN") or "").strip().rstrip("/")
    if explicit:
        return explicit
    if is_prod():
        return "https://dullypdf.com"
    return "http://localhost:5173"


def resolve_signing_invite_sender() -> Optional[str]:
    return (
        (_env_value("SIGNING_FROM_EMAIL") or "").strip()
        or (_env_value("CONTACT_FROM_EMAIL") or "").strip()
        or (_env_value("CONTACT_TO_EMAIL") or "").strip()
        or None
    )


def build_signing_invite_url(public_path: str) -> str:
    normalized_path = f"/{str(public_path or '').strip().lstrip('/')}"
    return f"{resolve_signing_invite_origin()}{normalized_path}"


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
) -> SigningInviteDeliveryResult:
    attempted_at = now_iso()
    recipient = str(signer_email or "").strip()
    from_email = resolve_signing_invite_sender()
    if not recipient or not from_email:
        return SigningInviteDeliveryResult(
            delivery_status=SIGNING_INVITE_DELIVERY_SKIPPED,
            attempted_at=attempted_at,
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
                error_message="Signing invite email is not configured.",
            )
        logger.warning("Signing invite email skipped outside production because Gmail API is not configured.")
        return SigningInviteDeliveryResult(
            delivery_status=SIGNING_INVITE_DELIVERY_SKIPPED,
            attempted_at=attempted_at,
            error_message="Signing invite email skipped because Gmail API is not configured in this environment.",
        )

    try:
        await send_gmail_message(
            to_email=recipient,
            from_email=from_email,
            subject=build_signing_invite_subject(document_name=document_name),
            body=build_signing_invite_body(
                signer_name=signer_name,
                document_name=document_name,
                signing_url=build_signing_invite_url(public_path),
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
            error_message="Failed to deliver the signing invite email.",
        )

    sent_at = now_iso()
    return SigningInviteDeliveryResult(
        delivery_status=SIGNING_INVITE_DELIVERY_SENT,
        attempted_at=attempted_at,
        sent_at=sent_at,
        error_message=None,
    )
