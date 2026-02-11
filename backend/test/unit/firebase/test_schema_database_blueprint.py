"""Unit tests for `backend/firebaseDB/schema_database.py`."""

from datetime import datetime, timedelta, timezone
import importlib

import pytest

from backend.firebaseDB import schema_database as sdb
from backend.test.unit.firebase._fakes import FakeFirestoreClient


def test_schema_expires_at_returns_none_when_ttl_disabled(monkeypatch) -> None:
    monkeypatch.setattr(sdb, "_SCHEMA_TTL_SECONDS", 0)
    assert sdb._schema_expires_at() is None


def test_schema_expires_at_returns_future_datetime_when_ttl_enabled(monkeypatch) -> None:
    monkeypatch.setattr(sdb, "_SCHEMA_TTL_SECONDS", 30)

    expires_at = sdb._schema_expires_at()

    assert expires_at is not None
    delta = expires_at - datetime.now(timezone.utc)
    assert 0 < delta.total_seconds() <= 30


def test_is_expired_handles_datetime_and_iso_string_values() -> None:
    now = datetime.now(timezone.utc)

    assert sdb._is_expired({"expires_at": now - timedelta(seconds=1)}) is True
    assert sdb._is_expired({"expires_at": now + timedelta(seconds=60)}) is False
    assert sdb._is_expired({"expires_at": (now - timedelta(seconds=1)).isoformat()}) is True
    assert sdb._is_expired({"expires_at": (now + timedelta(seconds=60)).isoformat()}) is False
    assert sdb._is_expired({"expires_at": "not-iso"}) is False
    assert sdb._is_expired({"expires_at": 12345}) is False
    assert sdb._is_expired({}) is False


def test_create_schema_validates_required_fields() -> None:
    with pytest.raises(ValueError, match="user_id is required"):
        sdb.create_schema(user_id="", fields=[{"name": "a"}])

    with pytest.raises(ValueError, match="Schema fields are required"):
        sdb.create_schema(user_id="user-1", fields=[])


def test_create_schema_persists_metadata_and_returns_record(mocker) -> None:
    client = FakeFirestoreClient()
    expires_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    mocker.patch("backend.firebaseDB.schema_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.schema_database.now_iso", return_value="ts-created")
    mocker.patch("backend.firebaseDB.schema_database._schema_expires_at", return_value=expires_at)

    record = sdb.create_schema(
        user_id="user-1",
        fields=[{"name": "first_name", "type": "string"}],
        name="Example",
        source="upload",
        sample_count=3,
    )

    assert record.id == "auto_0"
    assert record.owner_user_id == "user-1"
    assert record.fields == [{"name": "first_name", "type": "string"}]

    stored = client.collection(sdb.SCHEMAS_COLLECTION).document("auto_0").get().to_dict()
    assert stored == {
        "owner_user_id": "user-1",
        "name": "Example",
        "fields": [{"name": "first_name", "type": "string"}],
        "source": "upload",
        "sample_count": 3,
        "created_at": "ts-created",
        "updated_at": "ts-created",
        "expires_at": expires_at,
    }


def test_list_schemas_filters_expired_records_and_sorts_desc(mocker) -> None:
    client = FakeFirestoreClient()
    collection = client.collection(sdb.SCHEMAS_COLLECTION)
    collection.document("schema-old").seed(
        {
            "owner_user_id": "user-1",
            "fields": [{"name": "a"}],
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
        }
    )
    collection.document("schema-new").seed(
        {
            "owner_user_id": "user-1",
            "fields": [{"name": "b"}],
            "created_at": "2024-02-01T00:00:00+00:00",
            "updated_at": "2024-02-01T00:00:00+00:00",
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
        }
    )
    collection.document("schema-expired").seed(
        {
            "owner_user_id": "user-1",
            "fields": [{"name": "c"}],
            "created_at": "2024-03-01T00:00:00+00:00",
            "updated_at": "2024-03-01T00:00:00+00:00",
            "expires_at": datetime.now(timezone.utc) - timedelta(minutes=1),
        }
    )
    collection.document("schema-foreign").seed(
        {
            "owner_user_id": "user-2",
            "fields": [{"name": "d"}],
            "created_at": "2024-04-01T00:00:00+00:00",
            "updated_at": "2024-04-01T00:00:00+00:00",
        }
    )
    mocker.patch("backend.firebaseDB.schema_database.get_firestore_client", return_value=client)

    records = sdb.list_schemas("user-1")

    assert [record.id for record in records] == ["schema-new", "schema-old"]


