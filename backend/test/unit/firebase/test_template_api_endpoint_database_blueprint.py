from __future__ import annotations

from google.api_core import exceptions as google_api_exceptions

from backend.firebaseDB import template_api_endpoint_database as db
from backend.test.unit.firebase._fakes import FakeFirestoreClient
import pytest


def test_create_list_get_and_update_template_api_endpoint(mocker) -> None:
    client = FakeFirestoreClient()
    mocker.patch("backend.firebaseDB.template_api_endpoint_database.get_firestore_client", return_value=client)
    mocker.patch(
        "backend.firebaseDB.template_api_endpoint_database.now_iso",
        side_effect=["ts-created", "ts-updated"],
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
    public_metadata = db.get_template_api_endpoint_public_metadata("auto_0")
    assert public_metadata is not None
    assert public_metadata.id == "auto_0"
    assert public_metadata.snapshot is None

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


def test_record_template_api_endpoint_success_updates_usage_and_event_in_one_call(mocker) -> None:
    client = FakeFirestoreClient()
    mocker.patch("backend.firebaseDB.template_api_endpoint_database.get_firestore_client", return_value=client)
    mocker.patch(
        "backend.firebaseDB.template_api_endpoint_database.now_iso",
        side_effect=["ts-created", "ts-success"],
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

    recorded = db.record_template_api_endpoint_success(
        created.id,
        month_key="2026-03",
        monthly_limit=250,
        metadata={"strict": True, "responseBytes": 1234},
    )

    assert recorded is not None
    assert recorded.last_used_at == "ts-success"
    assert recorded.usage_count == 1
    assert recorded.current_usage_month == "2026-03"
    assert recorded.current_month_usage_count == 1
    assert recorded.audit_event_count == 1
    events = db.list_template_api_endpoint_events(created.id, user_id="user-1")
    assert len(events) == 1
    assert events[0].event_type == "fill_succeeded"
    assert events[0].metadata["responseBytes"] == 1234
    usage = db.get_template_api_monthly_usage("user-1", month_key="2026-03")
    assert usage is not None
    assert usage.request_count == 1


def test_record_template_api_endpoint_success_uses_reserved_month_key_for_endpoint_summary(mocker) -> None:
    client = FakeFirestoreClient()
    mocker.patch("backend.firebaseDB.template_api_endpoint_database.get_firestore_client", return_value=client)
    mocker.patch(
        "backend.firebaseDB.template_api_endpoint_database.now_iso",
        side_effect=["ts-created", "ts-success"],
    )
    mocker.patch("backend.firebaseDB.template_api_endpoint_database._current_month_key", return_value="2026-04")

    created = db.create_template_api_endpoint(
        user_id="user-1",
        template_id="tpl-1",
        template_name="Patient Intake",
        key_prefix="dpa_live_abc123",
        secret_hash="hash-1",
        snapshot={"version": 1, "fields": [{"name": "full_name"}]},
    )

    recorded = db.record_template_api_endpoint_success(
        created.id,
        month_key="2026-03",
        monthly_limit=250,
        metadata={"strict": True},
    )

    assert recorded is not None
    assert recorded.current_usage_month == "2026-03"
    assert recorded.current_month_usage_count == 1
    usage = db.get_template_api_monthly_usage("user-1", month_key="2026-03")
    assert usage is not None
    assert usage.request_count == 1


def test_record_template_api_endpoint_success_rolls_endpoint_summary_forward_for_new_month(mocker) -> None:
    client = FakeFirestoreClient()
    mocker.patch("backend.firebaseDB.template_api_endpoint_database.get_firestore_client", return_value=client)
    mocker.patch(
        "backend.firebaseDB.template_api_endpoint_database.now_iso",
        side_effect=["ts-created", "ts-mark-old-month", "ts-success"],
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
    db.update_template_api_endpoint(
        created.id,
        "user-1",
        usage_count=7,
        current_usage_month="2026-02",
        current_month_usage_count=4,
        last_used_at="ts-old-last-used",
    )

    recorded = db.record_template_api_endpoint_success(
        created.id,
        month_key="2026-03",
        monthly_limit=250,
        metadata={"strict": True},
    )

    assert recorded is not None
    assert recorded.usage_count == 8
    assert recorded.current_usage_month == "2026-03"
    assert recorded.current_month_usage_count == 1
    usage = db.get_template_api_monthly_usage("user-1", month_key="2026-03")
    assert usage is not None
    assert usage.request_count == 1
    events = db.list_template_api_endpoint_events(created.id, user_id="user-1")
    assert len(events) == 1
    assert events[0].event_type == "fill_succeeded"


def test_record_template_api_endpoint_success_fails_closed_when_monthly_limit_is_exhausted(mocker) -> None:
    client = FakeFirestoreClient()
    mocker.patch("backend.firebaseDB.template_api_endpoint_database.get_firestore_client", return_value=client)
    mocker.patch(
        "backend.firebaseDB.template_api_endpoint_database.now_iso",
        side_effect=["ts-created", "ts-success", "ts-limit-hit"],
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

    first = db.record_template_api_endpoint_success(
        created.id,
        month_key="2026-03",
        monthly_limit=1,
        metadata={"strict": True},
    )

    assert first is not None

    with pytest.raises(db.TemplateApiMonthlyLimitExceededError):
        db.record_template_api_endpoint_success(
            created.id,
            month_key="2026-03",
            monthly_limit=1,
            metadata={"strict": True},
        )

    recorded = db.get_template_api_endpoint(created.id, "user-1")
    assert recorded is not None
    assert recorded.usage_count == 1
    assert recorded.current_month_usage_count == 1
    assert recorded.audit_event_count == 1
    usage = db.get_template_api_monthly_usage("user-1", month_key="2026-03")
    assert usage is not None
    assert usage.request_count == 1
    events = db.list_template_api_endpoint_events(created.id, user_id="user-1")
    assert len(events) == 1


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
        runtime_failure=True,
        suspicious=True,
        reason="bad basic auth",
    )

    assert failed is not None
    assert failed.auth_failure_count == 1
    assert failed.runtime_failure_count == 1
    assert failed.suspicious_failure_count == 1
    assert failed.last_failure_reason == "bad basic auth"
    assert failed.audit_event_count == 1


def test_list_template_api_endpoint_events_returns_recent_subset(mocker) -> None:
    client = FakeFirestoreClient()
    mocker.patch("backend.firebaseDB.template_api_endpoint_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.template_api_endpoint_database.now_iso", return_value="ts-created")

    created = db.create_template_api_endpoint(
        user_id="user-1",
        template_id="tpl-1",
        template_name="Patient Intake",
        key_prefix="dpa_live_abc123",
        secret_hash="hash-1",
        snapshot={"version": 1},
    )

    db.create_template_api_endpoint_event(
        endpoint_id=created.id,
        user_id="user-1",
        template_id="tpl-1",
        event_type="published",
        created_at="2024-01-01T00:00:00+00:00",
    )
    db.create_template_api_endpoint_event(
        endpoint_id=created.id,
        user_id="user-1",
        template_id="tpl-1",
        event_type="rotated",
        created_at="2024-01-02T00:00:00+00:00",
    )
    db.create_template_api_endpoint_event(
        endpoint_id=created.id,
        user_id="user-1",
        template_id="tpl-1",
        event_type="revoked",
        created_at="2024-01-03T00:00:00+00:00",
    )

    listed_events = db.list_template_api_endpoint_events(created.id, user_id="user-1", limit=2)

    assert [event.event_type for event in listed_events] == ["revoked", "rotated"]


def test_list_template_api_endpoint_events_falls_back_when_composite_index_is_missing(mocker) -> None:
    class _Doc:
        def __init__(self, doc_id: str, payload: dict) -> None:
            self.id = doc_id
            self._payload = dict(payload)

        def to_dict(self) -> dict:
            return dict(self._payload)

    class _FallbackQuery:
        def __init__(self, docs, *, ordered: bool = False) -> None:
            self._docs = list(docs)
            self._ordered = ordered

        def order_by(self, *_args, **_kwargs):
            return _FallbackQuery(self._docs, ordered=True)

        def limit(self, _limit: int):
            return self

        def get(self):
            if self._ordered:
                raise google_api_exceptions.FailedPrecondition("missing index")
            return list(self._docs)

    docs = [
        _Doc(
            "evt-1",
            {
                "endpoint_id": "tep-1",
                "user_id": "user-1",
                "template_id": "tpl-1",
                "event_type": "published",
                "outcome": "success",
                "created_at": "2024-01-01T00:00:00+00:00",
                "metadata": {},
            },
        ),
        _Doc(
            "evt-2",
            {
                "endpoint_id": "tep-1",
                "user_id": "user-1",
                "template_id": "tpl-1",
                "event_type": "rotated",
                "outcome": "success",
                "created_at": "2024-01-03T00:00:00+00:00",
                "metadata": {},
            },
        ),
        _Doc(
            "evt-3",
            {
                "endpoint_id": "tep-1",
                "user_id": "user-1",
                "template_id": "tpl-1",
                "event_type": "revoked",
                "outcome": "success",
                "created_at": "2024-01-02T00:00:00+00:00",
                "metadata": {},
            },
        ),
    ]

    class _Client:
        def collection(self, _name: str):
            return object()

    mocker.patch("backend.firebaseDB.template_api_endpoint_database.get_firestore_client", return_value=_Client())
    mocker.patch("backend.firebaseDB.template_api_endpoint_database.where_equals", return_value=_FallbackQuery(docs))

    listed_events = db.list_template_api_endpoint_events("tep-1", user_id="user-1", limit=2)

    assert [event.event_type for event in listed_events] == ["rotated", "revoked"]


def test_publish_or_republish_heals_duplicate_active_rows_for_one_template(mocker) -> None:
    client = FakeFirestoreClient()
    mocker.patch("backend.firebaseDB.template_api_endpoint_database.get_firestore_client", return_value=client)
    mocker.patch(
        "backend.firebaseDB.template_api_endpoint_database.now_iso",
        side_effect=["ts-created-1", "ts-created-2", "ts-created-3", "ts-updated-2", "ts-published"],
    )

    first = db.create_template_api_endpoint(
        user_id="user-1",
        template_id="tpl-1",
        template_name="Patient Intake",
        key_prefix="dpa_live_first",
        secret_hash="hash-1",
        snapshot={"version": 1},
    )
    second = db.create_template_api_endpoint(
        user_id="user-1",
        template_id="tpl-1",
        template_name="Patient Intake",
        key_prefix="dpa_live_second",
        secret_hash="hash-2",
        snapshot={"version": 1},
    )
    other = db.create_template_api_endpoint(
        user_id="user-1",
        template_id="tpl-2",
        template_name="Another Form",
        key_prefix="dpa_live_other",
        secret_hash="hash-3",
        snapshot={"version": 1},
    )
    db.update_template_api_endpoint(second.id, "user-1", template_name="Patient Intake")

    republished, created = db.publish_or_republish_template_api_endpoint(
        user_id="user-1",
        template_id="tpl-1",
        template_name="Patient Intake",
        snapshot={"version": 2, "defaultExportMode": "flat"},
        active_limit=2,
        key_prefix="dpa_live_new",
        secret_hash="hash-new",
    )

    assert created is False
    assert republished.id == second.id
    assert republished.status == "active"
    assert republished.snapshot_version == 2
    stale_duplicate = db.get_template_api_endpoint(first.id, "user-1")
    assert stale_duplicate is not None
    assert stale_duplicate.status == "revoked"
    assert stale_duplicate.key_prefix is None
    assert stale_duplicate.secret_hash is None
    unaffected = db.get_template_api_endpoint(other.id, "user-1")
    assert unaffected is not None
    assert unaffected.status == "active"


def test_publish_or_republish_counts_active_rows_for_limit_enforcement(mocker) -> None:
    client = FakeFirestoreClient()
    mocker.patch("backend.firebaseDB.template_api_endpoint_database.get_firestore_client", return_value=client)
    mocker.patch(
        "backend.firebaseDB.template_api_endpoint_database.now_iso",
        side_effect=["ts-created-1", "ts-created-2", "ts-created-3", "ts-publish-attempt"],
    )

    db.create_template_api_endpoint(
        user_id="user-1",
        template_id="tpl-1",
        template_name="Patient Intake",
        key_prefix="dpa_live_first",
        secret_hash="hash-1",
        snapshot={"version": 1},
    )
    db.create_template_api_endpoint(
        user_id="user-1",
        template_id="tpl-1",
        template_name="Patient Intake Duplicate",
        key_prefix="dpa_live_second",
        secret_hash="hash-2",
        snapshot={"version": 1},
    )
    db.create_template_api_endpoint(
        user_id="user-1",
        template_id="tpl-2",
        template_name="Another Form",
        key_prefix="dpa_live_third",
        secret_hash="hash-3",
        snapshot={"version": 1},
    )

    with pytest.raises(db.TemplateApiActiveEndpointLimitError):
        db.publish_or_republish_template_api_endpoint(
            user_id="user-1",
            template_id="tpl-3",
            template_name="New Form",
            snapshot={"version": 2, "defaultExportMode": "flat"},
            active_limit=3,
            key_prefix="dpa_live_new",
            secret_hash="hash-new",
        )


def test_revoke_template_api_endpoint_atomic_revokes_duplicate_active_rows(mocker) -> None:
    client = FakeFirestoreClient()
    mocker.patch("backend.firebaseDB.template_api_endpoint_database.get_firestore_client", return_value=client)
    mocker.patch(
        "backend.firebaseDB.template_api_endpoint_database.now_iso",
        side_effect=["ts-created-1", "ts-created-2", "ts-mark-revoked", "ts-revoke"],
    )

    first = db.create_template_api_endpoint(
        user_id="user-1",
        template_id="tpl-1",
        template_name="Patient Intake",
        key_prefix="dpa_live_first",
        secret_hash="hash-1",
        snapshot={"version": 1},
    )
    second = db.create_template_api_endpoint(
        user_id="user-1",
        template_id="tpl-1",
        template_name="Patient Intake",
        key_prefix="dpa_live_second",
        secret_hash="hash-2",
        snapshot={"version": 1},
    )
    db.update_template_api_endpoint(first.id, "user-1", status="revoked")

    revoked = db.revoke_template_api_endpoint_atomic(first.id, "user-1")

    assert revoked is not None
    assert revoked.status == "revoked"
    sibling = db.get_template_api_endpoint(second.id, "user-1")
    assert sibling is not None
    assert sibling.status == "revoked"
    assert sibling.key_prefix is None
    assert sibling.secret_hash is None


def test_rotate_template_api_endpoint_secret_atomic_requires_active_status(mocker) -> None:
    client = FakeFirestoreClient()
    mocker.patch("backend.firebaseDB.template_api_endpoint_database.get_firestore_client", return_value=client)
    mocker.patch(
        "backend.firebaseDB.template_api_endpoint_database.now_iso",
        side_effect=["ts-created", "ts-revoked"],
    )

    endpoint = db.create_template_api_endpoint(
        user_id="user-1",
        template_id="tpl-1",
        template_name="Patient Intake",
        key_prefix="dpa_live_first",
        secret_hash="hash-1",
        snapshot={"version": 1},
    )
    db.update_template_api_endpoint(endpoint.id, "user-1", status="revoked")

    with pytest.raises(db.TemplateApiEndpointStatusError):
        db.rotate_template_api_endpoint_secret_atomic(
            endpoint.id,
            "user-1",
            key_prefix="dpa_live_rotated",
            secret_hash="hash-rotated",
        )
