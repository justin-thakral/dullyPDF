"""Unit tests for L1 cache behavior in backend.sessions.session_store."""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timedelta, timezone

import pytest

from backend.sessions import session_store as store
from backend.sessions import l1_cache
from backend.sessions import l2_persistence


@pytest.fixture(autouse=True)
def _reset_l1_cache() -> None:
    l1_cache._API_SESSION_CACHE.clear()
    l1_cache._LAST_SESSION_SWEEP = 0.0
    yield
    l1_cache._API_SESSION_CACHE.clear()
    l1_cache._LAST_SESSION_SWEEP = 0.0


def test_session_last_access_coerces_last_access_and_created_at() -> None:
    assert l1_cache._session_last_access({"last_access": "12.5"}) == 12.5
    assert l1_cache._session_last_access({"created_at": "7"}) == 7.0
    assert l1_cache._session_last_access({"last_access": 0, "created_at": 9}) == 9.0


def test_session_last_access_returns_zero_for_malformed_values() -> None:
    assert l1_cache._session_last_access({"last_access": object()}) == 0.0
    assert l1_cache._session_last_access({"created_at": "not-a-number"}) == 0.0


def test_prune_session_cache_removes_expired_entries(monkeypatch) -> None:
    monkeypatch.setattr(l1_cache, "_SESSION_TTL_SECONDS", 100)
    monkeypatch.setattr(l1_cache, "_SESSION_SWEEP_INTERVAL_SECONDS", 0)
    l1_cache._LAST_SESSION_SWEEP = 0.0
    l1_cache._API_SESSION_CACHE.update(
        OrderedDict(
            [
                ("expired", {"last_access": 1.0}),
                ("fresh", {"last_access": 150.0}),
            ]
        )
    )

    l1_cache._prune_session_cache(now=200.0)

    assert list(l1_cache._API_SESSION_CACHE.keys()) == ["fresh"]
    assert l1_cache._LAST_SESSION_SWEEP == 200.0


def test_prune_session_cache_short_circuits_within_sweep_interval(monkeypatch) -> None:
    monkeypatch.setattr(l1_cache, "_SESSION_TTL_SECONDS", 100)
    monkeypatch.setattr(l1_cache, "_SESSION_SWEEP_INTERVAL_SECONDS", 30)
    l1_cache._LAST_SESSION_SWEEP = 190.0
    l1_cache._API_SESSION_CACHE["expired"] = {"last_access": 10.0}

    l1_cache._prune_session_cache(now=200.0)

    assert list(l1_cache._API_SESSION_CACHE.keys()) == ["expired"]
    assert l1_cache._LAST_SESSION_SWEEP == 190.0


def test_trim_session_cache_size_evicts_lru(monkeypatch) -> None:
    monkeypatch.setattr(l1_cache, "_SESSION_MAX_ENTRIES", 2)
    l1_cache._API_SESSION_CACHE.update(
        OrderedDict(
            [
                ("a", {"last_access": 1.0}),
                ("b", {"last_access": 2.0}),
                ("c", {"last_access": 3.0}),
            ]
        )
    )

    l1_cache._trim_session_cache_size()

    assert list(l1_cache._API_SESSION_CACHE.keys()) == ["b", "c"]


def test_trim_session_cache_size_noop_when_max_entries_zero(monkeypatch) -> None:
    monkeypatch.setattr(l1_cache, "_SESSION_MAX_ENTRIES", 0)
    l1_cache._API_SESSION_CACHE.update(OrderedDict([("a", {}), ("b", {})]))

    l1_cache._trim_session_cache_size()

    assert list(l1_cache._API_SESSION_CACHE.keys()) == ["a", "b"]


