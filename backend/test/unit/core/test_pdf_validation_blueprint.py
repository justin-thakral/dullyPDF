"""Unit tests for backend.pdf_validation."""

import io

import pytest
from pypdf import PdfWriter

import backend.detection.pdf_validation as pdf_validation


def _make_pdf_bytes(*, encrypt_password: str | None = None) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    if encrypt_password is not None:
        writer.encrypt(encrypt_password)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_preflight_rejects_empty_pdf_bytes() -> None:
    with pytest.raises(pdf_validation.PdfValidationError, match="Uploaded file is empty"):
        pdf_validation.preflight_pdf_bytes(b"")


def test_preflight_rejects_corrupted_pdf_bytes() -> None:
    with pytest.raises(
        pdf_validation.PdfValidationError,
        match="PDF appears to be corrupted or unsupported",
    ):
        pdf_validation.preflight_pdf_bytes(b"not a real pdf")


def test_preflight_accepts_valid_pdf_bytes() -> None:
    pdf_bytes = _make_pdf_bytes()

    result = pdf_validation.preflight_pdf_bytes(pdf_bytes)

    assert result.pdf_bytes == pdf_bytes
    assert result.page_count >= 1
    assert result.was_decrypted is False


def test_preflight_rejects_encrypted_pdf_when_not_decryptable() -> None:
    encrypted_pdf = _make_pdf_bytes(encrypt_password="secret")

    with pytest.raises(
        pdf_validation.PdfValidationError,
        match="PDF is encrypted and cannot be processed",
    ):
        pdf_validation.preflight_pdf_bytes(encrypted_pdf, allow_encrypted=False)


def test_preflight_decrypts_empty_password_encrypted_pdf_when_allowed() -> None:
    encrypted_pdf = _make_pdf_bytes(encrypt_password="")

    result = pdf_validation.preflight_pdf_bytes(
        encrypted_pdf,
        allow_encrypted=False,
        allow_decrypt_empty_password=True,
    )

    assert result.page_count >= 1
    assert result.was_decrypted is True

    decrypted_reader = pdf_validation._load_reader(result.pdf_bytes)
    assert decrypted_reader.is_encrypted is False


def test_preflight_allows_encrypted_pdf_passthrough_when_allow_encrypted_true(
    mocker,
) -> None:
    reader = mocker.Mock()
    reader.is_encrypted = True
    reader.pages = [object(), object()]
    load_reader = mocker.patch("backend.detection.pdf_validation._load_reader", return_value=reader)
    decrypt = mocker.patch("backend.detection.pdf_validation._decrypt_with_empty_password", return_value=True)

    result = pdf_validation.preflight_pdf_bytes(b"encrypted", allow_encrypted=True)

    assert result.pdf_bytes == b"encrypted"
    assert result.page_count == 2
    assert result.was_decrypted is False
    load_reader.assert_called_once_with(b"encrypted")
    decrypt.assert_not_called()


def test_rewrite_decrypted_pdf_ignores_metadata_read_errors(mocker) -> None:
    encrypted_pdf = _make_pdf_bytes(encrypt_password="")
    reader = pdf_validation._load_reader(encrypted_pdf)
    assert reader.decrypt("")

    mocker.patch.object(
        type(reader),
        "metadata",
        new_callable=mocker.PropertyMock,
        side_effect=RuntimeError("metadata failed"),
    )

    rewritten = pdf_validation._rewrite_decrypted_pdf(reader)
    rewritten_reader = pdf_validation._load_reader(rewritten)

    assert rewritten
    assert len(rewritten_reader.pages) >= 1


def test_preflight_maps_page_count_failures_to_readable_error(mocker) -> None:
    class _BrokenReader:
        is_encrypted = False

        @property
        def pages(self):
            raise RuntimeError("cannot enumerate pages")

    mocker.patch("backend.detection.pdf_validation._load_reader", return_value=_BrokenReader())

    with pytest.raises(pdf_validation.PdfValidationError, match="Unable to read PDF pages"):
        pdf_validation.preflight_pdf_bytes(b"fake-pdf")


def test_decrypt_with_empty_password_returns_false_when_reader_raises(mocker) -> None:
    reader = mocker.Mock()
    reader.decrypt.side_effect = RuntimeError("decrypt failed")

    assert pdf_validation._decrypt_with_empty_password(reader) is False


def test_rewrite_decrypted_pdf_ignores_add_metadata_failure(mocker) -> None:
    class _Writer:
        def append_pages_from_reader(self, _reader) -> None:
            return None

        def add_metadata(self, _metadata) -> None:
            raise RuntimeError("metadata write failed")

        def write(self, output) -> None:
            output.write(b"%PDF-1.4\nok\n")

    fake_reader = mocker.Mock()
    fake_reader.metadata = {"/Title": "Sample"}
    mocker.patch("backend.detection.pdf_validation.PdfWriter", return_value=_Writer())

    rewritten = pdf_validation._rewrite_decrypted_pdf(fake_reader)

    assert rewritten.startswith(b"%PDF-1.4")
