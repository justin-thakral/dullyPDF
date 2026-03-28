from __future__ import annotations

import base64

from backend.firebaseDB.template_api_endpoint_database import (
    TemplateApiEndpointRecord,
    TemplateApiMonthlyLimitExceededError,
)
from fastapi import HTTPException


def _basic_auth(secret: str) -> dict[str, str]:
    token = base64.b64encode(f"{secret}:".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _endpoint_record(
    *,
    status: str = "active",
    key_prefix: str = "dpa_live_secret",
    secret_hash: str = "hash",
    snapshot: dict | None = None,
) -> TemplateApiEndpointRecord:
    return TemplateApiEndpointRecord(
        id="tep-1",
        user_id="user_base",
        template_id="tpl-1",
        template_name="Patient Intake",
        status=status,
        snapshot_version=2,
        key_prefix=key_prefix,
        secret_hash=secret_hash,
        snapshot=snapshot
        or {
            "version": 1,
            "templateName": "Patient Intake",
            "defaultExportMode": "flat",
            "fields": [{"name": "full_name", "type": "text", "page": 1, "rect": [1, 2, 3, 4]}],
            "checkboxRules": [],
            "textTransformRules": [],
            "radioGroups": [],
        },
        created_at="2024-01-01T00:00:00+00:00",
        updated_at="2024-01-01T00:00:00+00:00",
        published_at="2024-01-01T00:00:00+00:00",
        last_used_at=None,
        usage_count=0,
        current_usage_month="2026-03",
        current_month_usage_count=0,
        auth_failure_count=0,
        validation_failure_count=0,
        runtime_failure_count=0,
        suspicious_failure_count=0,
        last_failure_at=None,
        last_failure_reason=None,
        audit_event_count=0,
    )


def test_public_template_api_schema_and_fill_route(
    client,
    app_main,
    mocker,
    tmp_path,
) -> None:
    output_path = tmp_path / "filled.pdf"
    output_path.write_bytes(b"%PDF-1.4\n%mock\n")
    output_size = output_path.stat().st_size
    cleanup_targets = [output_path]

    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "get_user_profile", return_value=None)
    mocker.patch.object(app_main, "normalize_role", return_value="base")
    mocker.patch.object(app_main, "resolve_template_api_active_limit", return_value=1)
    mocker.patch.object(app_main, "resolve_template_api_requests_monthly_limit", return_value=250)
    mocker.patch.object(app_main, "resolve_template_api_max_pages", return_value=25)
    mocker.patch.object(app_main, "create_template_api_endpoint_event", return_value=None)
    mocker.patch.object(app_main, "get_template_api_endpoint_public_metadata", return_value=_endpoint_record())
    mocker.patch.object(app_main, "get_template_api_endpoint_public", return_value=_endpoint_record())
    mocker.patch.object(app_main, "verify_template_api_secret", return_value=True)
    mocker.patch.object(
        app_main,
        "build_template_api_schema",
        return_value={"fields": [{"key": "full_name"}], "checkboxFields": [], "checkboxGroups": [], "radioGroups": []},
    )
    resolve_data_mock = mocker.patch.object(
        app_main,
        "resolve_template_api_request_data",
        return_value={"full_name": "Ada Lovelace"},
    )
    materialize_mock = mocker.patch.object(
        app_main,
        "materialize_template_api_snapshot",
        return_value=(output_path, cleanup_targets, "patient-intake.pdf"),
    )
    record_success_mock = mocker.patch.object(app_main, "record_template_api_endpoint_success", return_value=_endpoint_record())

    schema_response = client.get("/api/v1/fill/tep-1/schema", headers=_basic_auth("dpa_live_secret"))

    assert schema_response.status_code == 200
    assert schema_response.headers["cache-control"] == "private, no-store"
    assert schema_response.json() == {
        "endpoint": {
            "id": "tep-1",
            "templateName": "Patient Intake",
            "status": "active",
            "snapshotVersion": 2,
            "fillPath": "/api/v1/fill/tep-1.pdf",
            "schemaPath": "/api/v1/fill/tep-1/schema",
        },
        "schema": {"fields": [{"key": "full_name"}], "checkboxFields": [], "checkboxGroups": [], "radioGroups": []},
    }

    fill_response = client.post(
        "/api/v1/fill/tep-1.pdf",
        json={
            "data": {"full_name": "Ada Lovelace"},
            "filename": "patient-intake-final.pdf",
            "exportMode": "editable",
            "strict": True,
        },
        headers=_basic_auth("dpa_live_secret"),
    )

    assert fill_response.status_code == 200
    assert fill_response.headers["content-type"] == "application/pdf"
    assert fill_response.headers["cache-control"] == "private, no-store"
    resolve_data_mock.assert_called_once_with(
        _endpoint_record().snapshot,
        {"full_name": "Ada Lovelace"},
        strict=True,
    )
    materialize_mock.assert_called_once_with(
        _endpoint_record().snapshot,
        data={"full_name": "Ada Lovelace"},
        export_mode="editable",
        filename="patient-intake-final.pdf",
    )
    record_success_mock.assert_called_once()
    assert record_success_mock.call_args.args == ("tep-1",)
    assert record_success_mock.call_args.kwargs["month_key"] == "2026-03"
    assert record_success_mock.call_args.kwargs["monthly_limit"] == 250
    assert record_success_mock.call_args.kwargs["metadata"]["strict"] is True
    assert record_success_mock.call_args.kwargs["metadata"]["responseBytes"] == output_size


