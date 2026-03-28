"""Helpers for public validation of completed signing records.

Validation is O(event_count) only when the caller inspects the embedded audit
manifest contents. The route performs O(1) storage reads because it loads the
completed audit-manifest envelope and, when present, the finalized signed PDF.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from backend.firebaseDB.storage_service import download_storage_bytes
from backend.services.signing_pdf_digital_service import async_validate_digital_pdf_signature
from backend.services.signing_audit_service import verify_signing_audit_envelope
from backend.services.signing_invite_service import build_signing_public_app_url
from backend.services.signing_storage_service import resolve_signing_storage_read_bucket_path
from backend.services.signing_service import (
    SIGNING_STATUS_COMPLETED,
    build_signing_validation_path,
    resolve_document_category_label,
    sha256_hex_for_bytes,
)
from backend.time_utils import now_iso


def build_signing_validation_url(request_id: str) -> str:
    return build_signing_public_app_url(build_signing_validation_path(request_id))


def _build_validation_checks(
    *,
    record,
    envelope_payload: Dict[str, Any],
    envelope_sha256: str,
) -> List[Dict[str, Any]]:
    manifest = dict((envelope_payload or {}).get("manifest") or {})
    document_evidence = dict(manifest.get("documentEvidence") or {})
    checks = [
        {
            "key": "audit_manifest_signature",
            "label": "Audit manifest envelope signature",
            "passed": verify_signing_audit_envelope(envelope_payload),
        },
        {
            "key": "audit_manifest_hash",
            "label": "Stored audit manifest hash matches the retained envelope",
            "passed": not getattr(record, "audit_manifest_sha256", None)
            or getattr(record, "audit_manifest_sha256", None) == envelope_sha256,
        },
        {
            "key": "source_pdf_hash",
            "label": "Source PDF hash matches the retained audit manifest",
            "passed": not getattr(record, "source_pdf_sha256", None)
            or getattr(record, "source_pdf_sha256", None) == document_evidence.get("sourcePdfSha256"),
        },
        {
            "key": "signed_pdf_hash",
            "label": "Signed PDF hash matches the retained audit manifest",
            "passed": not getattr(record, "signed_pdf_sha256", None)
            or getattr(record, "signed_pdf_sha256", None) == document_evidence.get("signedPdfSha256"),
        },
        {
            "key": "audit_receipt_present",
            "label": "Audit receipt artifact is retained for the completed request",
            "passed": bool(getattr(record, "audit_receipt_bucket_path", None) and getattr(record, "audit_receipt_sha256", None)),
        },
    ]
    return checks


async def build_signing_validation_payload(record) -> Dict[str, Any]:
    validation_path = build_signing_validation_path(record.id)
    payload: Dict[str, Any] = {
        "available": False,
        "valid": False,
        "status": "unavailable",
        "statusMessage": "The retained validation data for this signing record is unavailable.",
        "validatedAt": now_iso(),
        "requestId": record.id,
        "title": getattr(record, "title", None),
        "sourceDocumentName": record.source_document_name,
        "sourceVersion": getattr(record, "source_version", None),
        "documentCategory": record.document_category,
        "documentCategoryLabel": resolve_document_category_label(record.document_category),
        "completedAt": getattr(record, "completed_at", None),
        "retentionUntil": getattr(record, "retention_until", None),
        "sender": {
            "displayName": getattr(record, "sender_display_name", None),
            "contactEmail": getattr(record, "sender_contact_email", None) or getattr(record, "sender_email", None),
        },
        "signer": {
            "name": record.signer_name,
            "adoptedName": getattr(record, "signature_adopted_name", None),
        },
        "validationPath": validation_path,
        "validationUrl": build_signing_validation_url(record.id),
        "sourcePdfSha256": getattr(record, "source_pdf_sha256", None),
        "signedPdfSha256": getattr(record, "signed_pdf_sha256", None),
        "auditManifestSha256": getattr(record, "audit_manifest_sha256", None),
        "auditReceiptSha256": getattr(record, "audit_receipt_sha256", None),
        "checks": [],
        "eventCount": None,
        "signature": None,
        "digitalSignature": None,
    }
    if getattr(record, "status", None) != SIGNING_STATUS_COMPLETED:
        payload["statusMessage"] = "Only completed DullyPDF signing records can be validated."
        return payload
    if not getattr(record, "audit_manifest_bucket_path", None):
        return payload
    try:
        readable_audit_manifest_bucket_path = resolve_signing_storage_read_bucket_path(
            record.audit_manifest_bucket_path,
            retain_until=getattr(record, "retention_until", None),
        )
        envelope_bytes = download_storage_bytes(readable_audit_manifest_bucket_path)
    except Exception:
        return payload
    try:
        envelope_payload = json.loads(envelope_bytes.decode("utf-8"))
    except Exception:
        payload["available"] = True
        payload["status"] = "invalid"
        payload["statusMessage"] = "The retained audit manifest could not be decoded."
        return payload

    manifest = dict((envelope_payload or {}).get("manifest") or {})
    document_evidence = dict(manifest.get("documentEvidence") or {})
    signature = dict((envelope_payload or {}).get("signature") or {})
    envelope_sha256 = sha256_hex_for_bytes(envelope_bytes)
    checks = _build_validation_checks(
        record=record,
        envelope_payload=envelope_payload,
        envelope_sha256=envelope_sha256,
    )
    digital_signature = None
    if getattr(record, "signed_pdf_bucket_path", None):
        try:
            readable_signed_pdf_bucket_path = resolve_signing_storage_read_bucket_path(
                record.signed_pdf_bucket_path,
                retain_until=getattr(record, "retention_until", None),
            )
            signed_pdf_bytes = download_storage_bytes(readable_signed_pdf_bucket_path)
            digital_signature = await async_validate_digital_pdf_signature(
                signed_pdf_bytes,
                expected_sha256=document_evidence.get("signedPdfSha256") or getattr(record, "signed_pdf_sha256", None),
            )
        except Exception:
            digital_signature = None
    if digital_signature and digital_signature.present:
        # Product-valid Dully verification is anchored on the retained audit
        # envelope plus the finalized signed-PDF bytes. Certificate trust-chain
        # and TSA semantics stay informational until the repo ships a separate
        # advanced-digital-signature track.
        checks.append(
            {
                "key": "pdf_digital_signature_integrity",
                "label": "Embedded PDF digital signature is intact",
                "passed": bool(digital_signature.intact),
            }
        )
        if digital_signature.expected_sha256_matches is not None:
            checks.append(
                {
                    "key": "pdf_digital_signature_hash",
                    "label": "Embedded PDF digital signature covers the retained signed PDF artifact",
                    "passed": bool(digital_signature.expected_sha256_matches),
                }
            )
    valid = all(bool(check.get("passed")) for check in checks)
    payload.update(
        {
            "available": True,
            "valid": valid,
            "status": "valid" if valid else "invalid",
            "statusMessage": (
                "DullyPDF verified the retained audit evidence for this completed signing record."
                if valid
                else "DullyPDF could not verify one or more retained signing checks for this record."
            ),
            "sourcePdfSha256": document_evidence.get("sourcePdfSha256") or getattr(record, "source_pdf_sha256", None),
            "signedPdfSha256": document_evidence.get("signedPdfSha256") or getattr(record, "signed_pdf_sha256", None),
            "auditManifestSha256": envelope_sha256,
            "checks": checks,
            "eventCount": len(list(manifest.get("events") or [])),
            "signature": {
                "method": signature.get("method"),
                "algorithm": signature.get("algorithm"),
                "keyVersionName": signature.get("keyVersionName"),
                "digestSha256": signature.get("digestSha256"),
            },
            "digitalSignature": (
                {
                    "present": digital_signature.present,
                    "valid": digital_signature.valid,
                    "intact": digital_signature.intact,
                    "trusted": digital_signature.trusted,
                    "summary": digital_signature.summary,
                    "signatureCount": digital_signature.signature_count,
                    "fieldName": digital_signature.field_name,
                    "subfilter": digital_signature.subfilter,
                    "coverage": digital_signature.coverage,
                    "modificationLevel": digital_signature.modification_level,
                    "timestampPresent": digital_signature.timestamp_present,
                    "timestampValid": digital_signature.timestamp_valid,
                    "certificateSubject": digital_signature.certificate_subject,
                    "certificateIssuer": digital_signature.certificate_issuer,
                    "certificateSerialNumber": digital_signature.certificate_serial_number,
                    "certificateFingerprintSha256": digital_signature.certificate_fingerprint_sha256,
                    "expectedSha256Matches": digital_signature.expected_sha256_matches,
                    "actualSha256": digital_signature.actual_sha256,
                }
                if digital_signature is not None
                else None
            ),
        }
    )
    return payload
