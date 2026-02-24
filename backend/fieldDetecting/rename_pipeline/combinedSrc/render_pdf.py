"""
PDF rendering utilities for the rename pipeline.

We rasterize pages with PyMuPDF into BGR images and capture page metadata
needed for px<->pt conversions downstream.
"""

import io
import os
from typing import Dict, List, Optional

import cv2
import fitz  # PyMuPDF
import numpy as np

from .concurrency import resolve_workers, run_threaded_map
from .config import DEFAULT_DPI, get_logger

logger = get_logger(__name__)


def _render_page(pdf_bytes: bytes, *, page_index: int, dpi: int) -> Dict:
    """
    Render a single PDF page into a raster image (BGR).

    Data structures:
    - Returns a dict containing geometry metadata and a numpy image array.
    - This is used by downstream OpenCV detectors that operate on pixel grids.
    """
    scale = dpi / 72.0  # PDF points are 72 per inch.
    with fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf") as doc:
        page = doc.load_page(page_index)
        return _render_page_from_doc(page, page_index=page_index, scale=scale)


def _render_page_from_doc(page, *, page_index: int, scale: float) -> Dict:
    """
    Render a page from an open PyMuPDF document into a BGR image and metadata.
    """
    # Step 1: Rasterize the vector PDF page into a pixel grid at the target scale.
    matrix = fitz.Matrix(scale, scale)
    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
    width_points = float(page.cropbox.width)
    height_points = float(page.cropbox.height)

    # Step 2: Reinterpret MuPDF's contiguous sample bytes as an HxWxC numpy image.
    image = np.frombuffer(pixmap.samples, dtype=np.uint8)
    image = image.reshape(pixmap.height, pixmap.width, pixmap.n)
    # Step 3: Normalize color channels so downstream OpenCV code always receives 3 channels.
    if pixmap.n == 4:
        image = cv2.cvtColor(image, cv2.COLOR_RGBA2RGB)
    elif pixmap.n == 1:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)

    return {
        "page_index": page_index + 1,
        "width_points": width_points,
        "height_points": height_points,
        "rotation": page.rotation,
        "scale": scale,
        "image_width_px": pixmap.width,
        "image_height_px": pixmap.height,
        "image": image,
    }


def render_pdf_to_images(
    pdf_bytes: bytes,
    dpi: int = DEFAULT_DPI,
    *,
    max_workers: Optional[int] = None,
) -> List[Dict]:
    """
    Render each PDF page to a high-DPI image for downstream OpenCV processing.

    Code steps:
    1) Compute pixel scaling from DPI (PDF points are 1/72 inch).
    2) Prefer a sequential pass when worker count is 1 to avoid thread overhead.
    3) Otherwise dispatch one render task per page, reopening the PDF per worker.
    4) Return ordered page payloads with both geometry metadata and image arrays.

    Returns a list of dicts containing:
        - page_index: 1-based page number
        - width_points / height_points: original PDF dimensions in points
        - rotation: page rotation applied by the renderer
        - scale: pixels-per-point scaling factor used to render the image
        - image: numpy array in BGR color space

    Time complexity:
    - O(P) orchestration for P pages, plus rasterization cost per page.
    """
    # Rendering converts vector pages into pixel grids for OpenCV. The scale factor maps
    # PDF points (1/72 inch) to pixels so downstream geometry stays consistent at any DPI.
    scale = dpi / 72.0  # PDF points are 72 per inch.
    max_workers = max_workers or resolve_workers("render", default=min(4, os.cpu_count() or 4))
    with fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf") as doc:
        page_count = doc.page_count
        logger.info("Rendering %s pages at %s DPI (scale %.2f)", page_count, dpi, scale)
        # Step 2 (sequential path): reuse a single open document handle.
        if max_workers <= 1 or page_count <= 1:
            page_images: List[Dict] = []
            for idx, page in enumerate(doc):
                page_images.append(_render_page_from_doc(page, page_index=idx, scale=scale))
                logger.debug(
                    "Rendered page %s: size %sx%s px, %sx%s pts, rotation %s",
                    idx + 1,
                    page_images[-1]["image_width_px"],
                    page_images[-1]["image_height_px"],
                    round(page_images[-1]["width_points"], 2),
                    round(page_images[-1]["height_points"], 2),
                    page_images[-1]["rotation"],
                )
            return page_images

    # Step 3 (parallel path): PyMuPDF page objects are not thread-safe across threads.
    # Reopen per page in each worker and keep outputs ordered by page index.
    indices = list(range(page_count))
    rendered = run_threaded_map(
        indices,
        lambda idx: _render_page(pdf_bytes, page_index=idx, dpi=dpi),
        max_workers=max_workers,
        label="render",
    )
    for page in rendered:
        logger.debug(
            "Rendered page %s: size %sx%s px, %sx%s pts, rotation %s",
            page["page_index"],
            page["image_width_px"],
            page["image_height_px"],
            round(page["width_points"], 2),
            round(page["height_points"], 2),
            page["rotation"],
        )
    return rendered
