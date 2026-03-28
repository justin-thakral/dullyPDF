"""Email OTP helpers for public signing session verification.

The verification channel is intentionally scoped to an existing signing
request/session pair instead of creating user accounts for anonymous signers.
Each send operation is O(1): generate a short-lived code, send one Gmail
message, and record the provider message id for later audit correlation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from backend.logging_config import get_logger
from backend.time_utils import now_iso

from .app_config import is_prod
from .email_service import get_gmail_access_token, send_gmail_message
from .signing_invite_service import (
    build_signing_invite_url,
    resolve_signing_invite_sender,
)


logger = get_logger(__name__)


SIGNING_VERIFICATION_DELIVERY_SENT = "sent"
SIGNING_VERIFICATION_DELIVERY_FAILED = "failed"
SIGNING_VERIFICATION_DELIVERY_SKIPPED = "skipped"


@dataclass(frozen=True)
class SigningVerificationDeliveryResult:
    delivery_status: str
    attempted_at: str
    sent_at: Optional[str] = None
    error_message: Optional[str] = None
    message_id: Optional[str] = None


def build_signing_verification_subject(*, document_name: str) -> str:
    title = str(document_name or "").strip() or "DullyPDF document"
    return f"Your DullyPDF signing code for {title}"


def build_signing_verification_body(
    *,
    signer_name: str,
    document_name: str,
    verification_code: str,
    expires_in_minutes: int,
    signing_path: str,
    sender_email: Optional[str],
    request_origin: Optional[str],
) -> str:
    greeting_name = str(signer_name or "").strip() or "there"
    source_name = str(document_name or "").strip() or "your DullyPDF document"
    sender_line = f"\nSender: {sender_email}" if str(sender_email or "").strip() else ""
    signing_url = build_signing_invite_url(signing_path, request_origin=request_origin)
    return (
        f"Hello {greeting_name},\n\n"
        f"Use this one-time code to continue signing {source_name} through DullyPDF:\n\n"
        f"{verification_code}\n\n"
        f"This code expires in {expires_in_minutes} minutes and can only be used once."
        f"{sender_line}\n\n"
        f"Continue signing:\n{signing_url}\n\n"
        "If you did not request this code, do not share it and ignore this email."
    ).strip()


async def send_signing_verification_email(
    *,
    signer_email: str,
    signer_name: str,
    document_name: str,
    verification_code: str,
    expires_in_minutes: int,
    signing_path: str,
    sender_email: Optional[str] = None,
    request_origin: Optional[str] = None,
) -> SigningVerificationDeliveryResult:
    attempted_at = now_iso()
    recipient = str(signer_email or "").strip()
    from_email = resolve_signing_invite_sender()
    if not recipient or not from_email:
        return SigningVerificationDeliveryResult(
            delivery_status=SIGNING_VERIFICATION_DELIVERY_SKIPPED,
            attempted_at=attempted_at,
            error_message="Signing verification email routing is not configured.",
        )

    try:
        access_token = await get_gmail_access_token()
    except Exception:
        if is_prod():
            logger.exception("Signing verification email unavailable in production")
            return SigningVerificationDeliveryResult(
                delivery_status=SIGNING_VERIFICATION_DELIVERY_FAILED,
                attempted_at=attempted_at,
                error_message="Signing verification email is not configured.",
            )
        logger.warning("Signing verification email skipped outside production because Gmail API is not configured.")
        return SigningVerificationDeliveryResult(
            delivery_status=SIGNING_VERIFICATION_DELIVERY_SKIPPED,
            attempted_at=attempted_at,
            error_message="Signing verification email skipped because Gmail API is not configured in this environment.",
        )

    try:
        message_id = await send_gmail_message(
            to_email=recipient,
            from_email=from_email,
            subject=build_signing_verification_subject(document_name=document_name),
            body=build_signing_verification_body(
                signer_name=signer_name,
                document_name=document_name,
                verification_code=verification_code,
                expires_in_minutes=expires_in_minutes,
                signing_path=signing_path,
                sender_email=sender_email,
                request_origin=request_origin,
            ),
            access_token=access_token,
            reply_to={"email": sender_email, "name": sender_email} if str(sender_email or "").strip() else None,
            failure_context="Gmail API signing verification send",
            failure_detail="Failed to send signing verification email",
        )
    except Exception:
        logger.exception("Signing verification delivery failed for %s", recipient)
        return SigningVerificationDeliveryResult(
            delivery_status=SIGNING_VERIFICATION_DELIVERY_FAILED,
            attempted_at=attempted_at,
            error_message="Failed to deliver the signing verification email.",
        )

    sent_at = now_iso()
    return SigningVerificationDeliveryResult(
        delivery_status=SIGNING_VERIFICATION_DELIVERY_SENT,
        attempted_at=attempted_at,
        sent_at=sent_at,
        error_message=None,
        message_id=message_id,
    )
