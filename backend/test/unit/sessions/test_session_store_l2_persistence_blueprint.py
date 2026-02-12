"""Unit tests for L2 persistence behavior in backend.sessions.session_store."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.sessions import session_store as store
from backend.sessions import l2_persistence


def test_persist_session_entry_raises_when_persist_pdf_missing_bytes(mocker) -> None:
    upload_pdf = mocker.patch.object(l2_persistence, "upload_session_pdf_bytes")
    upsert = mocker.patch.object(l2_persistence, "upsert_session_metadata")

    with pytest.raises(ValueError, match="Session PDF bytes missing"):
        store._persist_session_entry("sess-1", {}, persist_pdf=True)

    upload_pdf.assert_not_called()
    upsert.assert_not_called()


def test_persist_session_entry_persists_flagged_artifacts_and_metadata(mocker, monkeypatch) -> None:
    entry = {
        "user_id": "user-1",
        "source_pdf": "source.pdf",
        "page_count": 2,
        "pdf_bytes": b"%PDF-1.4",
        "fields": [{"name": "A"}],
        "result": {"ok": True},
        "renames": {"A": "first_name"},
        "checkboxRules": [{"name": "agree"}],
        "checkboxHints": [{"name": "agree", "hint": "x"}],
        "detection_status": "complete",
    }
    upload_pdf = mocker.patch.object(l2_persistence, "upload_session_pdf_bytes", return_value="gs://bucket/sess/source.pdf")
    upload_json = mocker.patch.object(
        l2_persistence,
        "upload_session_json",
        side_effect=[
            "gs://bucket/sess/fields.json",
            "gs://bucket/sess/result.json",
            "gs://bucket/sess/renames.json",
            "gs://bucket/sess/checkbox-rules.json",
            "gs://bucket/sess/checkbox-hints.json",
        ],
    )
    upsert = mocker.patch.object(l2_persistence, "upsert_session_metadata")
    mocker.patch.object(l2_persistence, "now_iso", return_value="2026-02-11T00:00:00+00:00")
    monkeypatch.setattr(l2_persistence, "_session_now", lambda: 42.0)
    expires_at = datetime(2026, 2, 11, tzinfo=timezone.utc)
    monkeypatch.setattr(l2_persistence, "_expires_at", lambda: expires_at)

    store._persist_session_entry(
        "sess-1",
        entry,
        persist_pdf=True,
        persist_fields=True,
        persist_result=True,
        persist_renames=True,
        persist_checkbox_rules=True,
        persist_checkbox_hints=True,
        include_created_at=True,
    )

    upload_pdf.assert_called_once_with(b"%PDF-1.4", "sessions/sess-1/source.pdf")
    assert upload_json.call_count == 5
    upsert.assert_called_once()
    metadata = upsert.call_args.args[1]
    assert metadata["user_id"] == "user-1"
    assert metadata["source_pdf"] == "source.pdf"
    assert metadata["page_count"] == 2
    assert metadata["version"] == 1
    assert metadata["created_at"] == "2026-02-11T00:00:00+00:00"
    assert metadata["last_access_at"] == "2026-02-11T00:00:00+00:00"
    assert metadata["expires_at"] == expires_at
    assert metadata["pdf_path"] == "gs://bucket/sess/source.pdf"
    assert metadata["fields_path"] == "gs://bucket/sess/fields.json"
    assert metadata["result_path"] == "gs://bucket/sess/result.json"
    assert metadata["renames_path"] == "gs://bucket/sess/renames.json"
    assert metadata["checkbox_rules_path"] == "gs://bucket/sess/checkbox-rules.json"
    assert metadata["checkbox_hints_path"] == "gs://bucket/sess/checkbox-hints.json"
    assert metadata["detection_status"] == "complete"
    assert entry["pdf_path"] == "gs://bucket/sess/source.pdf"
    assert entry["fields_path"] == "gs://bucket/sess/fields.json"
    assert entry["result_path"] == "gs://bucket/sess/result.json"
    assert entry["renames_path"] == "gs://bucket/sess/renames.json"
    assert entry["checkbox_rules_path"] == "gs://bucket/sess/checkbox-rules.json"
    assert entry["checkbox_hints_path"] == "gs://bucket/sess/checkbox-hints.json"
    assert entry["_l2_touch_at"] == 42.0


def test_persist_session_entry_reuses_existing_paths_when_flags_disabled(mocker, monkeypatch) -> None:
    entry = {
        "user_id": "user-1",
        "source_pdf": "source.pdf",
        "page_count": 1,
        "pdf_path": "gs://bucket/sess/source.pdf",
        "fields_path": "gs://bucket/sess/fields.json",
        "result_path": "gs://bucket/sess/result.json",
        "renames_path": "gs://bucket/sess/renames.json",
        "checkbox_rules_path": "gs://bucket/sess/checkbox-rules.json",
        "checkbox_hints_path": "gs://bucket/sess/checkbox-hints.json",
    }
    upload_pdf = mocker.patch.object(l2_persistence, "upload_session_pdf_bytes")
    upload_json = mocker.patch.object(l2_persistence, "upload_session_json")
    upsert = mocker.patch.object(l2_persistence, "upsert_session_metadata")
    mocker.patch.object(l2_persistence, "now_iso", return_value="2026-02-11T00:00:00+00:00")
    monkeypatch.setattr(l2_persistence, "_session_now", lambda: 9.0)
    monkeypatch.setattr(l2_persistence, "_expires_at", lambda: None)

    store._persist_session_entry("sess-1", entry, persist_pdf=False, persist_fields=False, include_created_at=False)

    upload_pdf.assert_not_called()
    upload_json.assert_not_called()
    upsert.assert_called_once()
    metadata = upsert.call_args.args[1]
    assert metadata["pdf_path"] == "gs://bucket/sess/source.pdf"
    assert metadata["fields_path"] == "gs://bucket/sess/fields.json"
    assert metadata["result_path"] == "gs://bucket/sess/result.json"
    assert metadata["renames_path"] == "gs://bucket/sess/renames.json"
    assert metadata["checkbox_rules_path"] == "gs://bucket/sess/checkbox-rules.json"
    assert metadata["checkbox_hints_path"] == "gs://bucket/sess/checkbox-hints.json"
    assert "created_at" not in metadata
    assert "expires_at" not in metadata
    assert entry["_l2_touch_at"] == 9.0


@pytest.mark.parametrize(
    ("entry", "kwargs", "expected"),
    [
        ({}, {"include_pdf_bytes": True}, True),
        ({"pdf_bytes": b"x"}, {"include_pdf_bytes": True}, False),
        ({}, {"include_fields": True}, True),
        ({"fields": []}, {"include_fields": True}, False),
        ({"result_path": "r.json"}, {"include_result": True}, True),
        ({"result_path": "r.json", "result": {}}, {"include_result": True}, False),
        ({"renames_path": "renames.json"}, {"include_renames": True}, True),
        ({"checkbox_rules_path": "rules.json"}, {"include_checkbox_rules": True}, True),
        ({"checkbox_hints_path": "hints.json"}, {"include_checkbox_hints": True}, True),
    ],
)
def test_missing_required_data_logic(entry, kwargs, expected) -> None:
    result = store._missing_required_data(
        entry,
        include_pdf_bytes=kwargs.get("include_pdf_bytes", False),
        include_fields=kwargs.get("include_fields", False),
        include_result=kwargs.get("include_result", False),
        include_renames=kwargs.get("include_renames", False),
        include_checkbox_rules=kwargs.get("include_checkbox_rules", False),
        include_checkbox_hints=kwargs.get("include_checkbox_hints", False),
    )
    assert result is expected


def test_hydrate_from_l2_returns_none_when_metadata_missing(mocker) -> None:
    mocker.patch.object(l2_persistence, "get_session_metadata", return_value=None)
    download_pdf = mocker.patch.object(l2_persistence, "download_pdf_bytes")
    download_json = mocker.patch.object(l2_persistence, "download_session_json")

    entry = store._hydrate_from_l2(
        "sess-1",
        include_pdf_bytes=True,
        include_fields=True,
        include_result=True,
        include_renames=True,
        include_checkbox_rules=True,
        include_checkbox_hints=True,
    )

    assert entry is None
    download_pdf.assert_not_called()
    download_json.assert_not_called()


def test_hydrate_from_l2_populates_only_requested_artifacts(mocker) -> None:
    mocker.patch.object(
        l2_persistence,
        "get_session_metadata",
        return_value={
            "user_id": "user-1",
            "source_pdf": "source.pdf",
            "pdf_path": "sessions/sess-1/source.pdf",
            "fields_path": "sessions/sess-1/fields.json",
            "result_path": "sessions/sess-1/result.json",
            "renames_path": "sessions/sess-1/renames.json",
            "checkbox_rules_path": "sessions/sess-1/checkbox-rules.json",
            "checkbox_hints_path": "sessions/sess-1/checkbox-hints.json",
            "page_count": 1,
        },
    )
    download_pdf = mocker.patch.object(l2_persistence, "download_pdf_bytes", return_value=b"%PDF")
    download_json = mocker.patch.object(
        l2_persistence,
        "download_session_json",
        side_effect=[
            None,
            {"done": True},
            {"A": "first_name"},
            [{"rule": "x"}],
            None,
        ],
    )

    entry = store._hydrate_from_l2(
        "sess-1",
        include_pdf_bytes=True,
        include_fields=True,
        include_result=True,
        include_renames=True,
        include_checkbox_rules=True,
        include_checkbox_hints=True,
    )

    assert entry is not None
    assert entry["pdf_bytes"] == b"%PDF"
    assert entry["fields"] == []
    assert entry["result"] == {"done": True}
    assert entry["renames"] == {"A": "first_name"}
    assert entry["checkboxRules"] == [{"rule": "x"}]
    assert entry["checkboxHints"] == []
    download_pdf.assert_called_once_with("sessions/sess-1/source.pdf")
    assert download_json.call_count == 5


def test_hydrate_from_l2_skips_downloads_when_paths_absent(mocker) -> None:
    mocker.patch.object(l2_persistence, "get_session_metadata", return_value={"user_id": "user-1", "source_pdf": "a.pdf"})
    download_pdf = mocker.patch.object(l2_persistence, "download_pdf_bytes")
    download_json = mocker.patch.object(l2_persistence, "download_session_json")

    entry = store._hydrate_from_l2(
        "sess-1",
        include_pdf_bytes=True,
        include_fields=True,
        include_result=True,
        include_renames=True,
        include_checkbox_rules=True,
        include_checkbox_hints=True,
    )

    assert entry is not None
    assert "pdf_bytes" not in entry
    assert "fields" not in entry
    download_pdf.assert_not_called()
    download_json.assert_not_called()


def test_touch_l2_session_skips_when_ttl_or_interval_disabled(mocker, monkeypatch) -> None:
    upsert = mocker.patch.object(l2_persistence, "upsert_session_metadata")

    monkeypatch.setattr(l2_persistence, "_SESSION_TTL_SECONDS", 0)
    monkeypatch.setattr(l2_persistence, "_SESSION_L2_TOUCH_SECONDS", 60)
    store._touch_l2_session("sess-1", {}, now=100.0)
    upsert.assert_not_called()

    monkeypatch.setattr(l2_persistence, "_SESSION_TTL_SECONDS", 60)
    monkeypatch.setattr(l2_persistence, "_SESSION_L2_TOUCH_SECONDS", 0)
    store._touch_l2_session("sess-1", {}, now=100.0)
    upsert.assert_not_called()


def test_touch_l2_session_throttles_when_recently_touched(mocker, monkeypatch) -> None:
    upsert = mocker.patch.object(l2_persistence, "upsert_session_metadata")
    monkeypatch.setattr(l2_persistence, "_SESSION_TTL_SECONDS", 60)
    monkeypatch.setattr(l2_persistence, "_SESSION_L2_TOUCH_SECONDS", 20)

    entry = {"_l2_touch_at": 90.0}
    store._touch_l2_session("sess-1", entry, now=100.0)

    upsert.assert_not_called()
    assert entry["_l2_touch_at"] == 90.0


def test_touch_l2_session_updates_metadata_with_expires_at_when_due(mocker, monkeypatch) -> None:
    upsert = mocker.patch.object(l2_persistence, "upsert_session_metadata")
    mocker.patch.object(l2_persistence, "now_iso", return_value="2026-02-11T00:00:00+00:00")
    expires_at = datetime(2026, 2, 11, tzinfo=timezone.utc)
    monkeypatch.setattr(l2_persistence, "_expires_at", lambda: expires_at)
    monkeypatch.setattr(l2_persistence, "_SESSION_TTL_SECONDS", 60)
    monkeypatch.setattr(l2_persistence, "_SESSION_L2_TOUCH_SECONDS", 20)
    entry = {}

    store._touch_l2_session("sess-1", entry, now=100.0)

    upsert.assert_called_once_with(
        "sess-1",
        {"last_access_at": "2026-02-11T00:00:00+00:00", "expires_at": expires_at},
    )
    assert entry["_l2_touch_at"] == 100.0


def test_touch_l2_session_swallow_unexpected_upsert_errors(mocker, monkeypatch) -> None:
    mocker.patch.object(l2_persistence, "upsert_session_metadata", side_effect=RuntimeError("l2 unavailable"))
    mocker.patch.object(l2_persistence, "now_iso", return_value="2026-02-11T00:00:00+00:00")
    monkeypatch.setattr(l2_persistence, "_SESSION_TTL_SECONDS", 60)
    monkeypatch.setattr(l2_persistence, "_SESSION_L2_TOUCH_SECONDS", 20)
    monkeypatch.setattr(l2_persistence, "_expires_at", lambda: None)
    entry = {}

    store._touch_l2_session("sess-1", entry, now=100.0)

    assert "_l2_touch_at" not in entry


def test_ensure_l2_data_short_circuits_when_no_required_data_missing(mocker) -> None:
    hydrate = mocker.patch.object(l2_persistence, "_hydrate_from_l2")
    entry = {"user_id": "user-1", "pdf_bytes": b"%PDF", "fields": []}

    store._ensure_l2_data(
        "sess-1",
        entry,
        include_pdf_bytes=True,
        include_fields=True,
        include_result=False,
        include_renames=False,
        include_checkbox_rules=False,
        include_checkbox_hints=False,
    )

    hydrate.assert_not_called()


def test_ensure_l2_data_merges_hydrated_payload_when_required_data_missing(mocker) -> None:
    mocker.patch.object(l2_persistence, "_hydrate_from_l2", return_value={"pdf_bytes": b"%PDF", "fields": []})
    entry = {"user_id": "user-1"}

    store._ensure_l2_data(
        "sess-1",
        entry,
        include_pdf_bytes=True,
        include_fields=True,
        include_result=False,
        include_renames=False,
        include_checkbox_rules=False,
        include_checkbox_hints=False,
    )

    assert entry["pdf_bytes"] == b"%PDF"
    assert entry["fields"] == []


def test_store_session_entry_forwards_flags_to_persist_and_store(mocker) -> None:
    persist = mocker.patch.object(store, "_persist_session_entry")
    store_l1 = mocker.patch.object(store, "_store_l1_entry")
    entry = {"user_id": "user-1", "pdf_bytes": b"%PDF"}

    store.store_session_entry(
        "sess-1",
        entry,
        persist_pdf=False,
        persist_fields=False,
        persist_result=False,
        persist_checkbox_hints=True,
        persist_l1=True,
    )

    persist.assert_called_once_with(
        "sess-1",
        entry,
        persist_pdf=False,
        persist_fields=False,
        persist_result=False,
        persist_checkbox_hints=True,
        include_created_at=True,
    )
    store_l1.assert_called_once_with("sess-1", entry)


def test_store_session_entry_skips_l1_when_persist_l1_is_false(mocker) -> None:
    mocker.patch.object(store, "_persist_session_entry")
    store_l1 = mocker.patch.object(store, "_store_l1_entry")

    store.store_session_entry("sess-1", {"user_id": "user-1"}, persist_l1=False)

    store_l1.assert_not_called()


def test_update_session_entry_forwards_flags_to_persist(mocker) -> None:
    persist = mocker.patch.object(store, "_persist_session_entry")
    entry = {"user_id": "user-1"}

    store.update_session_entry(
        "sess-1",
        entry,
        persist_pdf=True,
        persist_fields=True,
        persist_result=True,
        persist_renames=True,
        persist_checkbox_rules=True,
        persist_checkbox_hints=True,
    )

    persist.assert_called_once_with(
        "sess-1",
        entry,
        persist_pdf=True,
        persist_fields=True,
        persist_result=True,
        persist_renames=True,
        persist_checkbox_rules=True,
        persist_checkbox_hints=True,
        include_created_at=False,
    )


# ---------------------------------------------------------------------------
# Edge-case tests for L2 persistence and related helpers
# ---------------------------------------------------------------------------


def test_persist_session_entry_skips_upload_when_pdf_path_already_set(mocker, monkeypatch) -> None:
    """When persist_pdf=True but the entry already carries a pdf_path, the
    upload_session_pdf_bytes call is skipped entirely and the existing path is
    reused in both the entry and the metadata dict.  This avoids redundant
    uploads for sessions whose PDF was already persisted in a prior call."""
    entry = {
        "user_id": "user-1",
        "source_pdf": "source.pdf",
        "page_count": 1,
        "pdf_bytes": b"%PDF-1.4",
        "pdf_path": "gs://bucket/sess/already-uploaded.pdf",
    }
    upload_pdf = mocker.patch.object(l2_persistence, "upload_session_pdf_bytes")
    upsert = mocker.patch.object(l2_persistence, "upsert_session_metadata")
    mocker.patch.object(l2_persistence, "now_iso", return_value="2026-02-11T00:00:00+00:00")
    monkeypatch.setattr(l2_persistence, "_session_now", lambda: 10.0)
    monkeypatch.setattr(l2_persistence, "_expires_at", lambda: None)

    store._persist_session_entry("sess-1", entry, persist_pdf=True)

    # upload_session_pdf_bytes must NOT be called because entry already has pdf_path.
    upload_pdf.assert_not_called()
    # The existing pdf_path must be preserved in both the entry and the metadata.
    assert entry["pdf_path"] == "gs://bucket/sess/already-uploaded.pdf"
    upsert.assert_called_once()
    metadata = upsert.call_args.args[1]
    assert metadata["pdf_path"] == "gs://bucket/sess/already-uploaded.pdf"


def test_persist_session_entry_filters_out_detection_key_with_none_value(mocker, monkeypatch) -> None:
    """Detection-related keys are only added to the metadata dict when the
    entry contains the key AND its value is not None.  The guard
    ``if key in entry and entry.get(key) is not None`` ensures that an explicit
    None value is filtered out, preventing None from being persisted to L2."""
    entry = {
        "user_id": "user-1",
        "source_pdf": "source.pdf",
        "page_count": 1,
        "detection_status": "complete",
        "detection_error": None,  # explicit None -- must be excluded
    }
    upsert = mocker.patch.object(l2_persistence, "upsert_session_metadata")
    mocker.patch.object(l2_persistence, "now_iso", return_value="2026-02-11T00:00:00+00:00")
    monkeypatch.setattr(l2_persistence, "_session_now", lambda: 20.0)
    monkeypatch.setattr(l2_persistence, "_expires_at", lambda: None)

    store._persist_session_entry("sess-1", entry)

    upsert.assert_called_once()
    metadata = upsert.call_args.args[1]
    # detection_status has a non-None value, so it must appear.
    assert metadata["detection_status"] == "complete"
    # detection_error is explicitly None, so it must be omitted.
    assert "detection_error" not in metadata


def test_ensure_l2_data_does_not_update_entry_when_hydrate_returns_none(mocker) -> None:
    """When required data is missing (triggering the L2 hydration path) but
    _hydrate_from_l2 returns None (session not found in L2), the entry dict
    must remain unchanged.  The ``if hydrated:`` guard prevents None from being
    passed to entry.update()."""
    mocker.patch.object(l2_persistence, "_hydrate_from_l2", return_value=None)
    entry = {"user_id": "user-1"}
    original_keys = set(entry.keys())

    store._ensure_l2_data(
        "sess-1",
        entry,
        include_pdf_bytes=True,
        include_fields=True,
        include_result=False,
        include_renames=False,
        include_checkbox_rules=False,
        include_checkbox_hints=False,
    )

    # Entry must not have gained any new keys from a None hydration result.
    assert set(entry.keys()) == original_keys


def test_missing_required_data_returns_false_when_all_flags_disabled() -> None:
    """When every include flag is False, no data requirement is checked and
    the function unconditionally returns False.  This is the base case that
    short-circuits the _ensure_l2_data path so no L2 fetch is triggered."""
    result = store._missing_required_data(
        {},
        include_pdf_bytes=False,
        include_fields=False,
        include_result=False,
        include_renames=False,
        include_checkbox_rules=False,
        include_checkbox_hints=False,
    )
    assert result is False
