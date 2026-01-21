"""PDF validation helpers."""

from __future__ import annotations

import io
from dataclasses import dataclass

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError


class PdfValidationError(ValueError):
    """Raised when a PDF fails preflight checks."""


@dataclass(frozen=True)
class PdfValidationResult:
    pdf_bytes: bytes
    page_count: int
    was_decrypted: bool


def _load_reader(pdf_bytes: bytes) -> PdfReader:
    try:
        return PdfReader(io.BytesIO(pdf_bytes))
    except PdfReadError as exc:
        raise PdfValidationError("PDF appears to be corrupted or unsupported") from exc


def _decrypt_with_empty_password(reader: PdfReader) -> bool:
    try:
        return bool(reader.decrypt(""))
    except Exception:
        return False


def _rewrite_decrypted_pdf(reader: PdfReader) -> bytes:
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    try:
        metadata = reader.metadata
    except Exception:
        metadata = None
    if metadata:
        try:
            writer.add_metadata(metadata)
        except Exception:
            pass
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def preflight_pdf_bytes(
    pdf_bytes: bytes,
    *,
    allow_encrypted: bool = False,
    allow_decrypt_empty_password: bool = True,
) -> PdfValidationResult:
    if not pdf_bytes:
        raise PdfValidationError("Uploaded file is empty")

    reader = _load_reader(pdf_bytes)
    was_decrypted = False

    if reader.is_encrypted:
        if allow_encrypted:
            pass
        elif allow_decrypt_empty_password and _decrypt_with_empty_password(reader):
            pdf_bytes = _rewrite_decrypted_pdf(reader)
            reader = _load_reader(pdf_bytes)
            was_decrypted = True
        else:
            raise PdfValidationError("PDF is encrypted and cannot be processed")

    try:
        page_count = len(reader.pages)
    except Exception as exc:
        raise PdfValidationError("Unable to read PDF pages") from exc

    return PdfValidationResult(
        pdf_bytes=pdf_bytes,
        page_count=max(1, int(page_count)),
        was_decrypted=was_decrypted,
    )