def test_public_template_api_fill_requires_valid_basic_auth(client, app_main, mocker) -> None:
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    get_metadata_mock = mocker.patch.object(app_main, "get_template_api_endpoint_public_metadata", return_value=None)
    get_endpoint_mock = mocker.patch.object(app_main, "get_template_api_endpoint_public")

    response = client.post("/api/v1/fill/tep-1.pdf", json={"data": {"full_name": "Ada Lovelace"}})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Basic realm="API Fill"'
    get_metadata_mock.assert_not_called()
    get_endpoint_mock.assert_not_called()


def test_public_template_api_fill_preserves_auth_error_when_telemetry_writes_fail(client, app_main, mocker) -> None:
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "get_template_api_endpoint_public_metadata", return_value=_endpoint_record())
    mocker.patch.object(app_main, "record_template_api_endpoint_failure", side_effect=RuntimeError("firestore unavailable"))
    mocker.patch.object(app_main, "create_template_api_endpoint_event", side_effect=RuntimeError("firestore unavailable"))

    response = client.post(
        "/api/v1/fill/tep-1.pdf",
        json={"data": {"full_name": "Ada Lovelace"}},
        headers=_basic_auth("dpa_live_other_secret"),
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Basic realm="API Fill"'


def test_public_template_api_fill_skips_endpoint_auth_failure_bucket_for_missing_endpoint(client, app_main, mocker) -> None:
    seen_keys: list[str] = []

    def _record_rate_limit_key(key: str, *, limit: int, window_seconds: int, fail_closed: bool = False) -> bool:
        seen_keys.append(key)
        return True

    mocker.patch.object(app_main, "check_rate_limit", side_effect=_record_rate_limit_key)
    mocker.patch.object(app_main, "get_template_api_endpoint_public_metadata", return_value=None)
    record_failure_mock = mocker.patch.object(app_main, "record_template_api_endpoint_failure")
    create_event_mock = mocker.patch.object(app_main, "create_template_api_endpoint_event")

    response = client.post(
        "/api/v1/fill/does-not-exist.pdf",
        json={"data": {"full_name": "Ada Lovelace"}},
        headers=_basic_auth("dpa_live_secret"),
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Basic realm="API Fill"'
    assert all("auth_failures:endpoint:" not in key for key in seen_keys)
    record_failure_mock.assert_not_called()
    create_event_mock.assert_not_called()


def test_public_template_api_schema_skips_endpoint_auth_failure_bucket_for_missing_endpoint(client, app_main, mocker) -> None:
    seen_keys: list[str] = []

    def _record_rate_limit_key(key: str, *, limit: int, window_seconds: int, fail_closed: bool = False) -> bool:
        seen_keys.append(key)
        return True

    mocker.patch.object(app_main, "check_rate_limit", side_effect=_record_rate_limit_key)
    mocker.patch.object(app_main, "get_template_api_endpoint_public_metadata", return_value=None)
    record_failure_mock = mocker.patch.object(app_main, "record_template_api_endpoint_failure")
    create_event_mock = mocker.patch.object(app_main, "create_template_api_endpoint_event")

    response = client.get(
        "/api/v1/fill/does-not-exist/schema",
        headers=_basic_auth("dpa_live_secret"),
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Basic realm="API Fill"'
    assert all("auth_failures:endpoint:" not in key for key in seen_keys)
    record_failure_mock.assert_not_called()
    create_event_mock.assert_not_called()


def test_public_template_api_fill_authenticates_before_body_parsing(client, app_main, mocker) -> None:
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    get_metadata_mock = mocker.patch.object(app_main, "get_template_api_endpoint_public_metadata", return_value=None)
    get_endpoint_mock = mocker.patch.object(app_main, "get_template_api_endpoint_public")

    response = client.post(
        "/api/v1/fill/tep-1.pdf",
        content='{"data":',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Basic realm="API Fill"'
    get_metadata_mock.assert_not_called()
    get_endpoint_mock.assert_not_called()


def test_public_template_api_fill_rejects_malformed_basic_auth_without_metadata_lookup(client, app_main, mocker) -> None:
    malformed_token = base64.b64encode(b"dpa_live_secret:not-blank").decode("ascii")
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    get_metadata_mock = mocker.patch.object(app_main, "get_template_api_endpoint_public_metadata", return_value=None)
    get_endpoint_mock = mocker.patch.object(app_main, "get_template_api_endpoint_public")

    response = client.post(
        "/api/v1/fill/tep-1.pdf",
        json={"data": {"full_name": "Ada Lovelace"}},
        headers={"Authorization": f"Basic {malformed_token}"},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Basic realm="API Fill"'
    get_metadata_mock.assert_not_called()
    get_endpoint_mock.assert_not_called()


def test_public_template_api_fill_blocks_disallowed_browser_origins(client, app_main, mocker) -> None:
    mocker.patch.object(app_main, "resolve_cors_origins", return_value=["https://app.example.com"])
    get_endpoint_mock = mocker.patch.object(app_main, "get_template_api_endpoint_public")

    response = client.post(
        "/api/v1/fill/tep-1.pdf",
        content='{"data":{"full_name":"Ada Lovelace"}}',
        headers={
            **_basic_auth("dpa_live_secret"),
            "Content-Type": "application/json",
            "Origin": "https://evil.example.com",
        },
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Origin not allowed."}
    get_endpoint_mock.assert_not_called()


def test_public_template_api_fill_rejects_wrong_key_prefix_before_snapshot_read(client, app_main, mocker) -> None:
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(
        app_main,
        "get_template_api_endpoint_public_metadata",
        return_value=_endpoint_record(key_prefix="dpa_live_expected"),
    )
    get_endpoint_mock = mocker.patch.object(app_main, "get_template_api_endpoint_public")
    verify_secret_mock = mocker.patch.object(app_main, "verify_template_api_secret")

    response = client.post(
        "/api/v1/fill/tep-1.pdf",
        json={"data": {"full_name": "Ada Lovelace"}},
        headers=_basic_auth("dpa_live_secret"),
    )

    assert response.status_code == 401
    get_endpoint_mock.assert_not_called()
    verify_secret_mock.assert_not_called()


def test_public_template_api_fill_requires_json_content_type(client, app_main, mocker) -> None:
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "get_template_api_endpoint_public_metadata", return_value=_endpoint_record())
    mocker.patch.object(app_main, "get_template_api_endpoint_public", return_value=_endpoint_record())
    mocker.patch.object(app_main, "verify_template_api_secret", return_value=True)
    resolve_data_mock = mocker.patch.object(app_main, "resolve_template_api_request_data")

    response = client.post(
        "/api/v1/fill/tep-1.pdf",
        content='{"data":{"full_name":"Ada Lovelace"}}',
        headers={
            **_basic_auth("dpa_live_secret"),
            "Content-Type": "text/plain",
        },
    )

    assert response.status_code == 415
    assert response.json() == {"detail": "API Fill requests must use application/json."}
    resolve_data_mock.assert_not_called()


def test_public_template_api_fill_rejects_unknown_top_level_request_fields(client, app_main, mocker) -> None:
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "get_user_profile", return_value=None)
    mocker.patch.object(app_main, "normalize_role", return_value="base")
    mocker.patch.object(app_main, "resolve_template_api_active_limit", return_value=1)
    mocker.patch.object(app_main, "resolve_template_api_requests_monthly_limit", return_value=250)
    mocker.patch.object(app_main, "resolve_template_api_max_pages", return_value=25)
    mocker.patch.object(app_main, "create_template_api_endpoint_event", return_value=None)
    mocker.patch.object(app_main, "get_template_api_endpoint_public_metadata", return_value=_endpoint_record())
    mocker.patch.object(app_main, "get_template_api_endpoint_public", return_value=_endpoint_record())
    mocker.patch.object(app_main, "verify_template_api_secret", return_value=True)
    record_failure_mock = mocker.patch.object(app_main, "record_template_api_endpoint_failure", return_value=_endpoint_record())
    resolve_data_mock = mocker.patch.object(app_main, "resolve_template_api_request_data")

    response = client.post(
        "/api/v1/fill/tep-1.pdf",
        json={
            "data": {"full_name": "Ada Lovelace"},
            "export_mode": "editable",
        },
        headers=_basic_auth("dpa_live_secret"),
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {
                "loc": ["export_mode"],
                "msg": "Extra inputs are not permitted",
                "type": "extra_forbidden",
            }
        ]
    }
    record_failure_mock.assert_called_once()
    resolve_data_mock.assert_not_called()


def test_public_template_api_schema_rejects_conflicting_published_snapshot(client, app_main, mocker) -> None:
    conflicting_snapshot = {
        "version": 1,
        "defaultExportMode": "flat",
        "fields": [
            {"name": "consent_group", "type": "text", "page": 1, "rect": [1, 2, 3, 4]},
            {
                "name": "consent_yes",
                "type": "checkbox",
                "page": 1,
                "rect": [1, 2, 3, 4],
                "groupKey": "consent_group",
                "optionKey": "yes",
                "optionLabel": "Yes",
            },
            {
                "name": "consent_no",
                "type": "checkbox",
                "page": 1,
                "rect": [1, 2, 3, 4],
                "groupKey": "consent_group",
                "optionKey": "no",
                "optionLabel": "No",
            },
        ],
        "checkboxRules": [],
        "textTransformRules": [],
        "radioGroups": [],
    }

    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "get_template_api_endpoint_public_metadata", return_value=_endpoint_record(snapshot=conflicting_snapshot))
    mocker.patch.object(app_main, "get_template_api_endpoint_public", return_value=_endpoint_record(snapshot=conflicting_snapshot))
    mocker.patch.object(app_main, "verify_template_api_secret", return_value=True)

    response = client.get(
        "/api/v1/fill/tep-1/schema",
        headers=_basic_auth("dpa_live_secret"),
    )

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Published API Fill schema is invalid. Ask the template owner to republish the endpoint."
    }


def test_public_template_api_fill_does_not_store_raw_payload_values_in_validation_failures(client, app_main, mocker) -> None:
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "get_user_profile", return_value=None)
    mocker.patch.object(app_main, "normalize_role", return_value="base")
    mocker.patch.object(app_main, "resolve_template_api_active_limit", return_value=1)
    mocker.patch.object(app_main, "resolve_template_api_requests_monthly_limit", return_value=250)
    mocker.patch.object(app_main, "resolve_template_api_max_pages", return_value=25)
    mocker.patch.object(app_main, "create_template_api_endpoint_event", return_value=None)
    mocker.patch.object(app_main, "get_template_api_endpoint_public_metadata", return_value=_endpoint_record())
    mocker.patch.object(app_main, "get_template_api_endpoint_public", return_value=_endpoint_record())
    mocker.patch.object(app_main, "verify_template_api_secret", return_value=True)
    record_failure_mock = mocker.patch.object(app_main, "record_template_api_endpoint_failure", return_value=_endpoint_record())

    response = client.post(
        "/api/v1/fill/tep-1.pdf",
        json={"data": ["123-45-6789", "alice@example.com"]},
        headers=_basic_auth("dpa_live_secret"),
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {
                "loc": ["data"],
                "msg": "Input should be a valid dictionary",
                "type": "dict_type",
            }
        ]
    }
    stored_reason = record_failure_mock.call_args.kwargs["reason"]
    assert "123-45-6789" not in stored_reason
    assert "alice@example.com" not in stored_reason


