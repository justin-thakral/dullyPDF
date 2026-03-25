"""Unit coverage for Cloud KMS audit-signing helpers."""

from __future__ import annotations

from types import SimpleNamespace

from backend.services import cloud_kms_service


class _FakeKmsClient:
    def __init__(self) -> None:
        self.last_sign_request = None
        self.last_verify_request = None

    def get_crypto_key_version(self, *, name: str):
        return SimpleNamespace(algorithm="EC_SIGN_P256_SHA256", name=name)

    def asymmetric_sign(self, *, request):
        self.last_sign_request = request
        return SimpleNamespace(signature=b"kms-signature")

    def asymmetric_verify(self, *, request):
        self.last_verify_request = request
        return SimpleNamespace(verified=request.get("signature") == b"kms-signature")


def test_sign_audit_manifest_bytes_uses_cloud_kms_when_configured(monkeypatch) -> None:
    fake_client = _FakeKmsClient()
    fake_module = SimpleNamespace(KeyManagementServiceClient=lambda: fake_client)
    monkeypatch.setenv(
        "SIGNING_AUDIT_KMS_KEY",
        "projects/demo/locations/us/keyRings/signing/cryptoKeys/audit/cryptoKeyVersions/1",
    )
    monkeypatch.setattr(cloud_kms_service, "_require_kms_module", lambda: fake_module)

    envelope = cloud_kms_service.sign_audit_manifest_bytes(b'{"ok":true}')

    assert envelope.method == cloud_kms_service.AUDIT_SIGNATURE_METHOD_KMS
    assert envelope.key_version_name.endswith("/cryptoKeyVersions/1")
    assert envelope.algorithm == "EC_SIGN_P256_SHA256"
    assert fake_client.last_sign_request["name"].endswith("/cryptoKeyVersions/1")
    assert cloud_kms_service.verify_audit_manifest_signature(
        b'{"ok":true}',
        envelope.to_dict(),
    ) is True
