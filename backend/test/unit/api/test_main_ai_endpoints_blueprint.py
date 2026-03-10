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
    refund_mock = mocker.patch.object(app_main, "attempt_credit_refund", return_value=True)
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
    assert update_mock.call_args.kwargs["persist_checkbox_hints"] is True
    assert update_mock.call_args.kwargs["persist_text_transform_rules"] is True
    assert entry["checkboxHints"] == []
    assert entry["textTransformRules"] == []


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
    refund_mock = mocker.patch.object(app_main, "attempt_credit_refund", return_value=False)

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
    refund_mock = mocker.patch.object(app_main, "attempt_credit_refund", return_value=True)
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
    refund_mock.assert_called_once()
    refund_kwargs = refund_mock.call_args.kwargs
    assert refund_kwargs["user_id"] == base_user.app_user_id
    assert refund_kwargs["role"] == base_user.role
    assert refund_kwargs["credits"] == 1
    assert refund_kwargs["source"] == "rename.request_log"
    assert refund_kwargs["request_id"]


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
    mocker.patch.object(app_main, "_get_session_entry", return_value={"session": "entry", "page_count": 1})
    mocker.patch.object(app_main, "consume_openai_credits", return_value=(9, True))
    refund_mock = mocker.patch.object(app_main, "attempt_credit_refund", return_value=True)
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
    refund_mock.assert_called_once()
    refund_kwargs = refund_mock.call_args.kwargs
    assert refund_kwargs["user_id"] == base_user.app_user_id
    assert refund_kwargs["role"] == base_user.role
    assert refund_kwargs["credits"] == 1
    assert refund_kwargs["source"] == "remap.request_log"
    assert refund_kwargs["request_id"]


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
    mocker.patch.object(app_main, "_get_session_entry", return_value={"session": "entry", "page_count": 1})
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
    mocker.patch.object(app_main, "_get_session_entry", return_value={"session": "entry", "page_count": 1})
    mocker.patch.object(app_main, "call_openai_schema_mapping_chunked", side_effect=failure)
    refund_mock = mocker.patch.object(app_main, "attempt_credit_refund", return_value=False)

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
    refund_mock = mocker.patch.object(app_main, "attempt_credit_refund", return_value=True)
    mocker.patch.object(app_main, "record_openai_request", return_value=None)
    mocker.patch.object(app_main, "_get_session_entry", return_value={"session": "entry", "page_count": 1})
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