def test_list_schemas_returns_empty_for_missing_user_id(mocker) -> None:
    get_client = mocker.patch("backend.firebaseDB.schema_database.get_firestore_client")
    assert sdb.list_schemas("") == []
    get_client.assert_not_called()


def test_get_schema_enforces_ownership_and_expiration(mocker) -> None:
    client = FakeFirestoreClient()
    collection = client.collection(sdb.SCHEMAS_COLLECTION)
    collection.document("valid").seed(
        {
            "owner_user_id": "user-1",
            "fields": [{"name": "x"}],
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
        }
    )
    collection.document("foreign").seed(
        {
            "owner_user_id": "user-2",
            "fields": [{"name": "x"}],
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
        }
    )
    collection.document("expired").seed(
        {
            "owner_user_id": "user-1",
            "fields": [{"name": "x"}],
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
            "expires_at": datetime.now(timezone.utc) - timedelta(minutes=5),
        }
    )
    mocker.patch("backend.firebaseDB.schema_database.get_firestore_client", return_value=client)

    assert sdb.get_schema("valid", "user-1") is not None
    assert sdb.get_schema("foreign", "user-1") is None
    assert sdb.get_schema("expired", "user-1") is None
    assert sdb.get_schema("missing", "user-1") is None


def test_get_schema_returns_none_when_identifiers_missing(mocker) -> None:
    get_client = mocker.patch("backend.firebaseDB.schema_database.get_firestore_client")
    assert sdb.get_schema("", "user-1") is None
    assert sdb.get_schema("schema-1", "") is None
    get_client.assert_not_called()


def test_record_openai_request_validates_required_metadata() -> None:
    with pytest.raises(ValueError, match="Missing required OpenAI request metadata"):
        sdb.record_openai_request(request_id="", user_id="u1", schema_id="s1", template_id=None)

    with pytest.raises(ValueError, match="Missing required OpenAI request metadata"):
        sdb.record_openai_request(request_id="r1", user_id="", schema_id="s1", template_id=None)

    with pytest.raises(ValueError, match="Missing required OpenAI request metadata"):
        sdb.record_openai_request(request_id="r1", user_id="u1", schema_id="", template_id=None)


def test_record_openai_request_writes_payload_and_ttl(mocker) -> None:
    client = FakeFirestoreClient()
    expires_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    mocker.patch("backend.firebaseDB.schema_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.schema_database.now_iso", return_value="ts-created")
    mocker.patch("backend.firebaseDB.schema_database.log_expires_at", return_value=expires_at)

    sdb.record_openai_request(request_id="req-1", user_id="u1", schema_id="s1", template_id=None)

    payload = client.collection(sdb.OPENAI_REQUESTS_COLLECTION).document("req-1").get().to_dict()
    assert payload == {
        "request_id": "req-1",
        "user_id": "u1",
        "schema_id": "s1",
        "template_id": None,
        "created_at": "ts-created",
        "expires_at": expires_at,
    }


def test_record_openai_rename_request_validates_required_metadata() -> None:
    with pytest.raises(ValueError, match="Missing required OpenAI rename metadata"):
        sdb.record_openai_rename_request(request_id="", user_id="u1", session_id="sess")

    with pytest.raises(ValueError, match="Missing required OpenAI rename metadata"):
        sdb.record_openai_rename_request(request_id="r1", user_id="", session_id="sess")

    with pytest.raises(ValueError, match="Missing required OpenAI rename metadata"):
        sdb.record_openai_rename_request(request_id="r1", user_id="u1", session_id="")


