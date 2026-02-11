import io
import tempfile
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile


def test_resolve_upload_limit_parses_and_clamps(monkeypatch, app_main) -> None:
    monkeypatch.setenv("SANDBOX_MAX_UPLOAD_MB", "25")
    max_mb, max_bytes = app_main._resolve_upload_limit()
    assert max_mb == 25
    assert max_bytes == 25 * 1024 * 1024

    monkeypatch.setenv("SANDBOX_MAX_UPLOAD_MB", "bad")
    assert app_main._resolve_upload_limit()[0] == 50

    monkeypatch.setenv("SANDBOX_MAX_UPLOAD_MB", "0")
    assert app_main._resolve_upload_limit()[0] == 1


@pytest.mark.anyio
async def test_read_upload_bytes_success_and_over_limit(app_main) -> None:
    small = UploadFile(filename="x.pdf", file=io.BytesIO(b"hello"))
    assert await app_main._read_upload_bytes(small, max_bytes=10, limit_message="too big") == b"hello"

    large = UploadFile(filename="x.pdf", file=io.BytesIO(b"0123456789"))
    with pytest.raises(HTTPException) as ctx:
        await app_main._read_upload_bytes(large, max_bytes=5, limit_message="too big")
    assert ctx.value.status_code == 413
    assert ctx.value.detail == "too big"


def test_write_upload_to_temp_success(tmp_path: Path, app_main, monkeypatch) -> None:
    upload = UploadFile(filename="x.pdf", file=io.BytesIO(b"content"))
    path = app_main._write_upload_to_temp(upload, max_bytes=20, limit_message="too big")
    try:
        assert path.exists()
        assert path.read_bytes() == b"content"
    finally:
        path.unlink(missing_ok=True)


def test_write_upload_to_temp_over_limit_cleans_temp_file(tmp_path: Path, app_main, monkeypatch) -> None:
    captured_path = tmp_path / "overflow.pdf"

    class _FakeTmp:
        def __init__(self, path: Path) -> None:
            self.name = str(path)
            self._fp = open(path, "wb")

        def write(self, chunk: bytes) -> int:
            return self._fp.write(chunk)

        def flush(self) -> None:
            self._fp.flush()

        def close(self) -> None:
            self._fp.close()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            self._fp.close()

    monkeypatch.setattr(
        tempfile,
        "NamedTemporaryFile",
        lambda delete, suffix: _FakeTmp(captured_path),
    )
    upload = UploadFile(filename="x.pdf", file=io.BytesIO(b"0123456789"))
    with pytest.raises(HTTPException) as ctx:
        app_main._write_upload_to_temp(upload, max_bytes=3, limit_message="too big")
    assert ctx.value.status_code == 413
    assert captured_path.exists() is False


def test_parse_json_list_form_field_validation(app_main) -> None:
    assert app_main._parse_json_list_form_field(None, "checkboxRules") is None
    parsed = app_main._parse_json_list_form_field('[{"a": 1}, 2, {"b": 3}]', "checkboxRules")
    assert parsed == [{"a": 1}, {"b": 3}]

    with pytest.raises(HTTPException) as ctx:
        app_main._parse_json_list_form_field("{bad", "checkboxRules")
    assert ctx.value.status_code == 400
    assert "Invalid checkboxRules payload" in str(ctx.value.detail)

    with pytest.raises(HTTPException) as ctx:
        app_main._parse_json_list_form_field('{"a": 1}', "checkboxRules")
    assert ctx.value.status_code == 400
    assert "must be a JSON array" in str(ctx.value.detail)


def test_filename_helpers_sanitize_traversal_and_crlf(app_main) -> None:
    sanitized = app_main._sanitize_basename_segment("../evil\r\nname.pdf", "fallback")
    assert ".." not in sanitized
    assert "\r" not in sanitized
    assert "\n" not in sanitized

    safe_name = app_main._safe_pdf_download_filename("../evil", fallback="doc")
    assert safe_name.endswith(".pdf")
    assert "/" not in safe_name

    long_name = "a" * 500
    assert len(app_main._safe_pdf_download_filename(long_name)) <= 180


def test_log_pdf_label_returns_stable_non_sensitive_id(app_main) -> None:
    label_1 = app_main._log_pdf_label("../secret/path.pdf")
    label_2 = app_main._log_pdf_label("../secret/path.pdf")
    assert label_1 == label_2
    assert label_1.startswith("pdf")
    assert "secret" not in label_1


# ---------------------------------------------------------------------------
# Edge-case: cleanup_paths continues when unlink raises
# ---------------------------------------------------------------------------
# The helper is best-effort: if one path fails to unlink, the remaining paths
# should still be attempted.  This verifies the except/continue branch.
def test_cleanup_paths_continues_when_unlink_fails(app_main, tmp_path) -> None:
    good_file = tmp_path / "good.pdf"
    good_file.write_bytes(b"data")

    # Create a Path-like object whose unlink always raises, simulating
    # a permission error or a path that was already removed externally.
    class _FailPath:
        def unlink(self, missing_ok=False):
            raise PermissionError("not allowed")

    fail_path = _FailPath()

    # cleanup_paths should not raise even though one of the paths fails.
    app_main._cleanup_paths([fail_path, good_file])

    # The second file should still be cleaned up despite the first failure.
    assert not good_file.exists()
