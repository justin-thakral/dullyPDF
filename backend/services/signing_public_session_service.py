"""Session and OTP helpers for the public signing ceremony."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .signing_service import (
    build_signing_session_ip_scope,
    build_signing_user_agent_fingerprint,
    resolve_signing_verification_resend_cooldown_seconds,
)


def parse_public_signing_timestamp(value: Optional[str]) -> Optional[datetime]:
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


def resolve_public_signing_verification_resend_available_at(session) -> Optional[str]:
    sent_at = parse_public_signing_timestamp(getattr(session, "verification_sent_at", None))
    if sent_at is None:
        return None
    return (sent_at + timedelta(seconds=resolve_signing_verification_resend_cooldown_seconds())).isoformat()


def session_has_public_signing_email_verification(session) -> bool:
    return bool(getattr(session, "verification_completed_at", None))


def serialize_public_signing_session(session, *, session_token: str) -> Dict[str, Any]:
    return {
        "id": session.id,
        "token": session_token,
        "expiresAt": session.expires_at,
        "verifiedAt": getattr(session, "verification_completed_at", None),
        "verificationSentAt": getattr(session, "verification_sent_at", None),
        "verificationExpiresAt": getattr(session, "verification_expires_at", None),
        "verificationAttemptCount": getattr(session, "verification_attempt_count", 0),
        "verificationResendCount": getattr(session, "verification_resend_count", 0),
        "verificationResendAvailableAt": resolve_public_signing_verification_resend_available_at(session),
    }


def normalize_public_signing_session_header(value: Optional[str]) -> str:
    return str(value or "").strip()


def resolve_public_signing_session_binding_mismatch(
    session,
    *,
    client_ip: Optional[str],
    user_agent: Optional[str],
) -> Dict[str, Optional[str]]:
    current_ip_scope = build_signing_session_ip_scope(client_ip)
    current_user_agent_hash = build_signing_user_agent_fingerprint(user_agent)
    if session.binding_ip_scope and current_ip_scope and session.binding_ip_scope != current_ip_scope:
        return {
            "reason": "ip_scope",
            "currentIpScope": current_ip_scope,
            "currentUserAgentHash": current_user_agent_hash,
        }
    if session.binding_user_agent_hash and session.binding_user_agent_hash != current_user_agent_hash:
        return {
            "reason": "user_agent",
            "currentIpScope": current_ip_scope,
            "currentUserAgentHash": current_user_agent_hash,
        }
    return {
        "reason": None,
        "currentIpScope": current_ip_scope,
        "currentUserAgentHash": current_user_agent_hash,
    }
