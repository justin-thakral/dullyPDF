import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.fieldDetecting.commonforms import commonForm as cf


def test_parse_int_env_uses_int_or_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_PARSE_INT", "42")
    assert cf._parse_int_env("TEST_PARSE_INT", 9) == 42

    monkeypatch.setenv("TEST_PARSE_INT", "bad")
    assert cf._parse_int_env("TEST_PARSE_INT", 9) == 9

    monkeypatch.setenv("TEST_PARSE_INT", "   ")
    assert cf._parse_int_env("TEST_PARSE_INT", 9) == 9


@pytest.mark.parametrize(
    "uri",
    [
        "https://weights-bucket/models/FFDNet-L.pt",
        "gs://",
        "gs://weights-bucket",
        "gs:///models/FFDNet-L.pt",
    ],
)
def test_parse_gcs_uri_rejects_malformed_uri(uri: str) -> None:
    with pytest.raises(ValueError):
        cf._parse_gcs_uri(uri)


def test_parse_gcs_uri_accepts_valid_uri() -> None:
    assert cf._parse_gcs_uri("gs://weights-bucket/models/FFDNet-L.pt") == (
        "weights-bucket",
        "models/FFDNet-L.pt",
    )


def test_safe_cache_key_normalizes_to_filesystem_friendly_token() -> None:
    assert cf._safe_cache_key("  FFDNet-L / v1  ") == "FFDNet-L___v1"
    assert cf._safe_cache_key("") == "model"
    assert cf._safe_cache_key("  ") == "model"


def test_acquire_download_lock_removes_stale_lock(tmp_path: Path) -> None:
    lock_path = tmp_path / ".download.lock"
    lock_path.write_text("locked")
    stale_timestamp = time.time() - 30
    os.utime(lock_path, (stale_timestamp, stale_timestamp))

    cf._acquire_download_lock(lock_path, timeout_seconds=2)
    assert lock_path.exists()

    lock_path.unlink(missing_ok=True)


def test_acquire_download_lock_times_out_on_fresh_lock(tmp_path: Path, mocker) -> None:
    lock_path = tmp_path / ".download.lock"
    lock_path.write_text("locked")
    now = time.time()
    os.utime(lock_path, (now, now))

    mocker.patch("backend.fieldDetecting.commonforms.commonForm.time.time", return_value=now)
    mocker.patch(
        "backend.fieldDetecting.commonforms.commonForm.time.monotonic",
        side_effect=[0.0, 1.0],
    )
    mocker.patch("backend.fieldDetecting.commonforms.commonForm.time.sleep", return_value=None)

    with pytest.raises(TimeoutError):
        cf._acquire_download_lock(lock_path, timeout_seconds=1)

    assert lock_path.exists()


def test_category_for_confidence_handles_misordered_thresholds(mocker) -> None:
    mocker.patch.object(cf, "COMMONFORMS_CONFIDENCE_GREEN", 0.7)
    mocker.patch.object(cf, "COMMONFORMS_CONFIDENCE_YELLOW", 0.9)

    assert cf._category_for_confidence(0.8) == "green"
    assert cf._category_for_confidence(0.7) == "green"
    assert cf._category_for_confidence(0.69) == "red"


def test_category_for_confidence_normal_buckets(mocker) -> None:
    mocker.patch.object(cf, "COMMONFORMS_CONFIDENCE_GREEN", 0.8)
    mocker.patch.object(cf, "COMMONFORMS_CONFIDENCE_YELLOW", 0.6)

    assert cf._category_for_confidence(0.85) == "green"
    assert cf._category_for_confidence(0.65) == "yellow"
    assert cf._category_for_confidence(0.2) == "red"


def test_batch_splits_items_with_trailing_partial_batch() -> None:
    assert list(cf._batch([1, 2, 3, 4, 5], size=2)) == [[1, 2], [3, 4], [5]]


def test_bbox_to_rect_clamps_and_orders_coordinates() -> None:
    bbox = SimpleNamespace(x0=1.2, y0=0.8, x1=-0.2, y1=0.1)
    rect = cf._bbox_to_rect(bbox, page_width=100.0, page_height=200.0)
    assert rect == [0.0, 20.0, 100.0, 160.0]


def test_field_type_maps_known_and_fallback_widget_types() -> None:
    assert cf._field_type("TextBox", use_signature_fields=False) == "text"
    assert cf._field_type("ChoiceButton", use_signature_fields=False) == "checkbox"
    assert cf._field_type("Signature", use_signature_fields=True) == "signature"
    assert cf._field_type("Signature", use_signature_fields=False) == "text"
    assert cf._field_type("UnknownWidget", use_signature_fields=False) == "text"


def test_resolve_output_root_honors_priority_rules() -> None:
    assert cf._resolve_output_root(
        Path("/tmp/from-output.json"),
        Path("/tmp/from-output-dir"),
    ) == Path("/tmp/from-output-dir")
    assert cf._resolve_output_root(Path("/tmp/artifacts.json"), None) == Path("/tmp")
    assert cf._resolve_output_root(Path("/tmp/output-root"), None) == Path("/tmp/output-root")
    assert cf._resolve_output_root(None, None) == Path("backend/fieldDetecting/outputArtifacts")
