import pytest

from backend.firebaseDB.schema_database import SchemaRecord


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


def _template_field_payload() -> dict:
    return {
        "name": "A1",
        "type": "text",
        "page": 1,
        "rect": {"x": 10, "y": 20, "width": 100, "height": 30},
    }


def _session_entry() -> dict:
    return {
        "pdf_bytes": b"%PDF-1.4\nfake\n",
        "fields": [{"name": "fallback", "type": "text", "page": 1, "rect": [1, 2, 3, 4]}],
        "source_pdf": "sample.pdf",
        "page_count": 1,
        "user_id": "user_base",
    }


def _patch_auth(mocker, app_main, base_user) -> None:
    mocker.patch.object(app_main, "_verify_token", return_value={"uid": base_user.app_user_id})
    mocker.patch.object(app_main, "ensure_user", return_value=base_user)


def test_rename_endpoint_validates_session_fields_and_schema_ownership(client, app_main, base_user, mocker, auth_headers) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_get_session_entry", return_value={**_session_entry(), "fields": []})
    response = client.post(
        "/api/renames/ai",
        json={"sessionId": "sess-1"},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "No fields available for rename" in response.text

    mocker.patch.object(app_main, "_get_session_entry", return_value=_session_entry())
    mocker.patch.object(app_main, "get_schema", return_value=None)
    response = client.post(
        "/api/renames/ai",
        json={"sessionId": "sess-1", "schemaId": "missing", "templateFields": [_template_field_payload()]},
        headers=auth_headers,
    )
    assert response.status_code == 404
    assert "Schema not found" in response.text


def test_rename_endpoint_rate_limit_and_credit_charge_amounts(client, app_main, base_user, mocker, auth_headers) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_get_session_entry", return_value=_session_entry())
    mocker.patch.object(app_main, "check_rate_limit", return_value=False)
    response = client.post(
        "/api/renames/ai",
        json={"sessionId": "sess-1", "templateFields": [_template_field_payload()]},
        headers=auth_headers,
    )
    assert response.status_code == 429

    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    consume_mock = mocker.patch.object(app_main, "consume_openai_credits", return_value=(9, True))
    mocker.patch.object(app_main, "record_openai_rename_request", return_value=None)
    mocker.patch.object(
        app_main,
        "run_openai_rename_on_pdf",
        return_value=({"checkboxRules": []}, [{"name": "first_name"}]),
    )
    mocker.patch.object(app_main, "_update_session_entry", return_value=None)
    response = client.post(
        "/api/renames/ai",
        json={"sessionId": "sess-1", "templateFields": [_template_field_payload()]},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert consume_mock.call_args.kwargs["credits"] == 1

    mocker.patch.object(app_main, "get_schema", return_value=_schema_record())
    response = client.post(
        "/api/renames/ai",
        json={"sessionId": "sess-1", "schemaId": "schema_1", "templateFields": [_template_field_payload()]},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert consume_mock.call_args.kwargs["credits"] == 2


def test_rename_endpoint_refunds_credit_and_maps_custom_status_code(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    class _OpenAiFailure(Exception):
        def __init__(self, message: str, status_code: int) -> None:
            super().__init__(message)
            self.status_code = status_code

    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_get_session_entry", return_value=_session_entry())
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "consume_openai_credits", return_value=(8, True))
    refund_mock = mocker.patch.object(app_main, "refund_openai_credits", return_value=9)
    mocker.patch.object(app_main, "record_openai_rename_request", return_value=None)
    mocker.patch.object(
        app_main,
        "run_openai_rename_on_pdf",
        side_effect=_OpenAiFailure("downstream failed", 422),
    )

    response = client.post(
        "/api/renames/ai",
        json={"sessionId": "sess-1", "templateFields": [_template_field_payload()]},
        headers=auth_headers,
    )
    assert response.status_code == 422
    refund_mock.assert_called_once()


def test_rename_endpoint_persists_renames_and_checkbox_rules(client, app_main, base_user, mocker, auth_headers) -> None:
    _patch_auth(mocker, app_main, base_user)
    entry = _session_entry()
    mocker.patch.object(app_main, "_get_session_entry", return_value=entry)
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "consume_openai_credits", return_value=(8, True))
    mocker.patch.object(app_main, "record_openai_rename_request", return_value=None)
    mocker.patch.object(
        app_main,
        "run_openai_rename_on_pdf",
        return_value=(
            {"checkboxRules": [{"databaseField": "consent", "groupKey": "consent_group"}]},
            [{"name": "first_name"}],
        ),
    )
    update_mock = mocker.patch.object(app_main, "_update_session_entry", return_value=None)

    response = client.post(
        "/api/renames/ai",
        json={"sessionId": "sess-1", "templateFields": [_template_field_payload()]},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["checkboxRules"] == [{"databaseField": "consent", "groupKey": "consent_group"}]
    assert update_mock.call_args.kwargs["persist_fields"] is True
    assert update_mock.call_args.kwargs["persist_renames"] is True
    assert update_mock.call_args.kwargs["persist_checkbox_rules"] is True


def test_rename_endpoint_schema_allowlist_empty_rejects_before_credit_charge(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_get_session_entry", return_value=_session_entry())
    mocker.patch.object(app_main, "get_schema", return_value=_schema_record())
    mocker.patch.object(app_main, "build_allowlist_payload", return_value={"schemaFields": []})
    consume_mock = mocker.patch.object(app_main, "consume_openai_credits", return_value=(9, True))

    response = client.post(
        "/api/renames/ai",
        json={"sessionId": "sess-1", "schemaId": "schema_1", "templateFields": [_template_field_payload()]},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "Schema fields are required for rename" in response.text
    consume_mock.assert_not_called()


def test_rename_endpoint_credit_exhaustion_returns_402(client, app_main, base_user, mocker, auth_headers) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_get_session_entry", return_value=_session_entry())
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "consume_openai_credits", return_value=(0, False))
    run_mock = mocker.patch.object(app_main, "run_openai_rename_on_pdf")

    response = client.post(
        "/api/renames/ai",
        json={"sessionId": "sess-1", "templateFields": [_template_field_payload()]},
        headers=auth_headers,
    )
    assert response.status_code == 402
    assert "OpenAI credits exhausted (remaining=0, required=1)" in response.text
    run_mock.assert_not_called()


def test_rename_endpoint_preserves_openai_error_when_refund_fails(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    class _OpenAiFailure(Exception):
        def __init__(self, message: str, status_code: int) -> None:
            super().__init__(message)
            self.status_code = status_code

    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_get_session_entry", return_value=_session_entry())
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "consume_openai_credits", return_value=(8, True))
    mocker.patch.object(app_main, "record_openai_rename_request", return_value=None)
    mocker.patch.object(
        app_main,
        "run_openai_rename_on_pdf",
        side_effect=_OpenAiFailure("downstream failed", 422),
    )
    refund_mock = mocker.patch.object(app_main, "refund_openai_credits", side_effect=RuntimeError("refund failed"))

    response = client.post(
        "/api/renames/ai",
        json={"sessionId": "sess-1", "templateFields": [_template_field_payload()]},
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert "downstream failed" in response.text
    refund_mock.assert_called_once()


def test_rename_endpoint_refunds_credits_when_request_logging_fails(
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_get_session_entry", return_value=_session_entry())
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "consume_openai_credits", return_value=(8, True))
    refund_mock = mocker.patch.object(app_main, "refund_openai_credits", return_value=9)
    mocker.patch.object(app_main, "record_openai_rename_request", side_effect=RuntimeError("request log down"))
    run_mock = mocker.patch.object(app_main, "run_openai_rename_on_pdf")

    from fastapi.testclient import TestClient

    local_client = TestClient(app_main.app, raise_server_exceptions=False)
    response = local_client.post(
        "/api/renames/ai",
        json={"sessionId": "sess-1", "templateFields": [_template_field_payload()]},
        headers=auth_headers,
    )

    assert response.status_code == 500
    run_mock.assert_not_called()
    refund_mock.assert_called_once_with(base_user.app_user_id, credits=1, role=base_user.role)


def test_mapping_endpoint_refunds_credits_when_request_logging_fails(
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "get_schema", return_value=_schema_record())
    mocker.patch.object(
        app_main,
        "build_allowlist_payload",
        return_value={"schemaFields": [{"name": "first_name"}], "templateTags": [{"tag": "A1"}]},
    )
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "_get_session_entry", return_value={"session": "entry"})
    mocker.patch.object(app_main, "consume_openai_credits", return_value=(9, True))
    refund_mock = mocker.patch.object(app_main, "refund_openai_credits", return_value=10)
    mocker.patch.object(app_main, "record_openai_request", side_effect=RuntimeError("request log down"))
    openai_mock = mocker.patch.object(app_main, "call_openai_schema_mapping_chunked")

    from fastapi.testclient import TestClient

    local_client = TestClient(app_main.app, raise_server_exceptions=False)
    response = local_client.post(
        "/api/schema-mappings/ai",
        json={"schemaId": "schema_1", "templateFields": [_template_field_payload()], "sessionId": "sess-1"},
        headers=auth_headers,
    )

    assert response.status_code == 500
    openai_mock.assert_not_called()
    refund_mock.assert_called_once_with(base_user.app_user_id, credits=1, role=base_user.role)


def test_mapping_endpoint_validation_rate_limit_and_template_ownership(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "get_schema", return_value=_schema_record())

    response = client.post(
        "/api/schema-mappings/ai",
        json={"schemaId": "schema_1", "templateFields": [], "sessionId": "sess-1"},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "templateFields is required" in response.text

    mocker.patch.object(app_main, "get_template", return_value=None)
    response = client.post(
        "/api/schema-mappings/ai",
        json={"schemaId": "schema_1", "templateId": "tpl-1", "templateFields": [_template_field_payload()]},
        headers=auth_headers,
    )
    assert response.status_code == 403
    assert "Template access denied" in response.text

    mocker.patch.object(app_main, "check_rate_limit", return_value=False)
    mocker.patch.object(
        app_main,
        "build_allowlist_payload",
        return_value={"schemaFields": [{"name": "first_name"}], "templateTags": [{"tag": "A1"}]},
    )
    response = client.post(
        "/api/schema-mappings/ai",
        json={"schemaId": "schema_1", "templateFields": [_template_field_payload()], "sessionId": "sess-1"},
        headers=auth_headers,
    )
    assert response.status_code == 429


def test_mapping_endpoint_rejects_empty_template_tags_without_charging_credits(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "get_schema", return_value=_schema_record())
    mocker.patch.object(
        app_main,
        "build_allowlist_payload",
        return_value={"schemaFields": [{"name": "first_name"}], "templateTags": []},
    )
    consume_mock = mocker.patch.object(app_main, "consume_openai_credits", return_value=(9, True))

    response = client.post(
        "/api/schema-mappings/ai",
        json={"schemaId": "schema_1", "templateFields": [_template_field_payload()], "sessionId": "sess-1"},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "No valid template tags provided" in response.text
    consume_mock.assert_not_called()


def test_mapping_endpoint_credit_exhaustion_returns_402(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "get_schema", return_value=_schema_record())
    mocker.patch.object(
        app_main,
        "build_allowlist_payload",
        return_value={"schemaFields": [{"name": "first_name"}], "templateTags": [{"tag": "A1"}]},
    )
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "_get_session_entry", return_value={"session": "entry"})
    mocker.patch.object(app_main, "consume_openai_credits", return_value=(0, False))
    openai_mock = mocker.patch.object(app_main, "call_openai_schema_mapping_chunked")

    response = client.post(
        "/api/schema-mappings/ai",
        json={"schemaId": "schema_1", "templateFields": [_template_field_payload()], "sessionId": "sess-1"},
        headers=auth_headers,
    )
    assert response.status_code == 402
    assert "OpenAI credits exhausted (remaining=0, required=1)" in response.text
    openai_mock.assert_not_called()


@pytest.mark.parametrize(
    ("failure", "expected_status"),
    [
        (ValueError("payload invalid"), 400),
        (type("_MappingFailure", (Exception,), {"status_code": 504})("upstream timeout"), 504),
    ],
)
def test_mapping_endpoint_refund_failure_does_not_mask_original_error(
    failure,
    expected_status,
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "get_schema", return_value=_schema_record())
    mocker.patch.object(
        app_main,
        "build_allowlist_payload",
        return_value={"schemaFields": [{"name": "first_name"}], "templateTags": [{"tag": "A1"}]},
    )
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "consume_openai_credits", return_value=(9, True))
    mocker.patch.object(app_main, "record_openai_request", return_value=None)
    mocker.patch.object(app_main, "_get_session_entry", return_value={"session": "entry"})
    mocker.patch.object(app_main, "call_openai_schema_mapping_chunked", side_effect=failure)
    refund_mock = mocker.patch.object(app_main, "refund_openai_credits", side_effect=RuntimeError("refund failed"))

    response = client.post(
        "/api/schema-mappings/ai",
        json={"schemaId": "schema_1", "templateFields": [_template_field_payload()], "sessionId": "sess-1"},
        headers=auth_headers,
    )
    assert response.status_code == expected_status
    assert str(failure) in response.text
    refund_mock.assert_called_once()


def test_mapping_endpoint_credit_charge_refund_and_custom_status_code(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    class _MappingFailure(Exception):
        def __init__(self, message: str, status_code: int) -> None:
            super().__init__(message)
            self.status_code = status_code

    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "get_schema", return_value=_schema_record())
    mocker.patch.object(
        app_main,
        "build_allowlist_payload",
        return_value={"schemaFields": [{"name": "first_name"}], "templateTags": [{"tag": "A1"}]},
    )
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    consume_mock = mocker.patch.object(app_main, "consume_openai_credits", return_value=(9, True))
    refund_mock = mocker.patch.object(app_main, "refund_openai_credits", return_value=10)
    mocker.patch.object(app_main, "record_openai_request", return_value=None)
    mocker.patch.object(app_main, "_get_session_entry", return_value={"session": "entry"})
    mocker.patch.object(
        app_main,
        "call_openai_schema_mapping_chunked",
        side_effect=_MappingFailure("downstream exploded", 503),
    )

    response = client.post(
        "/api/schema-mappings/ai",
        json={"schemaId": "schema_1", "templateFields": [_template_field_payload()], "sessionId": "sess-1"},
        headers=auth_headers,
    )
    assert response.status_code == 503
    assert consume_mock.call_args.kwargs["credits"] == 1
    refund_mock.assert_called_once()


def test_mapping_endpoint_persists_checkbox_rules_and_hints_and_passes_response_envelope(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "get_schema", return_value=_schema_record())
    mocker.patch.object(
        app_main,
        "build_allowlist_payload",
        return_value={"schemaFields": [{"name": "first_name"}], "templateTags": [{"tag": "A1"}]},
    )
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "consume_openai_credits", return_value=(9, True))
    mocker.patch.object(app_main, "record_openai_request", return_value=None)
    mocker.patch.object(app_main, "_get_session_entry", return_value={"session": "entry"})
    mocker.patch.object(app_main, "call_openai_schema_mapping_chunked", return_value={"raw": True})
    mapping_payload = {
        "mappings": [],
        "checkboxRules": [{"databaseField": "consent", "groupKey": "consent_group"}],
        "checkboxHints": [{"databaseField": "consent", "groupKey": "consent_group"}],
    }
    mocker.patch.object(app_main, "_build_schema_mapping_payload", return_value=mapping_payload)
    update_mock = mocker.patch.object(app_main, "_update_session_entry", return_value=None)

    response = client.post(
        "/api/schema-mappings/ai",
        json={"schemaId": "schema_1", "templateFields": [_template_field_payload()], "sessionId": "sess-1"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mappingResults"] == mapping_payload
    assert "requestId" in body
    assert update_mock.call_args.kwargs["persist_checkbox_rules"] is True
    assert update_mock.call_args.kwargs["persist_checkbox_hints"] is True


# ---------------------------------------------------------------------------
# Edge-case: Rename endpoint with templateFields=None falls back to session fields
# ---------------------------------------------------------------------------
# When the request omits templateFields the endpoint should use the fields
# stored on the session entry instead of requiring template overlay fields.
def test_rename_endpoint_falls_back_to_session_fields_when_template_fields_none(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    # Session has fields but no templateFields in the request.
    entry = _session_entry()
    # Capture expected fields before the endpoint mutates entry["fields"]
    # with the renamed result.
    expected_fields = list(entry["fields"])
    mocker.patch.object(app_main, "_get_session_entry", return_value=entry)
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "consume_openai_credits", return_value=(9, True))
    mocker.patch.object(app_main, "record_openai_rename_request", return_value=None)
    run_mock = mocker.patch.object(
        app_main,
        "run_openai_rename_on_pdf",
        return_value=({"checkboxRules": []}, [{"name": "renamed_fallback"}]),
    )
    mocker.patch.object(app_main, "_update_session_entry", return_value=None)

    # No templateFields key in payload at all -- only sessionId.
    response = client.post(
        "/api/renames/ai",
        json={"sessionId": "sess-1"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    # The run_openai_rename_on_pdf should have been called with session fields.
    called_fields = run_mock.call_args.kwargs["fields"]
    assert called_fields == expected_fields


# ---------------------------------------------------------------------------
# Edge-case: Mapping endpoint skips session update when no sessionId provided
# ---------------------------------------------------------------------------
# When sessionId is not provided the update_session_entry block should be
# skipped entirely; only template ownership resolution is used.
def test_mapping_endpoint_skips_update_when_no_session_id(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    from backend.firebaseDB.template_database import TemplateRecord

    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "get_schema", return_value=_schema_record())
    mocker.patch.object(
        app_main,
        "get_template",
        return_value=TemplateRecord(
            id="tpl-1",
            pdf_bucket_path="gs://forms/tpl.pdf",
            template_bucket_path="gs://templates/tpl.pdf",
            metadata={},
            created_at=None,
            updated_at=None,
            name="Template",
        ),
    )
    mocker.patch.object(
        app_main,
        "build_allowlist_payload",
        return_value={"schemaFields": [{"name": "first_name"}], "templateTags": [{"tag": "A1"}]},
    )
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "consume_openai_credits", return_value=(9, True))
    mocker.patch.object(app_main, "record_openai_request", return_value=None)
    mocker.patch.object(app_main, "call_openai_schema_mapping_chunked", return_value={"raw": True})
    mapping_payload = {"mappings": [], "checkboxRules": [], "checkboxHints": []}
    mocker.patch.object(app_main, "_build_schema_mapping_payload", return_value=mapping_payload)
    update_mock = mocker.patch.object(app_main, "_update_session_entry", return_value=None)

    # templateId is provided but sessionId is not -- update block should be skipped.
    response = client.post(
        "/api/schema-mappings/ai",
        json={
            "schemaId": "schema_1",
            "templateId": "tpl-1",
            "templateFields": [_template_field_payload()],
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    # Session update should NOT have been called.
    update_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Edge-case: AI rate-limit env vars should reject negative numeric values
# ---------------------------------------------------------------------------
# The endpoints parse env vars with int(...), but negative values are unsafe
# for throttling. They should fall back to secure defaults.
def test_ai_endpoints_rate_limit_env_negative_values_fallback_to_safe_defaults(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
    monkeypatch,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_get_session_entry", return_value=_session_entry())
    check_rate_limit_mock = mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "consume_openai_credits", return_value=(9, True))
    mocker.patch.object(app_main, "record_openai_rename_request", return_value=None)
    mocker.patch.object(
        app_main,
        "run_openai_rename_on_pdf",
        return_value=({"checkboxRules": []}, [{"name": "renamed"}]),
    )
    mocker.patch.object(app_main, "_update_session_entry", return_value=None)
    mocker.patch.object(app_main, "get_schema", return_value=_schema_record())
    mocker.patch.object(
        app_main,
        "build_allowlist_payload",
        return_value={"schemaFields": [{"name": "first_name"}], "templateTags": [{"tag": "A1"}]},
    )
    mocker.patch.object(app_main, "record_openai_request", return_value=None)
    mocker.patch.object(app_main, "call_openai_schema_mapping_chunked", return_value={"raw": True})
    mocker.patch.object(
        app_main,
        "_build_schema_mapping_payload",
        return_value={"mappings": [], "checkboxRules": [], "checkboxHints": []},
    )

    monkeypatch.setenv("OPENAI_RENAME_RATE_LIMIT_WINDOW_SECONDS", "-1")
    monkeypatch.setenv("OPENAI_RENAME_RATE_LIMIT_PER_USER", "-2")
    monkeypatch.setenv("OPENAI_SCHEMA_RATE_LIMIT_WINDOW_SECONDS", "-3")
    monkeypatch.setenv("OPENAI_SCHEMA_RATE_LIMIT_PER_USER", "-4")

    rename_response = client.post(
        "/api/renames/ai",
        json={"sessionId": "sess-1", "templateFields": [_template_field_payload()]},
        headers=auth_headers,
    )
    assert rename_response.status_code == 200
    rename_call = check_rate_limit_mock.call_args_list[-1].kwargs
    assert rename_call["window_seconds"] == 60
    assert rename_call["limit"] == 6

    map_response = client.post(
        "/api/schema-mappings/ai",
        json={"schemaId": "schema_1", "templateFields": [_template_field_payload()], "sessionId": "sess-1"},
        headers=auth_headers,
    )
    assert map_response.status_code == 200
    mapping_call = check_rate_limit_mock.call_args_list[-1].kwargs
    assert mapping_call["window_seconds"] == 60
    assert mapping_call["limit"] == 10
