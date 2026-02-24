from pathlib import Path

from fastapi.testclient import TestClient

from backend.firebaseDB.template_database import TemplateRecord
from backend.detection.pdf_validation import PdfValidationResult


def _template_record(
    *,
    template_id: str = "tpl-1",
    pdf_path: str | None = "gs://forms/a.pdf",
    template_path: str | None = "gs://templates/a.pdf",
    metadata: dict | None = None,
    name: str = "Saved Form",
) -> TemplateRecord:
    return TemplateRecord(
        id=template_id,
        pdf_bucket_path=pdf_path,
        template_bucket_path=template_path,
        metadata=metadata or {},
        created_at=None,
        updated_at=None,
        name=name,
    )


def _patch_auth(mocker, app_main, user) -> None:
    mocker.patch.object(app_main, "_verify_token", return_value={"uid": user.app_user_id})
    mocker.patch.object(app_main, "ensure_user", return_value=user)


def test_saved_forms_list_and_get_not_found(client, app_main, base_user, mocker, auth_headers) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "list_templates", return_value=[_template_record(template_id="a"), _template_record(template_id="b")])
    response = client.get("/api/saved-forms", headers=auth_headers)
    assert response.status_code == 200
    assert len(response.json()["forms"]) == 2

    mocker.patch.object(app_main, "get_template", return_value=None)
    response = client.get("/api/saved-forms/missing", headers=auth_headers)
    assert response.status_code == 404
    assert "Form not found" in response.text


