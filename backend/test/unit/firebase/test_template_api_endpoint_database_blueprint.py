from __future__ import annotations

from backend.firebaseDB import template_api_endpoint_database as db
from backend.test.unit.firebase._fakes import FakeFirestoreClient


def test_create_list_get_and_update_template_api_endpoint(mocker) -> None:
    client = FakeFirestoreClient()
    mocker.patch("backend.firebaseDB.template_api_endpoint_database.get_firestore_client", return_value=client)
    mocker.patch(
        "backend.firebaseDB.template_api_endpoint_database.now_iso",
        side_effect=["ts-created", "ts-updated", "ts-used", "ts-used"],
    )
    mocker.patch("backend.firebaseDB.template_api_endpoint_database._current_month_key", return_value="2026-03")

    created = db.create_template_api_endpoint(
        user_id="user-1",
        template_id="tpl-1",
        template_name="Patient Intake",
        key_prefix="dpa_live_abc123",
        secret_hash="hash-1",
        snapshot={"version": 1, "fields": [{"name": "full_name"}]},
    )

    assert created.id == "auto_0"
    assert created.status == "active"
    assert created.snapshot_version == 1
    assert created.created_at == "ts-created"

    listed = db.list_template_api_endpoints("user-1")
    assert [record.id for record in listed] == ["auto_0"]

    fetched = db.get_template_api_endpoint("auto_0", "user-1")
    assert fetched is not None
    assert fetched.template_name == "Patient Intake"
    assert fetched.key_prefix == "dpa_live_abc123"
    public_fetched = db.get_template_api_endpoint_public("auto_0")
    assert public_fetched is not None
    assert public_fetched.id == "auto_0"
    secret_fetched = db.get_template_api_endpoint_for_secret("auto_0", key_prefix="dpa_live_abc123")
    assert secret_fetched is not None
    assert secret_fetched.id == "auto_0"

    updated = db.update_template_api_endpoint(
        "auto_0",
        "user-1",
        template_name="Patient Intake v2",
        snapshot_version=2,
        status="revoked",
        last_used_at="ts-last-used",
        usage_count=4,
    )

    assert updated is not None
    assert updated.template_name == "Patient Intake v2"
    assert updated.snapshot_version == 2
    assert updated.status == "revoked"
    assert updated.last_used_at == "ts-last-used"
    assert updated.usage_count == 4
    assert updated.updated_at == "ts-updated"

    used = db.record_template_api_endpoint_use("auto_0")
    assert used is not None
    assert used.last_used_at == "ts-used"
    assert used.usage_count == 5
    assert used.current_usage_month == "2026-03"
    assert used.current_month_usage_count == 1

    usage = db.get_template_api_monthly_usage("user-1", month_key="2026-03")
    assert usage is not None
    assert usage.request_count == 1


def test_get_active_template_api_endpoint_for_template_returns_only_active(mocker) -> None:
    client = FakeFirestoreClient()
    mocker.patch("backend.firebaseDB.template_api_endpoint_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.template_api_endpoint_database.now_iso", return_value="ts-created")

    first = db.create_template_api_endpoint(
        user_id="user-1",
        template_id="tpl-1",
        template_name="Patient Intake",
        key_prefix="dpa_live_abc123",
        secret_hash="hash-1",
        snapshot={"version": 1},
    )
    second = db.create_template_api_endpoint(
        user_id="user-1",
        template_id="tpl-1",
        template_name="Patient Intake Copy",
        key_prefix="dpa_live_def456",
        secret_hash="hash-2",
        snapshot={"version": 1},
    )
    db.update_template_api_endpoint(first.id, "user-1", status="revoked")

    active = db.get_active_template_api_endpoint_for_template("tpl-1", "user-1")

    assert active is not None
    assert active.id == second.id


def test_template_api_endpoint_events_and_failures_are_persisted(mocker) -> None:
    client = FakeFirestoreClient()
    mocker.patch("backend.firebaseDB.template_api_endpoint_database.get_firestore_client", return_value=client)
    mocker.patch(
        "backend.firebaseDB.template_api_endpoint_database.now_iso",
        side_effect=["ts-created", "ts-event", "ts-failure", "ts-failure"],
    )

    created = db.create_template_api_endpoint(
        user_id="user-1",
        template_id="tpl-1",
        template_name="Patient Intake",
        key_prefix="dpa_live_abc123",
        secret_hash="hash-1",
        snapshot={"version": 1},
    )

    event = db.create_template_api_endpoint_event(
        endpoint_id=created.id,
        user_id="user-1",
        template_id="tpl-1",
        event_type="rotated",
        snapshot_version=1,
        metadata={"keyPrefix": "dpa_live_abc123"},
    )

    assert event.event_type == "rotated"
    listed_events = db.list_template_api_endpoint_events(created.id, user_id="user-1")
    assert len(listed_events) == 1
    assert listed_events[0].metadata["keyPrefix"] == "dpa_live_abc123"

    failed = db.record_template_api_endpoint_failure(
        created.id,
        auth_failure=True,
        suspicious=True,
        reason="bad basic auth",
    )

    assert failed is not None
    assert failed.auth_failure_count == 1
    assert failed.suspicious_failure_count == 1
    assert failed.last_failure_reason == "bad basic auth"
    assert failed.audit_event_count == 1
