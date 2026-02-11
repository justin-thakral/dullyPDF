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
        return cls(
            x0=cx - (w / 2.0),
            y0=cy - (h / 2.0),
            x1=cx + (w / 2.0),
            y1=cy + (h / 2.0),
        )


class _FakeDetections:
    def __init__(
        self,
        *,
        xyxy: list[list[float]],
        class_id: list[int],
        confidence: list[float],
    ) -> None:
        self.xyxy = xyxy
        self.class_id = class_id
        self.confidence = confidence
        self.nms_calls: list[tuple[float, bool]] = []

    def with_nms(self, *, threshold: float, class_agnostic: bool) -> "_FakeDetections":
        self.nms_calls.append((threshold, class_agnostic))
        return self


class _EncryptedPdfError(Exception):
    pass


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


def _page(width: int = 200, height: int = 100) -> SimpleNamespace:
    return SimpleNamespace(image=SimpleNamespace(width=width, height=height))


def _pdf_path(root: Path) -> Path:
    path = root / "sample.pdf"
    path.write_bytes(b"%PDF-1.4\n%mock\n")
    return path


def _commonforms_import_tuple(render_pdf):
    return (
        _DummyFFDetrDetector,
        _DummyFFDNetDetector,
        render_pdf,
        _BoundingBoxStub,
        _EncryptedPdfError,
    )


def test_detect_ffdnet_extracts_widgets_and_sorts(mocker) -> None:
    boxes = _FakeBoxes(
        xywhn_rows=[
            [0.80, 0.20, 0.10, 0.10],
            [0.20, 0.20, 0.10, 0.10],
            [0.50, 0.50, 0.20, 0.10],
        ],
        cls_values=[1, 0, 99],
        conf_values=[0.90, 0.80, 0.70],
    )
    model = mocker.Mock()
    model.predict.return_value = [_FakeYoloResult(boxes)]
    detector = SimpleNamespace(
        fast=False,
        model=model,
        id_to_cls={0: "TextBox", 1: "ChoiceButton"},
        device="cpu",
    )

    widgets_by_page = cf._detect_ffdnet(
        detector,
        [_page()],
        confidence=0.3,
        image_size=1600,
        bounding_box_cls=_BoundingBoxStub,
    )

    assert sorted(widgets_by_page.keys()) == [0]
    ordered = widgets_by_page[0]
    assert [w.widget_type for w in ordered] == ["TextBox", "ChoiceButton", "TextBox"]
    assert [w.confidence for w in ordered] == [0.8, 0.9, 0.7]
    assert float(ordered[0].bounding_box.x0) < float(ordered[1].bounding_box.x0)
    model.predict.assert_called_once()


def test_detect_ffdnet_fast_mode_predicts_per_page(mocker) -> None:
    model = mocker.Mock()
    model.predict.side_effect = [
        [_FakeYoloResult(_FakeBoxes(xywhn_rows=[[0.5, 0.5, 0.2, 0.2]], cls_values=[0], conf_values=[0.9]))],
        [_FakeYoloResult(_FakeBoxes(xywhn_rows=[[0.5, 0.5, 0.2, 0.2]], cls_values=[1], conf_values=[0.8]))],
    ]
    detector = SimpleNamespace(
        fast=True,
        model=model,
        id_to_cls={0: "TextBox", 1: "ChoiceButton"},
        device="cpu",
    )
    pages = [_page(), _page()]

    widgets_by_page = cf._detect_ffdnet(
        detector,
        pages,
        confidence=0.4,
        image_size=1024,
        bounding_box_cls=_BoundingBoxStub,
    )

    assert sorted(widgets_by_page.keys()) == [0, 1]
    assert model.predict.call_count == 2
    assert widgets_by_page[0][0].widget_type == "TextBox"
    assert widgets_by_page[1][0].widget_type == "ChoiceButton"


