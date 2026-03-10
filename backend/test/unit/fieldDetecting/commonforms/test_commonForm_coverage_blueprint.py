from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.fieldDetecting.commonforms import commonForm as cf


class _Scalar:
    def __init__(self, value: float) -> None:
        self._value = value

    def item(self) -> float:
        return self._value


class _XYWHNRow:
    def __init__(self, values: list[float]) -> None:
        self._values = values

    def tolist(self) -> list[float]:
        return self._values


class _FakeBoxes:
    def __init__(
        self,
        *,
        xywhn_rows: list[list[float]],
        cls_values: list[int],
        conf_values: list[float] | None,
    ) -> None:
        self.xywhn = [_XYWHNRow(row) for row in xywhn_rows]
        self.cls = [_Scalar(v) for v in cls_values]
        self.conf = [_Scalar(v) for v in conf_values] if conf_values is not None else None

    def __len__(self) -> int:
        return len(self.xywhn)


class _FakeYoloResult:
    def __init__(self, boxes: _FakeBoxes | None) -> None:
        self.boxes = boxes


class _BoundingBoxStub:
    def __init__(self, *, x0: float, y0: float, x1: float, y1: float) -> None:
        self.x0 = x0
        self.y0 = y0
        self.x1 = x1
        self.y1 = y1

    @classmethod
    def from_yolo(cls, *, cx: float, cy: float, w: float, h: float) -> "_BoundingBoxStub":
        return cls(x0=cx - (w / 2.0), y0=cy - (h / 2.0), x1=cx + (w / 2.0), y1=cy + (h / 2.0))


class _DummyFFDNetDetector:
    def __init__(self, model: str, *, device: str, fast: bool) -> None:
        self.model = model
        self.device = device
        self.fast = fast
        self.id_to_cls = {}


class _DummyFFDetrDetector:
    def __init__(self, model: str, *, device: str) -> None:
        self.model = model
        self.device = device
        self.id_to_cls = {}


def _page(width: int = 100, height: int = 100) -> SimpleNamespace:
    return SimpleNamespace(image=SimpleNamespace(width=width, height=height))


def _commonforms_import_tuple(render_pdf):
    class _EncryptedPdfError(Exception):
        pass

    return (
        _DummyFFDetrDetector,
        _DummyFFDNetDetector,
        render_pdf,
        _BoundingBoxStub,
        _EncryptedPdfError,
    )


def test_sort_detected_widgets_groups_rows_and_orders() -> None:
    widgets = [
        cf.DetectedWidget("TextBox", _BoundingBoxStub(x0=0.4, y0=0.0, x1=0.5, y1=0.1), 0, 0.7),
        cf.DetectedWidget("TextBox", _BoundingBoxStub(x0=0.1, y0=0.0, x1=0.2, y1=0.1), 0, 0.8),
        cf.DetectedWidget("TextBox", _BoundingBoxStub(x0=0.2, y0=0.03, x1=0.3, y1=0.1), 0, 0.9),
    ]

    ordered = cf._sort_detected_widgets(widgets)

    assert [float(item.bounding_box.x0) for item in ordered] == [0.1, 0.4, 0.2]


def test_detect_ffdnet_defaults_confidence_when_missing_and_skips_empty(mocker) -> None:
    model = mocker.Mock()
    model.predict.return_value = [
        _FakeYoloResult(
            _FakeBoxes(
                xywhn_rows=[[0.5, 0.5, 0.2, 0.2]],
                cls_values=[0],
                conf_values=None,
            )
        ),
        _FakeYoloResult(_FakeBoxes(xywhn_rows=[], cls_values=[], conf_values=None)),
    ]
    detector = SimpleNamespace(
        fast=False,
        model=model,
        id_to_cls={0: "TextBox"},
        device="cpu",
    )

    widgets_by_page = cf._detect_ffdnet(
        detector,
        [_page(), _page()],
        confidence=0.3,
        image_size=1024,
        bounding_box_cls=_BoundingBoxStub,
    )

    assert sorted(widgets_by_page.keys()) == [0]
    assert widgets_by_page[0][0].confidence == pytest.approx(1.0)


def test_resolve_commonforms_model_uses_gcs_from_env_or_model(monkeypatch: pytest.MonkeyPatch, mocker) -> None:
    ensure = mocker.patch.object(cf, "_ensure_gcs_model", return_value=Path("/tmp/model.pt"))

    monkeypatch.setenv("COMMONFORMS_MODEL_GCS_URI", "gs://bucket/model.pt")
    model_label, model_path = cf._resolve_commonforms_model("FFDNet-L")
    assert (model_label, model_path) == ("FFDNet-L", "/tmp/model.pt")
    ensure.assert_called_once_with("gs://bucket/model.pt", "FFDNet-L")

    ensure.reset_mock()
    monkeypatch.delenv("COMMONFORMS_MODEL_GCS_URI", raising=False)
    model_label, model_path = cf._resolve_commonforms_model("gs://bucket/other.pt")
    assert (model_label, model_path) == ("gs://bucket/other.pt", "/tmp/model.pt")
    ensure.assert_called_once_with("gs://bucket/other.pt", "gs://bucket/other.pt")