def test_public_template_api_fill_treats_conflicting_published_schema_as_runtime_failure(client, app_main, mocker) -> None:
    conflicting_snapshot = {
        "version": 1,
        "defaultExportMode": "flat",
        "fields": [
            {"name": "consent_group", "type": "text", "page": 1, "rect": [1, 2, 3, 4]},
            {
                "name": "consent_yes",
                "type": "checkbox",
                "page": 1,
                "rect": [1, 2, 3, 4],
                "groupKey": "consent_group",
                "optionKey": "yes",
                "optionLabel": "Yes",
            },
            {
                "name": "consent_no",
                "type": "checkbox",
                "page": 1,
                "rect": [1, 2, 3, 4],
                "groupKey": "consent_group",
                "optionKey": "no",
                "optionLabel": "No",
            },
        ],
        "checkboxRules": [],
        "textTransformRules": [],
        "radioGroups": [],
    }

    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "get_template_api_endpoint_public_metadata", return_value=_endpoint_record(snapshot=conflicting_snapshot))
    mocker.patch.object(app_main, "get_template_api_endpoint_public", return_value=_endpoint_record(snapshot=conflicting_snapshot))
    mocker.patch.object(app_main, "verify_template_api_secret", return_value=True)
    runtime_failure_mock = mocker.patch.object(app_main, "_record_runtime_failure", return_value=None)
    validation_failure_mock = mocker.patch.object(app_main, "_record_failure_counters", return_value=None)

    response = client.post(
        "/api/v1/fill/tep-1.pdf",
        json={"data": {"consent_group": ["yes"]}},
        headers=_basic_auth("dpa_live_secret"),
    )

    assert response.status_code == 500
    assert "conflicting keys after normalization" in response.json()["detail"]
    runtime_failure_mock.assert_called_once()
    validation_failure_mock.assert_not_called()


