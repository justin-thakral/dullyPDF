"""Fill By Link post-submit signing helpers.

This service keeps the public respondent flow deterministic by reusing the
stored Fill By Link response snapshot and the existing signing data model. The
automation remains linear in the number of template fields because anchor
derivation walks the field list once and the snapshot materializer already
handles the filled-PDF generation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from backend.firebaseDB.fill_link_database import (
    FillLinkRecord,
    FillLinkResponseRecord,
    attach_fill_link_response_signing_request,
)
from backend.firebaseDB.template_database import get_template
from backend.firebaseDB.user_database import get_user_profile
from backend.firebaseDB.signing_database import (
    SigningRequestRecord,
    create_signing_request,
    get_signing_request_for_user,
    get_signing_monthly_usage,
    invalidate_signing_request,
    mark_signing_request_sent,
    rollback_signing_request_sent,
)
from backend.firebaseDB.storage_service import build_signing_bucket_uri, delete_storage_object
from backend.services.downgrade_retention_service import (
    get_user_retention_locked_template_ids,
    get_user_retention_pending_template_ids,
)
from backend.logging_config import get_logger
from backend.services.limits_service import resolve_signing_requests_monthly_limit
from backend.services.pdf_export_service import build_immutable_signing_source_pdf
from backend.services.signing_consumer_consent_service import (
    persist_business_disclosure_artifact,
    persist_consumer_disclosure_artifact,
)
from backend.services.signing_quota_service import SigningRequestMonthlyLimitError
from backend.services.signing_storage_service import (
    ensure_signing_storage_configuration,
    promote_signing_staged_object,
    resolve_signing_stage_bucket_path,
    upload_signing_staging_pdf_bytes_for_final,
)
from backend.services.signing_service import (
    SIGNING_INVITE_METHOD_EMAIL,
    SIGNING_MODE_FILL_AND_SIGN,
    build_signing_source_pdf_object_path,
    build_signing_source_version,
    normalize_optional_text,
    normalize_signature_mode,
    resolve_document_category_label,
    resolve_signing_company_authority_attestation,
    resolve_signing_consumer_disclosure_fields,
    resolve_signing_disclosure_version,
    sha256_hex_for_bytes,
    validate_document_category,
    validate_esign_eligibility_confirmation,
    validate_signer_email,
    validate_signer_name,
)
from backend.time_utils import now_iso


logger = get_logger(__name__)


@dataclass(frozen=True)
class FillLinkSigningRequestMaterialization:
    record: SigningRequestRecord
    created_now: bool
    sent_now: bool


class FillLinkSigningUnavailableError(ValueError):
    """Raised when a stored Fill By Link response cannot resume signing."""


def upload_signing_pdf_bytes(pdf_bytes: bytes, destination_path: str) -> str:
    """Compatibility wrapper that stages bytes but returns the final signing URI."""
    upload_signing_staging_pdf_bytes_for_final(pdf_bytes, destination_path)
    return build_signing_bucket_uri(destination_path)


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
    sender_display_name: Optional[str] = None,
    sender_email: Optional[str] = None,
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
    validate_esign_eligibility_confirmation(config.get("esignEligibilityConfirmed"))
    consumer_disclosure_fields = resolve_signing_consumer_disclosure_fields(
        signature_mode=signature_mode,
        sender_display_name=sender_display_name,
        sender_email=sender_email,
        paper_copy_procedure=config.get("consumerPaperCopyProcedure"),
        paper_copy_fee_description=config.get("consumerPaperCopyFeeDescription"),
        withdrawal_procedure=config.get("consumerWithdrawalProcedure"),
        withdrawal_consequences=config.get("consumerWithdrawalConsequences"),
        contact_update_procedure=config.get("consumerContactUpdateProcedure"),
        consent_scope_description=config.get("consumerConsentScopeDescription"),
        require_complete=True,
    )
    attested_at = now_iso()
    return {
        "enabled": True,
        "signature_mode": signature_mode,
        "document_category": document_category,
        "document_category_label": resolve_document_category_label(document_category),
        "esign_eligibility_confirmed": True,
        "esign_eligibility_confirmed_at": attested_at,
        "esign_eligibility_confirmed_source": "fill_link_publish",
        "company_binding_enabled": bool(config.get("companyBindingEnabled")),
        "manual_fallback_enabled": bool(config.get("manualFallbackEnabled", True)),
        "sender_display_name": consumer_disclosure_fields["sender_display_name"],
        "sender_contact_email": consumer_disclosure_fields["sender_contact_email"],
        "consumer_paper_copy_procedure": consumer_disclosure_fields["paper_copy_procedure"],
        "consumer_paper_copy_fee_description": consumer_disclosure_fields["paper_copy_fee_description"],
        "consumer_withdrawal_procedure": consumer_disclosure_fields["withdrawal_procedure"],
        "consumer_withdrawal_consequences": consumer_disclosure_fields["withdrawal_consequences"],
        "consumer_contact_update_procedure": consumer_disclosure_fields["contact_update_procedure"],
        "consumer_consent_scope_override": consumer_disclosure_fields["consent_scope_description"],
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
        "esignEligibilityConfirmed": bool(config.get("esign_eligibility_confirmed")),
        "esignEligibilityConfirmedAt": str(config.get("esign_eligibility_confirmed_at") or "").strip() or None,
        "companyBindingEnabled": bool(config.get("company_binding_enabled")),
        "manualFallbackEnabled": bool(config.get("manual_fallback_enabled", True)),
        "consumerPaperCopyProcedure": str(config.get("consumer_paper_copy_procedure") or "").strip() or None,
        "consumerPaperCopyFeeDescription": str(config.get("consumer_paper_copy_fee_description") or "").strip() or None,
        "consumerWithdrawalProcedure": str(config.get("consumer_withdrawal_procedure") or "").strip() or None,
        "consumerWithdrawalConsequences": str(config.get("consumer_withdrawal_consequences") or "").strip() or None,
        "consumerContactUpdateProcedure": str(config.get("consumer_contact_update_procedure") or "").strip() or None,
        "consumerConsentScopeDescription": str(config.get("consumer_consent_scope_override") or "").strip() or None,
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


def _ensure_fill_link_signing_source_available(
    *,
    link: FillLinkRecord,
    request_record: Optional[SigningRequestRecord],
) -> None:
    normalized_template_id = str(link.template_id or "").strip()
    if not normalized_template_id:
        return
    request_status = str(getattr(request_record, "status", "") or "").strip().lower()
    if request_status in {"sent", "completed"}:
        return
    if get_template(normalized_template_id, link.user_id) is None:
        if request_record is not None and request_status == "draft":
            invalidate_signing_request(
                request_record.id,
                link.user_id,
                reason="This signing draft can no longer be sent because its saved form was deleted.",
            )
        raise FillLinkSigningUnavailableError(
            "This signing request is unavailable because the source form was deleted. Contact the sender."
        )
    locked_template_ids = get_user_retention_pending_template_ids(link.user_id)
    if normalized_template_id in locked_template_ids:
        raise FillLinkSigningUnavailableError(
            "This signing request is unavailable until the sender upgrades and reactivates the source form. Contact the sender."
        )


def ensure_fill_link_response_signing_request(
    *,
    link: FillLinkRecord,
    response: FillLinkResponseRecord,
    source_pdf_bytes: Optional[bytes],
    signing_config: Dict[str, Any],
    sender_email: Optional[str] = None,
    sender_display_name: Optional[str] = None,
    public_app_origin: Optional[str] = None,
) -> FillLinkSigningRequestMaterialization:
    ensure_signing_storage_configuration(validate_remote=False)
    signer_name, signer_email = resolve_fill_link_signer_identity(response, signing_config)
    document_category = validate_document_category(
        str(signing_config.get("document_category") or "ordinary_business_form")
    )
    if not bool(signing_config.get("esign_eligibility_confirmed")):
        raise ValueError(
            "Republish the Fill By Link signing settings after confirming the document is eligible for DullyPDF's U.S. e-sign flow."
        )
    consumer_disclosure_fields = resolve_signing_consumer_disclosure_fields(
        signature_mode=str(signing_config.get("signature_mode") or "business"),
        sender_display_name=normalize_optional_text(
            signing_config.get("sender_display_name"),
            maximum_length=200,
        ) or normalize_optional_text(sender_display_name, maximum_length=200),
        sender_email=sender_email,
        sender_contact_email=normalize_optional_text(
            signing_config.get("sender_contact_email"),
            maximum_length=200,
        ),
        paper_copy_procedure=signing_config.get("consumer_paper_copy_procedure"),
        paper_copy_fee_description=signing_config.get("consumer_paper_copy_fee_description"),
        withdrawal_procedure=signing_config.get("consumer_withdrawal_procedure"),
        withdrawal_consequences=signing_config.get("consumer_withdrawal_consequences"),
        contact_update_procedure=signing_config.get("consumer_contact_update_procedure"),
        consent_scope_description=signing_config.get("consumer_consent_scope_override"),
        require_complete=True,
    )

    existing_request: Optional[SigningRequestRecord] = None
    if response.signing_request_id:
        existing_request = get_signing_request_for_user(response.signing_request_id, link.user_id)
        if existing_request is not None and existing_request.status == "invalidated":
            existing_request = None
    _ensure_fill_link_signing_source_available(
        link=link,
        request_record=existing_request,
    )
    if existing_request is not None and existing_request.status in {"sent", "completed"}:
        return FillLinkSigningRequestMaterialization(record=existing_request, created_now=False, sent_now=False)

    response_snapshot = (
        response.respondent_pdf_snapshot
        if isinstance(response.respondent_pdf_snapshot, dict)
        else link.respondent_pdf_snapshot
        if isinstance(link.respondent_pdf_snapshot, dict)
        else None
    )
    if not isinstance(response_snapshot, dict):
        raise ValueError("Fill By Link signing requires a saved response PDF snapshot.")

    anchors = build_fill_link_signing_anchors(response_snapshot.get("fields") or [])
    if not anchors:
        raise ValueError("No usable signature anchors were found for this template.")
    if source_pdf_bytes is None:
        raise ValueError("Fill By Link signing requires the submitted PDF before a draft can be sent.")

    immutable_source_pdf_bytes = build_immutable_signing_source_pdf(source_pdf_bytes)
    current_sha256 = sha256_hex_for_bytes(immutable_source_pdf_bytes)
    source_document_name = (
        str(link.template_name or link.title or response_snapshot.get("filename") or "fill-link-signing").strip()
        or "fill-link-signing"
    )
    owner_profile = get_user_profile(link.user_id)
    monthly_limit = resolve_signing_requests_monthly_limit(owner_profile.role if owner_profile else None)

    request_record = existing_request
    created_now = False
    if request_record is None:
        usage_record = get_signing_monthly_usage(link.user_id)
        if monthly_limit <= 0 or (usage_record is not None and usage_record.request_count >= monthly_limit):
            raise SigningRequestMonthlyLimitError(limit=monthly_limit)
        source_version = build_signing_source_version(
            source_type="fill_link_response",
            source_id=response.id,
            source_template_id=link.template_id,
            source_pdf_sha256=current_sha256,
        )
        disclosure_version = resolve_signing_disclosure_version(str(signing_config.get("signature_mode") or "business"))
        authority_attestation = resolve_signing_company_authority_attestation(
            signing_config.get("company_binding_enabled")
        )
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
            source_version=source_version,
            document_category=document_category,
            company_binding_enabled=bool(signing_config.get("company_binding_enabled")),
            authority_attestation_version=authority_attestation.get("version") if authority_attestation else None,
            authority_attestation_text=authority_attestation.get("text") if authority_attestation else None,
            authority_attestation_sha256=authority_attestation.get("sha256") if authority_attestation else None,
            manual_fallback_enabled=bool(signing_config.get("manual_fallback_enabled", True)),
            signer_name=signer_name,
            signer_email=signer_email,
            anchors=anchors,
            disclosure_version=disclosure_version,
            sender_display_name=consumer_disclosure_fields["sender_display_name"],
            esign_eligibility_confirmed_at=normalize_optional_text(
                signing_config.get("esign_eligibility_confirmed_at"),
                maximum_length=80,
            ) or now_iso(),
            esign_eligibility_confirmed_source=normalize_optional_text(
                signing_config.get("esign_eligibility_confirmed_source"),
                maximum_length=80,
            ) or "fill_link_publish",
            sender_email=sender_email,
            sender_contact_email=consumer_disclosure_fields["sender_contact_email"],
            consumer_paper_copy_procedure=consumer_disclosure_fields["paper_copy_procedure"],
            consumer_paper_copy_fee_description=consumer_disclosure_fields["paper_copy_fee_description"],
            consumer_withdrawal_procedure=consumer_disclosure_fields["withdrawal_procedure"],
            consumer_withdrawal_consequences=consumer_disclosure_fields["withdrawal_consequences"],
            consumer_contact_update_procedure=consumer_disclosure_fields["contact_update_procedure"],
            consumer_consent_scope_override=consumer_disclosure_fields["consent_scope_description"],
            invite_method=SIGNING_INVITE_METHOD_EMAIL,
        )
        created_now = True
        attach_fill_link_response_signing_request(
            response.id,
            link.id,
            link.user_id,
            signing_request_id=request_record.id,
        )

    source_pdf_object_path = build_signing_source_pdf_object_path(
        user_id=link.user_id,
        request_id=request_record.id,
        source_document_name=source_document_name,
    )
    source_pdf_bucket_path = upload_signing_pdf_bytes(
        immutable_source_pdf_bytes,
        source_pdf_object_path,
    )
    try:
        staged_source_pdf_bucket_path = resolve_signing_stage_bucket_path(source_pdf_bucket_path)
    except ValueError:
        staged_source_pdf_bucket_path = source_pdf_bucket_path
    try:
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
            monthly_limit=monthly_limit,
            owner_review_confirmed_at=now_iso(),
            public_app_origin=public_app_origin,
        )
    except Exception:
        try:
            delete_storage_object(staged_source_pdf_bucket_path)
        except Exception:
            logger.warning(
                "Failed to delete staged Fill By Link source PDF after send rejection for request %s: %s",
                request_record.id,
                staged_source_pdf_bucket_path,
            )
        raise
    if sent_record is None:
        delete_storage_object(staged_source_pdf_bucket_path)
        raise ValueError("Failed to create the signing request from this Fill By Link response.")
    if sent_record.status != "sent" or sent_record.source_pdf_bucket_path != source_pdf_bucket_path:
        delete_storage_object(staged_source_pdf_bucket_path)
        raise ValueError("This signing request changed before the Fill By Link handoff could be sent.")
    try:
        promote_signing_staged_object(
            source_pdf_bucket_path,
            retain_until=getattr(sent_record, "retention_until", None),
        )
    except Exception as exc:
        logger.warning(
            "Fill By Link signing source promotion failed for request %s (%s): %s",
            request_record.id,
            source_pdf_bucket_path,
            exc,
        )
        rollback_signing_request_sent(
            sent_record.id,
            link.user_id,
            expected_source_pdf_bucket_path=source_pdf_bucket_path,
            expected_source_pdf_sha256=current_sha256,
        )
        try:
            delete_storage_object(staged_source_pdf_bucket_path)
        except Exception:
            logger.warning(
                "Failed to delete staged Fill By Link source PDF after promotion failure for request %s: %s",
                request_record.id,
                staged_source_pdf_bucket_path,
            )
        raise FillLinkSigningUnavailableError(
            "DullyPDF could not finalize the retained source PDF for the post-submit signing request. Please try again."
        ) from exc
    sent_record = persist_business_disclosure_artifact(sent_record) or sent_record
    sent_record = persist_consumer_disclosure_artifact(sent_record) or sent_record

    return FillLinkSigningRequestMaterialization(record=sent_record, created_now=created_now, sent_now=True)