def test_mapping_endpoint_persists_checkbox_and_text_rules_and_passes_response_envelope(
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
    mocker.patch.object(app_main, "_get_session_entry", return_value={"session": "entry", "page_count": 1})
    mocker.patch.object(app_main, "call_openai_schema_mapping_chunked", return_value={"raw": True})
    mapping_payload = {
        "mappings": [],
        "checkboxRules": [{"databaseField": "consent", "groupKey": "consent_group"}],
        "checkboxHints": [{"databaseField": "consent", "groupKey": "consent_group"}],
        "textTransformRules": [{"targetField": "A1", "operation": "copy", "sources": ["first_name"]}],
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
    assert update_mock.call_args.kwargs["persist_text_transform_rules"] is True


def test_mapping_endpoint_persists_empty_checkbox_and_text_rules_to_clear_stale_state(
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
    session_entry = {
        "checkboxRules": [{"databaseField": "legacy", "groupKey": "legacy_group"}],
        "checkboxHints": [{"databaseField": "legacy", "groupKey": "legacy_group"}],
        "textTransformRules": [{"targetField": "legacy", "operation": "copy", "sources": ["legacy"]}],
        "page_count": 1,
    }
    mocker.patch.object(app_main, "_get_session_entry", return_value=session_entry)
    mocker.patch.object(app_main, "call_openai_schema_mapping_chunked", return_value={"raw": True})
    mocker.patch.object(
        app_main,
        "_build_schema_mapping_payload",
        return_value={"mappings": [], "checkboxRules": [], "checkboxHints": [], "textTransformRules": []},
    )
    update_mock = mocker.patch.object(app_main, "_update_session_entry", return_value=None)

    response = client.post(
        "/api/schema-mappings/ai",
        json={"schemaId": "schema_1", "templateFields": [_template_field_payload()], "sessionId": "sess-1"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert session_entry["checkboxRules"] == []
    assert session_entry["checkboxHints"] == []
    assert session_entry["textTransformRules"] == []
    assert update_mock.call_args.kwargs["persist_checkbox_rules"] is True
    assert update_mock.call_args.kwargs["persist_checkbox_hints"] is True
    assert update_mock.call_args.kwargs["persist_text_transform_rules"] is True


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
            metadata={"page_count": 1},
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
    assert rename_call["fail_closed"] is True

    map_response = client.post(
        "/api/schema-mappings/ai",
        json={"schemaId": "schema_1", "templateFields": [_template_field_payload()], "sessionId": "sess-1"},
        headers=auth_headers,
    )
    assert map_response.status_code == 200
    mapping_call = check_rate_limit_mock.call_args_list[-1].kwargs
    assert mapping_call["window_seconds"] == 60
    assert mapping_call["limit"] == 10
    assert mapping_call["fail_closed"] is True


def test_rename_endpoint_tasks_mode_enqueues_job_and_skips_inline_openai_call(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_get_session_entry", return_value=_session_entry())
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "consume_openai_credits", return_value=(9, True, {"base": 1, "monthly": 0, "refill": 0}))
    mocker.patch.object(app_main, "record_openai_rename_request", return_value=None)
    mocker.patch.object(app_main, "resolve_openai_rename_mode", return_value="tasks")
    mocker.patch.object(app_main, "resolve_openai_rename_profile", return_value="light")
    mocker.patch.object(
        app_main,
        "resolve_openai_task_config",
        return_value={"profile": "light", "queue": "openai-rename-light", "service_url": "https://rename"},
    )
    create_job_mock = mocker.patch.object(app_main, "create_openai_job", return_value=None)
    enqueue_mock = mocker.patch.object(app_main, "enqueue_openai_rename_task", return_value="tasks/rename-1")
    update_job_mock = mocker.patch.object(app_main, "update_openai_job", return_value=None)
    inline_openai_mock = mocker.patch.object(app_main, "run_openai_rename_on_pdf")

    response = client.post(
        "/api/renames/ai",
        json={"sessionId": "sess-1", "templateFields": [_template_field_payload()]},
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["jobId"] == body["requestId"]
    create_job_mock.assert_called_once()
    enqueue_payload = enqueue_mock.call_args.args[0]
    assert enqueue_payload["sessionId"] == "sess-1"
    assert any(call.kwargs.get("credit_breakdown") == {"base": 1, "monthly": 0, "refill": 0} for call in update_job_mock.call_args_list)
    assert any(call.kwargs.get("task_name") == "tasks/rename-1" for call in update_job_mock.call_args_list)
    inline_openai_mock.assert_not_called()


def test_rename_endpoint_tasks_mode_reuses_existing_idempotent_job_without_recharging(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_get_session_entry", return_value=_session_entry())
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "resolve_openai_rename_mode", return_value="tasks")
    mocker.patch.object(app_main, "_build_openai_request_id", return_value="rename-idem-1")
    mocker.patch.object(
        app_main,
        "get_openai_job",
        return_value={
            "job_type": "rename",
            "user_id": base_user.app_user_id,
            "request_id": "rename-idem-1",
            "session_id": "sess-1",
            "schema_id": None,
            "status": "queued",
            "page_count": 1,
            "credit_pricing": {"totalCredits": 1},
        },
    )
    consume_mock = mocker.patch.object(app_main, "consume_openai_credits", return_value=(9, True))
    create_job_mock = mocker.patch.object(app_main, "create_openai_job", return_value=None)
    enqueue_mock = mocker.patch.object(app_main, "enqueue_openai_rename_task", return_value="tasks/rename-1")

    response = client.post(
        "/api/renames/ai",
        json={"sessionId": "sess-1", "templateFields": [_template_field_payload()]},
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["jobId"] == "rename-idem-1"
    assert body["status"] == "queued"
    create_job_mock.assert_not_called()
    consume_mock.assert_not_called()
    enqueue_mock.assert_not_called()


def test_rename_endpoint_reuses_request_id_for_sync_retry_without_recharging(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_get_session_entry", return_value=_session_entry())
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "resolve_openai_rename_mode", return_value="sync")
    mocker.patch.object(
        app_main,
        "get_openai_job",
        return_value={
            "job_type": "rename",
            "user_id": base_user.app_user_id,
            "request_id": "rename-sync-1",
            "session_id": "sess-1",
            "schema_id": None,
            "status": "complete",
            "page_count": 1,
            "credit_pricing": {"totalCredits": 1},
            "result": {"success": True, "fields": [{"name": "first_name"}], "checkboxRules": []},
        },
    )
    consume_mock = mocker.patch.object(app_main, "consume_openai_credits", return_value=(9, True))
    create_job_mock = mocker.patch.object(app_main, "create_openai_job", return_value=None)
    openai_mock = mocker.patch.object(app_main, "run_openai_rename_on_pdf")

    response = client.post(
        "/api/renames/ai",
        json={
            "sessionId": "sess-1",
            "requestId": "rename-sync-1",
            "templateFields": [_template_field_payload()],
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["jobId"] == "rename-sync-1"
    assert body["status"] == "complete"
    assert body["fields"] == [{"name": "first_name"}]
    create_job_mock.assert_not_called()
    consume_mock.assert_not_called()
    openai_mock.assert_not_called()


def test_mapping_endpoint_tasks_mode_enqueues_job(
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
    mocker.patch.object(app_main, "_get_session_entry", return_value={"session": "entry", "page_count": 1})
    mocker.patch.object(app_main, "consume_openai_credits", return_value=(9, True, {"base": 1, "monthly": 0, "refill": 0}))
    mocker.patch.object(app_main, "record_openai_request", return_value=None)
    mocker.patch.object(app_main, "resolve_openai_remap_mode", return_value="tasks")
    mocker.patch.object(app_main, "resolve_openai_remap_profile", return_value="light")
    mocker.patch.object(
        app_main,
        "resolve_openai_task_config",
        return_value={"profile": "light", "queue": "openai-remap-light", "service_url": "https://remap"},
    )
    create_job_mock = mocker.patch.object(app_main, "create_openai_job", return_value=None)
    enqueue_mock = mocker.patch.object(app_main, "enqueue_openai_remap_task", return_value="tasks/remap-1")
    update_job_mock = mocker.patch.object(app_main, "update_openai_job", return_value=None)
    inline_openai_mock = mocker.patch.object(app_main, "call_openai_schema_mapping_chunked")

    response = client.post(
        "/api/schema-mappings/ai",
        json={"schemaId": "schema_1", "templateFields": [_template_field_payload()], "sessionId": "sess-1"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["jobId"] == body["requestId"]
    create_job_mock.assert_called_once()
    enqueue_payload = enqueue_mock.call_args.args[0]
    assert enqueue_payload["schemaId"] == "schema_1"
    assert any(call.kwargs.get("credit_breakdown") == {"base": 1, "monthly": 0, "refill": 0} for call in update_job_mock.call_args_list)
    assert any(call.kwargs.get("task_name") == "tasks/remap-1" for call in update_job_mock.call_args_list)
    inline_openai_mock.assert_not_called()


def test_mapping_endpoint_tasks_mode_reuses_existing_idempotent_job_without_recharging(
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
    mocker.patch.object(app_main, "_get_session_entry", return_value={"session": "entry", "page_count": 1})
    mocker.patch.object(app_main, "resolve_openai_remap_mode", return_value="tasks")
    mocker.patch.object(app_main, "_build_openai_request_id", return_value="remap-idem-1")
    mocker.patch.object(
        app_main,
        "get_openai_job",
        return_value={
            "job_type": "remap",
            "user_id": base_user.app_user_id,
            "request_id": "remap-idem-1",
            "schema_id": "schema_1",
            "session_id": "sess-1",
            "status": "queued",
            "page_count": 1,
            "credit_pricing": {"totalCredits": 1},
        },
    )
    consume_mock = mocker.patch.object(app_main, "consume_openai_credits", return_value=(9, True))
    create_job_mock = mocker.patch.object(app_main, "create_openai_job", return_value=None)
    enqueue_mock = mocker.patch.object(app_main, "enqueue_openai_remap_task", return_value="tasks/remap-1")

    response = client.post(
        "/api/schema-mappings/ai",
        json={"schemaId": "schema_1", "templateFields": [_template_field_payload()], "sessionId": "sess-1"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["jobId"] == "remap-idem-1"
    assert body["status"] == "queued"
    create_job_mock.assert_not_called()
    consume_mock.assert_not_called()
    enqueue_mock.assert_not_called()


def test_rename_endpoint_lost_create_race_reuses_existing_job_without_recharging(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_get_session_entry", return_value=_session_entry())
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "resolve_openai_rename_mode", return_value="tasks")
    mocker.patch.object(app_main, "resolve_openai_rename_profile", return_value="light")
    mocker.patch.object(
        app_main,
        "resolve_openai_task_config",
        return_value={"profile": "light", "queue": "openai-rename-light", "service_url": "https://rename"},
    )
    mocker.patch.object(app_main, "_build_openai_request_id", return_value="rename-race-1")
    get_job_mock = mocker.patch.object(
        app_main,
        "get_openai_job",
        side_effect=[
            None,
            {
                "job_type": "rename",
                "user_id": base_user.app_user_id,
                "request_id": "rename-race-1",
                "session_id": "sess-1",
                "schema_id": None,
                "status": "queued",
                "page_count": 1,
                "credit_pricing": {"totalCredits": 1},
            },
        ],
    )
    create_job_mock = mocker.patch.object(
        app_main,
        "create_openai_job",
        side_effect=app_main.OpenAiJobAlreadyExistsError("OpenAI job already exists: rename-race-1"),
    )
    consume_mock = mocker.patch.object(app_main, "consume_openai_credits", return_value=(9, True))
    enqueue_mock = mocker.patch.object(app_main, "enqueue_openai_rename_task", return_value="tasks/rename-1")

    response = client.post(
        "/api/renames/ai",
        json={"sessionId": "sess-1", "templateFields": [_template_field_payload()]},
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["jobId"] == "rename-race-1"
    assert body["status"] == "queued"
    assert get_job_mock.call_count == 2
    create_job_mock.assert_called_once()
    consume_mock.assert_not_called()
    enqueue_mock.assert_not_called()


def test_mapping_endpoint_reuses_request_id_for_sync_retry_without_recharging(
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
    mocker.patch.object(app_main, "_get_session_entry", return_value={"session": "entry", "page_count": 1})
    mocker.patch.object(app_main, "resolve_openai_remap_mode", return_value="sync")
    mocker.patch.object(
        app_main,
        "get_openai_job",
        return_value={
            "job_type": "remap",
            "user_id": base_user.app_user_id,
            "request_id": "remap-sync-1",
            "schema_id": "schema_1",
            "session_id": "sess-1",
            "template_id": None,
            "status": "complete",
            "page_count": 1,
            "credit_pricing": {"totalCredits": 1},
            "result": {"success": True, "mappingResults": {"mappings": [{"pdfField": "A1"}]}},
        },
    )
    consume_mock = mocker.patch.object(app_main, "consume_openai_credits", return_value=(9, True))
    create_job_mock = mocker.patch.object(app_main, "create_openai_job", return_value=None)
    openai_mock = mocker.patch.object(app_main, "call_openai_schema_mapping_chunked")

    response = client.post(
        "/api/schema-mappings/ai",
        json={
            "schemaId": "schema_1",
            "requestId": "remap-sync-1",
            "templateFields": [_template_field_payload()],
            "sessionId": "sess-1",
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["jobId"] == "remap-sync-1"
    assert body["status"] == "complete"
    assert body["mappingResults"]["mappings"] == [{"pdfField": "A1"}]
    create_job_mock.assert_not_called()
    consume_mock.assert_not_called()
    openai_mock.assert_not_called()


def test_openai_job_status_endpoints_enforce_ownership_and_return_result(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(
        app_main,
        "get_openai_job",
        return_value={
            "job_type": "rename",
            "user_id": base_user.app_user_id,
            "request_id": "job-1",
            "session_id": "sess-1",
            "schema_id": "schema-1",
            "status": "complete",
            "result": {"success": True, "fields": [{"name": "first_name"}]},
        },
    )

    ok_response = client.get("/api/renames/ai/job-1", headers=auth_headers)
    assert ok_response.status_code == 200
    assert ok_response.json()["fields"] == [{"name": "first_name"}]

    mocker.patch.object(
        app_main,
        "get_openai_job",
        return_value={
            "job_type": "remap",
            "user_id": "other-user",
            "request_id": "job-2",
            "status": "running",
        },
    )
    denied_response = client.get("/api/schema-mappings/ai/job-2", headers=auth_headers)
    assert denied_response.status_code == 403


def test_rename_plus_remap_twelve_pages_charges_six_credits_and_returns_pricing(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    entry = _session_entry()
    entry["page_count"] = 12
    mocker.patch.object(app_main, "_get_session_entry", return_value=entry)
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    consume_mock = mocker.patch.object(app_main, "consume_openai_credits", return_value=(90, True))
    mocker.patch.object(app_main, "get_schema", return_value=_schema_record())
    mocker.patch.object(app_main, "record_openai_rename_request", return_value=None)
    mocker.patch.object(
        app_main,
        "run_openai_rename_on_pdf",
        return_value=({"checkboxRules": []}, [{"name": "first_name"}]),
    )
    mocker.patch.object(app_main, "_update_session_entry", return_value=None)

    response = client.post(
        "/api/renames/ai",
        json={"sessionId": "sess-1", "schemaId": "schema_1", "templateFields": [_template_field_payload()]},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert consume_mock.call_args.kwargs["credits"] == 6
    body = response.json()
    assert body["pageCount"] == 12
    assert body["creditPricing"]["totalCredits"] == 6
    assert body["creditPricing"]["bucketCount"] == 3
    assert body["creditPricing"]["baseCost"] == 2


def test_rename_twelve_pages_charges_three_credits_and_returns_pricing(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    entry = _session_entry()
    entry["page_count"] = 12
    mocker.patch.object(app_main, "_get_session_entry", return_value=entry)
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    consume_mock = mocker.patch.object(app_main, "consume_openai_credits", return_value=(97, True))
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
    assert consume_mock.call_args.kwargs["credits"] == 3
    body = response.json()
    assert body["pageCount"] == 12
    assert body["creditPricing"]["totalCredits"] == 3
    assert body["creditPricing"]["bucketCount"] == 3
    assert body["creditPricing"]["baseCost"] == 1


def test_mapping_twelve_pages_charges_three_credits_and_returns_pricing(
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
    mocker.patch.object(app_main, "_get_session_entry", return_value={"session": "entry", "page_count": 12})
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    consume_mock = mocker.patch.object(app_main, "consume_openai_credits", return_value=(97, True))
    mocker.patch.object(app_main, "record_openai_request", return_value=None)
    mocker.patch.object(app_main, "call_openai_schema_mapping_chunked", return_value={"raw": True})
    mocker.patch.object(app_main, "_build_schema_mapping_payload", return_value={"mappings": []})
    mocker.patch.object(app_main, "_update_session_entry", return_value=None)

    response = client.post(
        "/api/schema-mappings/ai",
        json={"schemaId": "schema_1", "templateFields": [_template_field_payload()], "sessionId": "sess-1"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert consume_mock.call_args.kwargs["credits"] == 3
    body = response.json()
    assert body["pageCount"] == 12
    assert body["creditPricing"]["totalCredits"] == 3
    assert body["creditPricing"]["bucketCount"] == 3
    assert body["creditPricing"]["baseCost"] == 1


def test_rename_plus_remap_insufficient_credits_rejected_before_work_starts(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    entry = _session_entry()
    entry["page_count"] = 12
    mocker.patch.object(app_main, "_get_session_entry", return_value=entry)
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "get_schema", return_value=_schema_record())
    mocker.patch.object(app_main, "consume_openai_credits", return_value=(4, False))
    request_log_mock = mocker.patch.object(app_main, "record_openai_rename_request", return_value=None)
    run_mock = mocker.patch.object(app_main, "run_openai_rename_on_pdf")

    response = client.post(
        "/api/renames/ai",
        json={"sessionId": "sess-1", "schemaId": "schema_1", "templateFields": [_template_field_payload()]},
        headers=auth_headers,
    )

    assert response.status_code == 402
    assert "OpenAI credits exhausted (remaining=4, required=6)" in response.text
    request_log_mock.assert_not_called()
    run_mock.assert_not_called()


def test_mapping_page_count_falls_back_to_template_metadata_for_credit_pricing(
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
            metadata={"page_count": 12},
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
    get_session_mock = mocker.patch.object(app_main, "_get_session_entry")
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    consume_mock = mocker.patch.object(app_main, "consume_openai_credits", return_value=(97, True))
    mocker.patch.object(app_main, "record_openai_request", return_value=None)
    mocker.patch.object(app_main, "call_openai_schema_mapping_chunked", return_value={"raw": True})
    mocker.patch.object(app_main, "_build_schema_mapping_payload", return_value={"mappings": []})
    update_mock = mocker.patch.object(app_main, "_update_session_entry", return_value=None)

    response = client.post(
        "/api/schema-mappings/ai",
        json={"schemaId": "schema_1", "templateId": "tpl-1", "templateFields": [_template_field_payload()]},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert consume_mock.call_args.kwargs["credits"] == 3
    body = response.json()
    assert body["pageCount"] == 12
    assert body["creditPricing"]["totalCredits"] == 3
    get_session_mock.assert_not_called()
    update_mock.assert_not_called()


def test_mapping_rejects_when_page_count_missing_for_credit_pricing(
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
    mocker.patch.object(app_main, "_get_session_entry", return_value={"session": "entry"})
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    consume_mock = mocker.patch.object(app_main, "consume_openai_credits", return_value=(9, True))
    request_log_mock = mocker.patch.object(app_main, "record_openai_request", return_value=None)

    response = client.post(
        "/api/schema-mappings/ai",
        json={"schemaId": "schema_1", "templateFields": [_template_field_payload()], "sessionId": "sess-1"},
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "Unable to determine document page count for credit pricing" in response.text
    consume_mock.assert_not_called()
    request_log_mock.assert_not_called()


def test_rename_uses_pdf_page_count_fallback_when_session_page_count_missing(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    entry = _session_entry()
    entry["page_count"] = None
    mocker.patch.object(app_main, "_get_session_entry", return_value=entry)
    get_pdf_count_mock = mocker.patch.object(app_main, "get_pdf_page_count", return_value=12)
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    consume_mock = mocker.patch.object(app_main, "consume_openai_credits", return_value=(90, True))
    mocker.patch.object(app_main, "get_schema", return_value=_schema_record())
    mocker.patch.object(app_main, "record_openai_rename_request", return_value=None)
    mocker.patch.object(
        app_main,
        "run_openai_rename_on_pdf",
        return_value=({"checkboxRules": []}, [{"name": "first_name"}]),
    )
    mocker.patch.object(app_main, "_update_session_entry", return_value=None)

    response = client.post(
        "/api/renames/ai",
        json={"sessionId": "sess-1", "schemaId": "schema_1", "templateFields": [_template_field_payload()]},
        headers=auth_headers,
    )

    assert response.status_code == 200
    get_pdf_count_mock.assert_called_once()
    assert consume_mock.call_args.kwargs["credits"] == 6


def test_rename_task_mode_uses_bucketed_credit_costs_for_twelve_pages(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    entry = _session_entry()
    entry["page_count"] = 12
    mocker.patch.object(app_main, "_get_session_entry", return_value=entry)
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "consume_openai_credits", return_value=(90, True))
    mocker.patch.object(app_main, "get_schema", return_value=_schema_record())
    mocker.patch.object(app_main, "record_openai_rename_request", return_value=None)
    mocker.patch.object(app_main, "resolve_openai_rename_mode", return_value="tasks")
    mocker.patch.object(app_main, "resolve_openai_rename_profile", return_value="light")
    mocker.patch.object(
        app_main,
        "resolve_openai_task_config",
        return_value={"profile": "light", "queue": "openai-rename-light", "service_url": "https://rename"},
    )
    create_job_mock = mocker.patch.object(app_main, "create_openai_job", return_value=None)
    enqueue_mock = mocker.patch.object(app_main, "enqueue_openai_rename_task", return_value="tasks/rename-12")
    mocker.patch.object(app_main, "update_openai_job", return_value=None)
    inline_openai_mock = mocker.patch.object(app_main, "run_openai_rename_on_pdf")

    response = client.post(
        "/api/renames/ai",
        json={"sessionId": "sess-1", "schemaId": "schema_1", "templateFields": [_template_field_payload()]},
        headers=auth_headers,
    )

    assert response.status_code == 200
    create_kwargs = create_job_mock.call_args.kwargs
    assert create_kwargs["credits"] == 6
    assert create_kwargs["credit_pricing"]["totalCredits"] == 6
    enqueue_payload = enqueue_mock.call_args.args[0]
    assert enqueue_payload["credits"] == 6
    assert enqueue_payload["pageCount"] == 12
    assert enqueue_payload["creditPricing"]["totalCredits"] == 6
    inline_openai_mock.assert_not_called()
