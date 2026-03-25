"""Cloud KMS-backed signing helpers for signing audit manifests.

The production path uses Cloud KMS asymmetric signing so audit manifests are
sealed by an external key rather than an in-process secret. Local development
and unit tests still need deterministic signatures without requiring a real KMS
key, so this module falls back to an explicit HMAC-based dev signer outside
production. The verification helper understands both modes.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
from typing import Any, Dict, Optional

from backend.env_utils import env_value
from backend.logging_config import get_logger
from backend.time_utils import now_iso
from backend.services import signing_service


logger = get_logger(__name__)

AUDIT_SIGNATURE_METHOD_KMS = "cloud_kms_asymmetric_sign"
AUDIT_SIGNATURE_METHOD_DEV_HMAC = "dev_hmac_sha256"
_WARNED_DEV_AUDIT_SIGNER = False


@dataclass(frozen=True)
class AuditSignatureEnvelope:
    method: str
    signature_base64: str
    digest_sha256: str
    signed_at: str
    algorithm: str
    key_resource_name: Optional[str] = None
    key_version_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "method": self.method,
            "signatureBase64": self.signature_base64,
            "digestSha256": self.digest_sha256,
            "signedAt": self.signed_at,
            "algorithm": self.algorithm,
            "keyResourceName": self.key_resource_name,
            "keyVersionName": self.key_version_name,
        }


def _is_prod_env() -> bool:
    return (env_value("ENV") or "").strip().lower() in {"prod", "production"}


def _resolve_dev_audit_signing_secret() -> str:
    secret = (env_value("SIGNING_AUDIT_DEV_SECRET") or "").strip()
    if secret:
        return secret
    return signing_service._resolve_signing_token_secret()  # Reuse the process-scoped dev secret outside prod.


def _resolve_audit_kms_key_name() -> str:
    return (env_value("SIGNING_AUDIT_KMS_KEY") or "").strip()


def _require_kms_module():
    try:
        from google.cloud import kms  # type: ignore
    except Exception as exc:  # pragma: no cover - exercised when dependency is missing.
        raise RuntimeError("google-cloud-kms is required for Cloud KMS audit signing") from exc
    return kms


def _resolve_kms_key_version_name(client, key_name: str) -> tuple[str, str]:
    normalized = str(key_name or "").strip()
    if not normalized:
        raise RuntimeError("SIGNING_AUDIT_KMS_KEY must be configured for Cloud KMS audit signing")
    if "/cryptoKeyVersions/" in normalized:
        version = client.get_crypto_key_version(name=normalized)
        return normalized, str(version.algorithm)
    crypto_key = client.get_crypto_key(name=normalized)
    primary = getattr(crypto_key, "primary", None)
    primary_name = str(getattr(primary, "name", "") or "").strip()
    if not primary_name:
        raise RuntimeError("Cloud KMS key does not have a primary key version for audit signing")
    primary_algorithm = str(getattr(primary, "algorithm", "") or "").strip()
    if primary_algorithm:
        return primary_name, primary_algorithm
    version = client.get_crypto_key_version(name=primary_name)
    return primary_name, str(version.algorithm)


def sign_audit_manifest_bytes(manifest_bytes: bytes) -> AuditSignatureEnvelope:
    """Sign canonical manifest bytes with Cloud KMS or the dev fallback."""

    canonical_bytes = bytes(manifest_bytes or b"")
    digest = hashlib.sha256(canonical_bytes).digest()
    digest_hex = digest.hex()
    key_name = _resolve_audit_kms_key_name()
    if key_name:
        kms = _require_kms_module()
        client = kms.KeyManagementServiceClient()
        key_version_name, algorithm = _resolve_kms_key_version_name(client, key_name)
        response = client.asymmetric_sign(
            request={
                "name": key_version_name,
                "digest": {"sha256": digest},
            }
        )
        return AuditSignatureEnvelope(
            method=AUDIT_SIGNATURE_METHOD_KMS,
            signature_base64=base64.b64encode(bytes(response.signature or b"")).decode("ascii"),
            digest_sha256=digest_hex,
            signed_at=now_iso(),
            algorithm=algorithm or "EC_SIGN_P256_SHA256",
            key_resource_name=key_name,
            key_version_name=key_version_name,
        )
    if _is_prod_env():
        raise RuntimeError("SIGNING_AUDIT_KMS_KEY must be configured in production to sign audit manifests")
    global _WARNED_DEV_AUDIT_SIGNER
    if not _WARNED_DEV_AUDIT_SIGNER:
        logger.warning(
            "SIGNING_AUDIT_KMS_KEY is unset outside production; using a deterministic dev HMAC signer for audit manifests."
        )
        _WARNED_DEV_AUDIT_SIGNER = True
    dev_secret = _resolve_dev_audit_signing_secret().encode("utf-8")
    signature = hmac.new(dev_secret, canonical_bytes, hashlib.sha256).digest()
    return AuditSignatureEnvelope(
        method=AUDIT_SIGNATURE_METHOD_DEV_HMAC,
        signature_base64=base64.b64encode(signature).decode("ascii"),
        digest_sha256=digest_hex,
        signed_at=now_iso(),
        algorithm="HMAC_SHA256",
        key_resource_name=None,
        key_version_name=None,
    )


def verify_audit_manifest_signature(manifest_bytes: bytes, signature: Dict[str, Any]) -> bool:
    """Verify a canonical manifest against its stored signature envelope."""

    canonical_bytes = bytes(manifest_bytes or b"")
    digest_hex = hashlib.sha256(canonical_bytes).hexdigest()
    method = str((signature or {}).get("method") or "").strip()
    signature_b64 = str((signature or {}).get("signatureBase64") or "").strip()
    signature_digest = str((signature or {}).get("digestSha256") or "").strip().lower()
    if not method or not signature_b64 or signature_digest != digest_hex:
        return False
    try:
        signature_bytes = base64.b64decode(signature_b64.encode("ascii"), validate=True)
    except Exception:
        return False
    if method == AUDIT_SIGNATURE_METHOD_DEV_HMAC:
        dev_secret = _resolve_dev_audit_signing_secret().encode("utf-8")
        expected = hmac.new(dev_secret, canonical_bytes, hashlib.sha256).digest()
        return hmac.compare_digest(signature_bytes, expected)
    if method == AUDIT_SIGNATURE_METHOD_KMS:
        key_version_name = str((signature or {}).get("keyVersionName") or "").strip()
        if not key_version_name:
            return False
        kms = _require_kms_module()
        client = kms.KeyManagementServiceClient()
        response = client.asymmetric_verify(
            request={
                "name": key_version_name,
                "digest": {"sha256": bytes.fromhex(digest_hex)},
                "signature": signature_bytes,
            }
        )
        return bool(getattr(response, "verified", False))
    return False
