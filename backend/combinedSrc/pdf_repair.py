import io
import os
from typing import Callable, Tuple, TypeVar

import fitz  # PyMuPDF

from .config import get_logger

logger = get_logger(__name__)

_T = TypeVar("_T")


def _normalize_mode(raw: str) -> str:
    """
    Normalize the repair mode into one of: off | auto | always.

    - off: never repair
    - auto: probe for MuPDF warnings; repair only if warnings appear
    - always: always repair PDF bytes before downstream rendering
    """
    mode = (raw or "").strip().lower()
    if mode in {"0", "false", "no", "off"}:
        return "off"
    if mode in {"1", "true", "yes", "always"}:
        return "always"
    if mode in {"auto", ""}:
        return "auto"
    logger.warning("Unknown SANDBOX_REPAIR_PDF value %r; defaulting to auto", raw)
    return "auto"


def _run_mupdf_action(action: Callable[[], _T]) -> Tuple[_T, str]:
    """
    Run a PyMuPDF action while capturing MuPDF warnings/errors without printing them.

    We temporarily disable MuPDF error/warning output so noisy PDFs do not flood the console.
    The warnings text is returned to the caller for conditional repair decisions.
    """
    prev_errors = fitz.TOOLS.mupdf_display_errors()
    prev_warnings = fitz.TOOLS.mupdf_display_warnings()
    try:
        fitz.TOOLS.mupdf_display_errors(False)
        fitz.TOOLS.mupdf_display_warnings(False)
        fitz.TOOLS.reset_mupdf_warnings()
        result = action()
        warnings = fitz.TOOLS.mupdf_warnings() or ""
        return result, warnings
    finally:
        fitz.TOOLS.mupdf_display_errors(prev_errors)
        fitz.TOOLS.mupdf_display_warnings(prev_warnings)


def _probe_mupdf_warnings(pdf_bytes: bytes) -> str:
    """
    Load a single page at low DPI to surface MuPDF warnings on broken PDFs.

    Rendering even one page forces MuPDF to resolve object streams and will surface
    "object not found in object stream" warnings on corrupted files.
    """

    def _probe() -> None:
        with fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf") as doc:
            if doc.page_count <= 0:
                return
            page = doc.load_page(0)
            page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)

    _, warnings = _run_mupdf_action(_probe)
    return warnings


def _repair_pdf_bytes(pdf_bytes: bytes) -> Tuple[bytes, str]:
    """
    Re-save the PDF with full cleanup and no object streams.

    This mirrors a qpdf-style "rewrite" to eliminate broken object streams and
    produces stable bytes for downstream rendering/geometry passes.
    """

    def _repair() -> bytes:
        with fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf") as doc:
            out = io.BytesIO()
            doc.save(
                out,
                garbage=4,
                clean=1,
                deflate=1,
                deflate_images=1,
                deflate_fonts=1,
                linear=1,
                use_objstms=0,
            )
            return out.getvalue()

    repaired_bytes, warnings = _run_mupdf_action(_repair)
    return repaired_bytes, warnings


def maybe_repair_pdf(pdf_bytes: bytes, *, source: str | None = None) -> bytes:
    """
    Optionally repair PDF bytes before rendering, based on SANDBOX_REPAIR_PDF.

    This keeps the detection pipeline resilient to broken object streams without
    mutating the stored source PDF. All changes stay in-memory.
    """
    mode = _normalize_mode(os.getenv("SANDBOX_REPAIR_PDF", "auto"))
    if mode == "off":
        return pdf_bytes

    label = source or "PDF bytes"
    try:
        warnings = _probe_mupdf_warnings(pdf_bytes) if mode == "auto" else "forced"
    except Exception as exc:
        logger.warning(
            "MuPDF probe failed for %s; attempting repair anyway (%s)",
            label,
            exc,
        )
        warnings = "probe_failed"

    if mode == "auto" and not warnings:
        logger.debug("No MuPDF warnings detected for %s; skipping repair", label)
        return pdf_bytes

    logger.info("Repairing PDF bytes for %s (mode=%s)", label, mode)
    try:
        repaired_bytes, repair_warnings = _repair_pdf_bytes(pdf_bytes)
        if not repaired_bytes:
            logger.warning("Repair produced empty output for %s; using original bytes", label)
            return pdf_bytes
        if repair_warnings:
            logger.debug(
                "MuPDF repair warnings for %s: %s",
                label,
                repair_warnings.splitlines()[0],
            )
        return repaired_bytes
    except Exception as exc:
        logger.warning("Repair failed for %s; using original bytes (%s)", label, exc)
        return pdf_bytes
