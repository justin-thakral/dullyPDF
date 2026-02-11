"""Unit tests for `backend/firebaseDB/storage_service.py`."""

import importlib
import io
import json

import pytest


_ENV_KEYS = ["FORMS_BUCKET", "TEMPLATES_BUCKET", "SANDBOX_SESSION_BUCKET", "SESSION_BUCKET"]


def _reload_storage_service(monkeypatch, **env):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    import backend.firebaseDB.storage_service as storage_service

    return importlib.reload(storage_service)


def _mock_bucket_and_blob(mocker):
    blob = mocker.Mock()
    bucket = mocker.Mock()
    bucket.blob.return_value = blob
    return bucket, blob


def test_require_bucket_config_raises_when_required_buckets_missing(monkeypatch) -> None:
    ss = _reload_storage_service(monkeypatch, FORMS_BUCKET="", TEMPLATES_BUCKET="templates")
    with pytest.raises(RuntimeError, match="FORMS_BUCKET and TEMPLATES_BUCKET must be set"):
        ss._require_bucket_config()

    ss = _reload_storage_service(monkeypatch, FORMS_BUCKET="forms", TEMPLATES_BUCKET="")
    with pytest.raises(RuntimeError, match="FORMS_BUCKET and TEMPLATES_BUCKET must be set"):
        ss._require_bucket_config()


def test_require_session_bucket_config_prefers_session_bucket_and_falls_back(monkeypatch) -> None:
    ss = _reload_storage_service(
        monkeypatch,
        FORMS_BUCKET="forms",
        TEMPLATES_BUCKET="templates",
        SANDBOX_SESSION_BUCKET="sessions",
    )
    assert ss._require_session_bucket_config() == "sessions"

    ss = _reload_storage_service(monkeypatch, FORMS_BUCKET="forms", TEMPLATES_BUCKET="templates")
    assert ss._require_session_bucket_config() == "forms"

    ss = _reload_storage_service(monkeypatch, FORMS_BUCKET="", TEMPLATES_BUCKET="templates")
    with pytest.raises(RuntimeError, match="SANDBOX_SESSION_BUCKET or FORMS_BUCKET must be set"):
        ss._require_session_bucket_config()


@pytest.mark.parametrize(
    "path, expected_error",
    [
        ("", "Empty storage destination path"),
        ("/absolute/path.pdf", "must be relative"),
        ("..//traversal.pdf", "Refusing unsafe"),
        ("folder\\windows.pdf", "Refusing unsafe"),
        ("line\nbreak.pdf", "Invalid storage destination path"),
        ("a" * 1025, "too long"),
    ],
)
def test_assert_safe_object_path_rejects_unsafe_inputs(monkeypatch, path: str, expected_error: str) -> None:
    ss = _reload_storage_service(monkeypatch, FORMS_BUCKET="forms", TEMPLATES_BUCKET="templates")

    with pytest.raises(ValueError, match=expected_error):
        ss._assert_safe_object_path(path)


def test_assert_safe_object_path_accepts_relative_path(monkeypatch) -> None:
    ss = _reload_storage_service(monkeypatch, FORMS_BUCKET="forms", TEMPLATES_BUCKET="templates")
    assert ss._assert_safe_object_path("folder/file.pdf") == "folder/file.pdf"


def test_parse_gs_uri_validates_format_and_bucket_allowlist(monkeypatch) -> None:
    ss = _reload_storage_service(
        monkeypatch,
        FORMS_BUCKET="forms",
        TEMPLATES_BUCKET="templates",
        SANDBOX_SESSION_BUCKET="sessions",
    )

    assert ss._parse_gs_uri("gs://forms/path/file.pdf") == ("forms", "path/file.pdf")

    with pytest.raises(ValueError, match="Invalid bucket path format"):
        ss._parse_gs_uri("https://forms/path/file.pdf")

    with pytest.raises(ValueError, match="non-allowlisted bucket"):
        ss._parse_gs_uri("gs://other/path/file.pdf")


def test_is_gcs_path_detects_only_gs_uris(monkeypatch) -> None:
    ss = _reload_storage_service(monkeypatch, FORMS_BUCKET="forms", TEMPLATES_BUCKET="templates")

    assert ss.is_gcs_path("gs://forms/file.pdf") is True
    assert ss.is_gcs_path("https://example.com/file.pdf") is False
    assert ss.is_gcs_path(None) is False


