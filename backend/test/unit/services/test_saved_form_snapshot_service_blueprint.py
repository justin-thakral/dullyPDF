"""Unit coverage for saved-form editor snapshot helpers."""

from __future__ import annotations

from backend.services import saved_form_snapshot_service as snapshot_service


def _snapshot_payload() -> dict:
    return {
        "version": 1,
        "pageCount": 1,
        "pageSizes": {
            "1": {"width": 612, "height": 792},
        },
        "fields": [{
            "id": "field-1",
            "name": "full_name",
            "type": "text",
            "page": 1,
            "rect": {"x": 10, "y": 12, "width": 110, "height": 18},
            "value": None,
        }],
        "hasRenamedFields": True,
        "hasMappedSchema": False,
    }


def test_normalize_saved_form_editor_snapshot_payload_accepts_valid_payload() -> None:
    normalized = snapshot_service.normalize_saved_form_editor_snapshot_payload(_snapshot_payload())

    assert normalized["version"] == snapshot_service.SAVED_FORM_EDITOR_SNAPSHOT_VERSION
    assert normalized["pageCount"] == 1
    assert normalized["pageSizes"]["1"]["width"] == 612
    assert normalized["fields"][0]["name"] == "full_name"
    assert normalized["hasRenamedFields"] is True


def test_normalize_saved_form_editor_snapshot_payload_rejects_missing_page_size() -> None:
    payload = _snapshot_payload()
    payload["pageSizes"] = {}

    try:
        snapshot_service.normalize_saved_form_editor_snapshot_payload(payload)
    except ValueError as exc:
        assert str(exc) == "pageSizes missing entry for page 1"
    else:
        raise AssertionError("Expected ValueError for missing page size")


def test_load_saved_form_editor_snapshot_returns_none_when_storage_download_fails(mocker) -> None:
    download_mock = mocker.patch.object(
        snapshot_service,
        "download_saved_form_snapshot_json",
        side_effect=FileNotFoundError("missing"),
    )

    result = snapshot_service.load_saved_form_editor_snapshot({
        "editorSnapshot": {"version": 1, "path": "gs://sessions/snapshot.json"},
    })

    assert result is None
    download_mock.assert_called_once_with("gs://sessions/snapshot.json")


def test_upload_saved_form_editor_snapshot_builds_manifest(mocker) -> None:
    upload_mock = mocker.patch.object(
        snapshot_service,
        "upload_saved_form_snapshot_json",
        return_value="gs://sessions/new-snapshot.json",
    )

    bucket_path, manifest = snapshot_service.upload_saved_form_editor_snapshot(
        user_id="user-1",
        form_id="tpl-1",
        timestamp_ms=123,
        snapshot=_snapshot_payload(),
    )

    assert bucket_path == "gs://sessions/new-snapshot.json"
    assert manifest["version"] == snapshot_service.SAVED_FORM_EDITOR_SNAPSHOT_VERSION
    assert manifest["path"] == "gs://sessions/new-snapshot.json"
    assert manifest["fieldCount"] == 1
    upload_mock.assert_called_once_with(
        _snapshot_payload(),
        "users/user-1/saved-form-snapshots/123-tpl-1.json",
    )
