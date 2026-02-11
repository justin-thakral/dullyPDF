"""Unit tests for `backend/security/rate_limit.py`."""

from datetime import datetime, timezone

import pytest

from backend.security import rate_limit as rl
from backend.test.unit.firebase._fakes import FakeFirestoreClient


@pytest.fixture(autouse=True)
def clear_rate_limit_state() -> None:
    rl._RATE_LIMIT_BUCKETS.clear()


def test_memory_rate_limit_allows_when_limit_is_non_positive(mocker) -> None:
    monotonic = mocker.patch("backend.security.rate_limit.time.monotonic")

    assert rl._memory_rate_limit("k", limit=0, window_seconds=10) is True
    assert rl._memory_rate_limit("k", limit=-1, window_seconds=10) is True

    monotonic.assert_not_called()
    assert rl._RATE_LIMIT_BUCKETS == {}


def test_memory_rate_limit_sliding_window_and_rollover(mocker) -> None:
    mocker.patch("backend.security.rate_limit.time.monotonic", side_effect=[0.0, 1.0, 2.0, 12.1])

    assert rl._memory_rate_limit("key-1", limit=2, window_seconds=10) is True
    assert rl._memory_rate_limit("key-1", limit=2, window_seconds=10) is True
    assert rl._memory_rate_limit("key-1", limit=2, window_seconds=10) is False
    assert rl._memory_rate_limit("key-1", limit=2, window_seconds=10) is True

    assert list(rl._RATE_LIMIT_BUCKETS["key-1"]) == [12.1]


def test_rate_limit_doc_id_is_stable_and_unique() -> None:
    key_a = "contact:203.0.113.10"
    key_b = "contact:203.0.113.11"

    doc_a1 = rl._rate_limit_doc_id(key_a)
    doc_a2 = rl._rate_limit_doc_id(key_a)
    doc_b = rl._rate_limit_doc_id(key_b)

    assert doc_a1 == doc_a2
    assert doc_a1 != doc_b
    assert doc_a1.startswith("rl_")
    assert len(doc_a1) == 67


def test_firestore_rate_limit_allows_without_firestore_when_limits_disabled(mocker) -> None:
    get_client = mocker.patch("backend.security.rate_limit.get_firestore_client")

    assert rl._firestore_rate_limit("k", limit=0, window_seconds=10) is True
    assert rl._firestore_rate_limit("k", limit=5, window_seconds=0) is True

    get_client.assert_not_called()


def test_firestore_rate_limit_transaction_increments_and_blocks_at_limit(mocker) -> None:
    client = FakeFirestoreClient()
    key = "rename:user-1"
    doc_id = rl._rate_limit_doc_id(key)
    mocker.patch("backend.security.rate_limit.get_firestore_client", return_value=client)
    mocker.patch.object(rl.firebase_firestore, "transactional", side_effect=lambda fn: fn)
    mocker.patch("backend.security.rate_limit.time.time", side_effect=[100.0, 101.0, 102.0])

    assert rl._firestore_rate_limit(key, limit=2, window_seconds=60) is True
    assert rl._firestore_rate_limit(key, limit=2, window_seconds=60) is True
    assert rl._firestore_rate_limit(key, limit=2, window_seconds=60) is False

    doc = client.collection(rl._RATE_LIMIT_COLLECTION).document(doc_id)
    payload = doc.get().to_dict()
    assert payload["window_start"] == 100.0
    assert payload["count"] == 2
    assert payload["updated_at"] == rl.firebase_firestore.SERVER_TIMESTAMP
    assert payload["expires_at"] == datetime.fromtimestamp(160.0, tz=timezone.utc)
    assert len(client.transactions) == 3
    assert all(call["merge"] is True for txn in client.transactions for call in txn.set_calls)


def test_firestore_rate_limit_rolls_window_and_resets_counter(mocker) -> None:
    client = FakeFirestoreClient()
    key = "contact:global"
    doc = client.collection(rl._RATE_LIMIT_COLLECTION).document(rl._rate_limit_doc_id(key))
    doc.seed({"window_start": 10.0, "count": 9, "expires_at": "old"})
    mocker.patch("backend.security.rate_limit.get_firestore_client", return_value=client)
    mocker.patch.object(rl.firebase_firestore, "transactional", side_effect=lambda fn: fn)
    mocker.patch("backend.security.rate_limit.time.time", return_value=100.0)

    assert rl._firestore_rate_limit(key, limit=2, window_seconds=60) is True

    payload = doc.get().to_dict()
    assert payload["window_start"] == 100.0
    assert payload["count"] == 1
    assert payload["expires_at"] == datetime.fromtimestamp(160.0, tz=timezone.utc)


def test_firestore_rate_limit_coerces_malformed_window_data(mocker) -> None:
    client = FakeFirestoreClient()
    key = "mapping:user-1"
    doc = client.collection(rl._RATE_LIMIT_COLLECTION).document(rl._rate_limit_doc_id(key))
    doc.seed({"window_start": "not-a-number", "count": "not-an-int"})
    mocker.patch("backend.security.rate_limit.get_firestore_client", return_value=client)
    mocker.patch.object(rl.firebase_firestore, "transactional", side_effect=lambda fn: fn)
    mocker.patch("backend.security.rate_limit.time.time", return_value=100.0)

    assert rl._firestore_rate_limit(key, limit=2, window_seconds=60) is True

    payload = doc.get().to_dict()
    assert payload["window_start"] == 100.0
    assert payload["count"] == 1
    assert payload["expires_at"] == datetime.fromtimestamp(160.0, tz=timezone.utc)