def test_record_openai_rename_request_writes_payload_and_optional_schema(mocker) -> None:
    client = FakeFirestoreClient()
    mocker.patch("backend.firebaseDB.schema_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.schema_database.now_iso", return_value="ts-created")
    mocker.patch("backend.firebaseDB.schema_database.log_expires_at", return_value=None)

    sdb.record_openai_rename_request(request_id="req-1", user_id="u1", session_id="sess-1")

    payload = client.collection(sdb.OPENAI_RENAME_REQUESTS_COLLECTION).document("req-1").get().to_dict()
    assert payload == {
        "request_id": "req-1",
        "user_id": "u1",
        "schema_id": None,
        "session_id": "sess-1",
        "created_at": "ts-created",
    }


def test_record_openai_rename_request_includes_expires_at_when_ttl_enabled(mocker) -> None:
    client = FakeFirestoreClient()
    expires_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    mocker.patch("backend.firebaseDB.schema_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.schema_database.now_iso", return_value="ts-created")
    mocker.patch("backend.firebaseDB.schema_database.log_expires_at", return_value=expires_at)

    sdb.record_openai_rename_request(
        request_id="req-2",
        user_id="u1",
        session_id="sess-1",
        schema_id="schema-1",
    )

    payload = client.collection(sdb.OPENAI_RENAME_REQUESTS_COLLECTION).document("req-2").get().to_dict()
    assert payload == {
        "request_id": "req-2",
        "user_id": "u1",
        "schema_id": "schema-1",
        "session_id": "sess-1",
        "created_at": "ts-created",
        "expires_at": expires_at,
    }


def test_schema_ttl_env_invalid_falls_back_on_module_reload(monkeypatch) -> None:
    monkeypatch.setenv("SANDBOX_SCHEMA_TTL_SECONDS", "invalid")
    reloaded = importlib.reload(sdb)
    assert reloaded._SCHEMA_TTL_SECONDS == 3600


# ---------------------------------------------------------------------------
# Edge-case: create_schema when _schema_expires_at() returns None
# ---------------------------------------------------------------------------
# When the TTL is disabled (<=0), _schema_expires_at() returns None and the
# expires_at key should be omitted from the stored payload entirely.
def test_create_schema_omits_expires_at_when_ttl_disabled(mocker) -> None:
    client = FakeFirestoreClient()
    mocker.patch("backend.firebaseDB.schema_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.schema_database.now_iso", return_value="ts-created")
    mocker.patch("backend.firebaseDB.schema_database._schema_expires_at", return_value=None)

    record = sdb.create_schema(
        user_id="user-1",
        fields=[{"name": "field_a", "type": "string"}],
        name="No TTL",
    )

    assert record.id == "auto_0"
    stored = client.collection(sdb.SCHEMAS_COLLECTION).document("auto_0").get().to_dict()
    assert "expires_at" not in stored
    assert stored["owner_user_id"] == "user-1"
    assert stored["name"] == "No TTL"
    assert stored["fields"] == [{"name": "field_a", "type": "string"}]
    assert stored["created_at"] == "ts-created"
    assert stored["updated_at"] == "ts-created"


# ---------------------------------------------------------------------------
# Edge-case: record_openai_request with template_id provided (non-None)
# ---------------------------------------------------------------------------
# When a template_id is provided, it should be stored as-is in the payload
# rather than being coerced to None by the `or None` expression.
def test_record_openai_request_stores_template_id_when_provided(mocker) -> None:
    client = FakeFirestoreClient()
    expires_at = datetime(2026, 6, 1, tzinfo=timezone.utc)
    mocker.patch("backend.firebaseDB.schema_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.schema_database.now_iso", return_value="ts-created")
    mocker.patch("backend.firebaseDB.schema_database.log_expires_at", return_value=expires_at)

    sdb.record_openai_request(
        request_id="req-2",
        user_id="u1",
        schema_id="s1",
        template_id="tmpl-42",
    )

    payload = client.collection(sdb.OPENAI_REQUESTS_COLLECTION).document("req-2").get().to_dict()
    assert payload["template_id"] == "tmpl-42"
    assert payload["request_id"] == "req-2"
    assert payload["user_id"] == "u1"
    assert payload["schema_id"] == "s1"
    assert payload["created_at"] == "ts-created"
    assert payload["expires_at"] == expires_at
