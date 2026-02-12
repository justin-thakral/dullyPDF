"""Unit tests for user and template logic in `backend/firebaseDB/app_database.py`."""

import pytest

from backend.firebaseDB import user_database as adb
from backend.firebaseDB import template_database as tdb
from backend.test.unit.firebase._fakes import FakeFirestoreClient


def test_normalize_role_maps_unknown_inputs_to_base() -> None:
    assert adb.normalize_role(None) == adb.ROLE_BASE
    assert adb.normalize_role("") == adb.ROLE_BASE
    assert adb.normalize_role("base") == adb.ROLE_BASE
    assert adb.normalize_role("GOD") == adb.ROLE_GOD
    assert adb.normalize_role("owner") == adb.ROLE_BASE


def test_ensure_user_raises_for_missing_uid() -> None:
    with pytest.raises(ValueError, match="Missing firebase uid"):
        adb.ensure_user({"email": "missing@uid.test"})


def test_ensure_user_creates_new_user_with_defaults(mocker) -> None:
    client = FakeFirestoreClient()
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.user_database.now_iso", return_value="ts-created")

    request_user = adb.ensure_user({"uid": "u-1", "email": "user@example.com", "name": "User"})

    assert request_user.uid == "u-1"
    assert request_user.app_user_id == "u-1"
    assert request_user.email == "user@example.com"
    assert request_user.display_name == "User"
    assert request_user.role == adb.ROLE_BASE

    stored = client.collection(adb.USERS_COLLECTION).document("u-1").get().to_dict()
    assert stored["firebase_uid"] == "u-1"
    assert stored["email"] == "user@example.com"
    assert stored["displayName"] == "User"
    assert stored[adb.ROLE_FIELD] == adb.ROLE_BASE
    assert stored[adb.RENAME_COUNT_FIELD] == 0
    assert stored[adb.OPENAI_CREDITS_FIELD] == adb.BASE_OPENAI_CREDITS
    assert stored["created_at"] == "ts-created"
    assert stored["updated_at"] == "ts-created"


def test_ensure_user_updates_existing_doc_and_backfills_missing_defaults(mocker) -> None:
    client = FakeFirestoreClient()
    existing_doc = client.collection(adb.USERS_COLLECTION).document("u-1").seed(
        {
            "firebase_uid": "u-1",
            "email": "old@example.com",
            "displayName": None,
            "created_at": "old-created",
        }
    )
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.user_database.now_iso", return_value="ts-updated")

    request_user = adb.ensure_user({"uid": "u-1", "email": "new@example.com", "displayName": "New Name"})

    assert request_user.email == "new@example.com"
    assert request_user.display_name == "New Name"
    assert request_user.role == adb.ROLE_BASE

    assert len(existing_doc.update_calls) == 1
    updates = existing_doc.update_calls[0]
    assert updates["email"] == "new@example.com"
    assert updates["displayName"] == "New Name"
    assert updates[adb.ROLE_FIELD] == adb.ROLE_BASE
    assert updates[adb.RENAME_COUNT_FIELD] == 0
    assert updates[adb.OPENAI_CREDITS_FIELD] == adb.BASE_OPENAI_CREDITS
    assert updates["updated_at"] == "ts-updated"


def test_list_templates_returns_only_owned_templates_sorted_desc(mocker) -> None:
    client = FakeFirestoreClient()
    collection = client.collection(tdb.TEMPLATES_COLLECTION)
    collection.document("t-old").seed(
        {
            "user_id": "user-1",
            "pdf_bucket_path": "gs://forms/old.pdf",
            "template_bucket_path": "gs://templates/old.json",
            "metadata": {"name": "Old"},
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
        }
    )
    collection.document("t-new").seed(
        {
            "user_id": "user-1",
            "pdf_bucket_path": "gs://forms/new.pdf",
            "template_bucket_path": "gs://templates/new.json",
            "metadata": {"name": "New"},
            "created_at": "2024-02-01T00:00:00+00:00",
            "updated_at": "2024-02-01T00:00:00+00:00",
        }
    )
    collection.document("t-foreign").seed(
        {
            "user_id": "user-2",
            "pdf_bucket_path": "gs://forms/other.pdf",
            "template_bucket_path": "gs://templates/other.json",
            "metadata": {"name": "Other"},
            "created_at": "2024-03-01T00:00:00+00:00",
            "updated_at": "2024-03-01T00:00:00+00:00",
        }
    )
    mocker.patch("backend.firebaseDB.template_database.get_firestore_client", return_value=client)

    records = tdb.list_templates("user-1")

    assert [record.id for record in records] == ["t-new", "t-old"]
    assert [record.name for record in records] == ["New", "Old"]


