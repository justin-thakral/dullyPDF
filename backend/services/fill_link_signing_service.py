"""Fill By Link post-submit signing helpers.

This service keeps the public respondent flow deterministic by reusing the
stored Fill By Link response snapshot and the existing signing data model. The
automation remains linear in the number of template fields because anchor
derivation walks the field list once and the snapshot materializer already
handles the filled-PDF generation.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from backend.firebaseDB.fill_link_database import (
    FillLinkRecord,
    FillLinkResponseRecord,
    attach_fill_link_response_signing_request,
)
from backend.firebaseDB.signing_database import (
    SigningRequestRecord,
    create_signing_request,
    get_signing_request_for_user,
    mark_signing_request_invite_delivery,
    mark_signing_request_sent,
)
from backend.firebaseDB.storage_service import upload_signing_pdf_bytes
from backend.firebaseDB.storage_service import delete_storage_object
from backend.services.signing_invite_service import SIGNING_INVITE_DELIVERY_REDIRECTED
from backend.services.signing_service import (
    SIGNING_MODE_FILL_AND_SIGN,
    build_signing_source_pdf_object_path,
    build_signing_source_version,
    normalize_optional_text,
    normalize_signature_mode,
    resolve_document_category_label,
    resolve_signing_disclosure_version,
    sha256_hex_for_bytes,
    validate_document_category,
    validate_signer_email,
    validate_signer_name,
)
from backend.time_utils import now_iso


def _looks_like_signed_date_field(field_name: str, field_type: str) -> bool:
    normalized_name = str(field_name or "").strip().lower()
    return field_type == "date" and "sign" in normalized_name and "date" in normalized_name


def _coerce_text_answer(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(entry or "").strip() for entry in value if str(entry or "").strip())
    return str(value).strip()


def _question_candidate_keys(question: Dict[str, Any]) -> List[str]:
    return [
        str(question.get("type") or "").strip().lower(),
        str(question.get("key") or "").strip().lower(),
        str(question.get("sourceField") or "").strip().lower(),
        str(question.get("label") or "").strip().lower().replace(" ", "_"),
    ]


def _question_looks_like_email(question: Dict[str, Any]) -> bool:
    for candidate in _question_candidate_keys(question):
        if not candidate:
            continue
        if candidate == "email" or candidate.endswith("_email") or "email_address" in candidate:
            return True
    return False


def _extract_anchor_rect(field: Dict[str, Any]) -> Optional[Dict[str, float]]:
    rect_payload = field.get("rect")
    if isinstance(rect_payload, dict):
        candidate = rect_payload
    else:
        candidate = field
    try:
        normalized_rect = {
            "x": float(candidate.get("x")),
            "y": float(candidate.get("y")),
            "width": float(candidate.get("width")),
            "height": float(candidate.get("height")),
        }
    except (AttributeError, TypeError, ValueError):
        return None
    if normalized_rect["width"] <= 0 or normalized_rect["height"] <= 0:
        return None
    return normalized_rect


def build_fill_link_signing_anchors(fields: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    anchors: List[Dict[str, Any]] = []
    for field in fields:
        if not isinstance(field, dict):
            continue
        field_type = str(field.get("type") or "").strip().lower()
        field_name = str(field.get("name") or "").strip()
        page = field.get("page")
        if not field_name:
            continue
        try:
            normalized_page = max(1, int(page))
        except (TypeError, ValueError):
            continue
        normalized_rect = _extract_anchor_rect(field)
        if normalized_rect is None:
            continue
        if field_type == "signature":
            anchors.append(
                {
                    "kind": "signature",
                    "page": normalized_page,
                    "rect": normalized_rect,
                    "fieldName": field_name,
                }
            )
            continue
        if _looks_like_signed_date_field(field_name, field_type):
            anchors.append(
                {
                    "kind": "signed_date",
                    "page": normalized_page,
                    "rect": normalized_rect,
                    "fieldName": field_name,
                }
            )
    return anchors


def normalize_fill_link_signing_config(
    config: Any,
    *,
    scope_type: str,
    questions: Iterable[Dict[str, Any]],
    fields: Iterable[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not isinstance(config, dict):
        return None
    enabled = bool(config.get("enabled"))
    if not enabled:
        return None
    if str(scope_type or "").strip().lower() != "template":
        raise ValueError("Post-submit signing is currently available only for template Fill By Link.")

    signer_name_question_key = normalize_optional_text(config.get("signerNameQuestionKey"), maximum_length=160)
    signer_email_question_key = normalize_optional_text(config.get("signerEmailQuestionKey"), maximum_length=160)
    if not signer_name_question_key or not signer_email_question_key:
        raise ValueError("Choose both a signer name question and a signer email question before enabling signing.")

    visible_questions = [
        question
        for question in questions
        if isinstance(question, dict) and question.get("visible", True)
    ]
    visible_question_keys = {
        str(question.get("key") or "").strip(): question
        for question in visible_questions
        if str(question.get("key") or "").strip()
    }
    if signer_name_question_key not in visible_question_keys:
        raise ValueError("The signer name question must remain visible on the published Fill By Link form.")
    if signer_email_question_key not in visible_question_keys:
        raise ValueError("The signer email question must remain visible on the published Fill By Link form.")
    if not any(_question_looks_like_email(question) for question in visible_questions):
        raise ValueError("Add a visible email question before enabling post-submit signing.")
    if not _question_looks_like_email(visible_question_keys[signer_email_question_key]):
        raise ValueError("Choose a visible email question for the signer email mapping before enabling signing.")

    if not build_fill_link_signing_anchors(fields):
        raise ValueError("Add at least one signature field to the PDF before enabling post-submit signing.")

    signature_mode = normalize_signature_mode(config.get("signatureMode"))
    document_category = validate_document_category(config.get("documentCategory"))
    return {
        "enabled": True,
        "signature_mode": signature_mode,
        "document_category": document_category,
        "document_category_label": resolve_document_category_label(document_category),
        "manual_fallback_enabled": bool(config.get("manualFallbackEnabled", True)),
        "signer_name_question_key": signer_name_question_key,
        "signer_email_question_key": signer_email_question_key,
    }


def serialize_fill_link_signing_config(config: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(config, dict) or not config.get("enabled"):
        return None
    document_category = str(config.get("document_category") or "").strip()
    return {
        "enabled": True,
        "signatureMode": str(config.get("signature_mode") or "business").strip() or "business",
        "documentCategory": document_category,
        "documentCategoryLabel": (
            str(config.get("document_category_label") or "").strip()
            or resolve_document_category_label(document_category)
        ),
        "manualFallbackEnabled": bool(config.get("manual_fallback_enabled", True)),
        "signerNameQuestionKey": str(config.get("signer_name_question_key") or "").strip(),
        "signerEmailQuestionKey": str(config.get("signer_email_question_key") or "").strip(),
    }


def resolve_fill_link_signer_identity(
    response: FillLinkResponseRecord,
    signing_config: Dict[str, Any],
) -> Tuple[str, str]:
    return resolve_fill_link_signer_identity_from_answers(response.answers, signing_config)


def resolve_fill_link_signer_identity_from_answers(
    answers: Dict[str, Any],
    signing_config: Dict[str, Any],
) -> Tuple[str, str]:
    signer_name_key = str(signing_config.get("signer_name_question_key") or "").strip()
    signer_email_key = str(signing_config.get("signer_email_question_key") or "").strip()
    signer_name = validate_signer_name(_coerce_text_answer(answers.get(signer_name_key)))
    signer_email = validate_signer_email(_coerce_text_answer(answers.get(signer_email_key)))
    return signer_name, signer_email


def ensure_fill_link_response_signing_request(
    *,
    link: FillLinkRecord,
    response: FillLinkResponseRecord,
    source_pdf_bytes: bytes,
    signing_config: Dict[str, Any],
) -> SigningRequestRecord:
    response_snapshot = (
        response.respondent_pdf_snapshot
        if isinstance(response.respondent_pdf_snapshot, dict)
        else link.respondent_pdf_snapshot
        if isinstance(link.respondent_pdf_snapshot, dict)
        else None
    )
    if not isinstance(response_snapshot, dict):
        raise ValueError("Fill By Link signing requires a saved response PDF snapshot.")

    signer_name, signer_email = resolve_fill_link_signer_identity(response, signing_config)
    anchors = build_fill_link_signing_anchors(response_snapshot.get("fields") or [])
    if not anchors:
        raise ValueError("No usable signature anchors were found for this template.")

    existing_request: Optional[SigningRequestRecord] = None
    if response.signing_request_id:
        existing_request = get_signing_request_for_user(response.signing_request_id, link.user_id)
        if existing_request is not None and existing_request.status == "invalidated":
            existing_request = None

    current_sha256 = sha256_hex_for_bytes(source_pdf_bytes)
    source_document_name = (
        str(link.template_name or link.title or response_snapshot.get("filename") or "fill-link-signing").strip()
        or "fill-link-signing"
    )

    request_record = existing_request
    if request_record is None:
        disclosure_version = resolve_signing_disclosure_version(str(signing_config.get("signature_mode") or "business"))
        request_record = create_signing_request(
            user_id=link.user_id,
            title=f"{source_document_name} · {response.respondent_label}",
            mode=SIGNING_MODE_FILL_AND_SIGN,
            signature_mode=str(signing_config.get("signature_mode") or "business"),
            source_type="fill_link_response",
            source_id=response.id,
            source_link_id=link.id,
            source_record_label=response.respondent_label,
            source_document_name=source_document_name,
            source_template_id=link.template_id,
            source_template_name=link.template_name,
            source_pdf_sha256=current_sha256,
            source_version=build_signing_source_version(
                source_type="fill_link_response",
                source_id=response.id,
                source_template_id=link.template_id,
                source_pdf_sha256=current_sha256,
            ),
            document_category=str(signing_config.get("document_category") or "ordinary_business_form"),
            manual_fallback_enabled=bool(signing_config.get("manual_fallback_enabled", True)),
            signer_name=signer_name,
            signer_email=signer_email,
            anchors=anchors,
            disclosure_version=disclosure_version,
        )
        attach_fill_link_response_signing_request(
            response.id,
            link.id,
            link.user_id,
            signing_request_id=request_record.id,
        )

    if request_record.status in {"sent", "completed"}:
        return request_record

    source_pdf_object_path = build_signing_source_pdf_object_path(
        user_id=link.user_id,
        request_id=request_record.id,
        source_document_name=source_document_name,
    )
    source_pdf_bucket_path = upload_signing_pdf_bytes(source_pdf_bytes, source_pdf_object_path)
    sent_record = mark_signing_request_sent(
        request_record.id,
        link.user_id,
        source_pdf_bucket_path=source_pdf_bucket_path,
        source_pdf_sha256=current_sha256,
        source_version=build_signing_source_version(
            source_type="fill_link_response",
            source_id=response.id,
            source_template_id=link.template_id,
            source_pdf_sha256=current_sha256,
        ),
        owner_review_confirmed_at=now_iso(),
    )
    if sent_record is None:
        delete_storage_object(source_pdf_bucket_path)
        raise ValueError("Failed to create the signing request from this Fill By Link response.")
    if sent_record.status != "sent" or sent_record.source_pdf_bucket_path != source_pdf_bucket_path:
        delete_storage_object(source_pdf_bucket_path)
        raise ValueError("This signing request changed before the Fill By Link handoff could be sent.")

    redirected_record = mark_signing_request_invite_delivery(
        sent_record.id,
        link.user_id,
        delivery_status=SIGNING_INVITE_DELIVERY_REDIRECTED,
        attempted_at=now_iso(),
        sent_at=None,
        delivery_error=None,
    )
    return redirected_record or sent_record
