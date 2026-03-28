import io

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from backend.detection.status import (
    DETECTION_STATUS_COMPLETE,
    DETECTION_STATUS_FAILED,
    DETECTION_STATUS_QUEUED,
)
from backend.detection.pdf_validation import PdfValidationResult


def _patch_detect_auth(mocker, app_main, user):
    mocker.patch.object(app_main, "_verify_token", return_value={"uid": user.app_user_id})
    mocker.patch.object(app_main, "ensure_user", return_value=user)
    mocker.patch.object(app_main, "check_rate_limit", return_value=True)


def test_detect_fields_requires_auth_unless_admin_override(client, app_main, base_user, mocker) -> None:
    mocker.patch.object(app_main, "_has_admin_override", return_value=False)
    mocker.patch.object(app_main, "_verify_token", side_effect=HTTPException(status_code=401, detail="Missing Authorization token"))
    response = client.post("/detect-fields", files={"file": ("x.pdf", b"%PDF-1.4\n", "application/pdf")})
    assert response.status_code == 401

    # Admin override bypasses auth/user sync and still processes detection.
    mocker.patch.object(app_main, "_has_admin_override", return_value=True)
    mocker.patch.object(app_main, "_read_upload_bytes", return_value=b"%PDF-1.4\n")
    mocker.patch.object(
        app_main,
        "_validate_pdf_for_detection",
        return_value=PdfValidationResult(pdf_bytes=b"%PDF-1.4\n", page_count=1, was_decrypted=False),
    )
    mocker.patch.object(app_main, "_resolve_detection_mode", return_value="tasks")
    enqueue_mock = mocker.patch.object(
        app_main,
        "_enqueue_detection_job",
        return_value={"sessionId": "sess-admin", "status": DETECTION_STATUS_QUEUED, "pipeline": "commonforms"},
    )
    response = client.post(
        "/detect-fields",
        files={"file": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        headers={"x-admin-token": "admin"},
    )
    assert response.status_code == 200
    assert response.json()["sessionId"] == "sess-admin"
    assert enqueue_mock.call_args.args[2] is None


def test_detect_fields_validates_upload_and_pipeline(client, app_main, base_user, mocker, auth_headers) -> None:
    _patch_detect_auth(mocker, app_main, base_user)
    response = client.post(
        "/detect-fields",
        files={"file": ("x.txt", b"hello", "text/plain")},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "Only PDF uploads" in response.text

    mocker.patch.object(app_main, "_read_upload_bytes", return_value=b"")
    response = client.post(
        "/detect-fields",
        files={"file": ("x.pdf", b"", "application/pdf")},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "Uploaded file is empty" in response.text

    mocker.patch.object(app_main, "_read_upload_bytes", return_value=b"%PDF-1.4\n")
    mocker.patch.object(
        app_main,
        "_validate_pdf_for_detection",
        return_value=PdfValidationResult(pdf_bytes=b"%PDF-1.4\n", page_count=1, was_decrypted=False),
    )
    response = client.post(
        "/detect-fields",
        data={"pipeline": "legacy"},
        files={"file": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "Unsupported pipeline selection" in response.text


def test_detect_fields_enforces_page_limit_and_local_enqueue(client, app_main, base_user, mocker, auth_headers) -> None:
    _patch_detect_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_read_upload_bytes", return_value=b"%PDF-1.4\n")
    mocker.patch.object(
        app_main,
        "_validate_pdf_for_detection",
        return_value=PdfValidationResult(pdf_bytes=b"%PDF-1.4\n", page_count=10, was_decrypted=False),
    )
    mocker.patch.object(app_main, "_resolve_detect_max_pages", return_value=2)
    response = client.post(
        "/detect-fields",
        files={"file": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        headers=auth_headers,
    )
    assert response.status_code == 403
    assert "Detection limited to 2 pages" in response.text

    mocker.patch.object(
        app_main,
        "_validate_pdf_for_detection",
        return_value=PdfValidationResult(pdf_bytes=b"%PDF-1.4\n", page_count=1, was_decrypted=False),
    )
    mocker.patch.object(app_main, "_resolve_detect_max_pages", return_value=5)
    mocker.patch.object(app_main, "_resolve_detection_mode", return_value="local")
    enqueue_mock = mocker.patch.object(
        app_main,
        "_enqueue_local_detection_job",
        return_value={"sessionId": "sess-local", "status": DETECTION_STATUS_QUEUED, "pipeline": "commonforms"},
    )
    response = client.post(
        "/detect-fields",
        files={"file": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == DETECTION_STATUS_QUEUED
    assert enqueue_mock.call_args.kwargs["page_count"] == 1


def test_detect_fields_tasks_mode_enqueue_path(client, app_main, base_user, mocker, auth_headers) -> None:
    _patch_detect_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_read_upload_bytes", return_value=b"%PDF-1.4\n")
    mocker.patch.object(
        app_main,
        "_validate_pdf_for_detection",
        return_value=PdfValidationResult(pdf_bytes=b"%PDF-1.4\n", page_count=1, was_decrypted=False),
    )
    mocker.patch.object(app_main, "_resolve_detect_max_pages", return_value=10)
    mocker.patch.object(app_main, "_resolve_detection_mode", return_value="tasks")
    mocker.patch.object(
        app_main,
        "_enqueue_detection_job",
        return_value={"sessionId": "sess-q", "status": DETECTION_STATUS_QUEUED, "pipeline": "commonforms"},
    )
    response = client.post(
        "/detect-fields",
        files={"file": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == DETECTION_STATUS_QUEUED


def test_detect_fields_passes_openai_prewarm_flags_to_enqueue(client, app_main, base_user, mocker, auth_headers) -> None:
    _patch_detect_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_read_upload_bytes", return_value=b"%PDF-1.4\n")
    mocker.patch.object(
        app_main,
        "_validate_pdf_for_detection",
        return_value=PdfValidationResult(pdf_bytes=b"%PDF-1.4\n", page_count=4, was_decrypted=False),
    )
    mocker.patch.object(app_main, "_resolve_detect_max_pages", return_value=10)
    mocker.patch.object(app_main, "_resolve_detection_mode", return_value="tasks")
    enqueue_mock = mocker.patch.object(
        app_main,
        "_enqueue_detection_job",
        return_value={"sessionId": "sess-q", "status": DETECTION_STATUS_QUEUED, "pipeline": "commonforms"},
    )

    response = client.post(
        "/detect-fields",
        data={"prewarmRename": "true", "prewarmRemap": "true"},
        files={"file": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert enqueue_mock.call_args.kwargs["prewarm_rename"] is True
    assert enqueue_mock.call_args.kwargs["prewarm_remap"] is True


def test_detect_fields_defaults_openai_prewarm_flags_to_false(client, app_main, base_user, mocker, auth_headers) -> None:
    _patch_detect_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_read_upload_bytes", return_value=b"%PDF-1.4\n")
    mocker.patch.object(
        app_main,
        "_validate_pdf_for_detection",
        return_value=PdfValidationResult(pdf_bytes=b"%PDF-1.4\n", page_count=4, was_decrypted=False),
    )
    mocker.patch.object(app_main, "_resolve_detect_max_pages", return_value=10)
    mocker.patch.object(app_main, "_resolve_detection_mode", return_value="tasks")
    enqueue_mock = mocker.patch.object(
        app_main,
        "_enqueue_detection_job",
        return_value={"sessionId": "sess-q", "status": DETECTION_STATUS_QUEUED, "pipeline": "commonforms"},
    )

    response = client.post(
        "/detect-fields",
        files={"file": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert enqueue_mock.call_args.kwargs["prewarm_rename"] is False
    assert enqueue_mock.call_args.kwargs["prewarm_remap"] is False


def test_detect_fields_rate_limit_env_fallback_defaults_on_invalid_values(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
    monkeypatch,
) -> None:
    _patch_detect_auth(mocker, app_main, base_user)
    check_rate_limit_mock = mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "_read_upload_bytes", return_value=b"%PDF-1.4\n")
    mocker.patch.object(
        app_main,
        "_validate_pdf_for_detection",
        return_value=PdfValidationResult(pdf_bytes=b"%PDF-1.4\n", page_count=1, was_decrypted=False),
    )
    mocker.patch.object(app_main, "_resolve_detect_max_pages", return_value=10)
    mocker.patch.object(app_main, "_resolve_detection_mode", return_value="tasks")
    mocker.patch.object(
        app_main,
        "_enqueue_detection_job",
        return_value={"sessionId": "sess-q", "status": DETECTION_STATUS_QUEUED, "pipeline": "commonforms"},
    )
    monkeypatch.setenv("SANDBOX_DETECT_RATE_LIMIT_WINDOW_SECONDS", "not-a-number")
    monkeypatch.setenv("SANDBOX_DETECT_RATE_LIMIT_PER_USER", "also-bad")

    response = client.post(
        "/detect-fields",
        files={"file": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert check_rate_limit_mock.called
    assert check_rate_limit_mock.call_args.kwargs["window_seconds"] == 30
    assert check_rate_limit_mock.call_args.kwargs["limit"] == 6
    assert check_rate_limit_mock.call_args.kwargs["fail_closed"] is True


def test_detect_fields_rate_limit_env_negative_values_fallback_to_safe_defaults(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
    monkeypatch,
) -> None:
    _patch_detect_auth(mocker, app_main, base_user)
    check_rate_limit_mock = mocker.patch.object(app_main, "check_rate_limit", return_value=True)
    mocker.patch.object(app_main, "_read_upload_bytes", return_value=b"%PDF-1.4\n")
    mocker.patch.object(
        app_main,
        "_validate_pdf_for_detection",
        return_value=PdfValidationResult(pdf_bytes=b"%PDF-1.4\n", page_count=1, was_decrypted=False),
    )
    mocker.patch.object(app_main, "_resolve_detect_max_pages", return_value=10)
    mocker.patch.object(app_main, "_resolve_detection_mode", return_value="tasks")
    mocker.patch.object(
        app_main,
        "_enqueue_detection_job",
        return_value={"sessionId": "sess-q", "status": DETECTION_STATUS_QUEUED, "pipeline": "commonforms"},
    )
    monkeypatch.setenv("SANDBOX_DETECT_RATE_LIMIT_WINDOW_SECONDS", "-30")
    monkeypatch.setenv("SANDBOX_DETECT_RATE_LIMIT_PER_USER", "-1")

    response = client.post(
        "/detect-fields",
        files={"file": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert check_rate_limit_mock.called
    assert check_rate_limit_mock.call_args.kwargs["window_seconds"] == 30
    assert check_rate_limit_mock.call_args.kwargs["limit"] == 6
    assert check_rate_limit_mock.call_args.kwargs["fail_closed"] is True


def test_enqueue_detection_job_failure_marks_session_failed(app_main, base_user, mocker) -> None:
    mocker.patch.object(app_main.uuid, "uuid4", return_value=type("_U", (), {"__str__": lambda self: "sess-fail"})())
    mocker.patch.object(app_main, "resolve_detector_profile", return_value="light")
    mocker.patch.object(app_main, "resolve_detector_target", return_value="gpu")
    mocker.patch.object(
        app_main,
        "resolve_task_config",
        return_value={"profile": "light", "target": "gpu", "queue": "q", "service_url": "https://svc"},
    )

    def _store(session_id, entry, **kwargs):
        entry["pdf_path"] = "gs://bucket/path.pdf"

    mocker.patch.object(app_main, "_store_session_entry", side_effect=_store)
    mocker.patch.object(app_main, "record_detection_request", return_value=None)
    mocker.patch.object(app_main, "enqueue_detection_task", side_effect=RuntimeError("queue down"))
    update_session_mock = mocker.patch.object(app_main, "_update_session_entry", return_value=None)
    update_req_mock = mocker.patch.object(app_main, "update_detection_request", return_value=None)

    with pytest.raises(HTTPException) as ctx:
        app_main._enqueue_detection_job(b"%PDF", "sample.pdf", base_user, page_count=1)
    assert ctx.value.status_code == 500
    assert update_session_mock.called
    assert update_req_mock.call_args.kwargs["status"] == DETECTION_STATUS_FAILED


def test_enqueue_detection_job_raises_when_pdf_path_missing(app_main, base_user, mocker) -> None:
    mocker.patch.object(app_main.uuid, "uuid4", return_value=type("_U", (), {"__str__": lambda self: "sess-missing-path"})())
    mocker.patch.object(app_main, "resolve_detector_profile", return_value="light")
    mocker.patch.object(app_main, "resolve_detector_target", return_value="gpu")
    mocker.patch.object(
        app_main,
        "resolve_task_config",
        return_value={"profile": "light", "target": "gpu", "queue": "q", "service_url": "https://svc"},
    )
    mocker.patch.object(app_main, "_store_session_entry", return_value=None)
    record_mock = mocker.patch.object(app_main, "record_detection_request", return_value=None)

    with pytest.raises(HTTPException) as ctx:
        app_main._enqueue_detection_job(b"%PDF", "sample.pdf", base_user, page_count=1)
    assert ctx.value.status_code == 500
    assert "Session PDF storage failed" in str(ctx.value.detail)
    record_mock.assert_not_called()


def test_get_detection_status_ownership_and_transitions(client, app_main, base_user, mocker, auth_headers) -> None:
    _patch_detect_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_has_admin_override", return_value=False)
    mocker.patch.object(app_main, "get_session_metadata", return_value=None)
    response = client.get("/detect-fields/sess-1", headers=auth_headers)
    assert response.status_code == 404

    mocker.patch.object(app_main, "get_session_metadata", return_value={"user_id": "other"})
    response = client.get("/detect-fields/sess-1", headers=auth_headers)
    assert response.status_code == 403

    mocker.patch.object(
        app_main,
        "get_session_metadata",
        return_value={"user_id": base_user.app_user_id, "detection_status": DETECTION_STATUS_FAILED, "detection_error": "boom"},
    )
    response = client.get("/detect-fields/sess-1", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] == DETECTION_STATUS_FAILED
    assert response.json()["error"] == "Detection failed. Please retry the upload."

    mocker.patch.object(
        app_main,
        "get_session_metadata",
        return_value={
            "user_id": base_user.app_user_id,
            "detection_status": DETECTION_STATUS_COMPLETE,
            "fields_path": "gs://bucket/fields.json",
            "result_path": "gs://bucket/result.json",
        },
    )
    mocker.patch.object(app_main, "download_session_json", side_effect=[[{"name": "f1"}], {"pipeline": "commonforms"}])
    response = client.get("/detect-fields/sess-1", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["fieldCount"] == 1
    assert response.json()["fields"] == [{"name": "f1"}]


def test_legacy_detection_routes_and_hidden_when_disabled(client, app_main, base_user, mocker, auth_headers) -> None:
    _patch_detect_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_legacy_endpoints_enabled", return_value=False)
    response = client.post("/api/process-pdf", files={"pdf": ("x.pdf", b"%PDF-1.4\n", "application/pdf")}, headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "Not found"

    mocker.patch.object(app_main, "_legacy_endpoints_enabled", return_value=True)
    mocker.patch.object(app_main, "_read_upload_bytes", return_value=b"%PDF-1.4\n")
    mocker.patch.object(
        app_main,
        "_validate_pdf_for_detection",
        return_value=PdfValidationResult(pdf_bytes=b"%PDF-1.4\n", page_count=1, was_decrypted=False),
    )
    mocker.patch.object(app_main, "_resolve_detect_max_pages", return_value=10)
    mocker.patch.object(app_main, "_resolve_detection_mode", return_value="local")
    mocker.patch.object(
        app_main,
        "_enqueue_local_detection_job",
        return_value={"sessionId": "legacy-sess", "status": DETECTION_STATUS_QUEUED, "pipeline": "commonforms"},
    )

    response = client.post("/api/process-pdf", files={"pdf": ("x.pdf", b"%PDF-1.4\n", "application/pdf")}, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] == DETECTION_STATUS_QUEUED

    mocker.patch.object(app_main, "_get_session_entry", return_value={"fields": [{"name": "f1"}], "detection_status": DETECTION_STATUS_COMPLETE})
    response = client.get("/api/detected-fields", params={"sessionId": "legacy-sess"}, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["total"] == 1


def test_detect_fields_maps_user_sync_failure_and_unknown_detection_mode(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    mocker.patch.object(app_main, "_has_admin_override", return_value=False)
    mocker.patch.object(app_main, "_verify_token", return_value={"uid": base_user.app_user_id})
    mocker.patch.object(app_main, "ensure_user", side_effect=RuntimeError("sync failed"))
    response = client.post(
        "/detect-fields",
        files={"file": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        headers=auth_headers,
    )
    assert response.status_code == 500
    assert "Failed to synchronize user profile" in response.text

    _patch_detect_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_read_upload_bytes", return_value=b"%PDF-1.4\n")
    mocker.patch.object(
        app_main,
        "_validate_pdf_for_detection",
        return_value=PdfValidationResult(pdf_bytes=b"%PDF-1.4\n", page_count=1, was_decrypted=False),
    )
    mocker.patch.object(app_main, "_resolve_detect_max_pages", return_value=10)
    mocker.patch.object(app_main, "_resolve_detection_mode", return_value="mystery-mode")
    response = client.post(
        "/detect-fields",
        files={"file": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        headers=auth_headers,
    )
    assert response.status_code == 500
    assert "Unsupported detection mode: mystery-mode" in response.text


def test_get_detection_status_infers_missing_status_and_skips_download_when_not_complete(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_detect_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_has_admin_override", return_value=False)
    mocker.patch.object(
        app_main,
        "get_session_metadata",
        side_effect=[
            {
                "user_id": base_user.app_user_id,
                "detection_status": None,
                "fields_path": "gs://bucket/fields.json",
                "result_path": None,
            },
            {
                "user_id": base_user.app_user_id,
                "detection_status": DETECTION_STATUS_QUEUED,
                "fields_path": "gs://bucket/fields.json",
            },
        ],
    )
    download_mock = mocker.patch.object(app_main, "download_session_json", return_value=[{"name": "f1"}])

    inferred = client.get("/detect-fields/sess-1", headers=auth_headers)
    assert inferred.status_code == 200
    assert inferred.json()["status"] == DETECTION_STATUS_COMPLETE
    assert inferred.json()["fieldCount"] == 1
    assert inferred.json()["fields"] == [{"name": "f1"}]
    assert "result" not in inferred.json()

    queued = client.get("/detect-fields/sess-1", headers=auth_headers)
    assert queued.status_code == 200
    assert queued.json()["status"] == DETECTION_STATUS_QUEUED
    assert "fields" not in queued.json()
    assert "result" not in queued.json()
    assert download_mock.call_count == 1


def test_get_detection_status_denies_ownerless_session(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_detect_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_has_admin_override", return_value=False)
    mocker.patch.object(
        app_main,
        "get_session_metadata",
        return_value={
            "user_id": None,
            "detection_status": DETECTION_STATUS_QUEUED,
        },
    )

    response = client.get("/detect-fields/sess-ownerless", headers=auth_headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "Session access denied"


# ---------------------------------------------------------------------------
# Edge-case: detection status should return 404 when complete-session artifacts
# are missing from storage rather than bubbling an internal 500.
# ---------------------------------------------------------------------------
def test_get_detection_status_missing_artifacts_returns_404(
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_detect_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "_has_admin_override", return_value=False)
    mocker.patch.object(
        app_main,
        "get_session_metadata",
        return_value={
            "user_id": base_user.app_user_id,
            "detection_status": DETECTION_STATUS_COMPLETE,
            "fields_path": "gs://bucket/missing-fields.json",
            "result_path": "gs://bucket/missing-result.json",
        },
    )
    mocker.patch.object(app_main, "download_session_json", side_effect=FileNotFoundError("missing blob"))

    local_client = TestClient(app_main.app, raise_server_exceptions=False)
    response = local_client.get("/detect-fields/sess-missing-artifacts", headers=auth_headers)

    assert response.status_code == 404
    assert "Session data not found" in response.text
