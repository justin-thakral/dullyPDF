"""Unit tests for helper logic in `backend/detection/detector_app.py`."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

import backend.detection.detector_app as dm
from backend.detection.status import DETECTION_STATUS_FAILED


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "test")
    for key in (
        "DETECTOR_ALLOW_UNAUTHENTICATED",
        "DETECTOR_TASKS_MAX_ATTEMPTS",
        "DETECTOR_RETRY_AFTER_SECONDS",
        "DETECTOR_TASKS_AUDIENCE",
        "DETECTOR_SERVICE_URL",
        "DETECTOR_CALLER_SERVICE_ACCOUNT",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(dm, "_ALLOW_UNAUTHENTICATED", False)


def test_allow_unauthenticated_disabled_when_flag_is_not_truthy() -> None:
    assert dm._allow_unauthenticated() is False


def test_allow_unauthenticated_ignored_in_prod(
    mocker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DETECTOR_ALLOW_UNAUTHENTICATED", "true")
    monkeypatch.setenv("ENV", "prod")
    warning = mocker.patch.object(dm.logger, "warning")

    assert dm._allow_unauthenticated() is False
    warning.assert_called_once_with("DETECTOR_ALLOW_UNAUTHENTICATED is ignored in prod.")


def test_allow_unauthenticated_ignored_for_non_dev_env(
    mocker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DETECTOR_ALLOW_UNAUTHENTICATED", "true")
    monkeypatch.setenv("ENV", "staging")
    warning = mocker.patch.object(dm.logger, "warning")

    assert dm._allow_unauthenticated() is False
    warning.assert_called_once_with(
        "DETECTOR_ALLOW_UNAUTHENTICATED is ignored for ENV=%s.",
        "staging",
    )


def test_allow_unauthenticated_enabled_in_test_when_flag_truthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DETECTOR_ALLOW_UNAUTHENTICATED", "yes")
    monkeypatch.setenv("ENV", "test")

    assert dm._allow_unauthenticated() is True


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, 0),
        ("", 0),
        (" 3 ", 3),
        ("abc", 0),
        ("-7", 0),
    ],
)
def test_parse_retry_count(raw: str | None, expected: int) -> None:
    assert dm._parse_retry_count(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("0", None),
        ("-2", None),
        ("4", 4),
    ],
)
def test_max_task_attempts(
    raw: str | None,
    expected: int | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if raw is None:
        monkeypatch.delenv("DETECTOR_TASKS_MAX_ATTEMPTS", raising=False)
    else:
        monkeypatch.setenv("DETECTOR_TASKS_MAX_ATTEMPTS", raw)
    assert dm._max_task_attempts() == expected


def test_should_finalize_failure_false_without_max_attempts() -> None:
    assert dm._should_finalize_failure(0) is False
    assert dm._should_finalize_failure(999) is False


def test_should_finalize_failure_uses_max_attempts_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DETECTOR_TASKS_MAX_ATTEMPTS", "3")

    assert dm._should_finalize_failure(1) is False
    assert dm._should_finalize_failure(2) is True


def test_retry_headers_default() -> None:
    assert dm._retry_headers() == {"X-Dully-Retry": "true", "Retry-After": "5"}


def test_retry_headers_omits_retry_after_when_non_positive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DETECTOR_RETRY_AFTER_SECONDS", "0")
    assert dm._retry_headers() == {"X-Dully-Retry": "true"}


def test_require_internal_auth_allows_when_unauthenticated_mode_enabled(mocker) -> None:
    verify = mocker.patch.object(dm.id_token, "verify_oauth2_token")
    dm._ALLOW_UNAUTHENTICATED = True

    assert dm._require_internal_auth(None) == {}
    verify.assert_not_called()


def test_require_internal_auth_rejects_missing_or_empty_bearer_token() -> None:
    dm._ALLOW_UNAUTHENTICATED = False
    with pytest.raises(HTTPException) as exc_info:
        dm._require_internal_auth("Bearer ")
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Missing detector auth token"


def test_require_internal_auth_requires_audience_config() -> None:
    dm._ALLOW_UNAUTHENTICATED = False
    with pytest.raises(HTTPException) as exc_info:
        dm._require_internal_auth("Bearer token")
    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Detector audience is not configured"


def test_require_internal_auth_rejects_invalid_token(
    mocker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dm._ALLOW_UNAUTHENTICATED = False
    monkeypatch.setenv("DETECTOR_SERVICE_URL", "https://detector.example")
    mocker.patch.object(dm.id_token, "verify_oauth2_token", side_effect=ValueError("bad token"))

    with pytest.raises(HTTPException) as exc_info:
        dm._require_internal_auth("Bearer token")
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid detector auth token"


def test_require_internal_auth_requires_service_account_config_in_prod(
    mocker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dm._ALLOW_UNAUTHENTICATED = False
    monkeypatch.setenv("DETECTOR_SERVICE_URL", "https://detector.example")
    monkeypatch.setattr(dm, "_is_prod", lambda: True)
    mocker.patch.object(dm.id_token, "verify_oauth2_token", return_value={"email": "svc@example.com"})

    with pytest.raises(HTTPException) as exc_info:
        dm._require_internal_auth("Bearer token")
    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Detector caller service account is not configured"


def test_require_internal_auth_rejects_disallowed_service_account(
    mocker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dm._ALLOW_UNAUTHENTICATED = False
    monkeypatch.setenv("DETECTOR_SERVICE_URL", "https://detector.example")
    monkeypatch.setenv("DETECTOR_CALLER_SERVICE_ACCOUNT", "allowed@example.com")
    mocker.patch.object(dm.id_token, "verify_oauth2_token", return_value={"email": "other@example.com"})

    with pytest.raises(HTTPException) as exc_info:
        dm._require_internal_auth("Bearer token")
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Detector caller not allowed"


def test_require_internal_auth_returns_payload_for_allowed_caller(
    mocker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dm._ALLOW_UNAUTHENTICATED = False
    monkeypatch.setenv("DETECTOR_SERVICE_URL", "https://detector.example")
    monkeypatch.setenv("DETECTOR_CALLER_SERVICE_ACCOUNT", "allowed@example.com")
    payload = {"email": "allowed@example.com", "sub": "abc123"}
    verify = mocker.patch.object(dm.id_token, "verify_oauth2_token", return_value=payload)

    assert dm._require_internal_auth("Bearer token") == payload
    verify.assert_called_once()


def test_finish_detection_failure_updates_metadata_and_detection_request(mocker) -> None:
    now_iso = mocker.patch.object(dm, "now_iso", return_value="2026-02-11T00:00:00+00:00")
    upsert = mocker.patch.object(dm, "upsert_session_metadata")
    update = mocker.patch.object(dm, "update_detection_request")

    response = dm._finish_detection_failure("sess_123", "failed to detect")

    assert response == {
        "sessionId": "sess_123",
        "status": DETECTION_STATUS_FAILED,
        "error": "failed to detect",
    }
    upsert.assert_called_once_with(
        "sess_123",
        {
            "detection_status": DETECTION_STATUS_FAILED,
            "detection_completed_at": "2026-02-11T00:00:00+00:00",
            "detection_error": "failed to detect",
        },
    )
    update.assert_called_once_with(
        request_id="sess_123",
        status=DETECTION_STATUS_FAILED,
        error="failed to detect",
    )
    now_iso.assert_called_once_with()


# --- Edge case tests ---


@pytest.mark.parametrize("env_val", ["dev", "development", "local"])
def test_allow_unauthenticated_enabled_for_dev_local_development(
    monkeypatch: pytest.MonkeyPatch,
    env_val: str,
) -> None:
    """The allowed env set is {"dev", "development", "local", "test"}.
    Verify all non-test allowed values work."""
    monkeypatch.setenv("DETECTOR_ALLOW_UNAUTHENTICATED", "true")
    monkeypatch.setenv("ENV", env_val)
    assert dm._allow_unauthenticated() is True


def test_allow_unauthenticated_returns_false_when_env_is_completely_unset(
    mocker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ENV is unset, env_value returns "", which is not in the allowed
    set. The warning log shows "unset" via the `env_name or "unset"` fallback."""
    monkeypatch.setenv("DETECTOR_ALLOW_UNAUTHENTICATED", "true")
    monkeypatch.delenv("ENV", raising=False)
    warning = mocker.patch.object(dm.logger, "warning")

    assert dm._allow_unauthenticated() is False
    warning.assert_called_once_with(
        "DETECTOR_ALLOW_UNAUTHENTICATED is ignored for ENV=%s.",
        "unset",
    )