def test_public_template_api_fill_requires_data_top_level_field(client, app_main, mocker) -> None:
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "get_user_profile", return_value=None)
    mocker.patch.object(app_main, "normalize_role", return_value="base")
    mocker.patch.object(app_main, "resolve_template_api_active_limit", return_value=1)
    mocker.patch.object(app_main, "resolve_template_api_requests_monthly_limit", return_value=250)
    mocker.patch.object(app_main, "resolve_template_api_max_pages", return_value=25)
    mocker.patch.object(app_main, "create_template_api_endpoint_event", return_value=None)
    mocker.patch.object(app_main, "get_template_api_endpoint_public_metadata", return_value=_endpoint_record())
    mocker.patch.object(app_main, "get_template_api_endpoint_public", return_value=_endpoint_record())
    mocker.patch.object(app_main, "verify_template_api_secret", return_value=True)
    record_failure_mock = mocker.patch.object(app_main, "record_template_api_endpoint_failure", return_value=_endpoint_record())
    resolve_data_mock = mocker.patch.object(app_main, "resolve_template_api_request_data")

    response = client.post(
        "/api/v1/fill/tep-1.pdf",
        json={"fields": {"full_name": "Ada Lovelace"}},
        headers=_basic_auth("dpa_live_secret"),
    )

    assert response.status_code == 422
    record_failure_mock.assert_called_once()
    resolve_data_mock.assert_not_called()


