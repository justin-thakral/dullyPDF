"""Consumer consent helpers for public signing ceremonies."""

from __future__ import annotations

import hashlib
from io import BytesIO
import json
from typing import Any, Dict, Iterable, List, Optional

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from backend.firebaseDB.signing_database import store_signing_request_consumer_disclosure

from .signing_service import (
    SIGNING_STATUS_COMPLETED,
    SIGNATURE_MODE_CONSUMER,
    build_signing_consumer_access_code,
    build_signing_public_token,
    resolve_signing_disclosure_payload_for_record,
    resolve_signing_public_link_version,
)


def _canonicalize_json_bytes(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _normalize_optional_text(value: Any) -> Optional[str]:
    normalized = str(value or "").strip()
    return normalized or None


def _normalize_optional_dict(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    return dict(value)


def build_consumer_disclosure_payload(record, *, public_token: Optional[str] = None) -> Dict[str, Any]:
    if str(getattr(record, "signature_mode", "") or "").strip() != SIGNATURE_MODE_CONSUMER:
        raise ValueError("Consumer disclosure payload is only available for consumer signing requests.")
    resolved_public_token = public_token or build_signing_public_token(
        str(getattr(record, "id", "") or "").strip(),
        resolve_signing_public_link_version(record),
    )
    payload = resolve_signing_disclosure_payload_for_record(
        record,
        request_id=str(getattr(record, "id", "") or "").strip(),
    )
    access_check = dict(payload.get("accessCheck") or {})
    access_check["accessPath"] = f"/api/signing/public/{resolved_public_token}/consumer-access-pdf"
    return {
        **payload,
        "accessCheck": access_check,
    }


def build_consumer_disclosure_artifact(record, *, public_token: Optional[str] = None) -> Dict[str, Any]:
    payload = build_consumer_disclosure_payload(record, public_token=public_token)
    payload_bytes = _canonicalize_json_bytes(payload)
    return {
        "version": _normalize_optional_text(payload.get("version")),
        "payload": payload,
        "sha256": hashlib.sha256(payload_bytes).hexdigest(),
        "scope": _normalize_optional_text(payload.get("scope")),
    }


def resolve_consumer_disclosure_artifact(record, *, public_token: Optional[str] = None) -> Dict[str, Any]:
    stored_payload = _normalize_optional_dict(getattr(record, "consumer_disclosure_payload", None))
    if stored_payload:
        payload_bytes = _canonicalize_json_bytes(stored_payload)
        payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()
        return {
            "version": (
                _normalize_optional_text(getattr(record, "consumer_disclosure_version", None))
                or _normalize_optional_text(stored_payload.get("version"))
            ),
            "payload": stored_payload,
            "sha256": _normalize_optional_text(getattr(record, "consumer_disclosure_sha256", None)) or payload_sha256,
            "scope": (
                _normalize_optional_text(getattr(record, "consumer_consent_scope", None))
                or _normalize_optional_text(stored_payload.get("scope"))
            ),
        }
    return build_consumer_disclosure_artifact(record, public_token=public_token)


def persist_consumer_disclosure_artifact(record, *, client=None):
    if str(getattr(record, "signature_mode", "") or "").strip() != SIGNATURE_MODE_CONSUMER:
        return record
    artifact = build_consumer_disclosure_artifact(record)
    stored_payload = _normalize_optional_dict(getattr(record, "consumer_disclosure_payload", None))
    stored_sha256 = _normalize_optional_text(getattr(record, "consumer_disclosure_sha256", None))
    stored_version = _normalize_optional_text(getattr(record, "consumer_disclosure_version", None))
    stored_scope = _normalize_optional_text(getattr(record, "consumer_consent_scope", None))
    if (
        stored_payload == artifact["payload"]
        and stored_sha256 == artifact["sha256"]
        and stored_version == artifact["version"]
        and stored_scope == artifact["scope"]
    ):
        return record
    if str(getattr(record, "status", "") or "").strip() == SIGNING_STATUS_COMPLETED:
        return record
    reset_ceremony_progress = stored_payload is not None
    return (
        store_signing_request_consumer_disclosure(
            record.id,
            disclosure_version=artifact["version"],
            disclosure_payload=artifact["payload"],
            disclosure_sha256=artifact["sha256"],
            consent_scope=artifact["scope"],
            reset_ceremony_progress=reset_ceremony_progress,
            client=client,
        )
        or record
    )


def _wrap_text(text: str, *, width: int) -> List[str]:
    words = [segment for segment in str(text or "").strip().split() if segment]
    if not words:
        return []
    lines: List[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if len(candidate) <= width:
            current = candidate
            continue
        lines.append(current)
        current = word
    lines.append(current)
    return lines


def _draw_wrapped_lines(
    pdf: canvas.Canvas,
    *,
    lines: Iterable[str],
    x: float,
    y: float,
    width: int,
    leading: float,
) -> float:
    current_y = y
    for raw_line in lines:
        for wrapped in _wrap_text(raw_line, width=width):
            pdf.drawString(x, current_y, wrapped)
            current_y -= leading
    return current_y


def render_consumer_access_pdf(
    *,
    request_id: str,
    source_document_name: str,
    disclosure_payload: Dict[str, Any],
) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    page_width, page_height = letter
    code = build_signing_consumer_access_code(request_id)
    summary_lines = [
        str(entry).strip()
        for entry in disclosure_payload.get("summaryLines") or []
        if str(entry).strip()
    ]
    hardware_lines = [
        str(entry).strip()
        for entry in disclosure_payload.get("hardwareSoftware") or []
        if str(entry).strip()
    ]

    pdf.setTitle(f"Consumer access check - {source_document_name}")
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(54, page_height - 64, "DullyPDF Consumer Access Check")
    pdf.setFont("Helvetica", 11)
    current_y = page_height - 92
    current_y = _draw_wrapped_lines(
        pdf,
        lines=[
            f"Document: {source_document_name}",
            "Open this PDF and enter the access code shown below on the signing page.",
            "That step demonstrates you can access PDF records electronically before consenting.",
        ],
        x=54,
        y=current_y,
        width=88,
        leading=15,
    )
    current_y -= 12
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawString(54, current_y, f"Access Code: {code}")
    current_y -= 28

    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(54, current_y, "Consumer disclosure summary")
    current_y -= 18
    pdf.setFont("Helvetica", 11)
    current_y = _draw_wrapped_lines(
        pdf,
        lines=[f"- {line}" for line in summary_lines],
        x=54,
        y=current_y,
        width=92,
        leading=14,
    )
    current_y -= 8
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(54, current_y, "Hardware and software requirements")
    current_y -= 18
    pdf.setFont("Helvetica", 11)
    _draw_wrapped_lines(
        pdf,
        lines=[f"- {line}" for line in hardware_lines],
        x=54,
        y=current_y,
        width=92,
        leading=14,
    )
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
