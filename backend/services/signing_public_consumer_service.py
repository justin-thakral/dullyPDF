"""Consumer-specific helpers for the public signing ceremony.

These helpers keep the HTTP route focused on session validation and state
transitions while the consumer disclosure/evidence rules stay in one module.
Each helper is linear in the size of the disclosure payload, which is bounded
and small for this ceremony.
"""

from __future__ import annotations

from typing import Any, Dict

from backend.firebaseDB.signing_database import mark_signing_request_consumer_disclosure_presented

from .signing_consumer_consent_service import (
    persist_consumer_disclosure_artifact,
    resolve_consumer_disclosure_artifact,
)
from .signing_service import (
    SIGNING_STATUS_SENT,
    SIGNATURE_MODE_CONSUMER,
    resolve_signing_disclosure_payload_for_record,
)


def _resolve_consumer_disclosure_version(record, artifact: Dict[str, Any]) -> str:
    return (
        str(getattr(record, "consumer_disclosure_version", "") or "").strip()
        or str(artifact.get("version") or "").strip()
        or str(getattr(record, "disclosure_version", "") or "").strip()
    )


def _resolve_consumer_consent_scope(record, artifact: Dict[str, Any]) -> str | None:
    scope = str(getattr(record, "consumer_consent_scope", "") or "").strip()
    if scope:
        return scope
    artifact_scope = str(artifact.get("scope") or "").strip()
    return artifact_scope or None


def serialize_public_signing_disclosure(record, *, public_token: str) -> Dict[str, Any]:
    if str(getattr(record, "signature_mode", "") or "").strip() == SIGNATURE_MODE_CONSUMER:
        artifact = resolve_consumer_disclosure_artifact(record, public_token=public_token)
        return {
            **dict(artifact.get("payload") or {}),
            "sha256": artifact.get("sha256"),
            "presentedAt": getattr(record, "consumer_disclosure_presented_at", None),
            "acceptedAt": getattr(record, "consented_at", None),
            "consentScope": _resolve_consumer_consent_scope(record, artifact),
            "accessDemonstratedAt": getattr(record, "consumer_access_demonstrated_at", None),
            "accessDemonstrationMethod": getattr(record, "consumer_access_demonstration_method", None),
        }
    return resolve_signing_disclosure_payload_for_record(record)


def ensure_public_signing_consumer_disclosure_state(record, *, client=None):
    if str(getattr(record, "signature_mode", "") or "").strip() != SIGNATURE_MODE_CONSUMER:
        return record
    updated_record = persist_consumer_disclosure_artifact(record, client=client) or record
    if str(getattr(updated_record, "status", "") or "").strip() != SIGNING_STATUS_SENT:
        return updated_record
    presented_at = str(getattr(updated_record, "opened_at", None) or "").strip()
    if not presented_at:
        return updated_record
    return (
        mark_signing_request_consumer_disclosure_presented(
            updated_record.id,
            presented_at=presented_at,
            client=client,
        )
        or updated_record
    )


def build_public_signing_consumer_consent_event_details(
    record,
    *,
    public_token: str,
    access_code_length: int,
) -> Dict[str, Any]:
    artifact = resolve_consumer_disclosure_artifact(record, public_token=public_token)
    payload = dict(artifact.get("payload") or {})
    access_check = dict(payload.get("accessCheck") or {})
    return {
        "disclosureVersion": _resolve_consumer_disclosure_version(record, artifact),
        "disclosureSha256": getattr(record, "consumer_disclosure_sha256", None) or artifact.get("sha256"),
        "disclosurePresentedAt": getattr(record, "consumer_disclosure_presented_at", None),
        "documentCategory": getattr(record, "document_category", None),
        "disclosure": payload,
        "consentScope": _resolve_consumer_consent_scope(record, artifact),
        "accessCheck": {
            "format": access_check.get("format") or "pdf",
            "verified": True,
            "codeLength": int(access_code_length),
            "demonstratedAt": getattr(record, "consumer_access_demonstrated_at", None),
            "demonstrationMethod": getattr(record, "consumer_access_demonstration_method", None),
        },
    }


def build_public_signing_consumer_withdrawal_event_details(
    record,
    *,
    public_token: str,
) -> Dict[str, Any]:
    artifact = resolve_consumer_disclosure_artifact(record, public_token=public_token)
    return {
        "disclosureVersion": _resolve_consumer_disclosure_version(record, artifact),
        "disclosureSha256": getattr(record, "consumer_disclosure_sha256", None) or artifact.get("sha256"),
        "disclosurePresentedAt": getattr(record, "consumer_disclosure_presented_at", None),
        "documentCategory": getattr(record, "document_category", None),
        "disclosure": dict(artifact.get("payload") or {}),
        "consentScope": _resolve_consumer_consent_scope(record, artifact),
        "consentedAt": getattr(record, "consented_at", None),
    }
