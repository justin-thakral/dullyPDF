from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock


def test_public_signing_validation_returns_404_for_non_completed_record(client, app_main, mocker) -> None:
    mocker.patch.object(
        app_main,
        "get_signing_request_by_validation_token",
        return_value=SimpleNamespace(status="sent"),
    )

    response = client.get("/api/signing/public/validation/token-1")

    assert response.status_code == 404
    assert response.headers["cache-control"] == "private, no-store"


def test_public_signing_validation_returns_payload_for_completed_record(client, app_main, mocker) -> None:
    record = SimpleNamespace(id="req-1", status="completed")
    payload = {"requestId": "req-1", "valid": True, "status": "valid"}
    mocker.patch.object(app_main, "get_signing_request_by_validation_token", return_value=record)
    build_mock = mocker.patch.object(
        app_main,
        "build_signing_validation_payload",
        new=AsyncMock(return_value=payload),
    )

    response = client.get("/api/signing/public/validation/token-1")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {"validation": payload}
    build_mock.assert_called_once_with(record)
