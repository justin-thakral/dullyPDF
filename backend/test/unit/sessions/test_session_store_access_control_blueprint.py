"""Unit tests for access-control flows in backend.sessions.session_store."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from backend.firebaseDB.firebase_service import RequestUser
from backend.sessions import session_store as store
from backend.sessions import l1_cache
from backend.sessions import l2_persistence


def _user(app_user_id: str = "user-1") -> RequestUser:
    return RequestUser(uid=f"uid-{app_user_id}", app_user_id=app_user_id, email=f"{app_user_id}@example.com")


@pytest.fixture(autouse=True)
def _reset_l1_cache() -> None:
    store._API_SESSION_CACHE.clear()
    l1_cache._LAST_SESSION_SWEEP = 0.0
    yield
    store._API_SESSION_CACHE.clear()
    l1_cache._LAST_SESSION_SWEEP = 0.0


def test_require_owner_denies_when_user_id_missing() -> None:
    with pytest.raises(HTTPException) as excinfo:
        store._require_owner({}, _user())

    assert excinfo.value.status_code == 403
    assert excinfo.value.detail == "Session access denied"


def test_require_owner_denies_when_owner_mismatch() -> None:
    with pytest.raises(HTTPException) as excinfo:
        store._require_owner({"user_id": "user-2"}, _user("user-1"))

    assert excinfo.value.status_code == 403
    assert excinfo.value.detail == "Session access denied"


def test_require_owner_allows_matching_owner() -> None:
    store._require_owner({"user_id": "user-1"}, _user("user-1"))


def test_get_session_entry_raises_not_found_when_session_missing(mocker) -> None:
    mocker.patch.object(store, "_hydrate_from_l2", return_value=None)

    with pytest.raises(HTTPException) as excinfo:
        store.get_session_entry("sess-1", _user())

    assert excinfo.value.status_code == 404
    assert excinfo.value.detail == "Session not found"


def test_get_session_entry_raises_for_legacy_session_without_owner(mocker) -> None:
    mocker.patch.object(store, "_hydrate_from_l2", return_value={"source_pdf": "file.pdf"})

    with pytest.raises(HTTPException) as excinfo:
        store.get_session_entry("sess-legacy", _user())

    assert excinfo.value.status_code == 403


def test_get_session_entry_raises_for_cached_owner_mismatch(mocker, monkeypatch) -> None:
    store._API_SESSION_CACHE["sess-1"] = {
        "user_id": "user-2",
        "pdf_bytes": b"pdf",
        "fields": [],
        "result": {},
        "last_access": 100.0,
    }
    mocker.patch.object(store, "_hydrate_from_l2", return_value={"user_id": "user-1"})
    monkeypatch.setattr(l1_cache, "_SESSION_SWEEP_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(l1_cache, "_SESSION_TTL_SECONDS", -1)

    with pytest.raises(HTTPException) as excinfo:
        store.get_session_entry("sess-1", _user("user-1"))

    assert excinfo.value.status_code == 403
    store._hydrate_from_l2.assert_not_called()


def test_get_session_entry_force_l2_raises_not_found(mocker) -> None:
    mocker.patch.object(store, "_hydrate_from_l2", return_value=None)

    with pytest.raises(HTTPException) as excinfo:
        store.get_session_entry("sess-1", _user(), force_l2=True)

    assert excinfo.value.status_code == 404
    assert excinfo.value.detail == "Session not found"


def test_get_session_entry_force_l2_returns_entry_and_updates_l1_and_touch(mocker, monkeypatch) -> None:
    entry = {"user_id": "user-1", "source_pdf": "source.pdf"}
    mocker.patch.object(store, "_hydrate_from_l2", return_value=entry)
    store_l1 = mocker.patch.object(store, "_store_l1_entry")
    touch_l2 = mocker.patch.object(store, "_touch_l2_session")
    monkeypatch.setattr(store, "_session_now", lambda: 123.0)

    result = store.get_session_entry("sess-1", _user("user-1"), force_l2=True)

    assert result == entry
    store_l1.assert_called_once_with("sess-1", entry)
    touch_l2.assert_called_once_with("sess-1", entry, 123.0)


def test_get_session_entry_cached_hit_updates_last_access_and_touches_l2(mocker, monkeypatch) -> None:
    session_id = "sess-cache"
    entry = {"user_id": "user-1", "pdf_bytes": b"%PDF", "fields": [], "result": {}, "last_access": 10.0}
    store._API_SESSION_CACHE[session_id] = entry
    ensure = mocker.patch.object(store, "_ensure_l2_data")
    touch_l2 = mocker.patch.object(store, "_touch_l2_session")
    monkeypatch.setattr(l1_cache, "_SESSION_SWEEP_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(l1_cache, "_SESSION_TTL_SECONDS", -1)
    monkeypatch.setattr(store, "_session_now", lambda: 200.0)

    result = store.get_session_entry(session_id, _user("user-1"))

    assert result == entry
    assert entry["last_access"] == 200.0
    ensure.assert_called_once()
    touch_l2.assert_called_once_with(session_id, entry, 200.0)


def test_get_session_entry_cached_hit_raises_when_required_data_still_missing(mocker, monkeypatch) -> None:
    session_id = "sess-partial"
    store._API_SESSION_CACHE[session_id] = {"user_id": "user-1", "fields": [], "result": {}, "last_access": 10.0}
    mocker.patch.object(store, "_ensure_l2_data")
    touch_l2 = mocker.patch.object(store, "_touch_l2_session")
    monkeypatch.setattr(l1_cache, "_SESSION_SWEEP_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(l1_cache, "_SESSION_TTL_SECONDS", -1)
    monkeypatch.setattr(store, "_session_now", lambda: 200.0)

    with pytest.raises(HTTPException) as excinfo:
        store.get_session_entry(session_id, _user("user-1"))

    assert excinfo.value.status_code == 404
    assert excinfo.value.detail == "Session data not found"
    touch_l2.assert_not_called()


def test_get_session_entry_hydrates_from_l2_when_not_cached(mocker, monkeypatch) -> None:
    hydrated = {"user_id": "user-1", "pdf_bytes": b"%PDF", "fields": [], "result": {}}
    mocker.patch.object(store, "_hydrate_from_l2", return_value=hydrated)
    store_l1 = mocker.patch.object(store, "_store_l1_entry")
    touch_l2 = mocker.patch.object(store, "_touch_l2_session")
    monkeypatch.setattr(l1_cache, "_SESSION_SWEEP_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(l1_cache, "_SESSION_TTL_SECONDS", -1)
    times = iter([50.0, 60.0])
    monkeypatch.setattr(store, "_session_now", lambda: next(times))

    result = store.get_session_entry("sess-l2", _user("user-1"))

    assert result == hydrated
    store_l1.assert_called_once_with("sess-l2", hydrated)
    touch_l2.assert_called_once_with("sess-l2", hydrated, 60.0)


def test_get_session_entry_if_present_returns_none_for_empty_session_id() -> None:
    assert store.get_session_entry_if_present(None, _user()) is None


def test_get_session_entry_if_present_returns_none_when_not_found(mocker) -> None:
    mocker.patch.object(store, "_hydrate_from_l2", return_value=None)

    result = store.get_session_entry_if_present("sess-missing", _user())

    assert result is None


def test_get_session_entry_if_present_returns_none_when_required_data_missing(mocker, monkeypatch) -> None:
    session_id = "sess-partial"
    store._API_SESSION_CACHE[session_id] = {
        "user_id": "user-1",
        "fields": [],
        "result": {},
        "last_access": 100.0,
    }
    hydrate = mocker.patch.object(l2_persistence, "_hydrate_from_l2", return_value=None)
    monkeypatch.setattr(l1_cache, "_SESSION_SWEEP_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(l1_cache, "_SESSION_TTL_SECONDS", -1)

    result = store.get_session_entry_if_present(session_id, _user("user-1"))

    assert result is None
    hydrate.assert_called_once_with(
        session_id,
        include_pdf_bytes=True,
        include_fields=True,
        include_result=True,
        include_renames=True,
        include_checkbox_rules=True,
        include_text_transform_rules=False,
    )


def test_get_session_entry_if_present_force_l2_returns_none_when_not_found(mocker) -> None:
    mocker.patch.object(store, "_hydrate_from_l2", return_value=None)

    assert store.get_session_entry_if_present("sess-1", _user(), force_l2=True) is None


def test_get_session_entry_if_present_force_l2_returns_entry_and_updates_l1_and_touch(mocker, monkeypatch) -> None:
    entry = {"user_id": "user-1", "source_pdf": "source.pdf"}
    mocker.patch.object(store, "_hydrate_from_l2", return_value=entry)
    store_l1 = mocker.patch.object(store, "_store_l1_entry")
    touch_l2 = mocker.patch.object(store, "_touch_l2_session")
    monkeypatch.setattr(store, "_session_now", lambda: 300.0)

    result = store.get_session_entry_if_present("sess-1", _user("user-1"), force_l2=True)

    assert result == entry
    store_l1.assert_called_once_with("sess-1", entry)
    touch_l2.assert_called_once_with("sess-1", entry, 300.0)


def test_get_session_entry_if_present_cached_hit_updates_last_access_and_touches_l2(mocker, monkeypatch) -> None:
    session_id = "sess-cache"
    entry = {"user_id": "user-1", "pdf_bytes": b"%PDF", "fields": [], "result": {}, "last_access": 10.0}
    store._API_SESSION_CACHE[session_id] = entry
    ensure = mocker.patch.object(store, "_ensure_l2_data")
    touch_l2 = mocker.patch.object(store, "_touch_l2_session")
    monkeypatch.setattr(l1_cache, "_SESSION_SWEEP_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(l1_cache, "_SESSION_TTL_SECONDS", -1)
    monkeypatch.setattr(store, "_session_now", lambda: 400.0)

    result = store.get_session_entry_if_present(session_id, _user("user-1"))

    assert result == entry
    assert entry["last_access"] == 400.0
    ensure.assert_called_once()
    touch_l2.assert_called_once_with(session_id, entry, 400.0)


def test_get_session_entry_if_present_hydrates_from_l2_when_not_cached(mocker, monkeypatch) -> None:
    hydrated = {"user_id": "user-1", "pdf_bytes": b"%PDF", "fields": [], "result": {}}
    mocker.patch.object(store, "_hydrate_from_l2", return_value=hydrated)
    store_l1 = mocker.patch.object(store, "_store_l1_entry")
    touch_l2 = mocker.patch.object(store, "_touch_l2_session")
    monkeypatch.setattr(l1_cache, "_SESSION_SWEEP_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(l1_cache, "_SESSION_TTL_SECONDS", -1)
    times = iter([70.0, 80.0])
    monkeypatch.setattr(store, "_session_now", lambda: next(times))

    result = store.get_session_entry_if_present("sess-l2", _user("user-1"))

    assert result == hydrated
    store_l1.assert_called_once_with("sess-l2", hydrated)
    touch_l2.assert_called_once_with("sess-l2", hydrated, 80.0)


def test_touch_session_entry_raises_not_found_when_metadata_missing(mocker) -> None:
    mocker.patch.object(store, "get_session_metadata", return_value=None)

    with pytest.raises(HTTPException) as excinfo:
        store.touch_session_entry("sess-1", _user())

    assert excinfo.value.status_code == 404
    assert excinfo.value.detail == "Session not found"


def test_touch_session_entry_enforces_owner_for_legacy_missing_user_id(mocker) -> None:
    mocker.patch.object(store, "get_session_metadata", return_value={"source_pdf": "legacy.pdf"})

    with pytest.raises(HTTPException) as excinfo:
        store.touch_session_entry("sess-legacy", _user())

    assert excinfo.value.status_code == 403


def test_touch_session_entry_maps_l2_failure_to_503(mocker, monkeypatch) -> None:
    mocker.patch.object(store, "get_session_metadata", return_value={"user_id": "user-1"})
    mocker.patch.object(store, "upsert_session_metadata", side_effect=RuntimeError("firestore unavailable"))
    mocker.patch.object(store, "now_iso", return_value="2026-02-11T00:00:00+00:00")
    monkeypatch.setattr(store, "_expires_at", lambda: None)

    with pytest.raises(HTTPException) as excinfo:
        store.touch_session_entry("sess-1", _user("user-1"))

    assert excinfo.value.status_code == 503
    assert excinfo.value.detail == "Failed to refresh session"


def test_touch_session_entry_updates_cache_and_payload_on_success(mocker, monkeypatch) -> None:
    session_id = "sess-1"
    store._API_SESSION_CACHE[session_id] = {"user_id": "user-1", "last_access": 1.0}
    mocker.patch.object(store, "get_session_metadata", return_value={"user_id": "user-1"})
    upsert = mocker.patch.object(store, "upsert_session_metadata")
    mocker.patch.object(store, "now_iso", return_value="2026-02-11T00:00:00+00:00")
    expires_at = datetime(2026, 2, 11, tzinfo=timezone.utc)
    monkeypatch.setattr(store, "_expires_at", lambda: expires_at)
    monkeypatch.setattr(store, "_session_now", lambda: 55.5)

    store.touch_session_entry(session_id, _user("user-1"))

    upsert.assert_called_once_with(
        session_id,
        {"last_access_at": "2026-02-11T00:00:00+00:00", "expires_at": expires_at},
    )
    assert store._API_SESSION_CACHE[session_id]["last_access"] == 55.5
    assert store._API_SESSION_CACHE[session_id]["_l2_touch_at"] == 55.5


# ---------------------------------------------------------------------------
# Edge-case tests for _require_owner and session retrieval paths
# ---------------------------------------------------------------------------


def test_require_owner_denies_when_user_id_is_whitespace_only() -> None:
    """A user_id consisting entirely of whitespace is stripped to empty string
    by the ``(entry.get("user_id") or "").strip()`` chain, which means
    ``not owner_id`` is True and the function must raise 403 before ever
    comparing against the caller's app_user_id."""
    with pytest.raises(HTTPException) as excinfo:
        store._require_owner({"user_id": "   "}, _user("user-1"))

    assert excinfo.value.status_code == 403
    assert excinfo.value.detail == "Session access denied"


