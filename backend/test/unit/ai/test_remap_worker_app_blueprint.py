"""Unit tests for backend.ai.remap_worker_app."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

import backend.ai.remap_worker_app as remap_worker


def _payload(**overrides):
    payload = {
        "jobId": "job-1",
        "requestId": "job-1",
        "schemaId": "schema-1",
        "sessionId": "sess-1",
        "templateFields": [
            {
                "name": "A1",
                "type": "text",
                "page": 1,
                "rect": {"x": 1, "y": 2, "width": 30, "height": 12},
            }
        ],
        "userId": "user-1",
        "userRole": "base",
        "credits": 1,
        "creditsCharged": True,
    }
    payload.update(overrides)
    return payload


def test_remap_worker_completes_job_and_persists_checkbox_outputs(mocker) -> None:
    client = TestClient(remap_worker.app)
    mocker.patch.object(remap_worker, "_require_internal_auth", return_value={"sub": "task"})
    mocker.patch.object(
        remap_worker,
        "get_openai_job",
        return_value={
            "status": "queued",
            "user_id": "user-1",
            "request_id": "job-1",
        },
    )
    update_job_mock = mocker.patch.object(remap_worker, "update_openai_job", return_value=None)
    mocker.patch.object(
        remap_worker,
        "get_schema",
        return_value=SimpleNamespace(id="schema-1", fields=[{"name": "first_name", "type": "string"}]),
    )
    mocker.patch.object(
        remap_worker,
        "build_allowlist_payload",
        return_value={
            "schemaFields": [{"name": "first_name", "type": "string"}],
            "templateTags": [{"tag": "A1"}],
        },
    )
    mocker.patch.object(remap_worker, "_get_session_entry", return_value={"user_id": "user-1"})
    mocker.patch.object(remap_worker, "call_openai_schema_mapping_chunked", return_value={"mappings": []})
    mocker.patch.object(
        remap_worker,
        "build_schema_mapping_payload",
        return_value={
            "mappings": [{"databaseField": "first_name", "pdfField": "first_name"}],
            "checkboxRules": [{"groupKey": "consent"}],
            "checkboxHints": [{"groupKey": "consent"}],
        },
    )
    update_session_mock = mocker.patch.object(remap_worker, "_update_session_entry", return_value=None)

    response = client.post("/internal/remap", json=_payload())

    assert response.status_code == 200
    assert response.json()["status"] == "complete"
    assert update_session_mock.called
    statuses = [call.kwargs.get("status") for call in update_job_mock.call_args_list if "status" in call.kwargs]
    assert "running" in statuses
    assert "complete" in statuses


def test_remap_worker_refunds_credits_when_schema_is_missing(mocker) -> None:
    client = TestClient(remap_worker.app)
    mocker.patch.object(remap_worker, "_require_internal_auth", return_value={"sub": "task"})
    mocker.patch.object(
        remap_worker,
        "get_openai_job",
        return_value={
            "status": "queued",
            "user_id": "user-1",
            "request_id": "job-1",
        },
    )
    mocker.patch.object(remap_worker, "update_openai_job", return_value=None)
    mocker.patch.object(remap_worker, "get_schema", return_value=None)
    refund_mock = mocker.patch.object(remap_worker, "refund_openai_credits", return_value=10)

    response = client.post("/internal/remap", json=_payload())

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "Schema not found" in response.json()["error"]
    refund_mock.assert_called_once_with("user-1", credits=1, role="base")


def test_remap_worker_treats_insufficient_quota_as_terminal_failure(mocker) -> None:
    class _QuotaError(Exception):
        code = "insufficient_quota"

    client = TestClient(remap_worker.app)
    mocker.patch.object(remap_worker, "_require_internal_auth", return_value={"sub": "task"})
    mocker.patch.object(
        remap_worker,
        "get_openai_job",
        return_value={
            "status": "queued",
            "user_id": "user-1",
            "request_id": "job-1",
        },
    )
    mocker.patch.object(
        remap_worker,
        "get_schema",
        return_value=SimpleNamespace(id="schema-1", fields=[{"name": "first_name", "type": "string"}]),
    )
    mocker.patch.object(
        remap_worker,
        "build_allowlist_payload",
        return_value={
            "schemaFields": [{"name": "first_name", "type": "string"}],
            "templateTags": [{"tag": "A1"}],
        },
    )
    mocker.patch.object(remap_worker, "_get_session_entry", return_value={"user_id": "user-1"})
    mocker.patch.object(remap_worker, "call_openai_schema_mapping_chunked", side_effect=_QuotaError("quota"))
    refund_mock = mocker.patch.object(remap_worker, "refund_openai_credits", return_value=10)

    response = client.post("/internal/remap", json=_payload())

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "insufficient_quota" in response.json()["error"]
    refund_mock.assert_called_once_with("user-1", credits=1, role="base")
