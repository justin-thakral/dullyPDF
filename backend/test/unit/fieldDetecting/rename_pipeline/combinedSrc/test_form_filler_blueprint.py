from __future__ import annotations

import json
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject, TextStringObject

from backend.fieldDetecting.rename_pipeline.combinedSrc import form_filler


def _write_blank_pdf(path: Path, *, width: float = 200, height: float = 200) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=height)
    with path.open("wb") as fh:
        writer.write(fh)


def _widget(writer: PdfWriter, *, rect: list[float], field_type: str = "/Tx", name: str = "field"):
    annot = DictionaryObject(
        {
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/FT"): NameObject(field_type),
            NameObject("/T"): TextStringObject(name),
            NameObject("/Rect"): ArrayObject([NumberObject(v) for v in rect]),
        }
    )
    return writer._add_object(annot)  # pylint: disable=protected-access


def test_normalization_helpers_cover_rect_and_field_kind() -> None:
    assert form_filler._normalize_rect({"rect": [1, 2, 3, 4]}) == [1.0, 2.0, 3.0, 4.0]
    assert form_filler._normalize_rect({"x": 1, "y": 2, "width": 3, "height": 4}) == [1.0, 2.0, 4.0, 6.0]
    assert form_filler._normalize_rect({"x": 1}) is None

    assert form_filler._normalize_field_kind("checkbox") == "button"
    assert form_filler._normalize_field_kind("combo") == "choice"
    assert form_filler._normalize_field_kind("signature") == "signature"
    assert form_filler._normalize_field_kind("text") == "text"


def test_checkbox_value_and_confidence_helpers() -> None:
    widget = DictionaryObject()
    form_filler._apply_checkbox_value(widget, export_value="Yes", value=True)
    assert widget[NameObject("/V")] == NameObject("/Yes")

    form_filler._apply_checkbox_value(widget, export_value="Yes", value=False)
    assert widget[NameObject("/V")] == NameObject("/Off")

    assert form_filler._confidence_tag({"confidence": "0.9"}) == "dullypdf:confidence=0.9000"
    assert form_filler._confidence_tag({"confidence": "bad"}) is None


def test_dedupe_existing_widgets_and_reset_acroform_fields() -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)

    first = _widget(writer, rect=[10, 10, 40, 20], name="a")
    second = _widget(writer, rect=[10.1, 10.1, 40.1, 20.1], name="b")
    page[NameObject("/Annots")] = ArrayObject([first, second])

    removed = form_filler._dedupe_existing_widget_annots(writer, tol=0.5)
    assert removed == 1
    assert len(page["/Annots"]) == 1

    acroform = DictionaryObject({NameObject("/Fields"): ArrayObject([first])})
    form_filler._reset_acroform_fields(acroform)
    assert list(acroform["/Fields"]) == []


def test_update_existing_widget_sets_name_value_and_appearance() -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    acroform = form_filler._ensure_acroform(writer)

    widget_ref = _widget(writer, rect=[10, 10, 70, 30], field_type="/Tx", name="old_name")
    page[NameObject("/Annots")] = ArrayObject([widget_ref])
    widget = widget_ref.get_object()

    changed = form_filler._update_existing_widget(
        writer,
        page,
        acroform,
        rect=[10, 10, 70, 30],
        field_type="text",
        value="Alice",
        export_value="Yes",
        new_name="new_name",
        confidence_tag="dullypdf:confidence=0.7500",
    )

    assert changed is True
    assert str(widget.get("/T")) == "new_name"
    assert str(widget.get("/V")) == "Alice"
    assert "/AP" in widget
    assert str(widget.get("/TU")) == "dullypdf:confidence=0.7500"