def test_get_template_enforces_ownership(mocker) -> None:
    client = FakeFirestoreClient()
    collection = client.collection(tdb.TEMPLATES_COLLECTION)
    collection.document("t-1").seed(
        {
            "user_id": "owner-1",
            "pdf_bucket_path": "gs://forms/form.pdf",
            "template_bucket_path": "gs://templates/template.json",
            "metadata": {"name": "Template"},
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
        }
    )
    mocker.patch("backend.firebaseDB.template_database.get_firestore_client", return_value=client)

    assert tdb.get_template("t-1", "owner-1") is not None
    assert tdb.get_template("t-1", "other-user") is None
    assert tdb.get_template("", "owner-1") is None
    assert tdb.get_template("missing", "owner-1") is None


def test_create_template_validates_required_fields() -> None:
    with pytest.raises(ValueError, match="user_id is required"):
        tdb.create_template("", "gs://forms/a.pdf", "gs://templates/a.json")

    with pytest.raises(ValueError, match="pdf_path and template_path are required"):
        tdb.create_template("user-1", "", "gs://templates/a.json")


def test_create_template_persists_payload_and_returns_record(mocker) -> None:
    client = FakeFirestoreClient()
    mocker.patch("backend.firebaseDB.template_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.template_database.now_iso", return_value="ts-created")

    record = tdb.create_template(
        "user-1",
        "gs://forms/a.pdf",
        "gs://templates/a.json",
        metadata={"name": "Template A"},
    )

    assert record.id == "auto_0"
    assert record.name == "Template A"
    stored = client.collection(tdb.TEMPLATES_COLLECTION).document("auto_0").get().to_dict()
    assert stored == {
        "user_id": "user-1",
        "pdf_bucket_path": "gs://forms/a.pdf",
        "template_bucket_path": "gs://templates/a.json",
        "metadata": {"name": "Template A"},
        "created_at": "ts-created",
        "updated_at": "ts-created",
    }


def test_update_template_returns_none_for_missing_or_unowned_docs(mocker) -> None:
    client = FakeFirestoreClient()
    collection = client.collection(tdb.TEMPLATES_COLLECTION)
    collection.document("owned").seed(
        {
            "user_id": "owner-1",
            "pdf_bucket_path": "gs://forms/a.pdf",
            "template_bucket_path": "gs://templates/a.json",
            "metadata": {"name": "A"},
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
        }
    )
    mocker.patch("backend.firebaseDB.template_database.get_firestore_client", return_value=client)

    assert tdb.update_template("missing", "owner-1", pdf_path="x") is None
    assert tdb.update_template("owned", "other-user", pdf_path="x") is None


