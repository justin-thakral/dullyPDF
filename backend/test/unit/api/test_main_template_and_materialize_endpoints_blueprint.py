import io
from pathlib import Path

from fastapi import HTTPException
import pytest

from backend.detection.pdf_validation import PdfValidationResult


def _patch_auth(mocker, app_main, user) -> None:
    mocker.patch.object(app_main, "_verify_token", return_value={"uid": user.app_user_id})
    mocker.patch.object(app_main, "ensure_user", return_value=user)


class _FakePdfDoc:
    def __init__(self, page_count: int = 1) -> None:
        self.page_count = page_count

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None


def test_template_session_fields_validation_and_page_limits(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    response = client.post(
        "/api/templates/session",
        files={"pdf": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        data={"fields": "{bad"},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "Invalid fields payload" in response.text

    mocker.patch.object(app_main, "_read_upload_bytes", return_value=b"%PDF-1.4\n")
    mocker.patch.object(
        app_main,
        "_validate_pdf_for_detection",
        return_value=PdfValidationResult(pdf_bytes=b"%PDF-1.4\n", page_count=10, was_decrypted=False),
    )
    mocker.patch.object(app_main, "_resolve_fillable_max_pages", return_value=5)
    response = client.post(
        "/api/templates/session",
        files={"pdf": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        data={"fields": '[{"name":"f","x":1,"y":2,"width":3,"height":4}]'},
        headers=auth_headers,
    )
    assert response.status_code == 403
    assert "Fillable upload limited to 5 pages" in response.text


def test_pdf_page_count_validates_upload_and_returns_detect_limit_metadata(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    response = client.post(
        "/api/pdf/page-count",
        files={"pdf": ("x.txt", b"hello", "text/plain")},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "Only PDF uploads" in response.text

    mocker.patch.object(app_main, "_read_upload_bytes", return_value=b"")
    response = client.post(
        "/api/pdf/page-count",
        files={"pdf": ("x.pdf", b"", "application/pdf")},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "Uploaded file is empty" in response.text

    mocker.patch.object(app_main, "_read_upload_bytes", return_value=b"%PDF-1.4\n")
    mocker.patch.object(
        app_main,
        "_validate_pdf_for_detection",
        return_value=PdfValidationResult(pdf_bytes=b"%PDF-1.4\n", page_count=7, was_decrypted=False),
    )
    mocker.patch.object(app_main, "_resolve_detect_max_pages", return_value=5)
    response = client.post(
        "/api/pdf/page-count",
        files={"pdf": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "pageCount": 7,
        "detectMaxPages": 5,
        "withinDetectLimit": False,
    }


def test_template_session_success_coerces_fields(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_read_upload_bytes", return_value=b"%PDF-1.4\n")
    mocker.patch.object(
        app_main,
        "_validate_pdf_for_detection",
        return_value=PdfValidationResult(pdf_bytes=b"%PDF-1.4\n", page_count=1, was_decrypted=False),
    )
    mocker.patch.object(app_main, "_resolve_fillable_max_pages", return_value=5)
    store_mock = mocker.patch.object(app_main, "_store_session_entry", return_value=None)
    response = client.post(
        "/api/templates/session",
        files={"pdf": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        data={"fields": '[{"name":"f","x":1,"y":2,"width":3,"height":4}]'},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["fieldCount"] == 1
    stored_entry = store_mock.call_args.args[1]
    assert stored_entry["fields"][0]["rect"] == [1.0, 2.0, 4.0, 6.0]


def test_materialize_empty_fields_fast_path_and_invalid_upload(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
    tmp_path: Path,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    temp_pdf = tmp_path / "materialize.pdf"
    temp_pdf.write_bytes(b"%PDF-1.4\nfake")
    mocker.patch.object(app_main, "_write_upload_to_temp", return_value=temp_pdf)
    mocker.patch.object(app_main.fitz, "open", return_value=_FakePdfDoc(page_count=1))
    mocker.patch.object(app_main, "_resolve_fillable_max_pages", return_value=10)
    mocker.patch.object(app_main, "_resolve_stream_cors_headers", return_value={"Access-Control-Allow-Origin": "https://app.example.com"})
    response = client.post(
        "/api/forms/materialize",
        files={"pdf": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        data={"fields": "[]"},
        headers={**auth_headers, "Origin": "https://app.example.com"},
    )
    assert response.status_code == 200
    assert "filename=\"x.pdf\"" in response.headers["content-disposition"]
    assert response.headers["access-control-allow-origin"] == "https://app.example.com"

    # Invalid PDF upload path triggers cleanup + 400.
    mocker.patch.object(app_main.fitz, "open", side_effect=RuntimeError("bad pdf"))
    cleanup_mock = mocker.patch.object(app_main, "_cleanup_paths", return_value=None)
    response = client.post(
        "/api/forms/materialize",
        files={"pdf": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        data={"fields": "[]"},
        headers=auth_headers,
    )
    assert response.status_code == 400
    cleanup_mock.assert_called()


def test_materialize_inject_fields_path_and_filename_sanitization(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
    tmp_path: Path,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    temp_pdf = tmp_path / "input.pdf"
    temp_pdf.write_bytes(b"%PDF-1.4\nfake")
    mocker.patch.object(app_main, "_write_upload_to_temp", return_value=temp_pdf)
    mocker.patch.object(app_main.fitz, "open", return_value=_FakePdfDoc(page_count=1))
    mocker.patch.object(app_main, "_resolve_fillable_max_pages", return_value=10)

    def _inject(temp_path, template_path, output_path):
        output_path.write_bytes(b"%PDF-1.4\noutput")

    mocker.patch.object(app_main, "inject_fields", side_effect=_inject)
    response = client.post(
        "/api/forms/materialize",
        files={"pdf": ("../../evil\r\n.pdf", b"%PDF-1.4\n", "application/pdf")},
        data={"fields": '[{"name":"f","x":1,"y":2,"width":3,"height":4}]'},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert "-fillable" in response.headers["content-disposition"]
    assert "\r" not in response.headers["content-disposition"]


def test_materialize_inject_failure_cleans_temp_files_immediately(
    app_main,
    base_user,
    mocker,
    auth_headers,
    tmp_path: Path,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    temp_pdf = tmp_path / "inject-fail.pdf"
    temp_pdf.write_bytes(b"%PDF-1.4\nfake")
    mocker.patch.object(app_main, "_write_upload_to_temp", return_value=temp_pdf)
    mocker.patch.object(app_main.fitz, "open", return_value=_FakePdfDoc(page_count=1))
    mocker.patch.object(app_main, "_resolve_fillable_max_pages", return_value=10)
    mocker.patch.object(app_main, "inject_fields", side_effect=RuntimeError("inject failed"))
    cleanup_mock = mocker.patch.object(app_main, "_cleanup_paths", return_value=None)

    from fastapi.testclient import TestClient

    local_client = TestClient(app_main.app, raise_server_exceptions=False)
    response = local_client.post(
        "/api/forms/materialize",
        files={"pdf": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        data={"fields": '[{"name":"f","x":1,"y":2,"width":3,"height":4}]'},
        headers=auth_headers,
    )

    assert response.status_code == 500
    cleanup_mock.assert_called_once()


def test_materialize_template_write_failure_cleans_temp_files_immediately(
    app_main,
    base_user,
    mocker,
    auth_headers,
    tmp_path: Path,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    temp_pdf = tmp_path / "template-write-fail.pdf"
    temp_pdf.write_bytes(b"%PDF-1.4\nfake")
    mocker.patch.object(app_main, "_write_upload_to_temp", return_value=temp_pdf)
    mocker.patch.object(app_main.fitz, "open", return_value=_FakePdfDoc(page_count=1))
    mocker.patch.object(app_main, "_resolve_fillable_max_pages", return_value=10)
    cleanup_mock = mocker.patch.object(app_main, "_cleanup_paths", return_value=None)
    mocker.patch.object(Path, "write_text", side_effect=OSError("disk full"))

    from fastapi.testclient import TestClient

    local_client = TestClient(app_main.app, raise_server_exceptions=False)
    response = local_client.post(
        "/api/forms/materialize",
        files={"pdf": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        data={"fields": '[{"name":"f","x":1,"y":2,"width":3,"height":4}]'},
        headers=auth_headers,
    )

    assert response.status_code == 500
    cleanup_mock.assert_called_once()


def test_materialize_output_temp_create_failure_cleans_temp_files_immediately(
    app_main,
    base_user,
    mocker,
    auth_headers,
    tmp_path: Path,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    temp_pdf = tmp_path / "output-create-fail.pdf"
    temp_pdf.write_bytes(b"%PDF-1.4\nfake")
    mocker.patch.object(app_main, "_write_upload_to_temp", return_value=temp_pdf)
    mocker.patch.object(app_main.fitz, "open", return_value=_FakePdfDoc(page_count=1))
    mocker.patch.object(app_main, "_resolve_fillable_max_pages", return_value=10)
    cleanup_mock = mocker.patch.object(app_main, "_cleanup_paths", return_value=None)

    first_fd, first_name = app_main.tempfile.mkstemp(suffix=".json", dir=str(tmp_path))
    mocker.patch.object(
        app_main.tempfile,
        "mkstemp",
        side_effect=[(first_fd, first_name), OSError("no space left on device")],
    )

    from fastapi.testclient import TestClient

    local_client = TestClient(app_main.app, raise_server_exceptions=False)
    response = local_client.post(
        "/api/forms/materialize",
        files={"pdf": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        data={"fields": '[{"name":"f","x":1,"y":2,"width":3,"height":4}]'},
        headers=auth_headers,
    )

    assert response.status_code == 500
    cleanup_mock.assert_called_once()


def test_register_fillable_page_limit_and_success(client, app_main, base_user, mocker, auth_headers) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_legacy_endpoints_enabled", return_value=True)
    mocker.patch.object(app_main, "_read_upload_bytes", return_value=b"%PDF-1.4\n")
    mocker.patch.object(app_main, "_get_pdf_page_count", return_value=20)
    mocker.patch.object(app_main, "_resolve_fillable_max_pages", return_value=5)
    response = client.post(
        "/api/register-fillable",
        files={"pdf": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        headers=auth_headers,
    )
    assert response.status_code == 403

    mocker.patch.object(app_main, "_get_pdf_page_count", return_value=2)
    mocker.patch.object(app_main, "_store_session_entry", return_value=None)
    response = client.post(
        "/api/register-fillable",
        files={"pdf": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["success"] is True


def test_register_fillable_rejects_non_pdf_and_empty_upload(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_legacy_endpoints_enabled", return_value=True)

    not_pdf = client.post(
        "/api/register-fillable",
        files={"pdf": ("x.txt", b"hello", "text/plain")},
        headers=auth_headers,
    )
    assert not_pdf.status_code == 400
    assert "Only PDF uploads are supported" in not_pdf.text

    mocker.patch.object(app_main, "_read_upload_bytes", return_value=b"")
    empty_pdf = client.post(
        "/api/register-fillable",
        files={"pdf": ("x.pdf", b"", "application/pdf")},
        headers=auth_headers,
    )
    assert empty_pdf.status_code == 400
    assert "Uploaded file is empty" in empty_pdf.text


def test_legacy_download_stream_headers_and_missing_pdf_path(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_legacy_endpoints_enabled", return_value=True)
    mocker.patch.object(
        app_main,
        "_get_session_entry",
        return_value={"source_pdf": "saved.pdf", "pdf_bytes": None, "pdf_path": "gs://forms/saved.pdf"},
    )
    mocker.patch.object(app_main, "stream_pdf", return_value=io.BytesIO(b"%PDF-1.4\n"))
    response = client.get(
        "/download/sess-1",
        headers={**auth_headers, "Origin": "https://app.example.com"},
    )
    assert response.status_code == 200
    assert "saved.pdf" in response.headers["content-disposition"]

    mocker.patch.object(
        app_main,
        "_get_session_entry",
        return_value={"source_pdf": "saved.pdf", "pdf_bytes": None, "pdf_path": None},
    )
    response = client.get("/download/sess-1", headers=auth_headers)
    assert response.status_code == 404
    assert "Session PDF not found" in response.text


def test_legacy_download_missing_storage_blob_returns_404(
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_legacy_endpoints_enabled", return_value=True)
    mocker.patch.object(
        app_main,
        "_get_session_entry",
        return_value={"source_pdf": "saved.pdf", "pdf_bytes": None, "pdf_path": "gs://forms/missing.pdf"},
    )
    mocker.patch.object(app_main, "stream_pdf", side_effect=FileNotFoundError("missing blob"))

    from fastapi.testclient import TestClient

    local_client = TestClient(app_main.app, raise_server_exceptions=False)
    response = local_client.get("/download/sess-1", headers=auth_headers)

    assert response.status_code == 404
    assert "Session PDF not found" in response.text


# ---------------------------------------------------------------------------
# Edge-case: materialize_form with fields as dict payload (dict-wrapping path)
# ---------------------------------------------------------------------------
# When the fields form param is a JSON object (dict) with a "fields" key, the
# endpoint should unwrap it and process the inner list.  This tests the
# isinstance(raw_payload, dict) branch in materialize_form.
def test_materialize_form_dict_fields_payload(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
    tmp_path,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    temp_pdf = tmp_path / "dict_fields.pdf"
    temp_pdf.write_bytes(b"%PDF-1.4\nfake")
    mocker.patch.object(app_main, "_write_upload_to_temp", return_value=temp_pdf)
    mocker.patch.object(app_main.fitz, "open", return_value=_FakePdfDoc(page_count=1))
    mocker.patch.object(app_main, "_resolve_fillable_max_pages", return_value=10)

    def _inject(temp_path, template_path, output_path):
        output_path.write_bytes(b"%PDF-1.4\noutput")

    mocker.patch.object(app_main, "inject_fields", side_effect=_inject)

    # Pass fields as a dict wrapping the actual field list, which exercises the
    # isinstance(raw_payload, dict) branch.
    import json

    fields_dict = json.dumps({
        "fields": [{"name": "f", "x": 1, "y": 2, "width": 3, "height": 4}],
        "coordinateSystem": "originBottom",
    })
    response = client.post(
        "/api/forms/materialize",
        files={"pdf": ("form.pdf", b"%PDF-1.4\n", "application/pdf")},
        data={"fields": fields_dict},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert "-fillable" in response.headers["content-disposition"]
