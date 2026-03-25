"""Unit coverage for signed PDF artifact rendering."""

from __future__ import annotations

from io import BytesIO

import fitz
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

from backend.services.signing_pdf_service import build_signed_pdf


def _blank_pdf_bytes(*, width: float = 200, height: float = 200) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=height)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _fillable_pdf_bytes(*, width: float = 200, height: float = 200) -> bytes:
    output = BytesIO()
    pdf_canvas = canvas.Canvas(output, pagesize=(width, height))
    pdf_canvas.drawString(20, 180, "Client intake")
    pdf_canvas.acroForm.textfield(
        name="client_name",
        x=20,
        y=130,
        width=120,
        height=24,
        value="Jordan Example",
    )
    pdf_canvas.save()
    return output.getvalue()


def test_build_signed_pdf_stamps_signature_date_and_initials() -> None:
    result = build_signed_pdf(
        source_pdf_bytes=_blank_pdf_bytes(),
        anchors=[
            {"kind": "signature", "page": 1, "rect": {"x": 20, "y": 20, "width": 120, "height": 30}},
            {"kind": "signed_date", "page": 1, "rect": {"x": 20, "y": 60, "width": 120, "height": 20}},
            {"kind": "initials", "page": 1, "rect": {"x": 20, "y": 90, "width": 40, "height": 20}},
        ],
        adopted_name="Alex Signer",
        completed_at="2026-03-24T12:05:00+00:00",
    )

    assert result.page_count == 1
    assert result.applied_anchor_count == 3

    reader = PdfReader(BytesIO(result.pdf_bytes))
    page_text = reader.pages[0].extract_text() or ""
    assert "Alex Signer" in page_text
    assert "Mar 24, 2026" in page_text
    assert "AS" in page_text


def test_build_signed_pdf_flattens_existing_form_fields() -> None:
    result = build_signed_pdf(
        source_pdf_bytes=_fillable_pdf_bytes(),
        anchors=[
            {"kind": "signature", "page": 1, "rect": {"x": 20, "y": 20, "width": 120, "height": 30}},
        ],
        adopted_name="Alex Signer",
        completed_at="2026-03-24T12:05:00+00:00",
    )

    document = fitz.open(stream=result.pdf_bytes, filetype="pdf")
    try:
        assert document.is_form_pdf is False
        assert list(document[0].widgets() or []) == []
        page_text = document[0].get_text("text")
    finally:
        document.close()

    assert "Jordan Example" in page_text
    assert "Alex Signer" in page_text