def test_update_template_merges_selected_fields_for_owner(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(tdb.TEMPLATES_COLLECTION).document("t-1").seed(
        {
            "user_id": "owner-1",
            "pdf_bucket_path": "gs://forms/a.pdf",
            "template_bucket_path": "gs://templates/a.json",
            "metadata": {"name": "Original"},
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
        }
    )
    mocker.patch("backend.firebaseDB.template_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.template_database.now_iso", return_value="ts-updated")

    record = tdb.update_template(
        "t-1",
        "owner-1",
        pdf_path="gs://forms/b.pdf",
        metadata={"name": "Updated"},
    )

    assert record is not None
    assert record.pdf_bucket_path == "gs://forms/b.pdf"
    assert record.name == "Updated"
    assert doc.set_calls[-1]["merge"] is True


def test_update_template_returns_none_when_required_identifiers_missing() -> None:
    assert tdb.update_template("", "owner-1", pdf_path="x") is None
    assert tdb.update_template("template-1", "", pdf_path="x") is None


def test_update_template_updates_template_path_when_provided(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(tdb.TEMPLATES_COLLECTION).document("t-1").seed(
        {
            "user_id": "owner-1",
            "pdf_bucket_path": "gs://forms/a.pdf",
            "template_bucket_path": "gs://templates/a.json",
            "metadata": {"name": "Original"},
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
        }
    )
    mocker.patch("backend.firebaseDB.template_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.template_database.now_iso", return_value="ts-updated")

    record = tdb.update_template(
        "t-1",
        "owner-1",
        template_path="gs://templates/b.json",
    )

    assert record is not None
    assert record.template_bucket_path == "gs://templates/b.json"
    assert doc.set_calls[-1]["merge"] is True


def test_delete_template_enforces_ownership_and_deletes_for_owner(mocker) -> None:
    client = FakeFirestoreClient()
    owned_doc = client.collection(tdb.TEMPLATES_COLLECTION).document("owned").seed(
        {
            "user_id": "owner-1",
            "pdf_bucket_path": "gs://forms/a.pdf",
            "template_bucket_path": "gs://templates/a.json",
        }
    )
    client.collection(tdb.TEMPLATES_COLLECTION).document("foreign").seed(
        {
            "user_id": "owner-2",
            "pdf_bucket_path": "gs://forms/a.pdf",
            "template_bucket_path": "gs://templates/a.json",
        }
    )
    mocker.patch("backend.firebaseDB.template_database.get_firestore_client", return_value=client)

    assert tdb.delete_template("missing", "owner-1") is False
    assert tdb.delete_template("foreign", "owner-1") is False
    assert tdb.delete_template("owned", "owner-1") is True
    assert owned_doc.delete_calls == 1


def test_delete_template_returns_false_when_identifiers_missing() -> None:
    assert tdb.delete_template("", "owner-1") is False
    assert tdb.delete_template("template-1", "") is False


def test_set_user_role_validates_uid_and_writes_normalized_role(mocker) -> None:
    client = FakeFirestoreClient()
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.user_database.now_iso", return_value="ts-updated")

    with pytest.raises(ValueError, match="Missing firebase uid"):
        adb.set_user_role("", adb.ROLE_GOD)

    adb.set_user_role("uid-1", "unknown-role")

    doc = client.collection(adb.USERS_COLLECTION).document("uid-1")
    assert doc.get().to_dict() == {
        adb.ROLE_FIELD: adb.ROLE_BASE,
        "updated_at": "ts-updated",
    }
    assert doc.set_calls[-1]["merge"] is True


def test_list_templates_returns_empty_for_missing_user_id(mocker) -> None:
    get_client = mocker.patch("backend.firebaseDB.template_database.get_firestore_client")
    assert tdb.list_templates("") == []
    get_client.assert_not_called()


# ---------------------------------------------------------------------------
# Edge-case: ensure_user uid resolution fallback to `user_id` key
# ---------------------------------------------------------------------------
# Some decoded tokens use "user_id" instead of "uid". The function should
# fall through the `or` chain and resolve the uid from the "user_id" key.
def test_ensure_user_resolves_uid_from_user_id_key(mocker) -> None:
    client = FakeFirestoreClient()
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.user_database.now_iso", return_value="ts-created")

    # No "uid" key present, but "user_id" is provided
    request_user = adb.ensure_user({"user_id": "u-from-user-id", "email": "a@test.com"})

    assert request_user.uid == "u-from-user-id"
    assert request_user.app_user_id == "u-from-user-id"
    stored = client.collection(adb.USERS_COLLECTION).document("u-from-user-id").get().to_dict()
    assert stored["firebase_uid"] == "u-from-user-id"


# ---------------------------------------------------------------------------
# Edge-case: ensure_user uid resolution fallback to `sub` key
# ---------------------------------------------------------------------------
# When neither "uid" nor "user_id" is present, the code falls back to "sub".
def test_ensure_user_resolves_uid_from_sub_key(mocker) -> None:
    client = FakeFirestoreClient()
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.user_database.now_iso", return_value="ts-created")

    request_user = adb.ensure_user({"sub": "u-from-sub", "email": "b@test.com"})

    assert request_user.uid == "u-from-sub"
    assert request_user.app_user_id == "u-from-sub"
    stored = client.collection(adb.USERS_COLLECTION).document("u-from-sub").get().to_dict()
    assert stored["firebase_uid"] == "u-from-sub"


# ---------------------------------------------------------------------------
# Edge-case: ensure_user existing user where no fields actually change
# ---------------------------------------------------------------------------
# When every field in the existing document already matches the decoded token
# values, the updates dict should remain empty and doc_ref.update() should
# never be called.
def test_ensure_user_skips_update_when_no_fields_change(mocker) -> None:
    client = FakeFirestoreClient()
    existing_doc = client.collection(adb.USERS_COLLECTION).document("u-1").seed(
        {
            "firebase_uid": "u-1",
            "email": "same@example.com",
            "displayName": "Same Name",
            adb.ROLE_FIELD: adb.ROLE_BASE,
            adb.RENAME_COUNT_FIELD: 0,
            adb.OPENAI_CREDITS_FIELD: adb.BASE_OPENAI_CREDITS,
            "created_at": "old-created",
            "updated_at": "old-updated",
        }
    )
    mocker.patch("backend.firebaseDB.user_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.user_database.now_iso", return_value="ts-new")

    request_user = adb.ensure_user({
        "uid": "u-1",
        "email": "same@example.com",
        "name": "Same Name",
    })

    # The existing doc should NOT have been updated because nothing changed
    assert len(existing_doc.update_calls) == 0
    assert request_user.uid == "u-1"
    assert request_user.email == "same@example.com"
    assert request_user.display_name == "Same Name"
    assert request_user.role == adb.ROLE_BASE
