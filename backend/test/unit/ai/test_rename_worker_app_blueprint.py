"""Unit tests for backend.ai.rename_worker_app."""

from __future__ import annotations

from fastapi.testclient import TestClient

import backend.ai.rename_worker_app as rename_worker


def _payload(**overrides):
    payload = {
        "jobId": "job-1",
        "requestId": "job-1",
        "sessionId": "sess-1",
        "userId": "user-1",
        "userRole": "base",
        "credits": 1,
        "creditsCharged": True,
    }
    payload.update(overrides)
    return payload


def test_rename_worker_completes_job_and_persists_session_updates(mocker) -> None:
    client = TestClient(rename_worker.app)
    mocker.patch.object(rename_worker, "_require_internal_auth", return_value={"sub": "task"})
    mocker.patch.object(
        rename_worker,
        "get_openai_job",
        return_value={
            "status": "queued",
            "user_id": "user-1",
            "request_id": "job-1",
        },
    )
    update_job_mock = mocker.patch.object(rename_worker, "update_openai_job", return_value=None)
    mocker.patch.object(
        rename_worker,
        "_get_session_entry",
        return_value={
            "pdf_bytes": b"%PDF-1.4\n",
            "fields": [{"name": "field_a", "type": "text", "page": 1, "rect": [1, 2, 3, 4]}],
            "source_pdf": "sample.pdf",
            "page_count": 1,
        },
    )
    mocker.patch.object(
        rename_worker,
        "run_openai_rename_on_pdf",
        return_value=(
            {"checkboxRules": []},
            [{"name": "first_name", "type": "text", "page": 1, "rect": [1, 2, 3, 4]}],
        ),
    )
    update_session_mock = mocker.patch.object(rename_worker, "_update_session_entry", return_value=None)

    response = client.post("/internal/rename", json=_payload())

    assert response.status_code == 200
    assert response.json()["status"] == "complete"
    assert update_session_mock.called
    statuses = [call.kwargs.get("status") for call in update_job_mock.call_args_list if "status" in call.kwargs]
    assert "running" in statuses
    assert "complete" in statuses


def test_rename_worker_refunds_credits_on_terminal_failure(mocker) -> None:
    client = TestClient(rename_worker.app)
    mocker.patch.object(rename_worker, "_require_internal_auth", return_value={"sub": "task"})
    mocker.patch.object(
        rename_worker,
        "get_openai_job",
        return_value={
            "status": "queued",
            "user_id": "user-1",
            "request_id": "job-1",
        },
    )
    mocker.patch.object(rename_worker, "update_openai_job", return_value=None)
    mocker.patch.object(rename_worker, "_get_session_entry", return_value={"pdf_bytes": None})
    refund_mock = mocker.patch.object(rename_worker, "refund_openai_credits", return_value=10)

    response = client.post("/internal/rename", json=_payload())

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "Session PDF not found" in response.json()["error"]
    refund_mock.assert_called_once_with("user-1", credits=1, role="base")


def test_rename_worker_treats_insufficient_quota_as_terminal_failure(mocker) -> None:
    class _QuotaError(Exception):
        code = "insufficient_quota"

    client = TestClient(rename_worker.app)
    mocker.patch.object(rename_worker, "_require_internal_auth", return_value={"sub": "task"})
    mocker.patch.object(
        rename_worker,
        "get_openai_job",
        return_value={
            "status": "queued",
            "user_id": "user-1",
            "request_id": "job-1",
        },
    )
    mocker.patch.object(
        rename_worker,
        "_get_session_entry",
        return_value={
            "pdf_bytes": b"%PDF-1.4\n",
            "fields": [{"name": "field_a", "type": "text", "page": 1, "rect": [1, 2, 3, 4]}],
            "source_pdf": "sample.pdf",
            "page_count": 1,
        },
    )
    mocker.patch.object(rename_worker, "run_openai_rename_on_pdf", side_effect=_QuotaError("quota"))
    refund_mock = mocker.patch.object(rename_worker, "refund_openai_credits", return_value=10)

    response = client.post("/internal/rename", json=_payload())

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "insufficient_quota" in response.json()["error"]
    refund_mock.assert_called_once_with("user-1", credits=1, role="base")
