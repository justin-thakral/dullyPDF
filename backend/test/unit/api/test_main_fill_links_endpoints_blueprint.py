from backend.firebaseDB.fill_link_database import (
    FillLinkRecord,
    FillLinkResponseRecord,
    FillLinkSubmissionResult,
)
from backend.firebaseDB.group_database import TemplateGroupRecord
from backend.firebaseDB.signing_database import SigningRequestRecord
from backend.firebaseDB.template_database import TemplateRecord
from backend.services.fill_links_service import build_fill_link_public_token


def _patch_auth(mocker, app_main, user) -> None:
    mocker.patch.object(app_main, "_verify_token", return_value={"uid": user.app_user_id})
    mocker.patch.object(app_main, "ensure_user", return_value=user)


def _template_record() -> TemplateRecord:
    return TemplateRecord(
        id="tpl-1",
        pdf_bucket_path="gs://forms/template.pdf",
        template_bucket_path="gs://templates/template.pdf",
        metadata={"name": "Template One"},
        created_at="2024-01-01T00:00:00+00:00",
        updated_at="2024-01-01T00:00:00+00:00",
        name="Template One",
    )


def _fill_link_record(
    *,
    status: str = "active",
    response_count: int = 0,
    max_responses: int = 5,
    public_token: str | None = None,
    respondent_pdf_download_enabled: bool = False,
    respondent_pdf_snapshot: dict | None = None,
    require_all_fields: bool = False,
    questions: list[dict] | None = None,
    web_form_config: dict | None = None,
    signing_config: dict | None = None,
) -> FillLinkRecord:
    resolved_questions = questions or [{"key": "full_name", "label": "Full Name", "type": "text"}]
    return FillLinkRecord(
        id="link-1",
        user_id="user_base",
        scope_type="template",
        template_id="tpl-1",
        template_name="Template One",
        group_id=None,
        group_name=None,
        template_ids=["tpl-1"],
        title="Template One Intake",
        public_token=public_token,
        status=status,
        closed_reason=None if status == "active" else "owner_closed",
        max_responses=max_responses,
        response_count=response_count,
        questions=resolved_questions,
        require_all_fields=require_all_fields,
        web_form_config=web_form_config or {"schemaVersion": 2, "questions": resolved_questions},
        signing_config=signing_config,
        created_at="2024-01-01T00:00:00+00:00",
        updated_at="2024-01-01T00:00:00+00:00",
        published_at="2024-01-01T00:00:00+00:00",
        closed_at=None if status == "active" else "2024-01-02T00:00:00+00:00",
        respondent_pdf_download_enabled=respondent_pdf_download_enabled,
        respondent_pdf_snapshot=respondent_pdf_snapshot,
    )


def _response_record(
    *,
    respondent_pdf_snapshot: dict | None = None,
    signing_request_id: str | None = None,
) -> FillLinkResponseRecord:
    return FillLinkResponseRecord(
        id="resp-1",
        link_id="link-1",
        user_id="user_base",
        scope_type="template",
        template_id="tpl-1",
        group_id=None,
        attempt_id=None,
        respondent_label="Ada Lovelace",
        respondent_secondary_label=None,
        answers={"full_name": "Ada Lovelace"},
        search_text="ada lovelace",
        submitted_at="2024-02-01T00:00:00+00:00",
        respondent_pdf_snapshot=respondent_pdf_snapshot,
        signing_request_id=signing_request_id,
    )


def _group_record() -> TemplateGroupRecord:
    return TemplateGroupRecord(
        id="group-1",
        user_id="user_base",
        name="Admissions Packet",
        normalized_name="admissions packet",
        template_ids=["tpl-1", "tpl-2"],
        created_at="2024-01-01T00:00:00+00:00",
        updated_at="2024-01-01T00:00:00+00:00",
    )


def _group_fill_link_record() -> FillLinkRecord:
    questions = [{"key": "full_name", "label": "Full Name", "type": "text"}]
    return FillLinkRecord(
        id="group-link-1",
        user_id="user_base",
        scope_type="group",
        template_id=None,
        template_name=None,
        group_id="group-1",
        group_name="Admissions Packet",
        template_ids=["tpl-1", "tpl-2"],
        title="Admissions Packet",
        public_token=None,
        status="active",
        closed_reason=None,
        max_responses=25,
        response_count=0,
        questions=questions,
        require_all_fields=True,
        web_form_config={"schemaVersion": 2, "questions": questions},
        signing_config=None,
        created_at="2024-01-01T00:00:00+00:00",
        updated_at="2024-01-01T00:00:00+00:00",
        published_at="2024-01-01T00:00:00+00:00",
        closed_at=None,
    )


def _signing_request_record(
    *,
    request_id: str = "sign-1",
    status: str = "completed",
) -> SigningRequestRecord:
    return SigningRequestRecord(
        id=request_id,
        user_id="user_base",
        title="Template One Intake",
        mode="sign",
        signature_mode="business",
        source_type="fill_link_response",
        source_id="resp-1",
        source_link_id="link-1",
        source_record_label="Ada Lovelace",
        source_document_name="Template One",
        source_template_id="tpl-1",
        source_template_name="Template One",
        source_pdf_sha256="abc123",
        source_pdf_bucket_path="gs://bucket/source.pdf",
        source_version="workspace:tpl-1:v1",
        document_category="client_intake_form",
        manual_fallback_enabled=True,
        signer_name="Ada Lovelace",
        signer_email="ada@example.com",
        invite_delivery_status="sent",
        invite_last_attempt_at="2024-02-01T00:00:00+00:00",
        invite_sent_at="2024-02-01T00:00:00+00:00",
        invite_delivery_error=None,
        status=status,
        anchors=[],
        disclosure_version="v1",
        created_at="2024-02-01T00:00:00+00:00",
        updated_at="2024-02-01T00:00:00+00:00",
        owner_review_confirmed_at="2024-02-01T00:00:00+00:00",
        sent_at="2024-02-01T00:00:00+00:00",
        opened_at="2024-02-01T00:05:00+00:00",
        reviewed_at="2024-02-01T00:06:00+00:00",
        consented_at="2024-02-01T00:07:00+00:00",
        signature_adopted_at="2024-02-01T00:08:00+00:00",
        signature_adopted_name="Ada Lovelace",
        manual_fallback_requested_at=None,
        manual_fallback_note=None,
        completed_at="2024-02-01T00:10:00+00:00" if status == "completed" else None,
        completed_session_id="sess-1" if status == "completed" else None,
        completed_ip_address="198.51.100.10" if status == "completed" else None,
        completed_user_agent="Mozilla/5.0" if status == "completed" else None,
        signed_pdf_bucket_path="gs://bucket/signed.pdf" if status == "completed" else None,
        signed_pdf_sha256="def456" if status == "completed" else None,
        audit_manifest_bucket_path="gs://bucket/audit.json" if status == "completed" else None,
        audit_manifest_sha256="ghi789" if status == "completed" else None,
        audit_receipt_bucket_path="gs://bucket/audit-receipt.pdf" if status == "completed" else None,
        audit_receipt_sha256="jkl012" if status == "completed" else None,
        audit_signature_method="kms" if status == "completed" else None,
        audit_signature_algorithm="RSASSA_PSS_SHA_256" if status == "completed" else None,
        audit_kms_key_resource_name="projects/test/locations/global/keyRings/test/cryptoKeys/test" if status == "completed" else None,
        audit_kms_key_version_name="projects/test/locations/global/keyRings/test/cryptoKeys/test/cryptoKeyVersions/1" if status == "completed" else None,
        artifacts_generated_at="2024-02-01T00:10:05+00:00" if status == "completed" else None,
        retention_until=None,
        invalidated_at=None,
        invalidation_reason=None,
    )