def test_detect_ffdetr_extracts_widgets_and_sorts(mocker) -> None:
    detections_page_1 = _FakeDetections(
        xyxy=[
            [120.0, 10.0, 180.0, 30.0],
            [20.0, 10.0, 80.0, 30.0],
        ],
        class_id=[1, 0],
        confidence=[0.9, 0.8],
    )
    detections_page_2 = _FakeDetections(
        xyxy=[[40.0, 20.0, 100.0, 40.0]],
        class_id=[99],
        confidence=[0.7],
    )
    model = mocker.Mock()
    model.predict.return_value = [detections_page_1, detections_page_2]
    detector = SimpleNamespace(model=model, id_to_cls={0: "TextBox", 1: "ChoiceButton"})

    widgets_by_page = cf._detect_ffdetr(
        detector,
        [_page(width=200, height=100), _page(width=200, height=100)],
        confidence=0.5,
        batch_size=2,
        bounding_box_cls=_BoundingBoxStub,
    )

    assert sorted(widgets_by_page.keys()) == [0, 1]
    assert [widget.widget_type for widget in widgets_by_page[0]] == ["TextBox", "ChoiceButton"]
    assert widgets_by_page[1][0].widget_type == "TextBox"
    assert detections_page_1.nms_calls == [(0.1, True)]
    assert detections_page_2.nms_calls == [(0.1, True)]


def test_detect_ffdetr_wraps_single_page_prediction(mocker) -> None:
    model = mocker.Mock()
    model.predict.return_value = _FakeDetections(
        xyxy=[[20.0, 10.0, 40.0, 20.0]],
        class_id=[0],
        confidence=[0.95],
    )
    detector = SimpleNamespace(model=model, id_to_cls={0: "TextBox"})

    widgets_by_page = cf._detect_ffdetr(
        detector,
        [_page(width=100, height=50)],
        confidence=0.2,
        batch_size=4,
        bounding_box_cls=_BoundingBoxStub,
    )

    assert sorted(widgets_by_page.keys()) == [0]
    assert widgets_by_page[0][0].widget_type == "TextBox"
    model.predict.assert_called_once()


def test_build_fields_emits_canonical_payload_shape() -> None:
    widgets_by_page = {
        0: [
            cf.DetectedWidget(
                widget_type="TextBox",
                bounding_box=_BoundingBoxStub.from_yolo(cx=0.20, cy=0.20, w=0.10, h=0.10),
                page_idx=0,
                confidence=0.9,
            ),
            cf.DetectedWidget(
                widget_type="Signature",
                bounding_box=_BoundingBoxStub.from_yolo(cx=0.50, cy=0.20, w=0.10, h=0.10),
                page_idx=0,
                confidence=0.75,
            ),
        ],
        1: [],
        2: [
            cf.DetectedWidget(
                widget_type="ChoiceButton",
                bounding_box=_BoundingBoxStub.from_yolo(cx=0.30, cy=0.30, w=0.20, h=0.10),
                page_idx=2,
                confidence=0.6,
            ),
        ],
    }

    fields = cf._build_fields(
        widgets_by_page,
        page_sizes={0: (100.0, 200.0), 2: (50.0, 100.0)},
        model="FFDNet-L",
        use_signature_fields=True,
    )

    assert len(fields) == 3
    assert fields[0]["name"] == "commonforms_text_p1_1"
    assert fields[1]["name"] == "commonforms_signature_p1_2"
    assert fields[2]["name"] == "commonforms_checkbox_p3_1"
    assert fields[0]["candidateId"] == "commonforms_1_1"
    assert fields[1]["candidateId"] == "commonforms_1_2"
    assert fields[2]["candidateId"] == "commonforms_3_1"
    assert fields[0]["source"] == "commonforms"
    assert fields[1]["model"] == "FFDNet-L"
    assert fields[0]["page"] == 1
    assert fields[2]["page"] == 3
    assert len(fields[0]["rect"]) == 4
    assert fields[0]["rect"][0] == pytest.approx(15.0)
    assert fields[0]["rect"][1] == pytest.approx(30.0)
    assert fields[0]["rect"][2] == pytest.approx(25.0)
    assert fields[0]["rect"][3] == pytest.approx(50.0)


def test_detect_commonforms_fields_routes_to_ffdnet(tmp_path: Path, mocker) -> None:
    pdf_path = _pdf_path(tmp_path)
    render_pdf = mocker.Mock(return_value=[SimpleNamespace(image=SimpleNamespace(width=100, height=100))])

    mocker.patch.object(cf, "_import_commonforms", return_value=_commonforms_import_tuple(render_pdf))
    mocker.patch.object(cf, "_resolve_commonforms_model", return_value=("FFDNet-L", "/tmp/ffdnet.pt"))
    detect_ffdnet = mocker.patch.object(cf, "_detect_ffdnet", return_value={0: []})
    detect_ffdetr = mocker.patch.object(cf, "_detect_ffdetr", return_value={})
    mocker.patch.object(cf, "_page_sizes", return_value={0: (100.0, 100.0)})
    mocker.patch.object(cf, "_build_fields", return_value=[{"name": "field_1"}])

    result = cf.detect_commonforms_fields(pdf_path, model="FFDNet-L")

    detect_ffdnet.assert_called_once()
    detect_ffdetr.assert_not_called()
    assert result["fields"] == [{"name": "field_1"}]
    assert result["meta"]["model"] == "FFDNet-L"


