from __future__ import annotations

from dataclasses import dataclass

import fitz
import numpy as np

from backend.fieldDetecting.rename_pipeline.combinedSrc import extract_labels
from backend.fieldDetecting.rename_pipeline.combinedSrc import render_pdf


@dataclass
class _FakeCropBox:
    width: float
    height: float


class _FakePixmap:
    def __init__(self, *, width: int, height: int, n: int) -> None:
        self.width = width
        self.height = height
        self.n = n
        data = np.arange(width * height * n, dtype=np.uint8)
        self.samples = data.tobytes()


class _FakePage:
    def __init__(self, *, width_pts: float, height_pts: float, rotation: int, pixmap_n: int) -> None:
        self.cropbox = _FakeCropBox(width=width_pts, height=height_pts)
        self.rotation = rotation
        self._pixmap_n = pixmap_n

    def get_pixmap(self, matrix=None, alpha=False):  # noqa: ARG002
        return _FakePixmap(width=6, height=4, n=self._pixmap_n)


class _FakeDoc:
    def __init__(self, pages):
        self._pages = pages
        self.page_count = len(pages)

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def __iter__(self):
        return iter(self._pages)

    def load_page(self, index: int):
        return self._pages[index]


def _patch_fitz_open(monkeypatch, pages_factory):
    def _open(*_args, **_kwargs):
        return _FakeDoc(pages_factory())

    monkeypatch.setattr(render_pdf.fitz, "open", _open)


def test_render_page_from_doc_converts_grayscale_and_rgba() -> None:
    gray_page = _FakePage(width_pts=200.0, height_pts=100.0, rotation=0, pixmap_n=1)
    rgba_page = _FakePage(width_pts=200.0, height_pts=100.0, rotation=90, pixmap_n=4)

    gray = render_pdf._render_page_from_doc(gray_page, page_index=0, scale=1.0)
    rgba = render_pdf._render_page_from_doc(rgba_page, page_index=1, scale=1.0)

    assert gray["image"].shape == (4, 6, 3)
    assert rgba["image"].shape == (4, 6, 3)
    assert gray["page_index"] == 1
    assert rgba["page_index"] == 2


def test_render_pdf_to_images_sequential_single_page_metadata(monkeypatch) -> None:
    def _pages():
        return [_FakePage(width_pts=200.0, height_pts=100.0, rotation=0, pixmap_n=3)]

    _patch_fitz_open(monkeypatch, _pages)

    pages = render_pdf.render_pdf_to_images(b"%PDF", dpi=72, max_workers=1)

    assert len(pages) == 1
    assert pages[0]["page_index"] == 1
    assert pages[0]["scale"] == 1.0
    assert pages[0]["width_points"] == 200.0
    assert pages[0]["height_points"] == 100.0
    assert pages[0]["image_width_px"] == 6
    assert pages[0]["image_height_px"] == 4


def test_render_pdf_to_images_parallel_preserves_page_order(monkeypatch) -> None:
    def _pages():
        return [
            _FakePage(width_pts=200.0, height_pts=100.0, rotation=0, pixmap_n=3),
            _FakePage(width_pts=200.0, height_pts=100.0, rotation=90, pixmap_n=3),
            _FakePage(width_pts=200.0, height_pts=100.0, rotation=180, pixmap_n=3),
        ]

    _patch_fitz_open(monkeypatch, _pages)

    pages = render_pdf.render_pdf_to_images(b"%PDF", dpi=144, max_workers=3)

    assert [p["page_index"] for p in pages] == [1, 2, 3]
    assert all(p["scale"] == 2.0 for p in pages)


def test_render_and_extract_labels_with_real_pdf_bytes() -> None:
    doc = fitz.open()
    page = doc.new_page(width=220, height=160)
    page.insert_text((24, 32), "Patient Name", fontsize=12)
    pdf_bytes = doc.tobytes()
    doc.close()

    rendered = render_pdf.render_pdf_to_images(pdf_bytes, dpi=96, max_workers=1)
    labels_by_page = extract_labels.extract_labels(
        pdf_bytes,
        rendered_pages=rendered,
        max_workers=1,
    )

    assert len(rendered) == 1
    assert rendered[0]["page_index"] == 1
    assert rendered[0]["image"].size > 0
    assert 1 in labels_by_page
    assert any("Patient" in label["text"] for label in labels_by_page[1])