def test_store_l1_entry_sets_timestamps_and_updates_lru_order(monkeypatch) -> None:
    times = iter([1.0, 2.0, 3.0])
    monkeypatch.setattr(l1_cache, "_session_now", lambda: next(times))
    monkeypatch.setattr(l1_cache, "_SESSION_SWEEP_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(l1_cache, "_SESSION_TTL_SECONDS", 1000)
    monkeypatch.setattr(l1_cache, "_SESSION_MAX_ENTRIES", 10)

    l1_cache._store_l1_entry("a", {"payload": "first"})
    l1_cache._store_l1_entry("b", {"payload": "second"})
    l1_cache._store_l1_entry("a", {"payload": "updated"})

    assert list(l1_cache._API_SESSION_CACHE.keys()) == ["b", "a"]
    assert l1_cache._API_SESSION_CACHE["a"]["created_at"] == 3.0
    assert l1_cache._API_SESSION_CACHE["a"]["last_access"] == 3.0
    assert l1_cache._API_SESSION_CACHE["a"]["payload"] == "updated"


def test_session_object_path_trims_inputs_and_builds_expected_path() -> None:
    assert l2_persistence._session_object_path("  sess-1  ", " /fields.json ") == "sessions/sess-1/fields.json"


def test_session_object_path_rejects_missing_session_id() -> None:
    with pytest.raises(ValueError, match="Missing session_id"):
        l2_persistence._session_object_path("   ", "fields.json")


def test_session_object_path_rejects_missing_suffix() -> None:
    with pytest.raises(ValueError, match="Missing session artifact suffix"):
        l2_persistence._session_object_path("sess-1", " / ")


def test_expires_at_returns_none_when_ttl_is_non_positive(monkeypatch) -> None:
    monkeypatch.setattr(l2_persistence, "_SESSION_TTL_SECONDS", 0)

    assert l2_persistence._expires_at() is None


def test_expires_at_returns_utc_timestamp_when_ttl_positive(monkeypatch) -> None:
    monkeypatch.setattr(l2_persistence, "_SESSION_TTL_SECONDS", 30)
    before = datetime.now(timezone.utc)

    value = l2_persistence._expires_at()
    after = datetime.now(timezone.utc)

    assert value is not None
    assert value.tzinfo is not None
    assert value.utcoffset() == timedelta(0)
    assert before + timedelta(seconds=30) <= value <= after + timedelta(seconds=30)


# ---------------------------------------------------------------------------
# Edge-case tests for L1 cache helpers
# ---------------------------------------------------------------------------


def test_session_last_access_zero_last_access_no_created_at_falls_through() -> None:
    """When last_access is 0 (integer zero is falsy) and created_at is absent,
    the ``or`` chain ``entry.get("last_access") or entry.get("created_at") or 0.0``
    evaluates each operand: 0 is falsy so it moves to created_at (missing, also
    falsy), then falls through to the literal 0.0.  The result is 0.0."""
    result = l1_cache._session_last_access({"last_access": 0})
    assert result == 0.0


def test_session_last_access_empty_dict_returns_zero() -> None:
    """An empty dict has neither last_access nor created_at, so every ``get``
    returns None (falsy) and the ``or`` chain produces the final literal 0.0."""
    result = l1_cache._session_last_access({})
    assert result == 0.0


def test_prune_session_cache_early_returns_when_ttl_non_positive(monkeypatch) -> None:
    """When _SESSION_TTL_SECONDS is zero or negative, pruning is completely
    disabled.  The function returns immediately without inspecting the cache or
    updating _LAST_SESSION_SWEEP, even if the cache contains entries."""
    monkeypatch.setattr(l1_cache, "_SESSION_TTL_SECONDS", 0)
    monkeypatch.setattr(l1_cache, "_SESSION_SWEEP_INTERVAL_SECONDS", 0)
    l1_cache._LAST_SESSION_SWEEP = 0.0
    l1_cache._API_SESSION_CACHE["old"] = {"last_access": 1.0}

    l1_cache._prune_session_cache(now=99999.0)

    # The entry must still be present because pruning was disabled.
    assert "old" in l1_cache._API_SESSION_CACHE
    # _LAST_SESSION_SWEEP must remain unchanged.
    assert l1_cache._LAST_SESSION_SWEEP == 0.0


def test_expires_at_returns_none_when_ttl_is_negative(monkeypatch) -> None:
    """A negative TTL is treated identically to zero: the ``<= 0`` guard fires
    and _expires_at returns None, meaning no expiry timestamp is generated."""
    monkeypatch.setattr(l2_persistence, "_SESSION_TTL_SECONDS", -5)

    assert l2_persistence._expires_at() is None