def test_upload_form_pdf_uses_forms_bucket(monkeypatch, mocker) -> None:
    ss = _reload_storage_service(monkeypatch, FORMS_BUCKET="forms", TEMPLATES_BUCKET="templates")
    bucket, blob = _mock_bucket_and_blob(mocker)
    mocker.patch("backend.firebaseDB.storage_service.get_storage_bucket", return_value=bucket)

    uri = ss.upload_form_pdf("/tmp/source.pdf", "uploads/form.pdf")

    assert uri == "gs://forms/uploads/form.pdf"
    assert blob.cache_control == "private, no-store"
    blob.upload_from_filename.assert_called_once_with("/tmp/source.pdf", content_type="application/pdf")


def test_upload_template_pdf_uses_templates_bucket(monkeypatch, mocker) -> None:
    ss = _reload_storage_service(monkeypatch, FORMS_BUCKET="forms", TEMPLATES_BUCKET="templates")
    bucket, blob = _mock_bucket_and_blob(mocker)
    mocker.patch("backend.firebaseDB.storage_service.get_storage_bucket", return_value=bucket)

    uri = ss.upload_template_pdf("/tmp/source.pdf", "uploads/template.pdf")

    assert uri == "gs://templates/uploads/template.pdf"
    blob.upload_from_filename.assert_called_once_with("/tmp/source.pdf", content_type="application/pdf")


def test_upload_pdf_to_bucket_path_uses_existing_uri_bucket(monkeypatch, mocker) -> None:
    ss = _reload_storage_service(
        monkeypatch,
        FORMS_BUCKET="forms",
        TEMPLATES_BUCKET="templates",
        SANDBOX_SESSION_BUCKET="sessions",
    )
    bucket, blob = _mock_bucket_and_blob(mocker)
    get_bucket = mocker.patch("backend.firebaseDB.storage_service.get_storage_bucket", return_value=bucket)

    uri = ss.upload_pdf_to_bucket_path("/tmp/source.pdf", "gs://sessions/path/file.pdf")

    assert uri == "gs://sessions/path/file.pdf"
    get_bucket.assert_called_once_with("sessions")
    blob.upload_from_filename.assert_called_once_with("/tmp/source.pdf", content_type="application/pdf")


def test_upload_session_pdf_bytes_uses_session_bucket(monkeypatch, mocker) -> None:
    ss = _reload_storage_service(
        monkeypatch,
        FORMS_BUCKET="forms",
        TEMPLATES_BUCKET="templates",
        SANDBOX_SESSION_BUCKET="sessions",
    )
    bucket, blob = _mock_bucket_and_blob(mocker)
    mocker.patch("backend.firebaseDB.storage_service.get_storage_bucket", return_value=bucket)

    uri = ss.upload_session_pdf_bytes(b"%PDF-1.4\n", "sessions/s1.pdf")

    assert uri == "gs://sessions/sessions/s1.pdf"
    blob.upload_from_string.assert_called_once_with(b"%PDF-1.4\n", content_type="application/pdf")


def test_upload_session_json_serializes_payload(monkeypatch, mocker) -> None:
    ss = _reload_storage_service(
        monkeypatch,
        FORMS_BUCKET="forms",
        TEMPLATES_BUCKET="templates",
        SANDBOX_SESSION_BUCKET="sessions",
    )
    bucket, blob = _mock_bucket_and_blob(mocker)
    mocker.patch("backend.firebaseDB.storage_service.get_storage_bucket", return_value=bucket)

    uri = ss.upload_session_json({"ok": True}, "sessions/s1.json")

    assert uri == "gs://sessions/sessions/s1.json"
    args, kwargs = blob.upload_from_string.call_args
    assert json.loads(args[0].decode("utf-8")) == {"ok": True}
    assert kwargs == {"content_type": "application/json"}


def test_delete_pdf_deletes_blob_from_allowlisted_bucket(monkeypatch, mocker) -> None:
    ss = _reload_storage_service(monkeypatch, FORMS_BUCKET="forms", TEMPLATES_BUCKET="templates")
    bucket, blob = _mock_bucket_and_blob(mocker)
    mocker.patch("backend.firebaseDB.storage_service.get_storage_bucket", return_value=bucket)

    ss.delete_pdf("gs://forms/path/to/file.pdf")

    blob.delete.assert_called_once_with(if_generation_match=None)


def test_stream_pdf_prefers_blob_stream(monkeypatch, mocker) -> None:
    ss = _reload_storage_service(monkeypatch, FORMS_BUCKET="forms", TEMPLATES_BUCKET="templates")
    bucket, blob = _mock_bucket_and_blob(mocker)
    stream = io.BytesIO(b"pdf")
    blob.open.return_value = stream
    mocker.patch("backend.firebaseDB.storage_service.get_storage_bucket", return_value=bucket)

    result = ss.stream_pdf("gs://forms/path/to/file.pdf")

    assert result is stream
    blob.download_as_bytes.assert_not_called()