def test_saved_form_get_includes_fill_rule_metadata(client, app_main, base_user, mocker, auth_headers) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(
        app_main,
        "get_template",
        return_value=_template_record(
            template_id="tpl-1",
            metadata={
                "checkboxRules": [{"databaseField": "consent", "groupKey": "consent_group"}],
                "checkboxHints": [{"databaseField": "consent", "groupKey": "consent_group"}],
                "textTransformRules": [{"targetField": "full_name", "operation": "copy", "sources": ["first_name"]}],
            },
        ),
    )

    response = client.get("/api/saved-forms/tpl-1", headers=auth_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["checkboxRules"] == [{"databaseField": "consent", "groupKey": "consent_group"}]
    assert payload["checkboxHints"] == [{"databaseField": "consent", "groupKey": "consent_group"}]
    assert payload["textTransformRules"] == [{"targetField": "full_name", "operation": "copy", "sources": ["first_name"]}]
    assert payload["fillRules"]["textTransformRules"] == payload["textTransformRules"]


def test_saved_form_get_uses_legacy_template_rules_as_text_transform_rules(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(
        app_main,
        "get_template",
        return_value=_template_record(
            template_id="tpl-legacy",
            metadata={
                "checkboxRules": [{"databaseField": "consent", "groupKey": "consent_group"}],
                "templateRules": [{"targetField": "full_name", "operation": "copy", "sources": ["first_name"]}],
            },
        ),
    )

    response = client.get("/api/saved-forms/tpl-legacy", headers=auth_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["textTransformRules"] == [{"targetField": "full_name", "operation": "copy", "sources": ["first_name"]}]
    assert payload["fillRules"]["textTransformRules"] == payload["textTransformRules"]


def test_saved_form_download_requires_gcs_path(client, app_main, base_user, mocker, auth_headers) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "get_template", return_value=_template_record(pdf_path="/tmp/local.pdf"))
    mocker.patch.object(app_main, "is_gcs_path", return_value=False)
    response = client.get("/api/saved-forms/tpl-1/download", headers=auth_headers)
    assert response.status_code == 404
    assert "not found in storage" in response.text


def test_saved_form_download_missing_storage_blob_returns_404(
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "get_template", return_value=_template_record(pdf_path="gs://forms/missing.pdf"))
    mocker.patch.object(app_main, "is_gcs_path", return_value=True)
    mocker.patch.object(app_main, "stream_pdf", side_effect=FileNotFoundError("missing blob"))

    local_client = TestClient(app_main.app, raise_server_exceptions=False)
    response = local_client.get("/api/saved-forms/tpl-1/download", headers=auth_headers)

    assert response.status_code == 404
    assert "Form PDF not found in storage" in response.text


def test_saved_form_download_storage_failure_returns_500(
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "get_template", return_value=_template_record(pdf_path="gs://forms/error.pdf"))
    mocker.patch.object(app_main, "is_gcs_path", return_value=True)
    mocker.patch.object(app_main, "stream_pdf", side_effect=RuntimeError("storage outage"))

    local_client = TestClient(app_main.app, raise_server_exceptions=False)
    response = local_client.get("/api/saved-forms/tpl-1/download", headers=auth_headers)

    assert response.status_code == 500
    assert "Failed to load saved form PDF" in response.text


def test_saved_form_session_creation_not_found_and_success(client, app_main, base_user, mocker, auth_headers) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "get_template", return_value=None)
    response = client.post("/api/saved-forms/missing/session", json={"fields": [{"name": "f"}]}, headers=auth_headers)
    assert response.status_code == 404

    mocker.patch.object(app_main, "get_template", return_value=_template_record())
    mocker.patch.object(app_main, "is_gcs_path", return_value=True)
    mocker.patch.object(app_main, "download_pdf_bytes", return_value=b"%PDF-1.4\n")
    mocker.patch.object(app_main, "_get_pdf_page_count", return_value=1)
    mocker.patch.object(app_main, "_store_session_entry", return_value=None)
    response = client.post(
        "/api/saved-forms/tpl-1/session",
        json={"fields": [{"name": "f", "x": 1, "y": 2, "width": 3, "height": 4}]},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["fieldCount"] == 1


def test_saved_form_session_missing_storage_blob_returns_404(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "get_template", return_value=_template_record(pdf_path="gs://forms/missing.pdf"))
    mocker.patch.object(app_main, "is_gcs_path", return_value=True)
    mocker.patch.object(app_main, "download_pdf_bytes", side_effect=FileNotFoundError("missing blob"))

    response = client.post(
        "/api/saved-forms/tpl-1/session",
        json={"fields": [{"name": "f", "x": 1, "y": 2, "width": 3, "height": 4}]},
        headers=auth_headers,
    )

    assert response.status_code == 404
    assert "Form PDF not found in storage" in response.text


def test_save_form_enforces_saved_form_limit_for_base_and_allows_god(
    client,
    app_main,
    base_user,
    god_user,
    mocker,
    auth_headers,
    tmp_path: Path,
) -> None:
    temp_pdf = tmp_path / "upload.pdf"
    temp_pdf.write_bytes(b"%PDF-1.4\n")

    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_write_upload_to_temp", return_value=temp_pdf)
    mocker.patch.object(app_main, "_validate_pdf_for_detection", return_value=PdfValidationResult(pdf_bytes=b"%PDF-1.4\n", page_count=1, was_decrypted=False))
    mocker.patch.object(app_main, "_resolve_fillable_max_pages", return_value=10)
    mocker.patch.object(app_main, "_resolve_saved_forms_limit", side_effect=lambda role: 1 if role == "base" else 2)
    mocker.patch.object(app_main, "list_templates", return_value=[_template_record(template_id="existing")])
    response = client.post(
        "/api/saved-forms",
        files={"pdf": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        data={"name": "My Form"},
        headers=auth_headers,
    )
    assert response.status_code == 403
    assert "Saved form limit reached" in response.text

    _patch_auth(mocker, app_main, god_user)
    mocker.patch.object(app_main, "list_templates", return_value=[_template_record(template_id="existing")])
    mocker.patch.object(app_main, "upload_form_pdf", return_value="gs://forms/new.pdf")
    mocker.patch.object(app_main, "upload_template_pdf", return_value="gs://templates/new.pdf")
    mocker.patch.object(app_main, "create_template", return_value=_template_record(template_id="created"))
    response = client.post(
        "/api/saved-forms",
        files={"pdf": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        data={"name": "My Form"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["id"] == "created"


def test_save_form_overwrite_updates_existing_form(client, app_main, base_user, mocker, auth_headers, tmp_path: Path) -> None:
    temp_pdf = tmp_path / "overwrite.pdf"
    temp_pdf.write_bytes(b"%PDF-1.4\n")
    _patch_auth(mocker, app_main, base_user)
    existing = _template_record(
        template_id="tpl-old",
        pdf_path="gs://forms/old.pdf",
        template_path="gs://templates/old.pdf",
        metadata={"existing": True},
    )
    updated = _template_record(template_id="tpl-old", metadata={"existing": True, "name": "Renamed"})

    mocker.patch.object(app_main, "get_template", return_value=existing)
    mocker.patch.object(app_main, "_write_upload_to_temp", return_value=temp_pdf)
    mocker.patch.object(app_main, "_validate_pdf_for_detection", return_value=PdfValidationResult(pdf_bytes=b"%PDF-1.4\n", page_count=1, was_decrypted=False))
    mocker.patch.object(app_main, "_resolve_fillable_max_pages", return_value=10)
    mocker.patch.object(app_main, "is_gcs_path", return_value=True)
    mocker.patch.object(app_main, "upload_pdf_to_bucket_path", side_effect=["gs://forms/new.pdf", "gs://templates/new.pdf"])
    update_mock = mocker.patch.object(app_main, "update_template", return_value=updated)
    delete_mock = mocker.patch.object(app_main, "delete_pdf", return_value=None)

    response = client.post(
        "/api/saved-forms",
        files={"pdf": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        data={"name": "Renamed", "overwriteFormId": "tpl-old"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["id"] == "tpl-old"
    assert update_mock.called
    assert delete_mock.call_count == 2


def test_save_form_merges_fill_rule_metadata_and_cleans_up_on_db_failure(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
    tmp_path: Path,
) -> None:
    temp_pdf = tmp_path / "upload.pdf"
    temp_pdf.write_bytes(b"%PDF-1.4\n")
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_write_upload_to_temp", return_value=temp_pdf)
    mocker.patch.object(app_main, "_validate_pdf_for_detection", return_value=PdfValidationResult(pdf_bytes=b"%PDF-1.4\n", page_count=1, was_decrypted=False))
    mocker.patch.object(app_main, "_resolve_fillable_max_pages", return_value=10)
    mocker.patch.object(app_main, "_resolve_saved_forms_limit", return_value=10)
    mocker.patch.object(app_main, "list_templates", return_value=[])
    mocker.patch.object(app_main, "upload_form_pdf", return_value="gs://forms/new.pdf")
    mocker.patch.object(app_main, "upload_template_pdf", return_value="gs://templates/new.pdf")
    mocker.patch.object(
        app_main,
        "_get_session_entry_if_present",
        return_value={
            "checkboxRules": [{"databaseField": "consent", "groupKey": "consent_group"}],
            "checkboxHints": [{"databaseField": "consent", "groupKey": "consent_group"}],
            "textTransformRules": [{"targetField": "full_name", "operation": "copy", "sources": ["first_name"]}],
        },
    )
    create_mock = mocker.patch.object(app_main, "create_template", side_effect=RuntimeError("db write failed"))
    delete_mock = mocker.patch.object(app_main, "delete_pdf", return_value=None)

    local_client = TestClient(app_main.app, raise_server_exceptions=False)
    response = local_client.post(
        "/api/saved-forms",
        files={"pdf": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        data={"name": "Name", "sessionId": "sess-1"},
        headers=auth_headers,
    )
    assert response.status_code == 500
    assert create_mock.called
    metadata = create_mock.call_args.kwargs["metadata"]
    assert metadata["originalSessionId"] == "sess-1"
    assert metadata["checkboxRules"] == [{"databaseField": "consent", "groupKey": "consent_group"}]
    assert metadata["checkboxHints"] == [{"databaseField": "consent", "groupKey": "consent_group"}]
    assert metadata["textTransformRules"] == [{"targetField": "full_name", "operation": "copy", "sources": ["first_name"]}]
    assert metadata["fillRules"]["textTransformRules"] == metadata["textTransformRules"]
    assert delete_mock.call_count == 2


def test_save_form_uses_explicit_empty_fill_rule_payloads_instead_of_session_fallback(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
    tmp_path: Path,
) -> None:
    temp_pdf = tmp_path / "upload-empty-checkboxes.pdf"
    temp_pdf.write_bytes(b"%PDF-1.4\n")
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_write_upload_to_temp", return_value=temp_pdf)
    mocker.patch.object(
        app_main,
        "_validate_pdf_for_detection",
        return_value=PdfValidationResult(pdf_bytes=b"%PDF-1.4\n", page_count=1, was_decrypted=False),
    )
    mocker.patch.object(app_main, "_resolve_fillable_max_pages", return_value=10)
    mocker.patch.object(app_main, "_resolve_saved_forms_limit", return_value=10)
    mocker.patch.object(app_main, "list_templates", return_value=[])
    mocker.patch.object(app_main, "upload_form_pdf", return_value="gs://forms/new.pdf")
    mocker.patch.object(app_main, "upload_template_pdf", return_value="gs://templates/new.pdf")
    mocker.patch.object(
        app_main,
        "_get_session_entry_if_present",
        return_value={
            "checkboxRules": [{"databaseField": "legacy", "groupKey": "legacy_group"}],
            "checkboxHints": [{"databaseField": "legacy", "groupKey": "legacy_group"}],
            "textTransformRules": [{"targetField": "legacy", "operation": "copy", "sources": ["legacy"]}],
        },
    )
    create_mock = mocker.patch.object(app_main, "create_template", return_value=_template_record(template_id="created"))

    response = client.post(
        "/api/saved-forms",
        files={"pdf": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        data={
            "name": "Name",
            "sessionId": "sess-1",
            "checkboxRules": "[]",
            "checkboxHints": "[]",
            "textTransformRules": "[]",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    metadata = create_mock.call_args.kwargs["metadata"]
    assert metadata["checkboxRules"] == []
    assert metadata["checkboxHints"] == []
    assert metadata["textTransformRules"] == []


def test_save_form_cleans_uploaded_form_blob_when_template_upload_fails(
    app_main,
    base_user,
    mocker,
    auth_headers,
    tmp_path: Path,
) -> None:
    temp_pdf = tmp_path / "partial-upload.pdf"
    temp_pdf.write_bytes(b"%PDF-1.4\n")
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_write_upload_to_temp", return_value=temp_pdf)
    mocker.patch.object(
        app_main,
        "_validate_pdf_for_detection",
        return_value=PdfValidationResult(pdf_bytes=b"%PDF-1.4\n", page_count=1, was_decrypted=False),
    )
    mocker.patch.object(app_main, "_resolve_fillable_max_pages", return_value=10)
    mocker.patch.object(app_main, "_resolve_saved_forms_limit", return_value=10)
    mocker.patch.object(app_main, "list_templates", return_value=[])
    mocker.patch.object(app_main, "upload_form_pdf", return_value="gs://forms/new.pdf")
    mocker.patch.object(app_main, "upload_template_pdf", side_effect=RuntimeError("template upload failed"))
    delete_mock = mocker.patch.object(app_main, "delete_pdf", return_value=None)

    local_client = TestClient(app_main.app, raise_server_exceptions=False)
    response = local_client.post(
        "/api/saved-forms",
        files={"pdf": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        data={"name": "Name"},
        headers=auth_headers,
    )

    assert response.status_code == 500
    delete_mock.assert_called_once_with("gs://forms/new.pdf")


def test_delete_saved_form_handles_storage_failure_and_success(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    template = _template_record(pdf_path="gs://forms/a.pdf", template_path="gs://templates/a.pdf")
    mocker.patch.object(app_main, "get_template", return_value=template)
    mocker.patch.object(app_main, "is_gcs_path", return_value=True)
    mocker.patch.object(app_main, "delete_pdf", side_effect=RuntimeError("delete fail"))
    response = client.delete("/api/saved-forms/tpl-1", headers=auth_headers)
    assert response.status_code == 500

    mocker.patch.object(app_main, "delete_pdf", return_value=None)
    mocker.patch.object(app_main, "delete_template", return_value=True)
    response = client.delete("/api/saved-forms/tpl-1", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {"success": True}


def test_delete_saved_form_allows_missing_storage_blob(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    template = _template_record(pdf_path="gs://forms/a.pdf", template_path="gs://templates/a.pdf")
    mocker.patch.object(app_main, "get_template", return_value=template)
    mocker.patch.object(app_main, "is_gcs_path", return_value=True)
    mocker.patch.object(app_main, "delete_pdf", side_effect=FileNotFoundError("already deleted"))
    delete_template_mock = mocker.patch.object(app_main, "delete_template", return_value=True)

    response = client.delete("/api/saved-forms/tpl-1", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {"success": True}
    assert delete_template_mock.called


# ---------------------------------------------------------------------------
# Edge-case: save_form rejects non-PDF upload (content-type validation)
# ---------------------------------------------------------------------------
# When the filename does not end with .pdf and the content-type is not
# application/pdf or application/octet-stream the endpoint should return 400.
def test_save_form_rejects_non_pdf_content_type(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    response = client.post(
        "/api/saved-forms",
        files={"pdf": ("report.txt", b"not a pdf", "text/plain")},
        data={"name": "My Form"},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "Only PDF uploads are supported" in response.text