def test_inject_fields_from_template_handles_duplicates_and_partial_fields(
    tmp_path: Path,
) -> None:
    input_pdf = tmp_path / "input.pdf"
    output_pdf = tmp_path / "output.pdf"
    _write_blank_pdf(input_pdf)

    template = {
        "coordinateSystem": "originTop",
        "fields": [
            {"name": "first_name", "type": "text", "page": 1, "rect": [10, 10, 80, 24], "value": "A"},
            {"name": "first_name_dup", "type": "text", "page": 1, "rect": [10.2, 10.2, 80.2, 24.2], "value": "B"},
            {"name": "agree", "type": "checkbox", "page": 1, "rect": [100, 10, 112, 22], "value": True},
            {"name": "missing_rect", "type": "text", "page": 1},
            {"name": "unknown_kind", "type": "wat", "page": 1, "rect": [10, 40, 20, 50]},
        ],
    }

    form_filler.inject_fields_from_template(input_pdf, template, output_pdf)

    reader = PdfReader(str(output_pdf))
    acroform = reader.trailer["/Root"]["/AcroForm"].get_object()
    fields = [ref.get_object() for ref in acroform.get("/Fields", [])]
    names = {str(f.get("/T")) for f in fields}

    assert output_pdf.exists()
    assert len(fields) == 2
    assert "first_name_dup" in names
    assert "agree" in names


def test_inject_fields_and_no_fields_edge_cases(tmp_path: Path) -> None:
    input_pdf = tmp_path / "input.pdf"
    json_path = tmp_path / "fields.json"
    output_pdf = tmp_path / "wrapped-output.pdf"
    _write_blank_pdf(input_pdf)

    template = {
        "fields": [
            {"name": "city", "type": "text", "page": 1, "rect": [20, 20, 70, 35], "value": "Austin"}
        ]
    }
    json_path.write_text(json.dumps(template), encoding="utf-8")

    form_filler.inject_fields(input_pdf, json_path, output_pdf)
    assert output_pdf.exists()

    with pytest.raises(ValueError, match="No fields to inject"):
        form_filler.inject_fields_from_template(input_pdf, {"fields": []}, tmp_path / "none.pdf")


def test_inject_fields_from_template_supports_radio_combo_and_signature(
    tmp_path: Path,
) -> None:
    input_pdf = tmp_path / "input-radio-combo-sig.pdf"
    output_pdf = tmp_path / "output-radio-combo-sig.pdf"
    _write_blank_pdf(input_pdf)

    template = {
        "coordinateSystem": "originTop",
        "fields": [
            {
                "name": "gender_m",
                "group": "gender",
                "type": "radio",
                "page": 1,
                "rect": [10, 10, 20, 20],
                "exportValue": "M",
                "value": "M",
            },
            {
                "name": "gender_f",
                "group": "gender",
                "type": "radio",
                "page": 1,
                "rect": [25, 10, 35, 20],
                "exportValue": "F",
            },
            {
                "name": "status",
                "type": "combo",
                "page": 1,
                "rect": [40, 10, 100, 25],
                "options": ["Single", "Married"],
                "value": "Married",
            },
            {
                "name": "signature",
                "type": "signature",
                "page": 1,
                "rect": [110, 10, 180, 30],
            },
        ],
    }

    form_filler.inject_fields_from_template(input_pdf, template, output_pdf)

    reader = PdfReader(str(output_pdf))
    acroform = reader.trailer["/Root"]["/AcroForm"].get_object()
    fields = [ref.get_object() for ref in acroform.get("/Fields", [])]

    radio_group = next(f for f in fields if f.get("/FT") == "/Btn")
    combo_field = next(f for f in fields if f.get("/FT") == "/Ch")
    signature_field = next(f for f in fields if f.get("/FT") == "/Sig")

    assert len(radio_group.get("/Kids", [])) == 2
    assert str(radio_group.get("/V")) == "/M"
    assert [str(opt) for opt in combo_field.get("/Opt", [])] == ["Single", "Married"]
    assert str(combo_field.get("/V")) == "Married"
    assert str(signature_field.get("/T")) == "signature"