def test_public_template_api_fill_rejects_misspelled_strict_flag(client, app_main, mocker) -> None:
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "get_user_profile", return_value=None)
    mocker.patch.object(app_main, "normalize_role", return_value="base")
    mocker.patch.object(app_main, "resolve_template_api_active_limit", return_value=1)
    mocker.patch.object(app_main, "resolve_template_api_requests_monthly_limit", return_value=250)
    mocker.patch.object(app_main, "resolve_template_api_max_pages", return_value=25)
    mocker.patch.object(app_main, "create_template_api_endpoint_event", return_value=None)
    mocker.patch.object(app_main, "get_template_api_endpoint_public_metadata", return_value=_endpoint_record())
    mocker.patch.object(app_main, "get_template_api_endpoint_public", return_value=_endpoint_record())
    mocker.patch.object(app_main, "verify_template_api_secret", return_value=True)
    record_failure_mock = mocker.patch.object(app_main, "record_template_api_endpoint_failure", return_value=_endpoint_record())
    resolve_data_mock = mocker.patch.object(app_main, "resolve_template_api_request_data")

    response = client.post(
        "/api/v1/fill/tep-1.pdf",
        json={"data": {"full_name": "Ada Lovelace"}, "stict": True},
        headers=_basic_auth("dpa_live_secret"),
    )

    assert response.status_code == 422
    record_failure_mock.assert_called_once()
    resolve_data_mock.assert_not_called()


def test_public_template_api_fill_preserves_validation_error_when_telemetry_writes_fail(client, app_main, mocker) -> None:
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "get_user_profile", return_value=None)
    mocker.patch.object(app_main, "normalize_role", return_value="base")
    mocker.patch.object(app_main, "resolve_template_api_active_limit", return_value=1)
    mocker.patch.object(app_main, "resolve_template_api_requests_monthly_limit", return_value=250)
    mocker.patch.object(app_main, "resolve_template_api_max_pages", return_value=25)
    mocker.patch.object(app_main, "get_template_api_endpoint_public_metadata", return_value=_endpoint_record())
    mocker.patch.object(app_main, "get_template_api_endpoint_public", return_value=_endpoint_record())
    mocker.patch.object(app_main, "verify_template_api_secret", return_value=True)
    mocker.patch.object(app_main, "record_template_api_endpoint_failure", side_effect=RuntimeError("firestore unavailable"))
    mocker.patch.object(app_main, "create_template_api_endpoint_event", side_effect=RuntimeError("firestore unavailable"))

    response = client.post(
        "/api/v1/fill/tep-1.pdf",
        json={"data": ["123-45-6789", "alice@example.com"]},
        headers=_basic_auth("dpa_live_secret"),
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {
                "loc": ["data"],
                "msg": "Input should be a valid dictionary",
                "type": "dict_type",
            }
        ]
    }


