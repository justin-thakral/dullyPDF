from __future__ import annotations

import base64

from backend.firebaseDB.template_api_endpoint_database import TemplateApiEndpointRecord
from fastapi import HTTPException


def _basic_auth(secret: str) -> dict[str, str]:
    token = base64.b64encode(f"{secret}:".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _endpoint_record(*, status: str = "active", snapshot: dict | None = None) -> TemplateApiEndpointRecord:
    return TemplateApiEndpointRecord(
        id="tep-1",
        user_id="user_base",
        template_id="tpl-1",
        template_name="Patient Intake",
        status=status,
        snapshot_version=2,
        key_prefix="dpa_live_secret",
        secret_hash="hash",
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
    cleanup_targets = [output_path]

    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "get_user_profile", return_value=None)
    mocker.patch.object(app_main, "normalize_role", return_value="base")
    mocker.patch.object(app_main, "resolve_template_api_active_limit", return_value=1)
    mocker.patch.object(app_main, "resolve_template_api_requests_monthly_limit", return_value=250)
    mocker.patch.object(app_main, "resolve_template_api_max_pages", return_value=25)
    mocker.patch.object(app_main, "get_template_api_monthly_usage", return_value=None)
    mocker.patch.object(app_main, "create_template_api_endpoint_event", return_value=None)
    mocker.patch.object(app_main, "get_template_api_endpoint_for_secret", return_value=_endpoint_record())
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
    record_use_mock = mocker.patch.object(app_main, "record_template_api_endpoint_use", return_value=_endpoint_record())

    schema_response = client.get("/api/v1/fill/tep-1/schema", headers=_basic_auth("dpa_live_secret"))

    assert schema_response.status_code == 200
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
    record_use_mock.assert_called_once_with("tep-1")


def test_public_template_api_fill_requires_valid_basic_auth(client, app_main, mocker) -> None:
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "get_template_api_endpoint_public", return_value=None)

    response = client.post("/api/v1/fill/tep-1.pdf", json={"data": {"full_name": "Ada Lovelace"}})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Basic realm="API Fill"'


def test_public_template_api_fill_propagates_request_validation_errors(client, app_main, mocker) -> None:
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "get_user_profile", return_value=None)
    mocker.patch.object(app_main, "normalize_role", return_value="base")
    mocker.patch.object(app_main, "resolve_template_api_active_limit", return_value=1)
    mocker.patch.object(app_main, "resolve_template_api_requests_monthly_limit", return_value=250)
    mocker.patch.object(app_main, "resolve_template_api_max_pages", return_value=25)
    mocker.patch.object(app_main, "get_template_api_monthly_usage", return_value=None)
    mocker.patch.object(app_main, "create_template_api_endpoint_event", return_value=None)
    mocker.patch.object(app_main, "get_template_api_endpoint_for_secret", return_value=_endpoint_record())
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


def test_public_template_api_fill_blocks_when_monthly_quota_is_exhausted(client, app_main, mocker) -> None:
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "get_user_profile", return_value=None)
    mocker.patch.object(app_main, "normalize_role", return_value="base")
    mocker.patch.object(app_main, "resolve_template_api_active_limit", return_value=1)
    mocker.patch.object(app_main, "resolve_template_api_requests_monthly_limit", return_value=10)
    mocker.patch.object(app_main, "resolve_template_api_max_pages", return_value=25)
    mocker.patch.object(
        app_main,
        "get_template_api_monthly_usage",
        return_value=type("MonthlyUsage", (), {"request_count": 10, "month_key": "2026-03"})(),
    )
    mocker.patch.object(app_main, "create_template_api_endpoint_event", return_value=None)
    mocker.patch.object(app_main, "get_template_api_endpoint_for_secret", return_value=_endpoint_record())
    mocker.patch.object(app_main, "verify_template_api_secret", return_value=True)

    response = client.post(
        "/api/v1/fill/tep-1.pdf",
        json={"data": {"full_name": "Ada Lovelace"}},
        headers=_basic_auth("dpa_live_secret"),
    )

    assert response.status_code == 429
    assert "monthly api fill request limit" in response.json()["detail"].lower()
