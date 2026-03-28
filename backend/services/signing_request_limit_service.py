"""Per-document signing request limit helpers."""

from __future__ import annotations

from typing import Optional

from backend.firebaseDB.signing_database import count_signing_request_limit_usage_for_source_version
from backend.services.limits_service import resolve_signing_requests_per_document_limit


def _normalize_message_document_name(source_document_name: Optional[str]) -> Optional[str]:
    normalized = str(source_document_name or "").strip()
    return normalized or None


def build_signing_request_limit_message(
    limit: int,
    *,
    source_document_name: Optional[str] = None,
) -> str:
    document_name = _normalize_message_document_name(source_document_name)
    if document_name:
        return (
            f"{document_name} has already reached the {limit} signature request limit for your current tier."
        )
    return f"This document has already reached the {limit} signature request limit for your current tier."


def build_public_signing_request_limit_message() -> str:
    return (
        "This submitted record has already reached the sender's signature request limit for this document. "
        "Contact the sender for an offline copy."
    )


class SigningRequestDocumentLimitError(ValueError):
    """Raised when a document has exhausted its per-tier signing request budget."""

    def __init__(
        self,
        *,
        limit: int,
        source_document_name: Optional[str] = None,
        public_message: Optional[str] = None,
    ) -> None:
        self.limit = max(1, int(limit))
        self.source_document_name = _normalize_message_document_name(source_document_name)
        self.public_message = public_message or build_public_signing_request_limit_message()
        super().__init__(
            build_signing_request_limit_message(
                self.limit,
                source_document_name=self.source_document_name,
            )
        )


def ensure_signing_request_limit_available(
    *,
    user_id: str,
    role: Optional[str],
    source_version: Optional[str],
    source_document_name: Optional[str] = None,
    client=None,
) -> None:
    normalized_user_id = str(user_id or "").strip()
    normalized_source_version = str(source_version or "").strip()
    if not normalized_user_id or not normalized_source_version:
        return
    limit = resolve_signing_requests_per_document_limit(role)
    used = count_signing_request_limit_usage_for_source_version(
        normalized_user_id,
        normalized_source_version,
        client=client,
    )
    if used >= limit:
        raise SigningRequestDocumentLimitError(
            limit=limit,
            source_document_name=source_document_name,
        )