def test_check_rate_limit_uses_memory_backend_when_configured(mocker) -> None:
    mocker.patch.object(rl, "_RATE_LIMIT_BACKEND", "memory")
    memory_limit = mocker.patch.object(rl, "_memory_rate_limit", return_value=True)
    firestore_limit = mocker.patch.object(rl, "_firestore_rate_limit", return_value=False)

    assert rl.check_rate_limit("k", limit=3, window_seconds=30) is True
    memory_limit.assert_called_once_with("k", limit=3, window_seconds=30)
    firestore_limit.assert_not_called()


def test_check_rate_limit_uses_firestore_backend_when_available(mocker) -> None:
    mocker.patch.object(rl, "_RATE_LIMIT_BACKEND", "firestore")
    firestore_limit = mocker.patch.object(rl, "_firestore_rate_limit", return_value=True)
    memory_limit = mocker.patch.object(rl, "_memory_rate_limit")

    assert rl.check_rate_limit("k", limit=3, window_seconds=30) is True
    firestore_limit.assert_called_once_with("k", limit=3, window_seconds=30)
    memory_limit.assert_not_called()


def test_check_rate_limit_falls_back_to_memory_on_firestore_error(mocker) -> None:
    mocker.patch.object(rl, "_RATE_LIMIT_BACKEND", "firestore")
    mocker.patch.object(rl, "_firestore_rate_limit", side_effect=RuntimeError("firestore down"))
    memory_limit = mocker.patch.object(rl, "_memory_rate_limit", return_value=False)
    warning = mocker.patch.object(rl.logger, "warning")

    assert rl.check_rate_limit("k", limit=3, window_seconds=30) is False
    memory_limit.assert_called_once_with("k", limit=3, window_seconds=30)
    warning.assert_called_once()


def test_check_rate_limit_unknown_backend_still_falls_back_on_firestore_error(mocker) -> None:
    mocker.patch.object(rl, "_RATE_LIMIT_BACKEND", "unknown")
    firestore_limit = mocker.patch.object(rl, "_firestore_rate_limit", side_effect=RuntimeError("boom"))
    memory_limit = mocker.patch.object(rl, "_memory_rate_limit", return_value=True)

    assert rl.check_rate_limit("k", limit=3, window_seconds=30) is True
    firestore_limit.assert_called_once_with("k", limit=3, window_seconds=30)
    memory_limit.assert_called_once_with("k", limit=3, window_seconds=30)


# ---------------------------------------------------------------------------
# Edge-case tests added for additional branch coverage
# ---------------------------------------------------------------------------


def test_memory_rate_limit_different_keys_are_independent(mocker) -> None:
    """Rate-limiting key A should not affect key B. Exhausting the limit on
    one key must leave the other key unaffected."""
    mocker.patch(
        "backend.security.rate_limit.time.monotonic",
        # 3 calls for key_a (0, 1, 2) then 1 call for key_b (3)
        side_effect=[0.0, 1.0, 2.0, 3.0],
    )

    # Exhaust the limit for key_a (limit=2)
    assert rl._memory_rate_limit("key_a", limit=2, window_seconds=60) is True
    assert rl._memory_rate_limit("key_a", limit=2, window_seconds=60) is True
    assert rl._memory_rate_limit("key_a", limit=2, window_seconds=60) is False

    # key_b should still be allowed despite key_a being exhausted
    assert rl._memory_rate_limit("key_b", limit=2, window_seconds=60) is True


def test_memory_rate_limit_window_seconds_zero_evicts_all_previous(mocker) -> None:
    """With window_seconds=0, every previous timestamp satisfies
    (now - bucket[0]) > 0, so the entire bucket is evicted on each call.
    This means every request is allowed as long as limit >= 1."""
    mocker.patch(
        "backend.security.rate_limit.time.monotonic",
        side_effect=[0.0, 0.0, 0.0, 0.0],
    )

    # Even with limit=1, each call evicts old entries (>0 window) so all pass.
    # At t=0, (0 - 0) > 0 is False so the first entry stays, meaning the
    # second call at the same time sees a full bucket if limit=1.
    # Let's use sequential timestamps to show the eviction behaviour.
    rl._RATE_LIMIT_BUCKETS.clear()
    mocker.stopall()
    mocker.patch(
        "backend.security.rate_limit.time.monotonic",
        side_effect=[1.0, 2.0, 3.0],
    )

    assert rl._memory_rate_limit("z", limit=1, window_seconds=0) is True
    # At t=2.0, (2.0 - 1.0) > 0 is True, so the bucket is cleared, allowing
    assert rl._memory_rate_limit("z", limit=1, window_seconds=0) is True
    assert rl._memory_rate_limit("z", limit=1, window_seconds=0) is True


def test_firestore_rate_limit_allows_when_limit_negative(mocker) -> None:
    """When limit is negative (limit <= 0), _firestore_rate_limit should
    return True immediately without touching Firestore at all."""
    get_client = mocker.patch("backend.security.rate_limit.get_firestore_client")

    assert rl._firestore_rate_limit("k", limit=-1, window_seconds=10) is True

    get_client.assert_not_called()
