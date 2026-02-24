"""Unit tests for Stripe webhook event lock bookkeeping."""

from __future__ import annotations

import pytest

from backend.firebaseDB import billing_database as bdb
from backend.test.unit.firebase._fakes import FakeFirestoreClient


def test_start_billing_event_returns_false_for_processed_event(mocker) -> None:
    client = FakeFirestoreClient()
    client.collection(bdb.BILLING_EVENTS_COLLECTION).document("evt_1").seed(
        {
            "event_id": "evt_1",
            "event_type": "checkout.session.completed",
            "status": bdb.BILLING_EVENT_STATUS_PROCESSED,
            "created_at": "ts-created",
            "updated_at": "ts-updated",
            "attempts": 1,
        }
    )
    mocker.patch("backend.firebaseDB.billing_database.get_firestore_client", return_value=client)
    mocker.patch(
        "backend.firebaseDB.billing_database.firebase_firestore.transactional",
        side_effect=lambda fn: fn,
    )

    started = bdb.start_billing_event("evt_1", "checkout.session.completed")

    assert started is False
    assert client.transactions[0].set_calls == []


def test_start_billing_event_reclaims_failed_event_and_increments_attempts(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(bdb.BILLING_EVENTS_COLLECTION).document("evt_2").seed(
        {
            "event_id": "evt_2",
            "event_type": "checkout.session.completed",
            "status": bdb.BILLING_EVENT_STATUS_FAILED,
            "created_at": "ts-created",
            "updated_at": "ts-old",
            "attempts": 2,
        }
    )
    mocker.patch("backend.firebaseDB.billing_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.billing_database.now_iso", return_value="ts-retry")
    mocker.patch("backend.firebaseDB.billing_database.log_expires_at", return_value=None)
    mocker.patch(
        "backend.firebaseDB.billing_database.firebase_firestore.transactional",
        side_effect=lambda fn: fn,
    )

    started = bdb.start_billing_event("evt_2", "invoice.paid")

    assert started is True
    stored = doc.get().to_dict()
    assert stored["status"] == bdb.BILLING_EVENT_STATUS_PROCESSING
    assert stored["event_type"] == "invoice.paid"
    assert stored["attempts"] == 3
    assert stored["updated_at"] == "ts-retry"


def test_start_billing_event_reclaims_stale_processing_lock(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(bdb.BILLING_EVENTS_COLLECTION).document("evt_3").seed(
        {
            "event_id": "evt_3",
            "event_type": "checkout.session.completed",
            "status": bdb.BILLING_EVENT_STATUS_PROCESSING,
            "created_at": "ts-created",
            "updated_at": "2000-01-01T00:00:00+00:00",
            "attempts": 1,
        }
    )
    mocker.patch("backend.firebaseDB.billing_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.billing_database.now_iso", return_value="ts-stale-retry")
    mocker.patch("backend.firebaseDB.billing_database.log_expires_at", return_value=None)
    mocker.patch("backend.firebaseDB.billing_database.BILLING_EVENT_LOCK_TIMEOUT_SECONDS", 60)
    mocker.patch(
        "backend.firebaseDB.billing_database.firebase_firestore.transactional",
        side_effect=lambda fn: fn,
    )

    started = bdb.start_billing_event("evt_3", "checkout.session.completed")

    assert started is True
    stored = doc.get().to_dict()
    assert stored["status"] == bdb.BILLING_EVENT_STATUS_PROCESSING
    assert stored["attempts"] == 2
    assert stored["updated_at"] == "ts-stale-retry"


def test_start_billing_event_keeps_fresh_processing_lock(mocker) -> None:
    client = FakeFirestoreClient()
    client.collection(bdb.BILLING_EVENTS_COLLECTION).document("evt_4").seed(
        {
            "event_id": "evt_4",
            "event_type": "checkout.session.completed",
            "status": bdb.BILLING_EVENT_STATUS_PROCESSING,
            "created_at": "ts-created",
            "updated_at": "2999-01-01T00:00:00+00:00",
            "attempts": 1,
        }
    )
    mocker.patch("backend.firebaseDB.billing_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.billing_database.now_iso", return_value="ts-now")
    mocker.patch("backend.firebaseDB.billing_database.log_expires_at", return_value=None)
    mocker.patch("backend.firebaseDB.billing_database.BILLING_EVENT_LOCK_TIMEOUT_SECONDS", 60)
    mocker.patch(
        "backend.firebaseDB.billing_database.firebase_firestore.transactional",
        side_effect=lambda fn: fn,
    )

    with pytest.raises(bdb.BillingEventInProgressError):
        bdb.start_billing_event("evt_4", "checkout.session.completed")

    assert client.transactions[0].set_calls == []


def test_clear_billing_event_marks_failed_instead_of_deleting(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(bdb.BILLING_EVENTS_COLLECTION).document("evt_5").seed(
        {
            "event_id": "evt_5",
            "status": bdb.BILLING_EVENT_STATUS_PROCESSING,
        }
    )
    mocker.patch("backend.firebaseDB.billing_database.get_firestore_client", return_value=client)
    mocker.patch("backend.firebaseDB.billing_database.now_iso", return_value="ts-failed")

    bdb.clear_billing_event("evt_5")

    stored = doc.get().to_dict()
    assert stored["status"] == bdb.BILLING_EVENT_STATUS_FAILED
    assert stored["updated_at"] == "ts-failed"
    assert doc.delete_calls == 0


def test_delete_billing_event_removes_lock_document(mocker) -> None:
    client = FakeFirestoreClient()
    doc = client.collection(bdb.BILLING_EVENTS_COLLECTION).document("evt_delete").seed(
        {
            "event_id": "evt_delete",
            "status": bdb.BILLING_EVENT_STATUS_PROCESSING,
        }
    )
    mocker.patch("backend.firebaseDB.billing_database.get_firestore_client", return_value=client)

    bdb.delete_billing_event("evt_delete")

    assert doc.delete_calls == 1
