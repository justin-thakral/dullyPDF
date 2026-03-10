"""Unit tests for backend.ai.remap_worker_app."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
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


def test_require_internal_auth_accepts_profile_specific_remap_audience(mocker, monkeypatch) -> None:
    remap_worker._ALLOW_UNAUTHENTICATED = False
    monkeypatch.delenv("OPENAI_REMAP_TASKS_AUDIENCE", raising=False)
    monkeypatch.delenv("OPENAI_REMAP_SERVICE_URL", raising=False)
    monkeypatch.setenv("OPENAI_REMAP_TASKS_AUDIENCE_LIGHT", "remap-light-audience")
    monkeypatch.setenv("OPENAI_REMAP_CALLER_SERVICE_ACCOUNT", "allowed@example.com")
    payload = {"email": "allowed@example.com", "sub": "remap-task"}
    verify = mocker.patch(
        "backend.services.task_auth_service.id_token.verify_oauth2_token",
        return_value=payload,
    )

    assert remap_worker._require_internal_auth("Bearer token") == payload
    assert verify.call_args.kwargs["audience"] == "remap-light-audience"


def test_require_internal_auth_rejects_invalid_remap_token(mocker, monkeypatch) -> None:
    remap_worker._ALLOW_UNAUTHENTICATED = False
    monkeypatch.setenv("OPENAI_REMAP_SERVICE_URL", "https://remap.example.com")
    mocker.patch(
        "backend.services.task_auth_service.id_token.verify_oauth2_token",
        side_effect=ValueError("bad token"),
    )

    with pytest.raises(HTTPException) as exc_info:
        remap_worker._require_internal_auth("Bearer token")
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid remap worker auth token"


def test_remap_worker_completes_job_and_persists_checkbox_outputs(mocker) -> None:
    client = TestClient(remap_worker.app)
    mocker.patch.object(remap_worker, "_require_internal_auth", return_value={"sub": "task"})
    mocker.patch.object(
        remap_worker,
        "get_openai_job",
        return_value={
            "status": "queued",
            "user_id": "user-1",
            "schema_id": "schema-1",
            "session_id": "sess-1",
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
            "schema_id": "schema-1",
            "session_id": "sess-1",
            "request_id": "job-1",
        },
    )
    mocker.patch.object(remap_worker, "update_openai_job", return_value=None)
    mocker.patch.object(remap_worker, "get_schema", return_value=None)
    refund_mock = mocker.patch.object(remap_worker, "attempt_credit_refund", return_value=True)

    response = client.post("/internal/remap", json=_payload())

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "Schema not found" in response.json()["error"]
    refund_mock.assert_called_once_with(
        user_id="user-1",
        role="base",
        credits=1,
        source="remap.worker",
        request_id="job-1",
        job_id="job-1",
        credit_breakdown=None,
    )


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
            "schema_id": "schema-1",
            "session_id": "sess-1",
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
    refund_mock = mocker.patch.object(remap_worker, "attempt_credit_refund", return_value=True)

    response = client.post("/internal/remap", json=_payload())

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "insufficient_quota" in response.json()["error"]
    refund_mock.assert_called_once_with(
        user_id="user-1",
        role="base",
        credits=1,
        source="remap.worker",
        request_id="job-1",
        job_id="job-1",
        credit_breakdown=None,
    )


def test_remap_worker_rejects_missing_job_without_refund_or_upsert(mocker) -> None:
    client = TestClient(remap_worker.app)
    mocker.patch.object(remap_worker, "_require_internal_auth", return_value={"sub": "task"})
    mocker.patch.object(remap_worker, "get_openai_job", return_value=None)
    update_job_mock = mocker.patch.object(remap_worker, "update_openai_job", return_value=None)
    refund_mock = mocker.patch.object(remap_worker, "attempt_credit_refund", return_value=True)

    response = client.post("/internal/remap", json=_payload())

    assert response.status_code == 200
    assert response.json() == {
        "jobId": "job-1",
        "status": "failed",
        "error": "Schema mapping job metadata not found",
    }
    update_job_mock.assert_not_called()
    refund_mock.assert_not_called()


def test_remap_worker_uses_stored_job_identity_for_refunds(mocker) -> None:
    client = TestClient(remap_worker.app)
    mocker.patch.object(remap_worker, "_require_internal_auth", return_value={"sub": "task"})
    mocker.patch.object(
        remap_worker,
        "get_openai_job",
        return_value={
            "status": "queued",
            "user_id": "user-1",
            "schema_id": "schema-1",
            "request_id": "stored-request",
            "user_role": "pro",
            "credits": 9,
            "credits_charged": True,
            "credit_breakdown": {"proMonthly": 9},
        },
    )
    mocker.patch.object(remap_worker, "update_openai_job", return_value=None)
    mocker.patch.object(remap_worker, "get_schema", return_value=None)
    refund_mock = mocker.patch.object(remap_worker, "attempt_credit_refund", return_value=True)

    response = client.post(
        "/internal/remap",
        json=_payload(
            requestId="forged-request",
            userRole="base",
            credits=1,
            creditBreakdown={"base": 1},
        ),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    refund_mock.assert_called_once_with(
        user_id="user-1",
        role="pro",
        credits=9,
        source="remap.worker",
        request_id="stored-request",
        job_id="job-1",
        credit_breakdown={"proMonthly": 9},
    )


def test_remap_worker_rejects_payload_user_mismatch_without_mutation(mocker) -> None:
    client = TestClient(remap_worker.app)
    mocker.patch.object(remap_worker, "_require_internal_auth", return_value={"sub": "task"})
    mocker.patch.object(
        remap_worker,
        "get_openai_job",
        return_value={
            "status": "queued",
            "user_id": "user-1",
            "schema_id": "schema-1",
            "request_id": "job-1",
        },
    )
    update_job_mock = mocker.patch.object(remap_worker, "update_openai_job", return_value=None)
    refund_mock = mocker.patch.object(remap_worker, "attempt_credit_refund", return_value=True)

    response = client.post("/internal/remap", json=_payload(userId="user-2"))

    assert response.status_code == 200
    assert response.json()["error"] == "Schema mapping job user mismatch"
    update_job_mock.assert_called_once()
    assert update_job_mock.call_args.kwargs["job_id"] == "job-1"
    assert update_job_mock.call_args.kwargs["status"] == "failed"
    assert update_job_mock.call_args.kwargs["error"] == "Schema mapping job user mismatch"
    refund_mock.assert_not_called()
