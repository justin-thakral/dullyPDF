"""Unit tests for `backend/firebaseDB/session_database.py`."""

import pytest

from backend.firebaseDB import session_database as sdb
from backend.test.unit.firebase._fakes import FakeFirestoreClient


def test_get_session_metadata_returns_none_when_session_id_missing(mocker) -> None:
    get_client = mocker.patch("backend.firebaseDB.session_database.get_firestore_client")

    assert sdb.get_session_metadata("") is None
    get_client.assert_not_called()


def test_get_session_metadata_returns_none_when_document_missing(mocker) -> None:
    client = FakeFirestoreClient()
    mocker.patch("backend.firebaseDB.session_database.get_firestore_client", return_value=client)

    assert sdb.get_session_metadata("session-1") is None


def test_get_session_metadata_returns_payload_when_document_exists(mocker) -> None:
    client = FakeFirestoreClient()
    client.collection(sdb.SESSION_COLLECTION).document("session-1").seed({"k": "v"})
    mocker.patch("backend.firebaseDB.session_database.get_firestore_client", return_value=client)

    assert sdb.get_session_metadata("session-1") == {"k": "v"}


def test_upsert_session_metadata_raises_for_missing_session_id() -> None:
    with pytest.raises(ValueError, match="Missing session_id"):
        sdb.upsert_session_metadata("", {})


def test_upsert_session_metadata_injects_updated_at_when_missing(mocker) -> None:
    client = FakeFirestoreClient()
    mocker.patch("backend.firebaseDB.session_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.session_database.now_iso", return_value="ts-now")

    sdb.upsert_session_metadata("session-1", {"status": "ready"})

    doc = client.collection(sdb.SESSION_COLLECTION).document("session-1")
    assert doc.get().to_dict() == {"status": "ready", "updated_at": "ts-now"}
    assert doc.set_calls[-1]["merge"] is True


def test_upsert_session_metadata_keeps_updated_at_when_provided(mocker) -> None:
    client = FakeFirestoreClient()
    mocker.patch("backend.firebaseDB.session_database.get_firestore_client", return_value=client)
    now_iso = mocker.patch("backend.firebaseDB.session_database.now_iso")

    sdb.upsert_session_metadata("session-1", {"updated_at": "manual-ts", "status": "done"})

    doc = client.collection(sdb.SESSION_COLLECTION).document("session-1")
    assert doc.get().to_dict() == {"updated_at": "manual-ts", "status": "done"}
    now_iso.assert_not_called()


def test_delete_session_metadata_skips_when_session_id_missing(mocker) -> None:
    get_client = mocker.patch("backend.firebaseDB.session_database.get_firestore_client")

    sdb.delete_session_metadata("")

    get_client.assert_not_called()


def test_delete_session_metadata_deletes_document(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(sdb.SESSION_COLLECTION).document("session-1").seed({"status": "ready"})
    mocker.patch("backend.firebaseDB.session_database.get_firestore_client", return_value=client)

    sdb.delete_session_metadata("session-1")

    assert doc.delete_calls == 1
    assert doc.get().exists is False