def test_detect_commonforms_fields_routes_to_ffdetr(tmp_path: Path, mocker) -> None:
    pdf_path = _pdf_path(tmp_path)
    render_pdf = mocker.Mock(return_value=[SimpleNamespace(image=SimpleNamespace(width=100, height=100))])

    mocker.patch.object(cf, "_import_commonforms", return_value=_commonforms_import_tuple(render_pdf))
    mocker.patch.object(cf, "_resolve_commonforms_model", return_value=("FFDetr", "/tmp/ffdetr.pth"))
    detect_ffdnet = mocker.patch.object(cf, "_detect_ffdnet", return_value={})
    detect_ffdetr = mocker.patch.object(cf, "_detect_ffdetr", return_value={0: []})
    mocker.patch.object(cf, "_page_sizes", return_value={0: (100.0, 100.0)})

    result = cf.detect_commonforms_fields(pdf_path, model="FFDetr")

    detect_ffdnet.assert_not_called()
    detect_ffdetr.assert_called_once()
    assert result["fields"] == []
    assert result["meta"]["model"] == "FFDetr"


def test_detect_commonforms_fields_rejects_unsupported_model(tmp_path: Path, mocker) -> None:
    pdf_path = _pdf_path(tmp_path)
    render_pdf = mocker.Mock(return_value=[SimpleNamespace(image=SimpleNamespace(width=100, height=100))])

    mocker.patch.object(cf, "_import_commonforms", return_value=_commonforms_import_tuple(render_pdf))
    mocker.patch.object(cf, "_resolve_commonforms_model", return_value=("NotARealModel", "/tmp/model.bin"))

    with pytest.raises(ValueError) as ctx:
        cf.detect_commonforms_fields(pdf_path, model="NotARealModel")

    assert "Unsupported CommonForms model" in str(ctx.value)


def test_detect_commonforms_fields_maps_encrypted_pdf_error(tmp_path: Path, mocker) -> None:
    pdf_path = _pdf_path(tmp_path)
    render_pdf = mocker.Mock(side_effect=_EncryptedPdfError("encrypted"))

    mocker.patch.object(cf, "_import_commonforms", return_value=_commonforms_import_tuple(render_pdf))
    mocker.patch.object(cf, "_resolve_commonforms_model", return_value=("FFDNet-L", "/tmp/ffdnet.pt"))

    with pytest.raises(RuntimeError) as ctx:
        cf.detect_commonforms_fields(pdf_path, model="FFDNet-L")

    assert "cannot open encrypted PDFs" in str(ctx.value)


def test_detect_commonforms_fields_maps_generic_render_error(tmp_path: Path, mocker) -> None:
    pdf_path = _pdf_path(tmp_path)
    render_pdf = mocker.Mock(side_effect=RuntimeError("boom"))

    mocker.patch.object(cf, "_import_commonforms", return_value=_commonforms_import_tuple(render_pdf))
    mocker.patch.object(cf, "_resolve_commonforms_model", return_value=("FFDNet-L", "/tmp/ffdnet.pt"))

    with pytest.raises(RuntimeError) as ctx:
        cf.detect_commonforms_fields(pdf_path, model="FFDNet-L")

    assert "failed to render the PDF" in str(ctx.value)


def test_detect_commonforms_fields_returns_empty_fields_when_no_detections(
    tmp_path: Path,
    mocker,
) -> None:
    pdf_path = _pdf_path(tmp_path)
    render_pdf = mocker.Mock(return_value=[SimpleNamespace(image=SimpleNamespace(width=100, height=100))])

    mocker.patch.object(cf, "_import_commonforms", return_value=_commonforms_import_tuple(render_pdf))
    mocker.patch.object(cf, "_resolve_commonforms_model", return_value=("FFDNet-L", "/tmp/ffdnet.pt"))
    mocker.patch.object(cf, "_detect_ffdnet", return_value={})
    mocker.patch.object(cf, "_page_sizes", return_value={0: (100.0, 100.0)})

    result = cf.detect_commonforms_fields(pdf_path, model="FFDNet-L")

    assert result["fields"] == []
    assert result["coordinateSystem"] == "originTop"