def test_stream_pdf_falls_back_to_downloaded_bytes(monkeypatch, mocker) -> None:
    ss = _reload_storage_service(monkeypatch, FORMS_BUCKET="forms", TEMPLATES_BUCKET="templates")
    bucket, blob = _mock_bucket_and_blob(mocker)
    blob.open.side_effect = RuntimeError("open failed")
    blob.download_as_bytes.return_value = b"pdf-bytes"
    mocker.patch("backend.firebaseDB.storage_service.get_storage_bucket", return_value=bucket)

    result = ss.stream_pdf("gs://forms/path/to/file.pdf")

    assert isinstance(result, io.BytesIO)
    assert result.read() == b"pdf-bytes"


def test_download_pdf_bytes_reads_blob_bytes(monkeypatch, mocker) -> None:
    ss = _reload_storage_service(
        monkeypatch,
        FORMS_BUCKET="forms",
        TEMPLATES_BUCKET="templates",
        SANDBOX_SESSION_BUCKET="sessions",
    )
    bucket, blob = _mock_bucket_and_blob(mocker)
    blob.download_as_bytes.return_value = b"pdf-bytes"
    mocker.patch("backend.firebaseDB.storage_service.get_storage_bucket", return_value=bucket)

    result = ss.download_pdf_bytes("gs://sessions/path/file.pdf")

    assert result == b"pdf-bytes"


def test_download_session_json_decodes_payload(monkeypatch, mocker) -> None:
    ss = _reload_storage_service(
        monkeypatch,
        FORMS_BUCKET="forms",
        TEMPLATES_BUCKET="templates",
        SANDBOX_SESSION_BUCKET="sessions",
    )
    bucket, blob = _mock_bucket_and_blob(mocker)
    blob.download_as_bytes.return_value = b'{"a": 1}'
    mocker.patch("backend.firebaseDB.storage_service.get_storage_bucket", return_value=bucket)

    result = ss.download_session_json("gs://sessions/path/file.json")

    assert result == {"a": 1}


# ---------------------------------------------------------------------------
# Edge-case: upload_session_json with payload=None defaults to {}
# ---------------------------------------------------------------------------
# When None is passed as the payload, the function should serialize an empty
# dict rather than raising a serialization error.
def test_upload_session_json_with_none_payload_defaults_to_empty_dict(monkeypatch, mocker) -> None:
    ss = _reload_storage_service(
        monkeypatch,
        FORMS_BUCKET="forms",
        TEMPLATES_BUCKET="templates",
        SANDBOX_SESSION_BUCKET="sessions",
    )
    bucket, blob = _mock_bucket_and_blob(mocker)
    mocker.patch("backend.firebaseDB.storage_service.get_storage_bucket", return_value=bucket)

    uri = ss.upload_session_json(None, "sessions/s1.json")

    assert uri == "gs://sessions/sessions/s1.json"
    args, kwargs = blob.upload_from_string.call_args
    assert json.loads(args[0].decode("utf-8")) == {}
    assert kwargs == {"content_type": "application/json"}


# ---------------------------------------------------------------------------
# Edge-case: download_session_json with invalid JSON in storage
# ---------------------------------------------------------------------------
# When the stored blob contains bytes that are not valid JSON, json.loads
# should raise a json.JSONDecodeError.
def test_download_session_json_raises_on_invalid_json(monkeypatch, mocker) -> None:
    ss = _reload_storage_service(
        monkeypatch,
        FORMS_BUCKET="forms",
        TEMPLATES_BUCKET="templates",
        SANDBOX_SESSION_BUCKET="sessions",
    )
    bucket, blob = _mock_bucket_and_blob(mocker)
    blob.download_as_bytes.return_value = b"not-valid-json{{"
    mocker.patch("backend.firebaseDB.storage_service.get_storage_bucket", return_value=bucket)

    with pytest.raises(json.JSONDecodeError):
        ss.download_session_json("gs://sessions/path/file.json")


# ---------------------------------------------------------------------------
# Edge-case: _require_session_bucket_config fallback to SESSION_BUCKET env var
# ---------------------------------------------------------------------------
# When SANDBOX_SESSION_BUCKET is not set but SESSION_BUCKET is, the module-level
# SESSION_BUCKET variable should be populated from SESSION_BUCKET and the
# function should return that value.
def test_require_session_bucket_config_falls_back_to_session_bucket_env(monkeypatch) -> None:
    ss = _reload_storage_service(
        monkeypatch,
        FORMS_BUCKET="forms",
        TEMPLATES_BUCKET="templates",
        SESSION_BUCKET="my-session-bucket",
    )
    assert ss._require_session_bucket_config() == "my-session-bucket"
