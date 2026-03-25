"""PDF export helpers shared by standard downloads and signing artifacts.

Flattening walks the document's pages and widget tree once, so the work stays
O(page_count + widget_count). The output preserves the visible field values but
removes the interactive AcroForm widgets that ordinary PDF viewers would
otherwise keep editable.
"""

from __future__ import annotations

import fitz


def flatten_pdf_form_widgets(pdf_bytes: bytes) -> bytes:
    """Bake visible widget appearances into page content and drop interactivity."""

    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        document.bake(annots=False, widgets=True)
        return document.tobytes(garbage=4, deflate=True)
    finally:
        document.close()