def test_require_owner_denies_when_user_id_is_explicit_none() -> None:
    """When the entry stores user_id as None (e.g. a legacy or corrupted
    record), the ``or ""`` fallback converts it to empty string, so the
    ``not owner_id`` guard fires and raises 403."""
    with pytest.raises(HTTPException) as excinfo:
        store._require_owner({"user_id": None}, _user("user-1"))

    assert excinfo.value.status_code == 403
    assert excinfo.value.detail == "Session access denied"


def test_get_session_entry_force_l2_raises_403_when_owner_mismatch(mocker, monkeypatch) -> None:
    """When force_l2=True, the entry is hydrated from L2 successfully but the
    owner check happens *after* hydration.  If the hydrated entry belongs to a
    different user, 403 must be raised and the entry must NOT be stored in L1."""
    hydrated = {"user_id": "user-other", "source_pdf": "source.pdf"}
    mocker.patch.object(store, "_hydrate_from_l2", return_value=hydrated)
    store_l1 = mocker.patch.object(store, "_store_l1_entry")
    touch_l2 = mocker.patch.object(store, "_touch_l2_session")
    monkeypatch.setattr(store, "_session_now", lambda: 500.0)

    with pytest.raises(HTTPException) as excinfo:
        store.get_session_entry("sess-1", _user("user-1"), force_l2=True)

    assert excinfo.value.status_code == 403
    # The entry must NOT be cached in L1 or touched in L2 after an access denial.
    store_l1.assert_not_called()
    touch_l2.assert_not_called()


def test_get_session_entry_if_present_returns_none_for_empty_string_session_id() -> None:
    """An empty string is falsy in Python, so the ``if not session_id`` guard
    at the top of get_session_entry_if_present must short-circuit and return
    None without attempting any cache or L2 lookup."""
    result = store.get_session_entry_if_present("", _user("user-1"))

    assert result is None
