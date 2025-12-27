import io
import os
from dataclasses import dataclass
from typing import Dict, List

import pdfplumber

from .config import get_logger

logger = get_logger(__name__)

TEXT_LAYER_MIN_WORDS_TOTAL = int(
    os.getenv("SANDBOX_TEXT_LAYER_MIN_WORDS_TOTAL", "30")
)
TEXT_LAYER_MIN_WORDS_PER_PAGE = float(
    os.getenv("SANDBOX_TEXT_LAYER_MIN_WORDS_PER_PAGE", "6")
)


@dataclass
class TextLayerStats:
    """
    Text-layer extraction summary used to decide native vs scanned routing.

    We track per-page counts so the router can avoid OCR-derived labels when
    deciding whether to route a PDF to the scanned pipeline.
    """

    total_pages: int
    total_words: int
    pages_with_text: int
    words_by_page: Dict[int, int]

    @property
    def avg_words_per_page(self) -> float:
        if self.total_pages <= 0:
            return 0.0
        return float(self.total_words) / float(self.total_pages)


@dataclass
class TextLayerGeometry:
    """
    Lightweight vector/text geometry extracted from native PDFs.

    We keep glyph and rect bboxes separate so downstream filters can treat each
    source differently (glyph overlap vs vector checkbox injection).
    """

    char_bboxes_by_page: Dict[int, List[Dict[str, object]]]
    rect_bboxes_by_page: Dict[int, List[Dict[str, object]]]


def summarize_text_layer(pdf_bytes: bytes) -> TextLayerStats:
    """
    Count extractable text-layer words using pdfplumber (no OCR).

    This is intentionally conservative: if the PDF has a weak or empty text layer,
    we treat it as scanned so the pipeline uses the scanned path.
    """
    words_by_page: Dict[int, int] = {}
    total_words = 0
    pages_with_text = 0
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for idx, page in enumerate(pdf.pages):
            words = page.extract_words(
                use_text_flow=True,
                keep_blank_chars=False,
                x_tolerance=1.5,
                y_tolerance=2,
            )
            count = len(words or [])
            page_idx = idx + 1
            words_by_page[page_idx] = count
            total_words += count
            if count > 0:
                pages_with_text += 1

    stats = TextLayerStats(
        total_pages=len(words_by_page),
        total_words=total_words,
        pages_with_text=pages_with_text,
        words_by_page=words_by_page,
    )
    logger.debug(
        "Text-layer stats: pages=%s total_words=%s avg_words=%.2f pages_with_text=%s",
        stats.total_pages,
        stats.total_words,
        stats.avg_words_per_page,
        stats.pages_with_text,
    )
    return stats


def is_native_text_layer(stats: TextLayerStats) -> bool:
    """
    Return True when the text layer is strong enough to run the native pipeline.

    Heuristic:
    - Use the total word count and average words per page so single-page forms
      with sparse labels still route correctly.
    - Thresholds are configurable via SANDBOX_TEXT_LAYER_MIN_WORDS_* env vars.
    """
    if stats.total_words >= TEXT_LAYER_MIN_WORDS_TOTAL:
        return True
    if stats.avg_words_per_page >= TEXT_LAYER_MIN_WORDS_PER_PAGE:
        return True
    return False


def extract_char_bboxes(pdf_bytes: bytes) -> Dict[int, List[Dict[str, object]]]:
    """
    Extract per-page character bounding boxes in originTop PDF points.

    This supports native-only filters that reject geometry candidates overlapping text glyphs.
    """
    geometry = extract_text_layer_geometry(pdf_bytes)
    return geometry.char_bboxes_by_page


def extract_text_layer_geometry(pdf_bytes: bytes) -> TextLayerGeometry:
    """
    Extract text-layer glyphs and vector rectangles from the PDF.

    This opens the PDF once and returns both data sets to avoid repeated parsing.
    """
    char_bboxes_by_page: Dict[int, List[Dict[str, object]]] = {}
    rect_bboxes_by_page: Dict[int, List[Dict[str, object]]] = {}
    total_chars = 0
    total_rects = 0
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for idx, page in enumerate(pdf.pages):
            page_idx = idx + 1
            char_boxes: List[Dict[str, object]] = []
            for ch in page.chars or []:
                text = (ch.get("text") or "")
                if not text or text.isspace():
                    continue
                x0 = ch.get("x0")
                x1 = ch.get("x1")
                top = ch.get("top")
                bottom = ch.get("bottom")
                if x0 is None or x1 is None or top is None or bottom is None:
                    continue
                obj_type = ch.get("object_type")
                char_boxes.append(
                    {
                        "bbox": [float(x0), float(top), float(x1), float(bottom)],
                        "text": text,
                        "fontname": ch.get("fontname"),
                        "object_type": obj_type,
                    }
                )
            char_bboxes_by_page[page_idx] = char_boxes
            total_chars += len(char_boxes)

            rect_boxes: List[Dict[str, object]] = []
            for rect in page.rects or []:
                x0 = rect.get("x0")
                x1 = rect.get("x1")
                top = rect.get("top")
                bottom = rect.get("bottom")
                if x0 is None or x1 is None or top is None or bottom is None:
                    continue
                rect_boxes.append(
                    {
                        "bbox": [float(x0), float(top), float(x1), float(bottom)],
                        "stroke": rect.get("stroke"),
                        "fill": rect.get("fill"),
                        "linewidth": rect.get("linewidth"),
                        "non_stroking_color": rect.get("non_stroking_color"),
                        "stroking_color": rect.get("stroking_color"),
                    }
                )
            rect_bboxes_by_page[page_idx] = rect_boxes
            total_rects += len(rect_boxes)

    logger.debug(
        "Extracted %s text-layer glyph boxes and %s vector rects across %s pages",
        total_chars,
        total_rects,
        len(char_bboxes_by_page),
    )
    return TextLayerGeometry(
        char_bboxes_by_page=char_bboxes_by_page,
        rect_bboxes_by_page=rect_bboxes_by_page,
    )
