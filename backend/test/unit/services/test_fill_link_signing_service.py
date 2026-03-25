from __future__ import annotations

from types import SimpleNamespace
import pytest

from backend.services import fill_link_signing_service as service


def test_ensure_fill_link_response_signing_request_uses_response_snapshot_when_link_snapshot_is_missing(mocker) -> None:
    create_mock = mocker.patch.object(
        service,
        "create_signing_request",
        return_value=SimpleNamespace(id="req-1", status="draft"),
    )
    mocker.patch.object(
        service,
        "mark_signing_request_sent",
        return_value=SimpleNamespace(id="req-1", status="sent", source_pdf_bucket_path="gs://bucket/source.pdf"),
    )
    upload_mock = mocker.patch.object(service, "upload_signing_pdf_bytes", return_value="gs://bucket/source.pdf")
    mocker.patch.object(service, "mark_signing_request_invite_delivery", return_value=SimpleNamespace(id="req-1", status="sent"))

    response_snapshot = {
        "filename": "template-one-response.pdf",
        "fields": [
            {
                "name": "signature",
                "type": "signature",
                "page": 1,
                "x": 1,
                "y": 2,
                "width": 100,
                "height": 20,
                "rect": [1, 2, 101, 22],
            },
        ],
    }
    link = SimpleNamespace(
        id="link-1",
        user_id="user-1",
        template_id="tpl-1",
        template_name="Template One",
        title="Template One Intake",
        respondent_pdf_snapshot=None,
    )
    response = SimpleNamespace(
        id="resp-1",
        respondent_label="Justin QA",
        answers={"full_name": "Justin QA", "email": "justin@example.com"},
        respondent_pdf_snapshot=response_snapshot,
        signing_request_id=None,
    )

    result = service.ensure_fill_link_response_signing_request(
        link=link,
        response=response,
        source_pdf_bytes=b"%PDF-1.4\nstub\n",
        signing_config={
            "signature_mode": "business",
            "document_category": "ordinary_business_form",
            "manual_fallback_enabled": True,
            "signer_name_question_key": "full_name",
            "signer_email_question_key": "email",
        },
    )

    assert result.id == "req-1"
    assert result.status == "sent"
    create_mock.assert_called_once()
    upload_mock.assert_called_once()


def test_normalize_fill_link_signing_config_requires_visible_email_question() -> None:
    with pytest.raises(ValueError, match="Add a visible email question"):
        service.normalize_fill_link_signing_config(
            {
                "enabled": True,
                "signatureMode": "business",
                "documentCategory": "ordinary_business_form",
                "manualFallbackEnabled": True,
                "signerNameQuestionKey": "name",
                "signerEmailQuestionKey": "name",
            },
            scope_type="template",
            questions=[
                {"key": "name", "label": "Name", "type": "text", "visible": True},
            ],
            fields=[
                {"name": "signature", "type": "signature", "page": 1, "rect": {"x": 1, "y": 1, "width": 2, "height": 1}},
            ],
        )


def test_resolve_fill_link_signer_identity_from_answers_requires_valid_email() -> None:
    with pytest.raises(ValueError, match="valid email address"):
        service.resolve_fill_link_signer_identity_from_answers(
            {"full_name": "Ada Lovelace", "email": "Ada Lovelace"},
            {
                "signer_name_question_key": "full_name",
                "signer_email_question_key": "email",
            },
        )


def test_ensure_fill_link_response_signing_request_recreates_invalidated_request(mocker) -> None:
    create_mock = mocker.patch.object(
        service,
        "create_signing_request",
        return_value=SimpleNamespace(id="req-new", status="draft"),
    )
    attach_mock = mocker.patch.object(service, "attach_fill_link_response_signing_request", return_value=None)
    mocker.patch.object(
        service,
        "get_signing_request_for_user",
        return_value=SimpleNamespace(id="req-old", status="invalidated"),
    )
    mocker.patch.object(service, "mark_signing_request_sent", return_value=SimpleNamespace(id="req-new", status="sent", source_pdf_bucket_path="gs://bucket/source-new.pdf"))
    mocker.patch.object(service, "upload_signing_pdf_bytes", return_value="gs://bucket/source-new.pdf")
    mocker.patch.object(service, "mark_signing_request_invite_delivery", return_value=SimpleNamespace(id="req-new", status="sent"))

    response_snapshot = {
        "filename": "template-one-response.pdf",
        "fields": [
            {
                "name": "signature",
                "type": "signature",
                "page": 1,
                "x": 1,
                "y": 2,
                "width": 100,
                "height": 20,
                "rect": [1, 2, 101, 22],
            },
        ],
    }
    link = SimpleNamespace(
        id="link-1",
        user_id="user-1",
        template_id="tpl-1",
        template_name="Template One",
        title="Template One Intake",
        respondent_pdf_snapshot=None,
    )
    response = SimpleNamespace(
        id="resp-1",
        respondent_label="Justin QA",
        answers={"full_name": "Justin QA", "email": "justin@example.com"},
        respondent_pdf_snapshot=response_snapshot,
        signing_request_id="req-old",
    )

    result = service.ensure_fill_link_response_signing_request(
        link=link,
        response=response,
        source_pdf_bytes=b"%PDF-1.4\nstub\n",
        signing_config={
            "signature_mode": "business",
            "document_category": "ordinary_business_form",
            "manual_fallback_enabled": True,
            "signer_name_question_key": "full_name",
            "signer_email_question_key": "email",
        },
    )

    assert result.id == "req-new"
    create_mock.assert_called_once()
    attach_mock.assert_called_once_with("resp-1", "link-1", "user-1", signing_request_id="req-new")