def test_public_template_api_fill_propagates_request_validation_errors(client, app_main, mocker) -> None:
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "get_user_profile", return_value=None)
    mocker.patch.object(app_main, "normalize_role", return_value="base")
    mocker.patch.object(app_main, "resolve_template_api_active_limit", return_value=1)
    mocker.patch.object(app_main, "resolve_template_api_requests_monthly_limit", return_value=250)
    mocker.patch.object(app_main, "resolve_template_api_max_pages", return_value=25)
    mocker.patch.object(app_main, "create_template_api_endpoint_event", return_value=None)
    mocker.patch.object(app_main, "get_template_api_endpoint_public_metadata", return_value=_endpoint_record())
    mocker.patch.object(app_main, "get_template_api_endpoint_public", return_value=_endpoint_record())
    mocker.patch.object(app_main, "verify_template_api_secret", return_value=True)
    record_failure_mock = mocker.patch.object(app_main, "record_template_api_endpoint_failure", return_value=_endpoint_record())
    mocker.patch.object(
        app_main,
        "resolve_template_api_request_data",
        side_effect=HTTPException(status_code=400, detail="Unknown API Fill keys: ignored_key."),
    )

    response = client.post(
        "/api/v1/fill/tep-1.pdf",
        json={"data": {"ignored_key": "value"}, "strict": True},
        headers=_basic_auth("dpa_live_secret"),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Unknown API Fill keys: ignored_key."}
    record_failure_mock.assert_called_once()


def test_public_template_api_fill_truncates_stored_failure_reasons(client, app_main, mocker) -> None:
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "get_user_profile", return_value=None)
    mocker.patch.object(app_main, "normalize_role", return_value="base")
    mocker.patch.object(app_main, "resolve_template_api_active_limit", return_value=1)
    mocker.patch.object(app_main, "resolve_template_api_requests_monthly_limit", return_value=250)
    mocker.patch.object(app_main, "resolve_template_api_max_pages", return_value=25)
    mocker.patch.object(app_main, "create_template_api_endpoint_event", return_value=None)
    mocker.patch.object(app_main, "get_template_api_endpoint_public_metadata", return_value=_endpoint_record())
    mocker.patch.object(app_main, "get_template_api_endpoint_public", return_value=_endpoint_record())
    mocker.patch.object(app_main, "verify_template_api_secret", return_value=True)
    record_failure_mock = mocker.patch.object(app_main, "record_template_api_endpoint_failure", return_value=_endpoint_record())
    mocker.patch.object(
        app_main,
        "resolve_template_api_request_data",
        side_effect=HTTPException(status_code=400, detail="x" * 4000),
    )

    response = client.post(
        "/api/v1/fill/tep-1.pdf",
        json={"data": {"full_name": "Ada Lovelace"}, "strict": True},
        headers=_basic_auth("dpa_live_secret"),
    )

    assert response.status_code == 400
    reason = record_failure_mock.call_args.kwargs["reason"]
    assert len(reason) <= 512
    assert reason.endswith("...")


def test_public_template_api_fill_does_not_consume_quota_when_materialization_fails(client, app_main, mocker) -> None:
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "get_user_profile", return_value=None)
    mocker.patch.object(app_main, "normalize_role", return_value="base")
    mocker.patch.object(app_main, "resolve_template_api_active_limit", return_value=1)
    mocker.patch.object(app_main, "resolve_template_api_requests_monthly_limit", return_value=250)
    mocker.patch.object(app_main, "resolve_template_api_max_pages", return_value=25)
    record_success_mock = mocker.patch.object(app_main, "record_template_api_endpoint_success")
    mocker.patch.object(app_main, "create_template_api_endpoint_event", return_value=None)
    mocker.patch.object(app_main, "get_template_api_endpoint_public_metadata", return_value=_endpoint_record())
    mocker.patch.object(app_main, "get_template_api_endpoint_public", return_value=_endpoint_record())
    mocker.patch.object(app_main, "verify_template_api_secret", return_value=True)
    mocker.patch.object(
        app_main,
        "resolve_template_api_request_data",
        return_value={"full_name": "Ada Lovelace"},
    )
    mocker.patch.object(
        app_main,
        "materialize_template_api_snapshot",
        side_effect=FileNotFoundError("Saved form PDF is unavailable for respondent download."),
    )

    response = client.post(
        "/api/v1/fill/tep-1.pdf",
        json={"data": {"full_name": "Ada Lovelace"}},
        headers=_basic_auth("dpa_live_secret"),
    )

    assert response.status_code == 404
    record_success_mock.assert_not_called()