def test_is_prod_recognizes_production_string(monkeypatch: pytest.MonkeyPatch) -> None:
    """_is_prod must return True for "production" as well as "prod".
    A failure here could cause auth requirements to be skipped in production."""
    monkeypatch.setenv("ENV", "production")
    assert dm._is_prod() is True


def test_is_prod_returns_false_for_non_prod_envs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "test")
    assert dm._is_prod() is False
    monkeypatch.setenv("ENV", "dev")
    assert dm._is_prod() is False


def test_require_internal_auth_rejects_none_authorization() -> None:
    """When authorization is None (not just empty bearer), the (None or "")
    fallback should still reject with 401."""
    dm._ALLOW_UNAUTHENTICATED = False
    with pytest.raises(HTTPException) as exc_info:
        dm._require_internal_auth(None)
    assert exc_info.value.status_code == 401


def test_require_internal_auth_rejects_non_bearer_scheme() -> None:
    """A non-Bearer scheme like "Basic abc123" should fail the startswith check."""
    dm._ALLOW_UNAUTHENTICATED = False
    with pytest.raises(HTTPException) as exc_info:
        dm._require_internal_auth("Basic abc123")
    assert exc_info.value.status_code == 401


def test_should_finalize_failure_boundary_first_attempt_is_final(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With max_attempts=1, retry_count=0 means 0 >= (1-1) = True,
    so the very first attempt should be finalized."""
    monkeypatch.setenv("DETECTOR_TASKS_MAX_ATTEMPTS", "1")
    assert dm._should_finalize_failure(0) is True


def test_require_internal_auth_skips_caller_check_in_non_prod_without_config(
    mocker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In non-prod, when DETECTOR_CALLER_SERVICE_ACCOUNT is not set, the
    caller check is skipped entirely and the payload is returned."""
    dm._ALLOW_UNAUTHENTICATED = False
    monkeypatch.setenv("DETECTOR_SERVICE_URL", "https://detector.example")
    monkeypatch.setenv("ENV", "test")
    payload = {"email": "any@example.com", "sub": "abc"}
    mocker.patch.object(dm.id_token, "verify_oauth2_token", return_value=payload)

    result = dm._require_internal_auth("Bearer valid-token")
    assert result == payload
