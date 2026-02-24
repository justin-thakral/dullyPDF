"""Unit tests for backend.firebaseDB.credit_refund_database."""

from __future__ import annotations

import pytest

from backend.firebaseDB import credit_refund_database as refund_db
from backend.test.unit.firebase._fakes import FakeFirestoreClient


def test_record_credit_refund_failure_persists_pending_entry(mocker) -> None:
    fake_client = FakeFirestoreClient()
    mocker.patch.object(refund_db, "get_firestore_client", return_value=fake_client)
    mocker.patch.object(refund_db, "now_iso", return_value="2026-02-24T00:00:00+00:00")
    mocker.patch.object(refund_db, "log_expires_at", return_value=None)

    record_id = refund_db.record_credit_refund_failure(
        user_id="user-123",
        credits=4,
        role="pro",
        source="rename.sync_openai",
        error_message="firestore down",
        attempts=3,
        credit_breakdown={"monthly": 2, "refill": 2},
        request_id="req-1",
        job_id="job-1",
    )

    snapshot = fake_client.collection(refund_db.CREDIT_REFUND_FAILURES_COLLECTION).document(record_id).get()
    payload = snapshot.to_dict()
    assert payload["record_id"] == record_id
    assert payload["status"] == refund_db.CREDIT_REFUND_STATUS_PENDING
    assert payload["user_id"] == "user-123"
    assert payload["credits"] == 4
    assert payload["role"] == "pro"
    assert payload["source"] == "rename.sync_openai"
    assert payload["attempts"] == 3
    assert payload["request_id"] == "req-1"
    assert payload["job_id"] == "job-1"
    assert payload["credit_breakdown"] == {"base": 0, "monthly": 2, "refill": 2}


def test_mark_credit_refund_failure_resolved_updates_status(mocker) -> None:
    fake_client = FakeFirestoreClient()
    mocker.patch.object(refund_db, "get_firestore_client", return_value=fake_client)
    mocker.patch.object(refund_db, "now_iso", return_value="2026-02-24T00:00:00+00:00")
    mocker.patch.object(refund_db, "log_expires_at", return_value=None)
    record_id = refund_db.record_credit_refund_failure(
        user_id="user-123",
        credits=2,
        role="base",
        source="remap.sync_openai",
        error_message="db timeout",
        attempts=2,
    )

    refund_db.mark_credit_refund_failure_resolved(record_id, resolution_note="manual replay")

    payload = fake_client.collection(refund_db.CREDIT_REFUND_FAILURES_COLLECTION).document(record_id).get().to_dict()
    assert payload["status"] == refund_db.CREDIT_REFUND_STATUS_RESOLVED
    assert payload["resolution_note"] == "manual replay"


def test_record_credit_refund_failure_requires_user_and_source(mocker) -> None:
    fake_client = FakeFirestoreClient()
    mocker.patch.object(refund_db, "get_firestore_client", return_value=fake_client)
    mocker.patch.object(refund_db, "now_iso", return_value="2026-02-24T00:00:00+00:00")
    mocker.patch.object(refund_db, "log_expires_at", return_value=None)

    with pytest.raises(ValueError, match="user_id is required"):
        refund_db.record_credit_refund_failure(
            user_id="",
            credits=1,
            role="base",
            source="rename.sync_openai",
            error_message="oops",
            attempts=1,
        )

    with pytest.raises(ValueError, match="source is required"):
        refund_db.record_credit_refund_failure(
            user_id="user-1",
            credits=1,
            role="base",
            source="",
            error_message="oops",
            attempts=1,
        )