def test_public_template_api_fill_preserves_runtime_error_when_telemetry_writes_fail(client, app_main, mocker) -> None:
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "get_user_profile", return_value=None)
    mocker.patch.object(app_main, "normalize_role", return_value="base")
    mocker.patch.object(app_main, "resolve_template_api_active_limit", return_value=1)
    mocker.patch.object(app_main, "resolve_template_api_requests_monthly_limit", return_value=250)
    mocker.patch.object(app_main, "resolve_template_api_max_pages", return_value=25)
    record_success_mock = mocker.patch.object(app_main, "record_template_api_endpoint_success")
    mocker.patch.object(app_main, "get_template_api_endpoint_public_metadata", return_value=_endpoint_record())
    mocker.patch.object(app_main, "get_template_api_endpoint_public", return_value=_endpoint_record())
    mocker.patch.object(app_main, "verify_template_api_secret", return_value=True)
    mocker.patch.object(
        app_main,
        "resolve_template_api_request_data",
        return_value={"full_name": "Ada Lovelace"},
    )
    mocker.patch.object(
        app_main,
        "materialize_template_api_snapshot",
        side_effect=FileNotFoundError("Saved form PDF is unavailable for respondent download."),
    )
    mocker.patch.object(app_main, "record_template_api_endpoint_failure", side_effect=RuntimeError("firestore unavailable"))
    mocker.patch.object(app_main, "create_template_api_endpoint_event", side_effect=RuntimeError("firestore unavailable"))

    response = client.post(
        "/api/v1/fill/tep-1.pdf",
        json={"data": {"full_name": "Ada Lovelace"}},
        headers=_basic_auth("dpa_live_secret"),
    )

    assert response.status_code == 404
    record_success_mock.assert_not_called()


def test_public_template_api_fill_returns_runtime_error_when_success_bookkeeping_fails(client, app_main, mocker, tmp_path) -> None:
    output_path = tmp_path / "filled.pdf"
    output_path.write_bytes(b"%PDF-1.4\n%mock\n")

    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "get_user_profile", return_value=None)
    mocker.patch.object(app_main, "normalize_role", return_value="base")
    mocker.patch.object(app_main, "resolve_template_api_active_limit", return_value=1)
    mocker.patch.object(app_main, "resolve_template_api_requests_monthly_limit", return_value=250)
    mocker.patch.object(app_main, "resolve_template_api_max_pages", return_value=25)
    mocker.patch.object(app_main, "create_template_api_endpoint_event", return_value=None)
    mocker.patch.object(app_main, "get_template_api_endpoint_public_metadata", return_value=_endpoint_record())
    mocker.patch.object(app_main, "get_template_api_endpoint_public", return_value=_endpoint_record())
    mocker.patch.object(app_main, "verify_template_api_secret", return_value=True)
    mocker.patch.object(
        app_main,
        "resolve_template_api_request_data",
        return_value={"full_name": "Ada Lovelace"},
    )
    mocker.patch.object(
        app_main,
        "materialize_template_api_snapshot",
        return_value=(output_path, [output_path], "patient-intake.pdf"),
    )
    mocker.patch.object(app_main, "record_template_api_endpoint_success", side_effect=RuntimeError("firestore unavailable"))
    runtime_failure_mock = mocker.patch.object(app_main, "_record_runtime_failure", return_value=None)

    response = client.post(
        "/api/v1/fill/tep-1.pdf",
        json={"data": {"full_name": "Ada Lovelace"}},
        headers=_basic_auth("dpa_live_secret"),
    )

    assert response.status_code == 500
    runtime_failure_mock.assert_called_once()


def test_public_template_api_fill_limits_repeated_auth_failures_per_endpoint(client, app_main, mocker) -> None:
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "get_template_api_endpoint_public_metadata", return_value=_endpoint_record())
    mocker.patch.object(app_main, "_check_endpoint_rate_limit", return_value=False)
    record_failure_mock = mocker.patch.object(app_main, "record_template_api_endpoint_failure")
    create_event_mock = mocker.patch.object(app_main, "create_template_api_endpoint_event")

    response = client.post(
        "/api/v1/fill/tep-1.pdf",
        json={"data": {"full_name": "Ada Lovelace"}},
        headers=_basic_auth("dpa_live_secret"),
    )

    assert response.status_code == 429
    assert response.json() == {"detail": "Too many API Fill authentication failures for this endpoint. Please wait and try again."}
    record_failure_mock.assert_not_called()
    create_event_mock.assert_not_called()


