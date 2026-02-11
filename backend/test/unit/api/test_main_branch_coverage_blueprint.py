from __future__ import annotations

import io

from fastapi import HTTPException

from backend.firebaseDB.schema_database import SchemaRecord


def _patch_auth(mocker, app_main, user) -> None:
    mocker.patch.object(app_main, "_verify_token", return_value={"uid": user.app_user_id})
    mocker.patch.object(app_main, "ensure_user", return_value=user)


def _schema_record(schema_id: str = "schema_1") -> SchemaRecord:
    return SchemaRecord(
        id=schema_id,
        name="Schema",
        fields=[{"name": "first_name", "type": "string"}],
        owner_user_id="user_base",
        created_at=None,
        updated_at=None,
        source=None,
        sample_count=None,
    )


def test_middleware_blocks_api_request_before_endpoint_logic_runs(client, app_main, mocker) -> None:
    mocker.patch.object(
        app_main,
        "_verify_token",
        side_effect=HTTPException(status_code=401, detail="Missing Authorization token"),
    )
    require_user = mocker.patch.object(app_main, "_require_user")

    response = client.get("/api/saved-forms")

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing Authorization token"
    require_user.assert_not_called()


def test_middleware_hides_legacy_download_when_disabled_before_auth(client, app_main, mocker) -> None:
    mocker.patch.object(app_main, "_legacy_endpoints_enabled", return_value=False)
    verify = mocker.patch.object(app_main, "_verify_token")

    response = client.get("/download/sess-1")

    assert response.status_code == 404
    assert response.json()["detail"] == "Not found"
    verify.assert_not_called()


def test_download_endpoint_prefers_cached_pdf_bytes_over_storage_stream(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_legacy_endpoints_enabled", return_value=True)
    mocker.patch.object(
        app_main,
        "_get_session_entry",
        return_value={
            "source_pdf": "saved.pdf",
            "pdf_bytes": b"%PDF-1.4\ncached\n",
            "pdf_path": "gs://forms/saved.pdf",
        },
    )
    stream_pdf = mocker.patch.object(app_main, "stream_pdf", return_value=io.BytesIO(b"%PDF-1.4\nstream\n"))

    response = client.get("/download/sess-1", headers=auth_headers)

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-1.4")
    assert "saved.pdf" in response.headers["content-disposition"]
    stream_pdf.assert_not_called()


def test_create_schema_endpoint_rejects_empty_allowlist(client, app_main, base_user, mocker, auth_headers) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "build_allowlist_payload", return_value={"schemaFields": []})
    validate = mocker.patch.object(app_main, "validate_payload_size")

    response = client.post(
        "/api/schemas",
        json={"name": "Patient", "fields": [{"name": "first_name", "type": "string"}]},
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "Schema fields are required" in response.text
    validate.assert_not_called()


def test_create_schema_endpoint_maps_payload_validation_error_to_400(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(
        app_main,
        "build_allowlist_payload",
        return_value={"schemaFields": [{"name": "first_name", "type": "string"}]},
    )
    mocker.patch.object(app_main, "validate_payload_size", side_effect=ValueError("OpenAI payload too large"))
    create_schema = mocker.patch.object(app_main, "create_schema")

    response = client.post(
        "/api/schemas",
        json={"name": "Patient", "fields": [{"name": "first_name", "type": "string"}]},
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "OpenAI payload too large" in response.text
    create_schema.assert_not_called()


def test_create_and_list_schemas_success_path(client, app_main, base_user, mocker, auth_headers) -> None:
    _patch_auth(mocker, app_main, base_user)
    allowlist = {"schemaFields": [{"name": "first_name", "type": "string"}]}
    mocker.patch.object(app_main, "build_allowlist_payload", return_value=allowlist)
    mocker.patch.object(app_main, "validate_payload_size", return_value=None)
    mocker.patch.object(app_main, "create_schema", return_value=_schema_record("schema_new"))

    create_response = client.post(
        "/api/schemas",
        json={"name": "Patient", "fields": [{"name": "first_name", "type": "string"}]},
        headers=auth_headers,
    )

    assert create_response.status_code == 200
    assert create_response.json()["schemaId"] == "schema_new"
    assert create_response.json()["fieldCount"] == 1

    mocker.patch.object(app_main, "list_schemas", return_value=[])
    list_response = client.get("/api/schemas", headers=auth_headers)
    assert list_response.status_code == 200
    assert list_response.json() == {"schemas": []}


def test_schema_mapping_requires_session_or_template(client, app_main, base_user, mocker, auth_headers) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "get_schema", return_value=_schema_record())

    response = client.post(
        "/api/schema-mappings/ai",
        json={
            "schemaId": "schema_1",
            "templateFields": [
                {"name": "A1", "type": "text", "page": 1, "rect": {"x": 10, "y": 10, "width": 20, "height": 10}}
            ],
        },
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "sessionId or templateId is required" in response.text


def test_rename_endpoint_rejects_missing_session_pdf(client, app_main, base_user, mocker, auth_headers) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(
        app_main,
        "_get_session_entry",
        return_value={
            "pdf_bytes": None,
            "fields": [{"name": "A1", "type": "text", "page": 1, "rect": [1, 2, 3, 4]}],
        },
    )

    response = client.post(
        "/api/renames/ai",
        json={"sessionId": "sess-1"},
        headers=auth_headers,
    )

    assert response.status_code == 404
    assert "Session PDF not found" in response.text


# ---------------------------------------------------------------------------
# Edge-case: Middleware OPTIONS request passthrough
# ---------------------------------------------------------------------------
# CORS preflight (OPTIONS) requests should be forwarded to the next handler
# without any auth checks.  This verifies that verify_token is never called.
def test_middleware_options_request_passthrough(client, app_main, mocker) -> None:
    verify_mock = mocker.patch.object(app_main, "_verify_token")
    response = client.options("/api/saved-forms")
    # OPTIONS should be passed through without auth.  The status code depends
    # on the CORS middleware configuration, but the key assertion is that
    # verify_token is never invoked.
    verify_mock.assert_not_called()
    # The response should not be a 401 or 403.
    assert response.status_code != 401
    assert response.status_code != 403
