from __future__ import annotations

from backend.firebaseDB.template_api_endpoint_database import (
    TemplateApiActiveEndpointLimitError,
    TemplateApiEndpointRecord,
    TemplateApiEndpointStatusError,
)
from backend.firebaseDB.template_database import TemplateRecord


def _patch_auth(mocker, app_main, user) -> None:
    mocker.patch.object(app_main, "_verify_token", return_value={"uid": user.app_user_id})
    mocker.patch.object(app_main, "ensure_user", return_value=user)


def _patch_limits(mocker, app_main) -> None:
    mocker.patch.object(app_main, "get_user_profile", return_value=None)
    mocker.patch.object(app_main, "normalize_role", return_value="base")
    mocker.patch.object(app_main, "get_template_api_monthly_usage", return_value=None)
    mocker.patch.object(app_main, "count_active_template_api_endpoints", return_value=1)
    mocker.patch.object(app_main, "resolve_template_api_active_limit", return_value=1)
    mocker.patch.object(app_main, "resolve_template_api_requests_monthly_limit", return_value=250)
    mocker.patch.object(app_main, "resolve_template_api_max_pages", return_value=25)
    mocker.patch.object(app_main, "list_template_api_endpoint_events", return_value=[])
    mocker.patch.object(app_main, "create_template_api_endpoint_event", return_value=None)


def _template_record() -> TemplateRecord:
    return TemplateRecord(
        id="tpl-1",
        pdf_bucket_path="gs://forms/patient-intake.pdf",
        template_bucket_path="gs://templates/patient-intake.json",
        metadata={"name": "Patient Intake"},
        created_at="2024-01-01T00:00:00+00:00",
        updated_at="2024-01-01T00:00:00+00:00",
        name="Patient Intake",
    )


def _endpoint_record(
    *,
    endpoint_id: str = "tep-1",
    template_id: str = "tpl-1",
    status: str = "active",
    snapshot_version: int = 1,
    key_prefix: str | None = "dpa_live_abc123",
    secret_hash: str | None = "hash",
    snapshot: dict | None = None,
    current_usage_month: str | None = "2026-03",
    current_month_usage_count: int = 0,
) -> TemplateApiEndpointRecord:
    return TemplateApiEndpointRecord(
        id=endpoint_id,
        user_id="user_base",
        template_id=template_id,
        template_name="Patient Intake",
        status=status,
        snapshot_version=snapshot_version,
        key_prefix=key_prefix,
        secret_hash=secret_hash,
        snapshot=snapshot
        or {
            "version": 1,
            "defaultExportMode": "flat",
            "fields": [{"name": "full_name", "type": "text", "page": 1, "rect": [1, 2, 3, 4]}],
            "checkboxRules": [],
            "textTransformRules": [],
        },
        created_at="2024-01-01T00:00:00+00:00",
        updated_at="2024-01-01T00:00:00+00:00",
        published_at="2024-01-01T00:00:00+00:00",
        last_used_at=None,
        usage_count=0,
        current_usage_month=current_usage_month,
        current_month_usage_count=current_month_usage_count,
        auth_failure_count=0,
        validation_failure_count=0,
        runtime_failure_count=0,
        suspicious_failure_count=0,
        last_failure_at=None,
        last_failure_reason=None,
        audit_event_count=0,
    )