def test_ensure_gcs_model_uses_cache_without_download(monkeypatch: pytest.MonkeyPatch, mocker, tmp_path: Path) -> None:
    monkeypatch.setenv("COMMONFORMS_WEIGHTS_CACHE_DIR", str(tmp_path))
    cache_dir = tmp_path / cf._safe_cache_key("FFDNet-L")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / "weights.pt"
    cached.write_bytes(b"cached")
    cf._cache_ready_marker(cached).write_text("ready\n", encoding="utf-8")

    download = mocker.patch.object(cf, "_download_gcs_blob")

    resolved = cf._ensure_gcs_model("gs://weights/models/weights.pt", "FFDNet-L")

    assert resolved == cached
    download.assert_not_called()


def test_ensure_gcs_model_releases_lock_when_download_fails(
    monkeypatch: pytest.MonkeyPatch,
    mocker,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("COMMONFORMS_WEIGHTS_CACHE_DIR", str(tmp_path))
    mocker.patch.object(cf, "_download_gcs_blob", side_effect=RuntimeError("download failed"))

    with pytest.raises(RuntimeError, match="download failed"):
        cf._ensure_gcs_model("gs://weights/models/weights.pt", "FFDNet-L")

    cache_dir = tmp_path / cf._safe_cache_key("FFDNet-L")
    lock_path = cache_dir / ".download.lock"
    local_path = cache_dir / "weights.pt"
    assert lock_path.exists() is False
    assert local_path.exists() is False
    assert cf._cache_ready_marker(local_path).exists() is False


def test_ensure_gcs_model_redownloads_cache_without_ready_marker(
    monkeypatch: pytest.MonkeyPatch,
    mocker,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("COMMONFORMS_WEIGHTS_CACHE_DIR", str(tmp_path))
    cache_dir = tmp_path / cf._safe_cache_key("FFDNet-L")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / "weights.pt"
    cached.write_bytes(b"stale-partial")

    def _write_download(_bucket: str, _object_name: str, dest: Path) -> None:
        dest.write_bytes(b"fresh-model")

    download = mocker.patch.object(cf, "_download_gcs_blob", side_effect=_write_download)

    resolved = cf._ensure_gcs_model("gs://weights/models/weights.pt", "FFDNet-L")

    assert resolved == cached
    assert cached.read_bytes() == b"fresh-model"
    assert cf._cache_ready_marker(cached).exists() is True
    download.assert_called_once()


def test_detect_commonforms_fields_missing_pdf_raises_file_not_found(tmp_path: Path) -> None:
    missing = tmp_path / "missing.pdf"
    with pytest.raises(FileNotFoundError, match="PDF not found"):
        cf.detect_commonforms_fields(missing)


def test_detect_commonforms_fields_calls_inject_when_output_pdf_requested(
    tmp_path: Path,
    mocker,
) -> None:
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%mock\n")
    output_pdf = tmp_path / "filled.pdf"

    render_pdf = mocker.Mock(return_value=[_page()])
    mocker.patch.object(cf, "_import_commonforms", return_value=_commonforms_import_tuple(render_pdf))
    mocker.patch.object(cf, "_resolve_commonforms_model", return_value=("FFDNet-L", "/tmp/ffdnet.pt"))
    mocker.patch.object(cf, "_detect_ffdnet", return_value={0: []})
    mocker.patch.object(cf, "_page_sizes", return_value={0: (100.0, 100.0)})
    mocker.patch.object(
        cf,
        "_build_fields",
        return_value=[{"name": "field_1", "type": "text", "page": 1, "rect": [1, 1, 2, 2]}],
    )
    inject = mocker.patch.object(cf, "inject_fields_from_template", return_value=None)

    result = cf.detect_commonforms_fields(pdf_path, output_pdf=output_pdf, model="FFDNet-L")

    assert result["fields"] == [{"name": "field_1", "type": "text", "page": 1, "rect": [1, 1, 2, 2]}]
    inject.assert_called_once()
    inject_args = inject.call_args.args
    assert inject_args[0] == pdf_path
    assert inject_args[2] == output_pdf
    assert inject_args[1]["coordinateSystem"] == "originTop"
