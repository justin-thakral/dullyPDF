from __future__ import annotations

import pytest

from backend.services import signing_storage_service as service


def test_ensure_signing_storage_configuration_surfaces_bucket_metadata_permission_error(
    monkeypatch,
    mocker,
) -> None:
    monkeypatch.setenv("SIGNING_BUCKET", "signing")
    monkeypatch.setenv("SANDBOX_SESSION_BUCKET", "sessions")
    monkeypatch.setenv("SIGNING_RETENTION_DAYS", "2555")

    bucket = mocker.Mock()
    bucket.reload.side_effect = PermissionError("403 storage.buckets.get denied")
    mocker.patch.object(service, "get_storage_bucket", return_value=bucket)

    with pytest.raises(RuntimeError, match="storage\\.buckets\\.get"):
        service.ensure_signing_storage_configuration(validate_remote=True)