def test_fill_links_list_create_and_response_endpoints(client, app_main, base_user, mocker, auth_headers) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "list_fill_links", return_value=[_fill_link_record()])
    response = client.get("/api/fill-links", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["links"][0]["publicPath"] == f"/respond/{build_fill_link_public_token('link-1')}"

    mocker.patch.object(app_main, "get_template", return_value=_template_record())
    mocker.patch.object(app_main, "get_fill_link_for_template", return_value=None)
    mocker.patch.object(app_main, "_resolve_fill_links_active_limit", return_value=1)
    mocker.patch.object(app_main, "_resolve_fill_link_response_limit", return_value=5)
    sync_mock = mocker.patch.object(app_main, "sync_user_downgrade_retention", return_value=None)
    mocker.patch.object(app_main, "list_fill_links", return_value=[])
    mocker.patch.object(
        app_main,
        "_build_template_web_form_schema",
        return_value=(
            {"schemaVersion": 2, "questions": [{"key": "full_name", "label": "Full Name", "type": "text"}]},
            [{"key": "full_name", "label": "Full Name", "type": "text"}],
        ),
    )
    snapshot_mock = mocker.patch.object(
        app_main,
        "build_template_fill_link_download_snapshot",
        return_value={
            "version": 1,
            "sourcePdfPath": "gs://forms/template.pdf",
            "fields": [{"name": "full_name", "type": "text", "page": 1}],
            "checkboxRules": [],
            "radioGroups": [],
            "textTransformRules": [],
            "filename": "template-one-response.pdf",
        },
    )
    mocker.patch.object(
        app_main,
        "create_or_update_fill_link",
        return_value=_fill_link_record(require_all_fields=True),
    )

    create_response = client.post(
        "/api/fill-links",
        json={
            "templateId": "tpl-1",
            "title": "Template One Intake",
            "templateName": "Template One",
            "requireAllFields": True,
            "respondentPdfDownloadEnabled": True,
            "fields": [{"name": "full_name", "type": "text", "page": 1, "rect": {"x": 1, "y": 2, "width": 3, "height": 4}}],
            "checkboxRules": [],
        },
        headers=auth_headers,
    )
    assert create_response.status_code == 200
    assert create_response.json()["link"]["status"] == "active"
    assert create_response.json()["link"]["requireAllFields"] is True
    sync_mock.assert_called_once_with(base_user.app_user_id, create_if_missing=True)
    snapshot_mock.assert_called_once()
    app_main.create_or_update_fill_link.assert_called_once_with(
        base_user.app_user_id,
        scope_type="template",
        template_id="tpl-1",
        template_name="Template One",
        group_id=None,
        group_name=None,
        template_ids=["tpl-1"],
        title="Template One Intake",
        questions=[{"key": "full_name", "label": "Full Name", "type": "text"}],
        require_all_fields=True,
        web_form_config={"schemaVersion": 2, "questions": [{"key": "full_name", "label": "Full Name", "type": "text"}]},
        signing_config=None,
        max_responses=5,
        respondent_pdf_download_enabled=True,
        respondent_pdf_snapshot={
            "version": 1,
            "sourcePdfPath": "gs://forms/template.pdf",
            "fields": [{"name": "full_name", "type": "text", "page": 1}],
            "checkboxRules": [],
            "radioGroups": [],
            "textTransformRules": [],
            "filename": "template-one-response.pdf",
        },
        status="active",
        closed_reason=None,
        active_limit=1,
    )

    mocker.patch.object(app_main, "get_fill_link", return_value=_fill_link_record())
    mocker.patch.object(app_main, "list_fill_link_responses", return_value=[_response_record()])
    responses_response = client.get("/api/fill-links/link-1/responses", headers=auth_headers)
    assert responses_response.status_code == 200
    assert responses_response.json()["responses"][0]["respondentLabel"] == "Ada Lovelace"

    mocker.patch.object(app_main, "get_fill_link_response", return_value=_response_record())
    detail_response = client.get("/api/fill-links/link-1/responses/resp-1", headers=auth_headers)
    assert detail_response.status_code == 200
    assert detail_response.json()["response"]["answers"]["full_name"] == "Ada Lovelace"


def test_fill_links_update_endpoint_uses_link_id_and_serializes_canonical_signed_public_token(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "get_fill_link", return_value=_fill_link_record(status="closed", public_token="token-old"))
    mocker.patch.object(app_main, "get_template", return_value=_template_record())
    mocker.patch.object(app_main, "sync_user_downgrade_retention", return_value=None)
    mocker.patch.object(
        app_main,
        "_build_template_web_form_schema",
        return_value=(
            {"schemaVersion": 2, "questions": [{"key": "full_name", "label": "Full Name", "type": "text"}]},
            [{"key": "full_name", "label": "Full Name", "type": "text"}],
        ),
    )
    snapshot_mock = mocker.patch.object(
        app_main,
        "build_template_fill_link_download_snapshot",
        return_value={
            "version": 1,
            "sourcePdfPath": "gs://forms/template.pdf",
            "fields": [{"name": "full_name", "type": "text", "page": 1}],
            "checkboxRules": [],
            "radioGroups": [],
            "textTransformRules": [],
            "filename": "template-one-response.pdf",
        },
    )
    mocker.patch.object(app_main, "_resolve_fill_links_active_limit", return_value=3)
    mocker.patch.object(app_main, "_resolve_fill_link_response_limit", return_value=25)
    update_mock = mocker.patch.object(
        app_main,
        "update_fill_link",
        return_value=_fill_link_record(
            status="active",
            max_responses=25,
            public_token="token-new",
            respondent_pdf_download_enabled=True,
            respondent_pdf_snapshot={
                "version": 1,
                "sourcePdfPath": "gs://forms/template.pdf",
                "fields": [{"name": "full_name", "type": "text", "page": 1}],
                "checkboxRules": [],
                "radioGroups": [],
                "textTransformRules": [],
                "filename": "template-one-response.pdf",
            },
        ),
    )
    create_or_update_mock = mocker.patch.object(app_main, "create_or_update_fill_link")

    response = client.patch(
        "/api/fill-links/link-1",
        json={
            "status": "active",
            "requireAllFields": True,
            "respondentPdfDownloadEnabled": True,
            "fields": [{"name": "full_name", "type": "text", "page": 1, "rect": {"x": 1, "y": 2, "width": 3, "height": 4}}],
            "checkboxRules": [],
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["link"]["publicPath"] == f"/respond/{build_fill_link_public_token('link-1')}"
    assert response.json()["link"]["respondentPdfDownloadEnabled"] is True
    snapshot_mock.assert_called_once()
    update_mock.assert_called_once_with(
        "link-1",
        base_user.app_user_id,
        title=None,
        questions=[{"key": "full_name", "label": "Full Name", "type": "text"}],
        group_name=None,
        template_ids=None,
        require_all_fields=True,
        web_form_config={"schemaVersion": 2, "questions": [{"key": "full_name", "label": "Full Name", "type": "text"}]},
        signing_config=None,
        respondent_pdf_download_enabled=True,
        respondent_pdf_snapshot={
            "version": 1,
            "sourcePdfPath": "gs://forms/template.pdf",
            "fields": [{"name": "full_name", "type": "text", "page": 1}],
            "checkboxRules": [],
            "radioGroups": [],
            "textTransformRules": [],
            "filename": "template-one-response.pdf",
        },
        status="active",
        closed_reason=None,
        max_responses=25,
        active_limit=3,
    )
    create_or_update_mock.assert_not_called()


def test_fill_links_create_accepts_template_post_submit_signing_config(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "get_template", return_value=_template_record())
    mocker.patch.object(app_main, "get_fill_link_for_template", return_value=None)
    mocker.patch.object(app_main, "_resolve_fill_links_active_limit", return_value=1)
    mocker.patch.object(app_main, "_resolve_fill_link_response_limit", return_value=5)
    mocker.patch.object(app_main, "sync_user_downgrade_retention", return_value=None)
    mocker.patch.object(app_main, "list_fill_links", return_value=[])
    mocker.patch.object(
        app_main,
        "_build_template_web_form_schema",
        return_value=(
            {
                "schemaVersion": 2,
                "questions": [
                    {"key": "full_name", "label": "Full Name", "type": "text", "visible": True},
                    {"key": "email", "label": "Email", "type": "email", "visible": True},
                ],
            },
            [
                {"key": "full_name", "label": "Full Name", "type": "text", "visible": True},
                {"key": "email", "label": "Email", "type": "email", "visible": True},
            ],
        ),
    )
    mocker.patch.object(
        app_main,
        "build_template_fill_link_download_snapshot",
        return_value={
            "version": 1,
            "sourcePdfPath": "gs://forms/template.pdf",
            "fields": [
                {"name": "Signer", "type": "signature", "page": 1, "rect": {"x": 1, "y": 2, "width": 3, "height": 1}},
                {"name": "full_name", "type": "text", "page": 1, "rect": {"x": 1, "y": 3, "width": 3, "height": 1}},
            ],
            "checkboxRules": [],
            "radioGroups": [],
            "textTransformRules": [],
            "filename": "template-one-response.pdf",
        },
    )
    create_mock = mocker.patch.object(
        app_main,
        "create_or_update_fill_link",
        return_value=_fill_link_record(
            signing_config={
                "enabled": True,
                "signature_mode": "consumer",
                "document_category": "client_intake_form",
                "document_category_label": "Client intake form",
                "manual_fallback_enabled": True,
                "signer_name_question_key": "full_name",
                "signer_email_question_key": "email",
            },
        ),
    )

    response = client.post(
        "/api/fill-links",
        json={
            "templateId": "tpl-1",
            "templateName": "Template One",
            "title": "Template One Intake",
            "fields": [
                {"name": "Signer", "type": "signature", "page": 1, "rect": {"x": 1, "y": 2, "width": 3, "height": 1}},
                {"name": "full_name", "type": "text", "page": 1, "rect": {"x": 1, "y": 3, "width": 3, "height": 1}},
            ],
            "webFormConfig": {
                "schemaVersion": 2,
                "questions": [
                    {"key": "full_name", "label": "Full Name", "type": "text", "visible": True},
                    {"key": "email", "label": "Email", "type": "email", "visible": True},
                ],
            },
            "signingConfig": {
                "enabled": True,
                "signatureMode": "consumer",
                "documentCategory": "client_intake_form",
                "manualFallbackEnabled": True,
                "signerNameQuestionKey": "full_name",
                "signerEmailQuestionKey": "email",
            },
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["link"]["signingConfig"]["enabled"] is True
    assert response.json()["link"]["signingConfig"]["signatureMode"] == "consumer"
    create_mock.assert_called_once()
    assert app_main._build_template_web_form_schema.call_args.kwargs["exclude_signing_questions"] is True
    assert create_mock.call_args.kwargs["signing_config"] == {
        "enabled": True,
        "signature_mode": "consumer",
        "document_category": "client_intake_form",
        "document_category_label": "Client intake form",
        "manual_fallback_enabled": True,
        "signer_name_question_key": "full_name",
        "signer_email_question_key": "email",
    }
    assert create_mock.call_args.kwargs["respondent_pdf_snapshot"]["fields"][0]["type"] == "signature"


def test_fill_links_create_forces_respondent_downloads_flat_when_post_submit_signing_is_enabled(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "get_template", return_value=_template_record())
    mocker.patch.object(app_main, "get_fill_link_for_template", return_value=None)
    mocker.patch.object(app_main, "_resolve_fill_links_active_limit", return_value=1)
    mocker.patch.object(app_main, "_resolve_fill_link_response_limit", return_value=5)
    mocker.patch.object(app_main, "sync_user_downgrade_retention", return_value=None)
    mocker.patch.object(app_main, "list_fill_links", return_value=[])
    mocker.patch.object(
        app_main,
        "_build_template_web_form_schema",
        return_value=(
            {
                "schemaVersion": 2,
                "questions": [
                    {"key": "full_name", "label": "Full Name", "type": "text", "visible": True},
                    {"key": "email", "label": "Email", "type": "email", "visible": True},
                ],
            },
            [
                {"key": "full_name", "label": "Full Name", "type": "text", "visible": True},
                {"key": "email", "label": "Email", "type": "email", "visible": True},
            ],
        ),
    )
    snapshot_mock = mocker.patch.object(
        app_main,
        "build_template_fill_link_download_snapshot",
        return_value={
            "version": 1,
            "sourcePdfPath": "gs://forms/template.pdf",
            "fields": [
                {"name": "Signer", "type": "signature", "page": 1, "rect": {"x": 1, "y": 2, "width": 3, "height": 1}},
                {"name": "full_name", "type": "text", "page": 1},
            ],
            "checkboxRules": [],
            "radioGroups": [],
            "textTransformRules": [],
            "filename": "template-one-response.pdf",
            "downloadMode": "flat",
        },
    )
    create_mock = mocker.patch.object(
        app_main,
        "create_or_update_fill_link",
        return_value=_fill_link_record(
            respondent_pdf_download_enabled=True,
            respondent_pdf_snapshot={
                "version": 1,
                "sourcePdfPath": "gs://forms/template.pdf",
                "fields": [
                    {"name": "Signer", "type": "signature", "page": 1, "rect": {"x": 1, "y": 2, "width": 3, "height": 1}},
                    {"name": "full_name", "type": "text", "page": 1},
                ],
                "downloadMode": "flat",
            },
            signing_config={
                "enabled": True,
                "signature_mode": "business",
                "document_category": "ordinary_business_form",
                "document_category_label": "Ordinary business form",
                "manual_fallback_enabled": True,
                "signer_name_question_key": "full_name",
                "signer_email_question_key": "email",
            },
        ),
    )

    response = client.post(
        "/api/fill-links",
        json={
            "templateId": "tpl-1",
            "templateName": "Template One",
            "title": "Template One Intake",
            "respondentPdfDownloadEnabled": True,
            "respondentPdfEditableEnabled": True,
            "fields": [
                {"name": "Signer", "type": "signature", "page": 1, "rect": {"x": 1, "y": 2, "width": 3, "height": 1}},
                {"name": "full_name", "type": "text", "page": 1, "rect": {"x": 1, "y": 3, "width": 3, "height": 4}},
            ],
            "signingConfig": {
                "enabled": True,
                "signatureMode": "business",
                "documentCategory": "ordinary_business_form",
                "manualFallbackEnabled": True,
                "signerNameQuestionKey": "full_name",
                "signerEmailQuestionKey": "email",
            },
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["link"]["respondentPdfEditableEnabled"] is False
    snapshot_mock.assert_called_once_with(template=mocker.ANY, fields=mocker.ANY, export_mode="flat")
    assert create_mock.call_args.kwargs["respondent_pdf_snapshot"]["downloadMode"] == "flat"


def test_fill_links_owner_responses_include_linked_signing_summary_for_signed_responses(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "get_fill_link", return_value=_fill_link_record())
    mocker.patch.object(
        app_main,
        "list_fill_link_responses",
        return_value=[_response_record(signing_request_id="sign-1")],
    )
    mocker.patch.object(app_main, "list_signing_requests", return_value=[_signing_request_record()])

    response = client.get("/api/fill-links/link-1/responses", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()["responses"][0]
    assert payload["signingRequestId"] == "sign-1"
    assert payload["signingStatus"] == "completed"
    assert payload["linkedSigning"]["requestId"] == "sign-1"
    assert payload["linkedSigning"]["artifacts"]["signedPdf"]["available"] is True
    assert payload["linkedSigning"]["artifacts"]["signedPdf"]["downloadPath"] == "/api/signing/requests/sign-1/artifacts/signed_pdf"
    assert payload["linkedSigning"]["artifacts"]["auditReceipt"]["downloadPath"] == "/api/signing/requests/sign-1/artifacts/audit_receipt"


def test_fill_links_create_enforces_active_limit(client, app_main, base_user, mocker, auth_headers) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "get_template", return_value=_template_record())
    mocker.patch.object(app_main, "get_fill_link_for_template", return_value=None)
    mocker.patch.object(app_main, "sync_user_downgrade_retention", return_value=None)
    mocker.patch.object(app_main, "list_fill_links", return_value=[_fill_link_record()])
    mocker.patch.object(app_main, "_resolve_fill_links_active_limit", return_value=1)
    mocker.patch.object(
        app_main,
        "build_fill_link_questions",
        return_value=[{"key": "full_name", "label": "Full Name", "type": "text"}],
    )

    response = client.post(
        "/api/fill-links",
        json={
            "templateId": "tpl-1",
            "fields": [{"name": "full_name", "type": "text", "page": 1, "rect": {"x": 1, "y": 2, "width": 3, "height": 4}}],
        },
        headers=auth_headers,
    )

    assert response.status_code == 403
    assert "Fill By Link limit reached" in response.text


def test_fill_links_create_maps_storage_active_limit_conflict_to_403(client, app_main, base_user, mocker, auth_headers) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "get_template", return_value=_template_record())
    mocker.patch.object(app_main, "get_fill_link_for_template", return_value=None)
    mocker.patch.object(app_main, "sync_user_downgrade_retention", return_value=None)
    mocker.patch.object(app_main, "list_fill_links", return_value=[])
    mocker.patch.object(app_main, "_resolve_fill_links_active_limit", return_value=1)
    mocker.patch.object(app_main, "_resolve_fill_link_response_limit", return_value=5)
    mocker.patch.object(
        app_main,
        "build_fill_link_questions",
        return_value=[{"key": "full_name", "label": "Full Name", "type": "text"}],
    )
    mocker.patch.object(
        app_main,
        "create_or_update_fill_link",
        side_effect=app_main.FillLinkActiveLimitExceededError("Fill By Link limit reached (1 active links max for your tier)."),
    )

    response = client.post(
        "/api/fill-links",
        json={
            "templateId": "tpl-1",
            "fields": [{"name": "full_name", "type": "text", "page": 1, "rect": {"x": 1, "y": 2, "width": 3, "height": 4}}],
        },
        headers=auth_headers,
    )

    assert response.status_code == 403
    assert "Fill By Link limit reached" in response.text


def test_fill_links_create_blocks_pending_delete_template_after_downgrade(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "get_template", return_value=_template_record())
    mocker.patch.object(app_main, "get_fill_link_for_template", return_value=None)
    sync_mock = mocker.patch.object(
        app_main,
        "sync_user_downgrade_retention",
        return_value={"pendingDeleteTemplateIds": ["tpl-1"]},
    )
    mocker.patch.object(
        app_main,
        "build_fill_link_questions",
        return_value=[{"key": "full_name", "label": "Full Name", "type": "text"}],
    )

    response = client.post(
        "/api/fill-links",
        json={
            "templateId": "tpl-1",
            "fields": [{"name": "full_name", "type": "text", "page": 1, "rect": {"x": 1, "y": 2, "width": 3, "height": 4}}],
        },
        headers=auth_headers,
    )

    assert response.status_code == 409
    assert "queued for deletion" in response.text.lower()
    sync_mock.assert_called_once_with(base_user.app_user_id, create_if_missing=True)


def test_fill_links_create_group_link_merges_group_templates(client, app_main, base_user, mocker, auth_headers) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "get_group", return_value=_group_record())
    mocker.patch.object(app_main, "sync_user_downgrade_retention", return_value=None)
    mocker.patch.object(
        app_main,
        "get_template",
        side_effect=[
            _template_record(),
            TemplateRecord(
                id="tpl-2",
                pdf_bucket_path="gs://forms/template-2.pdf",
                template_bucket_path="gs://templates/template-2.pdf",
                metadata={"name": "Template Two"},
                created_at="2024-01-02T00:00:00+00:00",
                updated_at="2024-01-02T00:00:00+00:00",
                name="Template Two",
            ),
        ],
    )
    mocker.patch.object(app_main, "get_fill_link_for_group", return_value=None)
    mocker.patch.object(app_main, "_resolve_fill_links_active_limit", return_value=3)
    mocker.patch.object(app_main, "_resolve_fill_link_response_limit", return_value=25)
    mocker.patch.object(app_main, "list_fill_links", return_value=[])
    build_questions_mock = mocker.patch.object(
        app_main,
        "build_group_fill_link_questions",
        return_value=[{"key": "full_name", "label": "Full Name", "type": "text"}],
    )
    create_mock = mocker.patch.object(app_main, "create_or_update_fill_link", return_value=_group_fill_link_record())

    response = client.post(
        "/api/fill-links",
        json={
            "scopeType": "group",
            "groupId": "group-1",
            "groupName": "Admissions Packet",
            "requireAllFields": True,
            "respondentPdfDownloadEnabled": True,
            "fields": [],
            "groupTemplates": [
                {
                    "templateId": "tpl-1",
                    "templateName": "Template One",
                    "fields": [{"name": "full_name", "type": "text", "page": 1}],
                    "checkboxRules": [],
                },
                {
                    "templateId": "tpl-2",
                    "templateName": "Template Two",
                    "fields": [{"name": "dob", "type": "date", "page": 1}],
                    "checkboxRules": [],
                },
            ],
        },
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "template fill by link" in response.text.lower()
    build_questions_mock.assert_not_called()
    create_mock.assert_not_called()


def test_fill_links_update_blocks_reactivate_when_template_is_queued_for_deletion(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "get_fill_link", return_value=_fill_link_record(status="closed"))
    mocker.patch.object(app_main, "get_template", return_value=_template_record())
    mocker.patch.object(
        app_main,
        "build_fill_link_questions",
        return_value=[{"key": "full_name", "label": "Full Name", "type": "text"}],
    )
    mocker.patch.object(
        app_main,
        "sync_user_downgrade_retention",
        return_value={"pendingDeleteTemplateIds": ["tpl-1"]},
    )

    response = client.patch(
        "/api/fill-links/link-1",
        json={
            "status": "active",
            "fields": [{"name": "full_name", "type": "text", "page": 1, "rect": {"x": 1, "y": 2, "width": 3, "height": 4}}],
        },
        headers=auth_headers,
    )

    assert response.status_code == 409
    assert "queued for deletion" in response.text.lower()


def test_fill_links_update_blocks_reactivate_when_backing_template_was_deleted(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "get_fill_link", return_value=_fill_link_record(status="closed"))
    mocker.patch.object(
        app_main,
        "build_fill_link_questions",
        return_value=[{"key": "full_name", "label": "Full Name", "type": "text"}],
    )
    mocker.patch.object(app_main, "get_template", return_value=None)
    update_mock = mocker.patch.object(app_main, "update_fill_link", return_value=None)

    response = client.patch(
        "/api/fill-links/link-1",
        json={
            "status": "active",
            "fields": [{"name": "full_name", "type": "text", "page": 1, "rect": {"x": 1, "y": 2, "width": 3, "height": 4}}],
        },
        headers=auth_headers,
    )

    assert response.status_code == 404
    assert "saved form not found" in response.text.lower()
    update_mock.assert_not_called()


def test_fill_links_public_get_and_submit(client, app_main, mocker) -> None:
    record = _fill_link_record(
        response_count=4,
        max_responses=5,
        respondent_pdf_download_enabled=True,
        respondent_pdf_snapshot={
            "version": 1,
            "sourcePdfPath": "gs://forms/template.pdf",
            "filename": "template-one-response.pdf",
            "fields": [{"name": "full_name", "type": "text", "page": 1}],
        },
    )
    mocker.patch.object(app_main, "get_fill_link_by_public_token", return_value=record)
    mocker.patch.object(app_main, "get_template", return_value=_template_record())
    mocker.patch.object(app_main, "_resolve_fill_link_view_rate_limits", return_value=(60, 60, 0))
    mocker.patch.object(app_main, "_resolve_client_ip", return_value="198.51.100.10")
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    response = client.get("/api/fill-links/public/token-1")
    assert response.status_code == 200
    assert response.json()["link"]["requireAllFields"] is False
    assert response.json()["link"]["respondentPdfDownloadEnabled"] is True

    mocker.patch.object(app_main, "_resolve_fill_link_submit_rate_limits", return_value=(300, 10, 0))
    mocker.patch.object(app_main, "_resolve_client_ip", return_value="198.51.100.10")
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    verify_mock = mocker.patch.object(app_main, "_verify_recaptcha_token", return_value=None)
    mocker.patch.object(app_main, "_resolve_fill_link_recaptcha_action", return_value="fill_link_submit")
    mocker.patch.object(app_main, "_recaptcha_required_for_fill_link", return_value=False)
    mocker.patch.object(app_main, "coerce_fill_link_answers", return_value={"full_name": "Ada Lovelace"})
    mocker.patch.object(app_main, "derive_fill_link_respondent_label", return_value=("Ada Lovelace", None))
    mocker.patch.object(app_main, "build_fill_link_search_text", return_value="ada lovelace")
    mocker.patch.object(
        app_main,
        "submit_fill_link_response",
        return_value=FillLinkSubmissionResult(
            status="accepted",
            link=_fill_link_record(
                status="closed",
                response_count=5,
                max_responses=5,
                respondent_pdf_download_enabled=True,
                respondent_pdf_snapshot={
                    "version": 1,
                    "sourcePdfPath": "gs://forms/template.pdf",
                    "filename": "template-one-response.pdf",
                    "fields": [{"name": "full_name", "type": "text", "page": 1}],
                },
            ),
            response=_response_record(),
        ),
    )

    submit_response = client.post(
        "/api/fill-links/public/token-1/submit",
        json={"answers": {"full_name": "Ada Lovelace"}, "attemptId": "attempt-public-1"},
    )

    assert submit_response.status_code == 200
    assert submit_response.json()["respondentLabel"] == "Ada Lovelace"
    assert submit_response.json()["responseDownloadAvailable"] is True
    assert submit_response.json()["responseDownloadPath"] == "/api/fill-links/public/token-1/responses/resp-1/download"
    assert submit_response.json()["download"]["downloadPath"] == "/api/fill-links/public/token-1/responses/resp-1/download"
    assert verify_mock.call_args.kwargs["required"] is False
    app_main.submit_fill_link_response.assert_called_once_with(
        "token-1",
        answers={"full_name": "Ada Lovelace"},
        attempt_id="attempt-public-1",
        respondent_label="Ada Lovelace",
        respondent_secondary_label=None,
        search_text="ada lovelace",
    )


def test_fill_links_public_submit_returns_signing_handoff_when_enabled(client, app_main, mocker, tmp_path) -> None:
    record = _fill_link_record(
        questions=[
            {"key": "full_name", "label": "Full Name", "type": "text", "visible": True},
            {"key": "email", "label": "Email", "type": "email", "visible": True},
        ],
        signing_config={
            "enabled": True,
            "signature_mode": "consumer",
            "document_category": "client_intake_form",
            "document_category_label": "Client intake form",
            "manual_fallback_enabled": True,
            "signer_name_question_key": "full_name",
            "signer_email_question_key": "email",
        },
        respondent_pdf_snapshot={
            "version": 1,
            "sourcePdfPath": "gs://forms/template.pdf",
            "filename": "template-one-response.pdf",
            "fields": [
                {"name": "Signer", "type": "signature", "page": 1, "rect": {"x": 1, "y": 2, "width": 3, "height": 1}},
                {"name": "full_name", "type": "text", "page": 1, "rect": {"x": 1, "y": 3, "width": 3, "height": 1}},
            ],
        },
    )
    response_record = FillLinkResponseRecord(
        id="resp-1",
        link_id="link-1",
        user_id="user_base",
        scope_type="template",
        template_id="tpl-1",
        group_id=None,
        attempt_id=None,
        respondent_label="Ada Lovelace",
        respondent_secondary_label="ada@example.com",
        answers={"full_name": "Ada Lovelace", "email": "ada@example.com"},
        search_text="ada lovelace ada@example.com",
        submitted_at="2024-02-01T00:00:00+00:00",
        respondent_pdf_snapshot=record.respondent_pdf_snapshot,
    )
    mocker.patch.object(app_main, "get_fill_link_by_public_token", return_value=record)
    mocker.patch.object(app_main, "get_template", return_value=_template_record())
    mocker.patch.object(app_main, "_resolve_fill_link_submit_rate_limits", return_value=(300, 10, 0))
    mocker.patch.object(app_main, "_resolve_client_ip", return_value="198.51.100.10")
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "_verify_recaptcha_token", return_value=None)
    mocker.patch.object(app_main, "_resolve_fill_link_recaptcha_action", return_value="fill_link_submit")
    mocker.patch.object(app_main, "_recaptcha_required_for_fill_link", return_value=False)
    mocker.patch.object(
        app_main,
        "coerce_fill_link_answers",
        return_value={"full_name": "Ada Lovelace", "email": "ada@example.com"},
    )
    mocker.patch.object(app_main, "derive_fill_link_respondent_label", return_value=("Ada Lovelace", "ada@example.com"))
    mocker.patch.object(app_main, "build_fill_link_search_text", return_value="ada lovelace ada@example.com")
    mocker.patch.object(
        app_main,
        "submit_fill_link_response",
        return_value=FillLinkSubmissionResult(status="accepted", link=record, response=response_record),
    )
    output_path = tmp_path / "submitted-fill-link-signing.pdf"
    output_path.write_bytes(b"%PDF-1.4\n%stub\n")
    materialize_mock = mocker.patch.object(
        app_main,
        "materialize_fill_link_response_download",
        return_value=(output_path, ["tmp-path"], "template-one-response.pdf"),
    )
    ensure_signing_mock = mocker.patch.object(
        app_main,
        "ensure_fill_link_response_signing_request",
        return_value=mocker.Mock(id="sign-1", status="sent"),
    )
    build_public_path_mock = mocker.patch.object(app_main, "build_signing_public_path", return_value="/sign/public-token")
    cleanup_mock = mocker.patch.object(app_main, "cleanup_paths")

    response = client.post(
        "/api/fill-links/public/token-1/submit",
        json={"answers": {"full_name": "Ada Lovelace", "email": "ada@example.com"}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["signing"] == {
        "enabled": True,
        "available": True,
        "requestId": "sign-1",
        "status": "sent",
        "publicPath": "/sign/public-token",
    }
    materialize_mock.assert_called_once_with(
        record.respondent_pdf_snapshot,
        answers={"full_name": "Ada Lovelace", "email": "ada@example.com"},
        export_mode="flat",
    )
    ensure_signing_mock.assert_called_once()
    build_public_path_mock.assert_called_once_with("sign-1")
    cleanup_mock.assert_called_once_with(["tmp-path"])


def test_fill_links_public_submit_rejects_invalid_signer_email_before_storing_response(client, app_main, mocker) -> None:
    record = _fill_link_record(
        questions=[
            {"key": "full_name", "label": "Full Name", "type": "text", "visible": True},
            {"key": "email", "label": "Email", "type": "email", "visible": True},
        ],
        signing_config={
            "enabled": True,
            "signature_mode": "business",
            "document_category": "ordinary_business_form",
            "document_category_label": "Ordinary business form",
            "manual_fallback_enabled": True,
            "signer_name_question_key": "full_name",
            "signer_email_question_key": "email",
        },
    )
    mocker.patch.object(app_main, "get_fill_link_by_public_token", return_value=record)
    mocker.patch.object(app_main, "get_template", return_value=_template_record())
    mocker.patch.object(app_main, "_resolve_fill_link_submit_rate_limits", return_value=(300, 10, 0))
    mocker.patch.object(app_main, "_resolve_client_ip", return_value="198.51.100.10")
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "_verify_recaptcha_token", return_value=None)
    mocker.patch.object(app_main, "_resolve_fill_link_recaptcha_action", return_value="fill_link_submit")
    mocker.patch.object(app_main, "_recaptcha_required_for_fill_link", return_value=False)
    submit_response_mock = mocker.patch.object(app_main, "submit_fill_link_response")
    mocker.patch.object(
        app_main,
        "coerce_fill_link_answers",
        return_value={"full_name": "Ada Lovelace", "email": "not-an-email"},
    )

    response = client.post(
        "/api/fill-links/public/token-1/submit",
        json={"answers": {"full_name": "Ada Lovelace", "email": "not-an-email"}},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Enter a valid signer email address before continuing to the signing step."
    submit_response_mock.assert_not_called()


def test_fill_links_public_get_previews_closed_state_without_mutating_link_when_template_is_deleted(client, app_main, mocker) -> None:
    record = _fill_link_record(status="active")
    mocker.patch.object(app_main, "get_fill_link_by_public_token", return_value=record)
    mocker.patch.object(app_main, "get_template", return_value=None)
    close_mock = mocker.patch.object(app_main, "close_fill_link", return_value=None)
    mocker.patch.object(app_main, "_resolve_fill_link_view_rate_limits", return_value=(60, 60, 0))
    mocker.patch.object(app_main, "_resolve_client_ip", return_value="198.51.100.10")
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)

    response = client.get("/api/fill-links/public/token-1")

    assert response.status_code == 200
    payload = response.json()["link"]
    assert payload["status"] == "closed"
    assert payload["statusMessage"] == "This link is no longer accepting responses."
    assert "questions" not in payload
    close_mock.assert_not_called()


def test_fill_links_public_submit_rejects_group_link_when_workflow_group_was_deleted(client, app_main, mocker) -> None:
    record = _group_fill_link_record()
    closed_record = FillLinkRecord(
        **{
            **record.__dict__,
            "status": "closed",
            "closed_reason": "group_deleted",
            "questions": [],
            "closed_at": "2024-01-03T00:00:00+00:00",
        }
    )
    mocker.patch.object(app_main, "get_fill_link_by_public_token", return_value=record)
    mocker.patch.object(app_main, "get_group", return_value=None)
    close_mock = mocker.patch.object(app_main, "close_fill_link", return_value=closed_record)
    mocker.patch.object(app_main, "_resolve_fill_link_submit_rate_limits", return_value=(300, 10, 0))
    mocker.patch.object(app_main, "_resolve_client_ip", return_value="198.51.100.10")
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "_verify_recaptcha_token", return_value=None)
    mocker.patch.object(app_main, "_resolve_fill_link_recaptcha_action", return_value="fill_link_submit")
    mocker.patch.object(app_main, "_recaptcha_required_for_fill_link", return_value=False)

    response = client.post("/api/fill-links/public/token-1/submit", json={"answers": {"full_name": "Ada Lovelace"}})

    assert response.status_code == 409
    assert "no longer accepting responses" in response.text.lower()
    close_mock.assert_called_once_with("group-link-1", "user_base", closed_reason="group_deleted")


def test_fill_links_public_get_closed_link_hides_schema_and_closed_reason(client, app_main, mocker) -> None:
    record = _fill_link_record(status="closed")
    record = FillLinkRecord(
        **{
            **record.__dict__,
            "closed_reason": "downgrade_retention",
            "require_all_fields": True,
            "questions": [{"key": "ssn", "label": "SSN", "type": "text"}],
        }
    )
    mocker.patch.object(app_main, "get_fill_link_by_public_token", return_value=record)
    mocker.patch.object(app_main, "_resolve_fill_link_view_rate_limits", return_value=(60, 60, 0))
    mocker.patch.object(app_main, "_resolve_client_ip", return_value="198.51.100.10")
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)

    response = client.get("/api/fill-links/public/token-1")

    assert response.status_code == 200
    payload = response.json()["link"]
    assert payload["status"] == "closed"
    assert payload["statusMessage"] == "This link is no longer accepting responses."
    assert "closedReason" not in payload
    assert "requireAllFields" not in payload
    assert "questions" not in payload


def test_fill_links_public_submit_blocks_closed_link(client, app_main, mocker) -> None:
    record = _fill_link_record(status="closed", response_count=5, max_responses=5)
    mocker.patch.object(app_main, "get_fill_link_by_public_token", return_value=record)
    mocker.patch.object(app_main, "_resolve_fill_link_submit_rate_limits", return_value=(300, 10, 0))
    mocker.patch.object(app_main, "_resolve_client_ip", return_value="198.51.100.10")
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "_verify_recaptcha_token", return_value=None)
    mocker.patch.object(app_main, "_resolve_fill_link_recaptcha_action", return_value="fill_link_submit")
    mocker.patch.object(app_main, "_recaptcha_required_for_fill_link", return_value=False)
    mocker.patch.object(app_main, "coerce_fill_link_answers", return_value={"full_name": "Ada Lovelace"})
    mocker.patch.object(app_main, "derive_fill_link_respondent_label", return_value=("Ada Lovelace", None))
    mocker.patch.object(app_main, "build_fill_link_search_text", return_value="ada lovelace")
    mocker.patch.object(
        app_main,
        "submit_fill_link_response",
        return_value=FillLinkSubmissionResult(status="closed", link=record, response=None),
    )

    response = client.post("/api/fill-links/public/token-1/submit", json={"answers": {"full_name": "Ada Lovelace"}})

    assert response.status_code == 409
    assert "no longer accepting responses" in response.text.lower()


def test_fill_links_public_submit_hides_downgrade_closure_reason(client, app_main, mocker) -> None:
    record = _fill_link_record(status="closed", response_count=0, max_responses=5)
    record = FillLinkRecord(
        **{
            **record.__dict__,
            "closed_reason": "downgrade_retention",
        }
    )
    mocker.patch.object(app_main, "get_fill_link_by_public_token", return_value=record)
    mocker.patch.object(app_main, "_resolve_fill_link_submit_rate_limits", return_value=(300, 10, 0))
    mocker.patch.object(app_main, "_resolve_client_ip", return_value="198.51.100.10")
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "_verify_recaptcha_token", return_value=None)
    mocker.patch.object(app_main, "_resolve_fill_link_recaptcha_action", return_value="fill_link_submit")
    mocker.patch.object(app_main, "_recaptcha_required_for_fill_link", return_value=False)
    mocker.patch.object(app_main, "coerce_fill_link_answers", return_value={"full_name": "Ada Lovelace"})
    mocker.patch.object(app_main, "derive_fill_link_respondent_label", return_value=("Ada Lovelace", None))
    mocker.patch.object(app_main, "build_fill_link_search_text", return_value="ada lovelace")
    mocker.patch.object(
        app_main,
        "submit_fill_link_response",
        return_value=FillLinkSubmissionResult(status="closed", link=record, response=None),
    )

    response = client.post("/api/fill-links/public/token-1/submit", json={"answers": {"full_name": "Ada Lovelace"}})

    assert response.status_code == 409
    assert "no longer accepting responses" in response.text.lower()


def test_fill_links_public_submit_requires_all_fields_when_enabled(client, app_main, mocker) -> None:
    record = _fill_link_record()
    record = FillLinkRecord(
        **{
            **record.__dict__,
            "questions": [
                {"key": "full_name", "label": "Full Name", "type": "text"},
                {"key": "dob", "label": "DOB", "type": "date"},
            ],
            "require_all_fields": True,
        }
    )
    mocker.patch.object(app_main, "get_fill_link_by_public_token", return_value=record)
    mocker.patch.object(app_main, "get_template", return_value=_template_record())
    mocker.patch.object(app_main, "_resolve_fill_link_submit_rate_limits", return_value=(300, 10, 0))
    mocker.patch.object(app_main, "_resolve_client_ip", return_value="198.51.100.10")
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "_verify_recaptcha_token", return_value=None)
    mocker.patch.object(app_main, "_resolve_fill_link_recaptcha_action", return_value="fill_link_submit")
    mocker.patch.object(app_main, "_recaptcha_required_for_fill_link", return_value=False)
    mocker.patch.object(app_main, "coerce_fill_link_answers", return_value={"full_name": "Ada Lovelace"})

    response = client.post("/api/fill-links/public/token-1/submit", json={"answers": {"full_name": "Ada Lovelace"}})

    assert response.status_code == 400
    assert "all fields are required" in response.text.lower()


def test_fill_links_public_download_materializes_snapshot_for_template_links(client, app_main, mocker, tmp_path) -> None:
    record = _fill_link_record(
        status="closed",
        respondent_pdf_download_enabled=True,
        respondent_pdf_snapshot={
            "version": 1,
            "sourcePdfPath": "gs://forms/template.pdf",
            "filename": "template-one-response.pdf",
            "fields": [{"name": "full_name", "type": "text", "page": 1}],
        },
    )
    mocker.patch.object(app_main, "get_fill_link_by_public_token", return_value=record)
    mocker.patch.object(app_main, "_resolve_fill_link_download_rate_limits", return_value=(300, 10, 0))
    mocker.patch.object(app_main, "_resolve_client_ip", return_value="198.51.100.10")
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "get_fill_link_response", return_value=_response_record())
    output_path = tmp_path / "respondent-download.pdf"
    output_path.write_bytes(b"%PDF-1.4\n%stub\n")
    materialize_mock = mocker.patch.object(
        app_main,
        "materialize_fill_link_response_download",
        return_value=(output_path, [output_path], "template-one-response.pdf"),
    )

    response = client.get("/api/fill-links/public/token-1/responses/resp-1/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "template-one-response.pdf" in response.headers["content-disposition"]
    materialize_mock.assert_called_once_with(
        {
            "version": 1,
            "sourcePdfPath": "gs://forms/template.pdf",
            "filename": "template-one-response.pdf",
            "fields": [{"name": "full_name", "type": "text", "page": 1}],
        },
        answers={"full_name": "Ada Lovelace"},
    )


def test_fill_links_public_download_prefers_response_snapshot_for_historical_submissions(client, app_main, mocker, tmp_path) -> None:
    record = _fill_link_record(
        status="closed",
        respondent_pdf_download_enabled=True,
        respondent_pdf_snapshot={
            "version": 1,
            "sourcePdfPath": "gs://forms/template-v2.pdf",
            "filename": "template-two-response.pdf",
            "fields": [{"name": "full_name", "type": "text", "page": 1}],
        },
    )
    mocker.patch.object(app_main, "get_fill_link_by_public_token", return_value=record)
    mocker.patch.object(app_main, "_resolve_fill_link_download_rate_limits", return_value=(300, 10, 0))
    mocker.patch.object(app_main, "_resolve_client_ip", return_value="198.51.100.10")
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(
        app_main,
        "get_fill_link_response",
        return_value=_response_record(
            respondent_pdf_snapshot={
                "version": 1,
                "sourcePdfPath": "gs://forms/template-v1.pdf",
                "filename": "template-one-response.pdf",
                "fields": [{"name": "full_name", "type": "text", "page": 1}],
            },
        ),
    )
    output_path = tmp_path / "respondent-download-historical.pdf"
    output_path.write_bytes(b"%PDF-1.4\n%stub\n")
    materialize_mock = mocker.patch.object(
        app_main,
        "materialize_fill_link_response_download",
        return_value=(output_path, [output_path], "template-one-response.pdf"),
    )

    response = client.get("/api/fill-links/public/token-1/responses/resp-1/download")

    assert response.status_code == 200
    materialize_mock.assert_called_once_with(
        {
            "version": 1,
            "sourcePdfPath": "gs://forms/template-v1.pdf",
            "filename": "template-one-response.pdf",
            "fields": [{"name": "full_name", "type": "text", "page": 1}],
        },
        answers={"full_name": "Ada Lovelace"},
    )