def test_template_api_endpoints_list_publish_rotate_revoke_and_schema(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    _patch_limits(mocker, app_main)
    mocker.patch.object(app_main, "count_active_template_api_endpoints", return_value=0)

    mocker.patch.object(app_main, "list_template_api_endpoints", return_value=[_endpoint_record()])
    response = client.get("/api/template-api-endpoints", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["endpoints"] == [
        {
            "id": "tep-1",
            "templateId": "tpl-1",
            "templateName": "Patient Intake",
            "status": "active",
            "snapshotVersion": 1,
            "keyPrefix": "dpa_live_abc123",
            "createdAt": "2024-01-01T00:00:00+00:00",
            "updatedAt": "2024-01-01T00:00:00+00:00",
            "publishedAt": "2024-01-01T00:00:00+00:00",
            "lastUsedAt": None,
            "usageCount": 0,
            "currentUsageMonth": "2026-03",
            "currentMonthUsageCount": 0,
            "authFailureCount": 0,
            "validationFailureCount": 0,
            "runtimeFailureCount": 0,
            "suspiciousFailureCount": 0,
            "lastFailureAt": None,
            "lastFailureReason": None,
            "auditEventCount": 0,
            "fillPath": "/api/v1/fill/tep-1.pdf",
            "schemaPath": "/api/template-api-endpoints/tep-1/schema",
        }
    ]
    assert response.json()["limits"]["activeEndpointsMax"] == 1

    mocker.patch.object(app_main, "get_template", return_value=_template_record())
    mocker.patch.object(app_main, "build_template_api_snapshot", return_value={"version": 1, "defaultExportMode": "flat", "pageCount": 1})
    mocker.patch.object(app_main, "build_template_api_schema", return_value={"fields": [], "checkboxGroups": [], "radioGroups": []})
    mocker.patch.object(app_main, "generate_template_api_secret", return_value="dpa_live_secret")
    mocker.patch.object(app_main, "build_template_api_key_prefix", return_value="dpa_live_secret")
    mocker.patch.object(app_main, "hash_template_api_secret", return_value="hashed-secret")
    created_record = _endpoint_record(key_prefix="dpa_live_secret")
    publish_mock = mocker.patch.object(
        app_main,
        "publish_or_republish_template_api_endpoint",
        return_value=(created_record, True),
    )
    mocker.patch.object(app_main, "get_template_api_endpoint", return_value=created_record)

    create_response = client.post(
        "/api/template-api-endpoints",
        json={"templateId": "tpl-1", "exportMode": "flat"},
        headers=auth_headers,
    )

    assert create_response.status_code == 200
    assert create_response.headers["cache-control"] == "private, no-store"
    assert create_response.json()["created"] is True
    assert create_response.json()["secret"] == "dpa_live_secret"
    assert create_response.json()["limits"]["maxPagesPerRequest"] == 25
    publish_mock.assert_called_once_with(
        user_id="user_base",
        template_id="tpl-1",
        template_name="Patient Intake",
        active_limit=1,
        key_prefix="dpa_live_secret",
        secret_hash="hashed-secret",
        snapshot={"version": 1, "defaultExportMode": "flat", "pageCount": 1},
    )

    mocker.patch.object(app_main, "get_template_api_endpoint", return_value=_endpoint_record())
    update_rotate_mock = mocker.patch.object(
        app_main,
        "rotate_template_api_endpoint_secret_atomic",
        return_value=_endpoint_record(key_prefix="dpa_live_rotated"),
    )
    mocker.patch.object(app_main, "generate_template_api_secret", return_value="dpa_live_rotated")
    mocker.patch.object(app_main, "build_template_api_key_prefix", return_value="dpa_live_rotated")
    mocker.patch.object(app_main, "hash_template_api_secret", return_value="hashed-rotated")

    rotate_response = client.post("/api/template-api-endpoints/tep-1/rotate", headers=auth_headers)
    assert rotate_response.status_code == 200
    assert rotate_response.headers["cache-control"] == "private, no-store"
    assert rotate_response.json()["secret"] == "dpa_live_rotated"
    update_rotate_mock.assert_called_once_with(
        "tep-1",
        "user_base",
        key_prefix="dpa_live_rotated",
        secret_hash="hashed-rotated",
    )

    revoke_mock = mocker.patch.object(
        app_main,
        "revoke_template_api_endpoint_atomic",
        return_value=_endpoint_record(status="revoked"),
    )
    mocker.patch.object(
        app_main,
        "get_template_api_endpoint",
        side_effect=[_endpoint_record(), _endpoint_record(status="revoked")],
    )
    revoke_response = client.post("/api/template-api-endpoints/tep-1/revoke", headers=auth_headers)
    assert revoke_response.status_code == 200
    assert revoke_response.headers["cache-control"] == "private, no-store"
    assert revoke_response.json()["endpoint"]["status"] == "revoked"
    revoke_mock.assert_called_once_with("tep-1", "user_base")

    mocker.patch.object(app_main, "get_template_api_endpoint", return_value=_endpoint_record(status="revoked"))
    schema_response = client.get("/api/template-api-endpoints/tep-1/schema", headers=auth_headers)
    assert schema_response.status_code == 200
    assert schema_response.headers["cache-control"] == "private, no-store"
    assert schema_response.json()["schema"] == {"fields": [], "checkboxGroups": [], "radioGroups": []}


def test_template_api_owner_lifecycle_ignores_event_logging_failures(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    _patch_limits(mocker, app_main)
    mocker.patch.object(app_main, "create_template_api_endpoint_event", side_effect=RuntimeError("firestore unavailable"))
    mocker.patch.object(app_main, "count_active_template_api_endpoints", return_value=0)

    mocker.patch.object(app_main, "get_template", return_value=_template_record())
    mocker.patch.object(app_main, "build_template_api_snapshot", return_value={"version": 1, "defaultExportMode": "flat", "pageCount": 1})
    mocker.patch.object(app_main, "build_template_api_schema", return_value={"fields": [], "checkboxGroups": [], "radioGroups": []})
    mocker.patch.object(app_main, "generate_template_api_secret", return_value="dpa_live_secret")
    mocker.patch.object(app_main, "build_template_api_key_prefix", return_value="dpa_live_secret")
    mocker.patch.object(app_main, "hash_template_api_secret", return_value="hashed-secret")
    created_record = _endpoint_record(key_prefix="dpa_live_secret")
    mocker.patch.object(
        app_main,
        "publish_or_republish_template_api_endpoint",
        return_value=(created_record, True),
    )
    mocker.patch.object(app_main, "get_template_api_endpoint", return_value=created_record)

    create_response = client.post(
        "/api/template-api-endpoints",
        json={"templateId": "tpl-1", "exportMode": "flat"},
        headers=auth_headers,
    )

    assert create_response.status_code == 200
    assert create_response.json()["secret"] == "dpa_live_secret"

    mocker.patch.object(app_main, "get_template_api_endpoint", return_value=_endpoint_record())
    mocker.patch.object(
        app_main,
        "rotate_template_api_endpoint_secret_atomic",
        return_value=_endpoint_record(key_prefix="dpa_live_rotated"),
    )
    mocker.patch.object(app_main, "generate_template_api_secret", return_value="dpa_live_rotated")
    mocker.patch.object(app_main, "build_template_api_key_prefix", return_value="dpa_live_rotated")
    mocker.patch.object(app_main, "hash_template_api_secret", return_value="hashed-rotated")

    rotate_response = client.post("/api/template-api-endpoints/tep-1/rotate", headers=auth_headers)

    assert rotate_response.status_code == 200
    assert rotate_response.json()["secret"] == "dpa_live_rotated"

    mocker.patch.object(
        app_main,
        "revoke_template_api_endpoint_atomic",
        return_value=_endpoint_record(status="revoked"),
    )
    mocker.patch.object(
        app_main,
        "get_template_api_endpoint",
        side_effect=[_endpoint_record(), _endpoint_record(status="revoked")],
    )

    revoke_response = client.post("/api/template-api-endpoints/tep-1/revoke", headers=auth_headers)

    assert revoke_response.status_code == 200
    assert revoke_response.json()["endpoint"]["status"] == "revoked"


def test_template_api_publish_returns_secret_when_owner_detail_reads_fail(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    _patch_limits(mocker, app_main)
    mocker.patch.object(app_main, "count_active_template_api_endpoints", return_value=0)
    mocker.patch.object(app_main, "get_template", return_value=_template_record())
    mocker.patch.object(app_main, "build_template_api_snapshot", return_value={"version": 1, "defaultExportMode": "flat", "pageCount": 1})
    mocker.patch.object(app_main, "build_template_api_schema", return_value={"fields": [], "checkboxFields": [], "checkboxGroups": [], "radioGroups": []})
    mocker.patch.object(app_main, "generate_template_api_secret", return_value="dpa_live_secret")
    mocker.patch.object(app_main, "build_template_api_key_prefix", return_value="dpa_live_secret")
    mocker.patch.object(app_main, "hash_template_api_secret", return_value="hashed-secret")
    mocker.patch.object(
        app_main,
        "publish_or_republish_template_api_endpoint",
        return_value=(_endpoint_record(key_prefix="dpa_live_secret"), True),
    )
    mocker.patch.object(app_main, "_build_owner_limit_summary", side_effect=RuntimeError("firestore unavailable"))
    mocker.patch.object(app_main, "list_template_api_endpoint_events", side_effect=RuntimeError("firestore unavailable"))
    get_endpoint_mock = mocker.patch.object(
        app_main,
        "get_template_api_endpoint",
        side_effect=AssertionError("publish should not refetch the endpoint after mutation"),
    )

    response = client.post(
        "/api/template-api-endpoints",
        json={"templateId": "tpl-1", "exportMode": "flat"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["secret"] == "dpa_live_secret"
    assert response.json()["recentEvents"] == []
    assert response.json()["limits"]["activeEndpointsMax"] == 1
    assert response.json()["schema"] == {
        "fields": [],
        "checkboxFields": [],
        "checkboxGroups": [],
        "radioGroups": [],
    }
    get_endpoint_mock.assert_not_called()


def test_template_api_rotate_and_revoke_skip_post_mutation_refetch_when_owner_detail_reads_fail(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    _patch_limits(mocker, app_main)
    mocker.patch.object(app_main, "_build_owner_limit_summary", side_effect=RuntimeError("firestore unavailable"))
    mocker.patch.object(app_main, "list_template_api_endpoint_events", side_effect=RuntimeError("firestore unavailable"))

    get_endpoint_rotate_mock = mocker.patch.object(
        app_main,
        "get_template_api_endpoint",
        side_effect=[_endpoint_record(), AssertionError("rotate should not refetch the endpoint after mutation")],
    )
    mocker.patch.object(
        app_main,
        "rotate_template_api_endpoint_secret_atomic",
        return_value=_endpoint_record(key_prefix="dpa_live_rotated"),
    )
    mocker.patch.object(app_main, "generate_template_api_secret", return_value="dpa_live_rotated")
    mocker.patch.object(app_main, "build_template_api_key_prefix", return_value="dpa_live_rotated")
    mocker.patch.object(app_main, "hash_template_api_secret", return_value="hashed-rotated")

    rotate_response = client.post("/api/template-api-endpoints/tep-1/rotate", headers=auth_headers)

    assert rotate_response.status_code == 200
    assert rotate_response.json()["secret"] == "dpa_live_rotated"
    assert rotate_response.json()["recentEvents"] == []
    assert get_endpoint_rotate_mock.call_count == 1

    get_endpoint_revoke_mock = mocker.patch.object(
        app_main,
        "get_template_api_endpoint",
        side_effect=[_endpoint_record(), AssertionError("revoke should not refetch the endpoint after mutation")],
    )
    mocker.patch.object(
        app_main,
        "revoke_template_api_endpoint_atomic",
        return_value=_endpoint_record(status="revoked"),
    )

    revoke_response = client.post("/api/template-api-endpoints/tep-1/revoke", headers=auth_headers)

    assert revoke_response.status_code == 200
    assert revoke_response.json()["endpoint"]["status"] == "revoked"
    assert revoke_response.json()["recentEvents"] == []
    assert get_endpoint_revoke_mock.call_count == 1


def test_template_api_owner_read_routes_degrade_when_limit_and_event_reads_fail(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    primary_endpoint = _endpoint_record(current_usage_month=None)
    sibling_endpoint = _endpoint_record(endpoint_id="tep-2", template_id="tpl-2", current_usage_month="2026-04")

    def _list_endpoints(user_id: str, template_id: str | None = None):
        assert user_id == "user_base"
        return [primary_endpoint] if template_id == "tpl-1" else [primary_endpoint, sibling_endpoint]

    mocker.patch.object(app_main, "get_user_profile", return_value=None)
    mocker.patch.object(app_main, "normalize_role", return_value="base")
    mocker.patch.object(app_main, "resolve_template_api_active_limit", return_value=1)
    mocker.patch.object(app_main, "resolve_template_api_requests_monthly_limit", return_value=250)
    mocker.patch.object(app_main, "resolve_template_api_max_pages", return_value=25)
    mocker.patch.object(app_main, "list_template_api_endpoints", side_effect=_list_endpoints)
    mocker.patch.object(app_main, "get_template_api_monthly_usage", side_effect=RuntimeError("firestore unavailable"))
    mocker.patch.object(app_main, "count_active_template_api_endpoints", side_effect=RuntimeError("firestore unavailable"))
    mocker.patch.object(app_main, "get_template_api_endpoint", return_value=primary_endpoint)
    mocker.patch.object(app_main, "list_template_api_endpoint_events", side_effect=RuntimeError("firestore unavailable"))
    mocker.patch.object(
        app_main,
        "build_template_api_schema",
        return_value={"fields": [], "checkboxFields": [], "checkboxGroups": [], "radioGroups": []},
    )

    list_response = client.get("/api/template-api-endpoints?templateId=tpl-1", headers=auth_headers)

    assert list_response.status_code == 200
    assert list_response.json()["limits"]["activeEndpointsMax"] == 1
    assert list_response.json()["limits"]["activeEndpointsUsed"] == 2
    assert list_response.json()["limits"]["requestsThisMonth"] == 0
    assert list_response.json()["limits"]["requestUsageMonth"] == "2026-04"

    schema_response = client.get("/api/template-api-endpoints/tep-1/schema", headers=auth_headers)

    assert schema_response.status_code == 200
    assert schema_response.json()["recentEvents"] == []
    assert schema_response.json()["limits"]["activeEndpointsMax"] == 1
    assert schema_response.json()["limits"]["activeEndpointsUsed"] == 2
    assert schema_response.json()["limits"]["requestsThisMonth"] == 0
    assert schema_response.json()["limits"]["requestUsageMonth"] == "2026-04"


def test_template_api_publish_reuses_existing_active_endpoint_without_rotating_secret(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    _patch_limits(mocker, app_main)
    mocker.patch.object(app_main, "get_template", return_value=_template_record())
    mocker.patch.object(app_main, "build_template_api_snapshot", return_value={"version": 1, "defaultExportMode": "editable", "pageCount": 1})
    mocker.patch.object(app_main, "build_template_api_schema", return_value={"fields": [{"key": "full_name"}]})
    mocker.patch.object(app_main, "generate_template_api_secret", return_value="dpa_live_secret")
    mocker.patch.object(app_main, "build_template_api_key_prefix", return_value="dpa_live_secret")
    mocker.patch.object(app_main, "hash_template_api_secret", return_value="hashed-secret")
    mocker.patch.object(app_main, "get_template_api_endpoint", return_value=_endpoint_record(snapshot_version=4))
    publish_mock = mocker.patch.object(
        app_main,
        "publish_or_republish_template_api_endpoint",
        return_value=(_endpoint_record(snapshot_version=4), False),
    )

    response = client.post(
        "/api/template-api-endpoints",
        json={"templateId": "tpl-1", "exportMode": "editable"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["created"] is False
    assert response.json()["secret"] is None
    publish_mock.assert_called_once_with(
        user_id="user_base",
        template_id="tpl-1",
        template_name="Patient Intake",
        active_limit=1,
        key_prefix="dpa_live_secret",
        secret_hash="hashed-secret",
        snapshot={"version": 1, "defaultExportMode": "editable", "pageCount": 1},
    )


def test_template_api_publish_returns_404_when_template_missing(client, app_main, base_user, mocker, auth_headers) -> None:
    _patch_auth(mocker, app_main, base_user)
    _patch_limits(mocker, app_main)
    mocker.patch.object(app_main, "get_template", return_value=None)

    response = client.post(
        "/api/template-api-endpoints",
        json={"templateId": "missing-template"},
        headers=auth_headers,
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Saved form not found"}


def test_template_api_publish_rejects_unknown_top_level_fields(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    get_template_mock = mocker.patch.object(app_main, "get_template")

    response = client.post(
        "/api/template-api-endpoints",
        json={"templateId": "tpl-1", "export_mode": "editable"},
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "export_mode"]
    get_template_mock.assert_not_called()


def test_template_api_publish_returns_400_when_snapshot_build_fails(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    _patch_limits(mocker, app_main)
    mocker.patch.object(app_main, "count_active_template_api_endpoints", return_value=0)
    mocker.patch.object(app_main, "get_template", return_value=_template_record())
    mocker.patch.object(
        app_main,
        "build_template_api_snapshot",
        side_effect=ValueError("Saved form needs an editor snapshot before API Fill can be published."),
    )

    response = client.post(
        "/api/template-api-endpoints",
        json={"templateId": "tpl-1"},
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "editor snapshot" in response.json()["detail"]


def test_template_api_rotate_requires_active_endpoint(client, app_main, base_user, mocker, auth_headers) -> None:
    _patch_auth(mocker, app_main, base_user)
    _patch_limits(mocker, app_main)
    mocker.patch.object(app_main, "get_template_api_endpoint", return_value=_endpoint_record(status="revoked"))

    response = client.post("/api/template-api-endpoints/tep-1/rotate", headers=auth_headers)

    assert response.status_code == 409
    assert "active" in response.json()["detail"].lower()


def test_template_api_rotate_surfaces_atomic_status_conflicts(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    _patch_limits(mocker, app_main)
    mocker.patch.object(app_main, "get_template_api_endpoint", return_value=_endpoint_record())
    mocker.patch.object(app_main, "generate_template_api_secret", return_value="dpa_live_rotated")
    mocker.patch.object(app_main, "build_template_api_key_prefix", return_value="dpa_live_rotated")
    mocker.patch.object(app_main, "hash_template_api_secret", return_value="hashed-rotated")
    mocker.patch.object(
        app_main,
        "rotate_template_api_endpoint_secret_atomic",
        side_effect=TemplateApiEndpointStatusError("Only active API Fill endpoints can rotate keys."),
    )

    response = client.post("/api/template-api-endpoints/tep-1/rotate", headers=auth_headers)

    assert response.status_code == 409
    assert "active" in response.json()["detail"].lower()


def test_template_api_publish_enforces_active_endpoint_limit(client, app_main, base_user, mocker, auth_headers) -> None:
    _patch_auth(mocker, app_main, base_user)
    _patch_limits(mocker, app_main)
    mocker.patch.object(app_main, "resolve_template_api_active_limit", return_value=1)
    mocker.patch.object(app_main, "get_template", return_value=_template_record())
    mocker.patch.object(app_main, "build_template_api_snapshot", return_value={"version": 1, "defaultExportMode": "flat", "pageCount": 1})
    mocker.patch.object(
        app_main,
        "publish_or_republish_template_api_endpoint",
        side_effect=TemplateApiActiveEndpointLimitError("Your plan allows up to 1 active API Fill endpoints."),
    )

    response = client.post(
        "/api/template-api-endpoints",
        json={"templateId": "tpl-1", "exportMode": "flat"},
        headers=auth_headers,
    )

    assert response.status_code == 409
    assert "active api fill endpoints" in response.json()["detail"].lower()


def test_template_api_publish_enforces_page_limit(client, app_main, base_user, mocker, auth_headers) -> None:
    _patch_auth(mocker, app_main, base_user)
    _patch_limits(mocker, app_main)
    mocker.patch.object(app_main, "get_template", return_value=_template_record())
    mocker.patch.object(
        app_main,
        "build_template_api_snapshot",
        return_value={"version": 1, "defaultExportMode": "flat", "pageCount": 40},
    )

    response = client.post(
        "/api/template-api-endpoints",
        json={"templateId": "tpl-1", "exportMode": "flat"},
        headers=auth_headers,
    )

    assert response.status_code == 403
    assert "limited to 25 pages" in response.json()["detail"].lower()
