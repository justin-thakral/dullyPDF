"""Route-level unit tests for `/internal/detect` in `backend/detector_main.py`."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import backend.detector_main as dm
from backend.detection_status import (
    DETECTION_STATUS_COMPLETE,
    DETECTION_STATUS_FAILED,
    DETECTION_STATUS_RUNNING,
)
from backend.pdf_validation import PdfValidationError


@pytest.fixture(autouse=True)
def _reset_detector_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "test")
    for key in ("DETECTOR_TASKS_MAX_ATTEMPTS", "DETECTOR_RETRY_AFTER_SECONDS"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def client() -> TestClient:
    return TestClient(dm.app)


@pytest.fixture
def detect_payload() -> dict[str, Any]:
    return {
        "sessionId": "sess_1",
        "pdfPath": "gs://bucket/forms/doc.pdf",
        "pipeline": "commonforms",
    }


def _metadata(pdf_path: str) -> dict[str, Any]:
    return {
        "user_id": "user_1",
        "source_pdf": "source.pdf",
        "pdf_path": pdf_path,
        "page_count": 8,
    }


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def _patch_request_setup(
    mocker,
    *,
    metadata: dict[str, Any] | None,
    gcs_path_ok: bool = True,
):
    auth = mocker.patch.object(dm, "_require_internal_auth", return_value={"sub": "task"})
    mocker.patch.object(dm, "is_gcs_path", return_value=gcs_path_ok)
    mocker.patch.object(dm, "get_session_metadata", return_value=metadata)
    upsert = mocker.patch.object(dm, "upsert_session_metadata")
    update = mocker.patch.object(dm, "update_detection_request")
    return auth, upsert, update


@pytest.mark.parametrize(
    ("status_code", "detail"),
    [
        (401, "Missing detector auth token"),
        (403, "Detector caller not allowed"),
    ],
)
def test_run_detection_re_raises_auth_failures(
    client: TestClient,
    mocker,
    detect_payload: dict[str, Any],
    status_code: int,
    detail: str,
) -> None:
    mocker.patch.object(
        dm,
        "_require_internal_auth",
        side_effect=HTTPException(status_code=status_code, detail=detail),
    )
    finish = mocker.patch.object(dm, "_finish_detection_failure")

    response = client.post("/internal/detect", json=detect_payload)

    assert response.status_code == status_code
    assert response.json() == {"detail": detail}
    finish.assert_not_called()


def test_run_detection_auth_success_path_calls_auth_guard_and_validates_pdf_path(
    client: TestClient,
    mocker,
    detect_payload: dict[str, Any],
) -> None:
    auth = mocker.patch.object(dm, "_require_internal_auth", return_value={"sub": "task"})
    mocker.patch.object(dm, "is_gcs_path", return_value=False)
    finish = mocker.patch.object(
        dm,
        "_finish_detection_failure",
        return_value={
            "sessionId": "sess_1",
            "status": DETECTION_STATUS_FAILED,
            "error": "Invalid PDF storage path",
        },
    )

    response = client.post(
        "/internal/detect",
        json=detect_payload,
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "sessionId": "sess_1",
        "status": DETECTION_STATUS_FAILED,
        "error": "Invalid PDF storage path",
    }
    auth.assert_called_once_with("Bearer valid-token")
    finish.assert_called_once_with("sess_1", "Invalid PDF storage path")


def test_run_detection_rejects_unsupported_pipeline(
    client: TestClient,
    mocker,
    detect_payload: dict[str, Any],
) -> None:
    _patch_request_setup(mocker, metadata=_metadata(detect_payload["pdfPath"]), gcs_path_ok=True)
    finish = mocker.patch.object(
        dm,
        "_finish_detection_failure",
        return_value={
            "sessionId": "sess_1",
            "status": DETECTION_STATUS_FAILED,
            "error": "Unsupported detection pipeline",
        },
    )

    response = client.post(
        "/internal/detect",
        json={**detect_payload, "pipeline": "legacy-opencv"},
    )

    assert response.status_code == 200
    assert response.json()["error"] == "Unsupported detection pipeline"
    finish.assert_called_once_with("sess_1", "Unsupported detection pipeline")


def test_run_detection_rejects_when_session_metadata_missing(
    client: TestClient,
    mocker,
    detect_payload: dict[str, Any],
) -> None:
    _patch_request_setup(mocker, metadata=None, gcs_path_ok=True)
    finish = mocker.patch.object(
        dm,
        "_finish_detection_failure",
        return_value={
            "sessionId": "sess_1",
            "status": DETECTION_STATUS_FAILED,
            "error": "Session metadata not found",
        },
    )

    response = client.post("/internal/detect", json=detect_payload)

    assert response.status_code == 200
    assert response.json()["error"] == "Session metadata not found"
    finish.assert_called_once_with("sess_1", "Session metadata not found")


def test_run_detection_rejects_when_session_pdf_path_mismatches(
    client: TestClient,
    mocker,
    detect_payload: dict[str, Any],
) -> None:
    _patch_request_setup(mocker, metadata=_metadata("gs://bucket/forms/other.pdf"), gcs_path_ok=True)
    finish = mocker.patch.object(
        dm,
        "_finish_detection_failure",
        return_value={
            "sessionId": "sess_1",
            "status": DETECTION_STATUS_FAILED,
            "error": "Session PDF path mismatch",
        },
    )

    response = client.post("/internal/detect", json=detect_payload)

    assert response.status_code == 200
    assert response.json()["error"] == "Session PDF path mismatch"
    finish.assert_called_once_with("sess_1", "Session PDF path mismatch")


def test_run_detection_success_persists_running_and_complete_states(
    client: TestClient,
    mocker,
    detect_payload: dict[str, Any],
) -> None:
    auth, upsert, update_detection = _patch_request_setup(
        mocker,
        metadata=_metadata(detect_payload["pdfPath"]),
        gcs_path_ok=True,
    )
    mocker.patch.object(dm, "download_pdf_bytes", return_value=b"%PDF-1.4\n")
    mocker.patch.object(
        dm,
        "preflight_pdf_bytes",
        return_value=SimpleNamespace(pdf_bytes=b"%PDF-1.4\nvalidated", was_decrypted=False, page_count=8),
    )
    mocker.patch.object(dm, "detect_commonforms_fields", return_value={"fields": [{"name": "A1"}, {"name": "A2"}]})
    update_session_entry = mocker.patch.object(dm, "update_session_entry")
    mocker.patch.object(dm, "now_iso", side_effect=["2026-02-11T00:00:00+00:00", "2026-02-11T00:00:05+00:00"])
    mocker.patch.object(
        dm,
        "time",
        SimpleNamespace(monotonic=mocker.Mock(side_effect=[100.0, 101.5])),
    )

    response = client.post("/internal/detect", json=detect_payload)

    assert response.status_code == 200
    assert response.json() == {
        "sessionId": "sess_1",
        "status": DETECTION_STATUS_COMPLETE,
        "fieldCount": 2,
    }
    auth.assert_called_once()
    upsert.assert_called_once_with(
        "sess_1",
        {
            "detection_status": DETECTION_STATUS_RUNNING,
            "detection_started_at": "2026-02-11T00:00:00+00:00",
            "detection_error": "",
        },
    )
    assert update_detection.call_count == 2
    assert update_detection.call_args_list[0].kwargs == {
        "request_id": "sess_1",
        "status": DETECTION_STATUS_RUNNING,
    }
    assert update_detection.call_args_list[1].kwargs == {
        "request_id": "sess_1",
        "status": DETECTION_STATUS_COMPLETE,
        "page_count": 8,
    }

    update_session_entry.assert_called_once()
    assert update_session_entry.call_args.kwargs == {
        "persist_fields": True,
        "persist_result": True,
    }
    assert update_session_entry.call_args.args[0] == "sess_1"
    entry = update_session_entry.call_args.args[1]
    assert entry["detection_status"] == DETECTION_STATUS_COMPLETE
    assert entry["pdf_path"] == "gs://bucket/forms/doc.pdf"
    assert entry["fields"] == [{"name": "A1"}, {"name": "A2"}]
    assert entry["result"]["pipeline"] == "commonforms"
    assert entry["detection_duration_seconds"] == pytest.approx(1.5)


def test_run_detection_logs_when_pdf_is_decrypted(
    client: TestClient,
    mocker,
    detect_payload: dict[str, Any],
) -> None:
    _patch_request_setup(mocker, metadata=_metadata(detect_payload["pdfPath"]), gcs_path_ok=True)
    mocker.patch.object(dm, "download_pdf_bytes", return_value=b"%PDF-1.4\n")
    mocker.patch.object(
        dm,
        "preflight_pdf_bytes",
        return_value=SimpleNamespace(pdf_bytes=b"%PDF-1.4\nvalidated", was_decrypted=True, page_count=8),
    )
    mocker.patch.object(dm, "detect_commonforms_fields", return_value={"fields": []})
    mocker.patch.object(dm, "update_session_entry")
    mocker.patch.object(dm, "now_iso", side_effect=["2026-02-11T00:00:00+00:00", "2026-02-11T00:00:05+00:00"])
    mocker.patch.object(
        dm,
        "time",
        SimpleNamespace(monotonic=mocker.Mock(side_effect=[10.0, 10.1])),
    )
    info_log = mocker.patch.object(dm.logger, "info")

    response = client.post("/internal/detect", json=detect_payload)

    assert response.status_code == 200
    assert any(
        "PDF decrypted with empty password." in str(call.args[0]) for call in info_log.call_args_list
    )


def test_run_detection_uses_payload_pdf_path_when_metadata_pdf_path_missing(
    client: TestClient,
    mocker,
    detect_payload: dict[str, Any],
) -> None:
    metadata_without_pdf_path = {
        "user_id": "user_1",
        "source_pdf": "source.pdf",
        "page_count": 8,
    }
    _patch_request_setup(mocker, metadata=metadata_without_pdf_path, gcs_path_ok=True)
    mocker.patch.object(dm, "download_pdf_bytes", return_value=b"%PDF-1.4\n")
    mocker.patch.object(
        dm,
        "preflight_pdf_bytes",
        return_value=SimpleNamespace(pdf_bytes=b"%PDF-1.4\nvalidated", was_decrypted=False, page_count=8),
    )
    mocker.patch.object(dm, "detect_commonforms_fields", return_value={"fields": []})
    update_session_entry = mocker.patch.object(dm, "update_session_entry")
    mocker.patch.object(dm, "now_iso", side_effect=["2026-02-11T00:00:00+00:00", "2026-02-11T00:00:05+00:00"])
    mocker.patch.object(
        dm,
        "time",
        SimpleNamespace(monotonic=mocker.Mock(side_effect=[20.0, 20.2])),
    )

    response = client.post("/internal/detect", json=detect_payload)

    assert response.status_code == 200
    entry = update_session_entry.call_args.args[1]
    assert entry["pdf_path"] == detect_payload["pdfPath"]


def test_run_detection_finalizes_failed_status_on_pdf_validation_error(
    client: TestClient,
    mocker,
    detect_payload: dict[str, Any],
) -> None:
    _patch_request_setup(mocker, metadata=_metadata(detect_payload["pdfPath"]), gcs_path_ok=True)
    mocker.patch.object(dm, "download_pdf_bytes", return_value=b"%PDF-1.4\n")
    mocker.patch.object(
        dm,
        "preflight_pdf_bytes",
        side_effect=PdfValidationError("PDF is encrypted and cannot be processed"),
    )
    finish = mocker.patch.object(
        dm,
        "_finish_detection_failure",
        return_value={
            "sessionId": "sess_1",
            "status": DETECTION_STATUS_FAILED,
            "error": "PDF is encrypted and cannot be processed",
        },
    )

    response = client.post("/internal/detect", json=detect_payload)

    assert response.status_code == 200
    assert response.json()["error"] == "PDF is encrypted and cannot be processed"
    finish.assert_called_once_with("sess_1", "PDF is encrypted and cannot be processed")


def test_run_detection_finalizes_http_exception_from_inner_pipeline_block(
    client: TestClient,
    mocker,
    detect_payload: dict[str, Any],
) -> None:
    _patch_request_setup(mocker, metadata=_metadata(detect_payload["pdfPath"]), gcs_path_ok=True)
    mocker.patch.object(dm, "download_pdf_bytes", return_value=b"%PDF-1.4\n")
    mocker.patch.object(
        dm,
        "preflight_pdf_bytes",
        return_value=SimpleNamespace(pdf_bytes=b"%PDF-1.4\nvalidated", was_decrypted=False, page_count=8),
    )
    mocker.patch.object(
        dm,
        "detect_commonforms_fields",
        side_effect=HTTPException(status_code=409, detail={"reason": "conflict"}),
    )
    finish = mocker.patch.object(
        dm,
        "_finish_detection_failure",
        return_value={
            "sessionId": "sess_1",
            "status": DETECTION_STATUS_FAILED,
            "error": "Detector request rejected",
        },
    )

    response = client.post("/internal/detect", json=detect_payload)

    assert response.status_code == 200
    assert response.json() == {
        "sessionId": "sess_1",
        "status": DETECTION_STATUS_FAILED,
        "error": "Detector request rejected",
    }
    finish.assert_called_once_with("sess_1", "Detector request rejected")


@pytest.mark.parametrize("retry_header", [None, "bad-value"])
def test_run_detection_returns_retryable_500_until_final_attempt(
    client: TestClient,
    mocker,
    monkeypatch: pytest.MonkeyPatch,
    detect_payload: dict[str, Any],
    retry_header: str | None,
) -> None:
    _patch_request_setup(mocker, metadata=_metadata(detect_payload["pdfPath"]), gcs_path_ok=True)
    mocker.patch.object(dm, "download_pdf_bytes", return_value=b"%PDF-1.4\n")
    mocker.patch.object(
        dm,
        "preflight_pdf_bytes",
        return_value=SimpleNamespace(pdf_bytes=b"%PDF-1.4\nvalidated", was_decrypted=False, page_count=8),
    )
    mocker.patch.object(dm, "detect_commonforms_fields", side_effect=RuntimeError("boom"))
    finish = mocker.patch.object(dm, "_finish_detection_failure")
    monkeypatch.setenv("DETECTOR_TASKS_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("DETECTOR_RETRY_AFTER_SECONDS", "9")

    headers = {}
    if retry_header is not None:
        headers["X-CloudTasks-TaskRetryCount"] = retry_header
    response = client.post("/internal/detect", json=detect_payload, headers=headers)

    assert response.status_code == 500
    assert response.json() == {"detail": "Detector failed; retrying"}
    assert response.headers.get("x-dully-retry") == "true"
    assert response.headers.get("retry-after") == "9"
    finish.assert_not_called()


def test_run_detection_finalizes_terminal_failure_when_retry_limit_reached(
    client: TestClient,
    mocker,
    monkeypatch: pytest.MonkeyPatch,
    detect_payload: dict[str, Any],
) -> None:
    _patch_request_setup(mocker, metadata=_metadata(detect_payload["pdfPath"]), gcs_path_ok=True)
    mocker.patch.object(dm, "download_pdf_bytes", return_value=b"%PDF-1.4\n")
    mocker.patch.object(
        dm,
        "preflight_pdf_bytes",
        return_value=SimpleNamespace(pdf_bytes=b"%PDF-1.4\nvalidated", was_decrypted=False, page_count=8),
    )
    mocker.patch.object(dm, "detect_commonforms_fields", side_effect=RuntimeError("boom"))
    monkeypatch.setenv("DETECTOR_TASKS_MAX_ATTEMPTS", "3")
    finish = mocker.patch.object(
        dm,
        "_finish_detection_failure",
        return_value={
            "sessionId": "sess_1",
            "status": DETECTION_STATUS_FAILED,
            "error": "Detector failed after 3 attempts: boom",
        },
    )

    response = client.post(
        "/internal/detect",
        json=detect_payload,
        headers={"X-CloudTasks-TaskRetryCount": "2"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "sessionId": "sess_1",
        "status": DETECTION_STATUS_FAILED,
        "error": "Detector failed after 3 attempts: boom",
    }
    finish.assert_called_once_with("sess_1", "Detector failed after 3 attempts: boom")


# --- Edge case tests ---


def test_run_detection_handles_missing_fields_key_in_result(
    client: TestClient,
    mocker,
    detect_payload: dict[str, Any],
) -> None:
    """When detect_commonforms_fields returns a dict without "fields" key,
    it should default to [] and fieldCount should be 0 (line 206)."""
    _patch_request_setup(mocker, metadata=_metadata(detect_payload["pdfPath"]), gcs_path_ok=True)
    mocker.patch.object(dm, "download_pdf_bytes", return_value=b"%PDF-1.4\n")
    mocker.patch.object(
        dm,
        "preflight_pdf_bytes",
        return_value=SimpleNamespace(pdf_bytes=b"%PDF-1.4\n", was_decrypted=False, page_count=1),
    )
    # Return empty dict with no "fields" key
    mocker.patch.object(dm, "detect_commonforms_fields", return_value={})
    mocker.patch.object(dm, "update_session_entry")
    mocker.patch.object(dm, "now_iso", side_effect=["t1", "t2"])
    mocker.patch.object(
        dm, "time", SimpleNamespace(monotonic=mocker.Mock(side_effect=[0.0, 0.5])),
    )

    response = client.post("/internal/detect", json=detect_payload)

    assert response.status_code == 200
    assert response.json()["fieldCount"] == 0


def test_run_detection_retries_on_download_failure_without_max_attempts(
    client: TestClient,
    mocker,
    detect_payload: dict[str, Any],
) -> None:
    """When download_pdf_bytes raises and DETECTOR_TASKS_MAX_ATTEMPTS is not set,
    _should_finalize_failure returns False so every failure returns 500 for retry."""
    _patch_request_setup(mocker, metadata=_metadata(detect_payload["pdfPath"]), gcs_path_ok=True)
    mocker.patch.object(
        dm, "download_pdf_bytes", side_effect=ConnectionError("GCS unreachable")
    )
    finish = mocker.patch.object(dm, "_finish_detection_failure")

    response = client.post("/internal/detect", json=detect_payload)

    assert response.status_code == 500
    assert response.json()["detail"] == "Detector failed; retrying"
    finish.assert_not_called()


def test_run_detection_finalizes_download_failure_when_max_attempts_reached(
    client: TestClient,
    mocker,
    monkeypatch: pytest.MonkeyPatch,
    detect_payload: dict[str, Any],
) -> None:
    """download_pdf_bytes failure at the final retry should finalize as failed."""
    _patch_request_setup(mocker, metadata=_metadata(detect_payload["pdfPath"]), gcs_path_ok=True)
    mocker.patch.object(
        dm, "download_pdf_bytes", side_effect=ConnectionError("GCS unreachable")
    )
    monkeypatch.setenv("DETECTOR_TASKS_MAX_ATTEMPTS", "2")
    finish = mocker.patch.object(
        dm,
        "_finish_detection_failure",
        return_value={
            "sessionId": "sess_1",
            "status": DETECTION_STATUS_FAILED,
            "error": "Detector failed after 2 attempts: GCS unreachable",
        },
    )

    response = client.post(
        "/internal/detect",
        json=detect_payload,
        headers={"X-CloudTasks-TaskRetryCount": "1"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == DETECTION_STATUS_FAILED
    finish.assert_called_once()


def test_run_detection_inner_http_exception_with_string_detail(
    client: TestClient,
    mocker,
    detect_payload: dict[str, Any],
) -> None:
    """When the inner pipeline raises HTTPException with a plain string detail,
    that string should be passed directly (not the fallback 'Detector request rejected')."""
    _patch_request_setup(mocker, metadata=_metadata(detect_payload["pdfPath"]), gcs_path_ok=True)
    mocker.patch.object(dm, "download_pdf_bytes", return_value=b"%PDF-1.4\n")
    mocker.patch.object(
        dm,
        "preflight_pdf_bytes",
        return_value=SimpleNamespace(pdf_bytes=b"%PDF-1.4\n", was_decrypted=False, page_count=1),
    )
    mocker.patch.object(
        dm,
        "detect_commonforms_fields",
        side_effect=HTTPException(status_code=500, detail="Model loading failed"),
    )
    finish = mocker.patch.object(
        dm,
        "_finish_detection_failure",
        return_value={
            "sessionId": "sess_1",
            "status": DETECTION_STATUS_FAILED,
            "error": "Model loading failed",
        },
    )

    response = client.post("/internal/detect", json=detect_payload)

    assert response.status_code == 200
    finish.assert_called_once_with("sess_1", "Model loading failed")