def test_public_template_api_schema_limits_repeated_auth_failures_per_endpoint(client, app_main, mocker) -> None:
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "get_template_api_endpoint_public_metadata", return_value=_endpoint_record())
    mocker.patch.object(app_main, "_check_endpoint_rate_limit", return_value=False)
    record_failure_mock = mocker.patch.object(app_main, "record_template_api_endpoint_failure")
    create_event_mock = mocker.patch.object(app_main, "create_template_api_endpoint_event")

    response = client.get(
        "/api/v1/fill/tep-1/schema",
        headers=_basic_auth("dpa_live_secret"),
    )

    assert response.status_code == 429
    assert response.json() == {"detail": "Too many API Fill authentication failures for this endpoint. Please wait and try again."}
    record_failure_mock.assert_not_called()
    create_event_mock.assert_not_called()


def test_public_template_api_fill_blocks_when_monthly_quota_is_exhausted(client, app_main, mocker) -> None:
    mock_pdf_path = "/tmp/mock-filled.pdf"
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "get_user_profile", return_value=None)
    mocker.patch.object(app_main, "normalize_role", return_value="base")
    mocker.patch.object(app_main, "resolve_template_api_active_limit", return_value=1)
    mocker.patch.object(app_main, "resolve_template_api_requests_monthly_limit", return_value=10)
    mocker.patch.object(app_main, "resolve_template_api_max_pages", return_value=25)
    create_event_mock = mocker.patch.object(app_main, "create_template_api_endpoint_event", return_value=None)
    mocker.patch.object(app_main, "get_template_api_endpoint_public_metadata", return_value=_endpoint_record())
    mocker.patch.object(app_main, "get_template_api_endpoint_public", return_value=_endpoint_record())
    mocker.patch.object(app_main, "verify_template_api_secret", return_value=True)
    mocker.patch.object(
        app_main,
        "resolve_template_api_request_data",
        return_value={"full_name": "Ada Lovelace"},
    )
    mocker.patch.object(
        app_main,
        "materialize_template_api_snapshot",
        return_value=(mock_pdf_path, [mock_pdf_path], "patient-intake.pdf"),
    )
    mocker.patch.object(
        app_main,
        "record_template_api_endpoint_success",
        side_effect=TemplateApiMonthlyLimitExceededError(
            "This account has reached its monthly API Fill request limit."
        ),
    )
    runtime_failure_mock = mocker.patch.object(app_main, "_record_runtime_failure", return_value=None)
    cleanup_mock = mocker.patch.object(app_main, "cleanup_paths", return_value=None)

    response = client.post(
        "/api/v1/fill/tep-1.pdf",
        json={"data": {"full_name": "Ada Lovelace"}},
        headers=_basic_auth("dpa_live_secret"),
    )

    assert response.status_code == 429
    assert "monthly api fill request limit" in response.json()["detail"].lower()
    assert create_event_mock.call_args.kwargs["event_type"] == "fill_quota_blocked"
    runtime_failure_mock.assert_not_called()
    cleanup_mock.assert_called_once_with([mock_pdf_path])


def test_public_template_api_fill_records_plan_blocks_separately_from_quota(client, app_main, mocker) -> None:
    over_limit_snapshot = {
        **_endpoint_record().snapshot,
        "pageCount": 40,
    }
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "get_user_profile", return_value=None)
    mocker.patch.object(app_main, "normalize_role", return_value="base")
    mocker.patch.object(app_main, "resolve_template_api_active_limit", return_value=1)
    mocker.patch.object(app_main, "resolve_template_api_requests_monthly_limit", return_value=250)
    mocker.patch.object(app_main, "resolve_template_api_max_pages", return_value=25)
    create_event_mock = mocker.patch.object(app_main, "create_template_api_endpoint_event", return_value=None)
    mocker.patch.object(app_main, "get_template_api_endpoint_public_metadata", return_value=_endpoint_record(snapshot=over_limit_snapshot))
    mocker.patch.object(app_main, "get_template_api_endpoint_public", return_value=_endpoint_record(snapshot=over_limit_snapshot))
    mocker.patch.object(app_main, "verify_template_api_secret", return_value=True)
    mocker.patch.object(
        app_main,
        "resolve_template_api_request_data",
        return_value={"full_name": "Ada Lovelace"},
    )

    response = client.post(
        "/api/v1/fill/tep-1.pdf",
        json={"data": {"full_name": "Ada Lovelace"}},
        headers=_basic_auth("dpa_live_secret"),
    )

    assert response.status_code == 403
    assert "limited to 25 pages" in response.json()["detail"].lower()
    assert create_event_mock.call_args.kwargs["event_type"] == "fill_plan_blocked"
