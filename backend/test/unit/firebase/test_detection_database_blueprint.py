"""Unit tests for `backend/firebaseDB/detection_database.py`."""

from datetime import datetime, timezone

import pytest

from backend.firebaseDB import detection_database as ddb
from backend.test.unit.firebase._fakes import FakeFirestoreClient


def test_record_detection_request_requires_request_and_session_ids() -> None:
    with pytest.raises(ValueError, match="request_id and session_id are required"):
        ddb.record_detection_request(request_id="", session_id="s1", user_id=None, status="queued")

    with pytest.raises(ValueError, match="request_id and session_id are required"):
        ddb.record_detection_request(request_id="r1", session_id="", user_id=None, status="queued")


def test_record_detection_request_writes_payload_with_optional_fields(mocker) -> None:
    client = FakeFirestoreClient()
    expires_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    mocker.patch("backend.firebaseDB.detection_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.detection_database.now_iso", side_effect=["created-ts", "updated-ts"])
    mocker.patch("backend.firebaseDB.detection_database.log_expires_at", return_value=expires_at)

    ddb.record_detection_request(
        request_id="req-1",
        session_id="sess-1",
        user_id="user-1",
        status="queued",
        page_count=5,
        error="",
    )

    doc = client.collection(ddb.DETECTION_REQUESTS_COLLECTION).document("req-1").get().to_dict()
    assert doc == {
        "request_id": "req-1",
        "session_id": "sess-1",
        "user_id": "user-1",
        "status": "queued",
        "page_count": 5,
        "error": None,
        "created_at": "created-ts",
        "updated_at": "updated-ts",
        "expires_at": expires_at,
    }


def test_record_detection_request_omits_expires_at_when_ttl_disabled(mocker) -> None:
    client = FakeFirestoreClient()
    mocker.patch("backend.firebaseDB.detection_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.detection_database.now_iso", side_effect=["created-ts", "updated-ts"])
    mocker.patch("backend.firebaseDB.detection_database.log_expires_at", return_value=None)

    ddb.record_detection_request(
        request_id="req-1",
        session_id="sess-1",
        user_id=None,
        status="queued",
    )

    payload = client.collection(ddb.DETECTION_REQUESTS_COLLECTION).document("req-1").get().to_dict()
    assert "expires_at" not in payload
    assert payload["page_count"] is None
    assert payload["error"] is None


def test_update_detection_request_requires_request_id() -> None:
    with pytest.raises(ValueError, match="request_id is required"):
        ddb.update_detection_request(request_id="", status="done")


def test_update_detection_request_uses_merge_and_optional_fields(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(ddb.DETECTION_REQUESTS_COLLECTION).document("req-1").seed(
        {
            "request_id": "req-1",
            "status": "queued",
            "page_count": 2,
            "error": "old",
        }
    )
    mocker.patch("backend.firebaseDB.detection_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.detection_database.now_iso", return_value="updated-ts")

    ddb.update_detection_request(request_id="req-1", status="failed", page_count=7, error="")

    assert doc.set_calls[-1]["merge"] is True
    assert doc.get().to_dict() == {
        "request_id": "req-1",
        "status": "failed",
        "page_count": 7,
        "error": None,
        "updated_at": "updated-ts",
    }


def test_update_detection_request_leaves_error_and_page_count_untouched_when_not_provided(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(ddb.DETECTION_REQUESTS_COLLECTION).document("req-1").seed(
        {
            "request_id": "req-1",
            "status": "queued",
            "page_count": 2,
            "error": "old",
        }
    )
    mocker.patch("backend.firebaseDB.detection_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.detection_database.now_iso", return_value="updated-ts")

    ddb.update_detection_request(request_id="req-1", status="done")

    assert doc.get().to_dict() == {
        "request_id": "req-1",
        "status": "done",
        "page_count": 2,
        "error": "old",
        "updated_at": "updated-ts",
    }


# ---------------------------------------------------------------------------
# Edge-case: record_detection_request with non-empty error string
# ---------------------------------------------------------------------------
# When error is a truthy non-empty string, the `error or None` expression
# should evaluate to the string itself. The error should be stored as-is.
def test_record_detection_request_stores_truthy_error_string(mocker) -> None:
    client = FakeFirestoreClient()
    mocker.patch("backend.firebaseDB.detection_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.detection_database.now_iso", side_effect=["created-ts", "updated-ts"])
    mocker.patch("backend.firebaseDB.detection_database.log_expires_at", return_value=None)

    ddb.record_detection_request(
        request_id="req-err",
        session_id="sess-1",
        user_id="user-1",
        status="failed",
        page_count=3,
        error="something went wrong",
    )

    payload = client.collection(ddb.DETECTION_REQUESTS_COLLECTION).document("req-err").get().to_dict()
    assert payload["error"] == "something went wrong"
    assert payload["status"] == "failed"
    assert payload["page_count"] == 3
    assert "expires_at" not in payload


# ---------------------------------------------------------------------------
# Edge-case: update_detection_request with non-empty error string
# ---------------------------------------------------------------------------
# When error is a truthy non-empty string passed to the update function, it
# should be stored verbatim (the `error or None` branch evaluates to the string).
def test_update_detection_request_stores_truthy_error_string(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(ddb.DETECTION_REQUESTS_COLLECTION).document("req-1").seed(
        {
            "request_id": "req-1",
            "status": "queued",
            "page_count": 2,
            "error": None,
        }
    )
    mocker.patch("backend.firebaseDB.detection_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.detection_database.now_iso", return_value="updated-ts")

    ddb.update_detection_request(
        request_id="req-1",
        status="failed",
        error="timeout exceeded",
    )

    assert doc.set_calls[-1]["merge"] is True
    stored = doc.get().to_dict()
    assert stored["error"] == "timeout exceeded"
    assert stored["status"] == "failed"
    assert stored["updated_at"] == "updated-ts"
