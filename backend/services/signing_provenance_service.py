"""Shared sender-side provenance event helpers for signing flows.

These helpers keep owner-driven sends and Fill By Link auto-sends aligned on
the same event payload contract. Each call is O(1) because it derives fields
from a single signing request record and records one event.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from backend.firebaseDB.signing_database import record_signing_event
from backend.logging_config import get_logger

from .signing_service import (
    build_signing_link_token_id,
    build_signing_public_token,
    resolve_signing_public_link_version,
    serialize_signing_sender_provenance,
)
from .signing_webhook_service import dispatch_signing_webhook_event

logger = get_logger(__name__)


def build_signing_provenance_event_details(
    record,
    *,
    sender_email: Optional[str] = None,
    invite_method: Optional[str] = None,
    source: Optional[str] = None,
    response_id: Optional[str] = None,
    source_link_id: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    details = dict(serialize_signing_sender_provenance(record))
    if sender_email is not None:
        details["senderEmail"] = sender_email or None
    if invite_method is not None:
        details["inviteMethod"] = invite_method or None
    if source is not None:
        details["source"] = source or None
    if response_id is not None:
        details["responseId"] = response_id or None
        details["sourceLinkId"] = source_link_id or getattr(record, "source_link_id", None)
    if extra:
        details.update(extra)
    return {key: value for key, value in details.items() if value is not None}


def resolve_signing_request_link_token_id(record) -> str:
    public_link_version = resolve_signing_public_link_version(record)
    public_token = build_signing_public_token(record.id, public_link_version)
    return build_signing_link_token_id(public_token)


def record_signing_provenance_event(
    record,
    *,
    event_type: str,
    sender_email: Optional[str] = None,
    invite_method: Optional[str] = None,
    source: Optional[str] = None,
    response_id: Optional[str] = None,
    source_link_id: Optional[str] = None,
    session_id: Optional[str] = None,
    client_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    include_link_token: bool = True,
    extra: Optional[Dict[str, Any]] = None,
    occurred_at: Optional[str] = None,
):
    try:
        result = record_signing_event(
            record.id,
            event_type=event_type,
            session_id=session_id,
            link_token_id=resolve_signing_request_link_token_id(record) if include_link_token else None,
            client_ip=client_ip,
            user_agent=user_agent,
            details=build_signing_provenance_event_details(
                record,
                sender_email=sender_email,
                invite_method=invite_method,
                source=source,
                response_id=response_id,
                source_link_id=source_link_id,
                extra=extra,
            ),
            occurred_at=occurred_at,
        )
        dispatch_signing_webhook_event(
            record,
            event_type=event_type,
            details=build_signing_provenance_event_details(
                record,
                sender_email=sender_email,
                invite_method=invite_method,
                source=source,
                response_id=response_id,
                source_link_id=source_link_id,
                extra=extra,
            ),
            occurred_at=occurred_at,
        )
        return result
    except Exception:
        logger.warning(
            "Signing provenance event recording failed for request=%s event=%s",
            getattr(record, "id", None),
            event_type,
            exc_info=True,
        )
        return None
