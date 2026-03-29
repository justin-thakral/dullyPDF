"""Unit coverage for cryptographic PDF signing helpers."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
import tempfile
from types import SimpleNamespace

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from reportlab.pdfgen import canvas

from backend.services import signing_pdf_digital_service


def _clear_signing_identity_env(monkeypatch) -> None:
    for name in (
        "SIGNING_PDF_PKCS12_B64",
        "SIGNING_PDF_PKCS12_PASSWORD",
        "SIGNING_PDF_P12_BASE64",
        "SIGNING_PDF_P12_PATH",
        "SIGNING_PDF_P12_PASSWORD",
        "SIGNING_PDF_CERT_PEM",
        "SIGNING_PDF_CERT_PEM_BASE64",
        "SIGNING_PDF_CERT_PATH",
        "SIGNING_PDF_CERT_CHAIN_PEM",
        "SIGNING_PDF_CERT_CHAIN_PEM_BASE64",
        "SIGNING_PDF_CERT_CHAIN_PATH",
        "SIGNING_PDF_KMS_KEY",
        "SIGNING_AUDIT_KMS_KEY",
        "SIGNING_PDF_TSA_URL",
        "SIGNING_PDF_USE_BUNDLED_DEV_CERT",
    ):
        monkeypatch.delenv(name, raising=False)
    signing_pdf_digital_service._resolve_pdf_signing_identity.cache_clear()


def _sample_pdf_bytes() -> bytes:
    output = BytesIO()
    pdf_canvas = canvas.Canvas(output)
    pdf_canvas.drawString(72, 720, "DullyPDF digital signing test")
    pdf_canvas.save()
    return output.getvalue()


def _write_test_pkcs12() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "DullyPDF Test"),
            x509.NameAttribute(NameOID.COMMON_NAME, "DullyPDF Test Signer"),
        ]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    bundle = pkcs12.serialize_key_and_certificates(
        name=b"dullypdf-test",
        key=key,
        cert=cert,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(b"secret123"),
    )
    with tempfile.NamedTemporaryFile(suffix=".p12", delete=False) as handle:
        handle.write(bundle)
        return handle.name


def test_apply_digital_pdf_signature_uses_bundled_dev_identity_by_default(monkeypatch) -> None:
    _clear_signing_identity_env(monkeypatch)

    result = signing_pdf_digital_service.apply_digital_pdf_signature(
        pdf_bytes=_sample_pdf_bytes(),
        signer_name="Alex Signer",
        source_document_name="Test Packet",
    )

    assert result.signature_info.signature_method == "dev_pem"
    assert result.signature_info.field_name == "DullyPDFDigitalSignature"
    assert result.signature_info.certificate_subject
    assert result.signature_info.certificate_fingerprint_sha256

    validation = signing_pdf_digital_service.validate_digital_pdf_signature(result.pdf_bytes)
    assert validation.present is True
    assert validation.valid is True
    assert validation.intact is True
    assert validation.trusted is True
    assert "TRUSTED" in validation.summary


def test_apply_digital_pdf_signature_is_noop_when_bundled_dev_identity_is_disabled(monkeypatch) -> None:
    _clear_signing_identity_env(monkeypatch)
    monkeypatch.setenv("SIGNING_PDF_USE_BUNDLED_DEV_CERT", "false")
    signing_pdf_digital_service._resolve_pdf_signing_identity.cache_clear()

    pdf_bytes = _sample_pdf_bytes()
    result = signing_pdf_digital_service.apply_digital_pdf_signature(
        pdf_bytes=pdf_bytes,
        signer_name="Alex Signer",
        source_document_name="Test Packet",
    )

    assert result.pdf_bytes == pdf_bytes
    assert result.signature_info.signature_method is None
    assert result.signature_info.field_name is None

    validation = signing_pdf_digital_service.validate_digital_pdf_signature(result.pdf_bytes)
    assert validation.present is False
    assert validation.summary == "missing_signature"


def test_apply_digital_pdf_signature_is_noop_in_prod_without_identity(monkeypatch) -> None:
    _clear_signing_identity_env(monkeypatch)
    monkeypatch.setattr(signing_pdf_digital_service, "is_prod", lambda: True)

    pdf_bytes = _sample_pdf_bytes()
    result = signing_pdf_digital_service.apply_digital_pdf_signature(
        pdf_bytes=pdf_bytes,
        signer_name="Alex Signer",
        source_document_name="Test Packet",
    )

    assert result.pdf_bytes == pdf_bytes
    assert result.signature_info.signature_method is None
    assert result.signature_info.field_name is None


def test_apply_digital_pdf_signature_signs_and_validates_pkcs12(monkeypatch) -> None:
    _clear_signing_identity_env(monkeypatch)
    pkcs12_path = _write_test_pkcs12()
    monkeypatch.setenv("SIGNING_PDF_P12_PATH", pkcs12_path)
    monkeypatch.setenv("SIGNING_PDF_P12_PASSWORD", "secret123")
    signing_pdf_digital_service._resolve_pdf_signing_identity.cache_clear()

    result = signing_pdf_digital_service.apply_digital_pdf_signature(
        pdf_bytes=_sample_pdf_bytes(),
        signer_name="Alex Signer",
        source_document_name="Test Packet",
    )

    assert result.signature_info.signature_method == "pkcs12"
    assert result.signature_info.field_name == "DullyPDFDigitalSignature"
    assert result.signature_info.subfilter == "/ETSI.CAdES.detached"
    assert result.signature_info.certificate_subject

    expected_sha256 = hashlib.sha256(result.pdf_bytes).hexdigest()
    validation = signing_pdf_digital_service.validate_digital_pdf_signature(
        result.pdf_bytes,
        expected_sha256=expected_sha256,
    )

    assert validation.present is True
    assert validation.valid is True
    assert validation.intact is True
    assert validation.trusted is True
    assert validation.expected_sha256_matches is True
    assert validation.subfilter == "/ETSI.CAdES.detached"


def test_resolve_kms_key_version_uses_latest_enabled_version_for_crypto_key() -> None:
    class _FakeKmsClient:
        def get_crypto_key(self, *, name: str):
            return SimpleNamespace(primary=None)

        def list_crypto_key_versions(self, *, request):
            assert request == {
                "parent": "projects/demo/locations/us/keyRings/signing/cryptoKeys/pdf"
            }
            return [
                SimpleNamespace(
                    name="projects/demo/locations/us/keyRings/signing/cryptoKeys/pdf/cryptoKeyVersions/2",
                    algorithm="EC_SIGN_P256_SHA256",
                    state=SimpleNamespace(name="DISABLED"),
                ),
                SimpleNamespace(
                    name="projects/demo/locations/us/keyRings/signing/cryptoKeys/pdf/cryptoKeyVersions/9",
                    algorithm=SimpleNamespace(name="EC_SIGN_P256_SHA256"),
                    state=SimpleNamespace(name="ENABLED"),
                ),
            ]

        def get_crypto_key_version(self, *, name: str):
            return SimpleNamespace(name=name, algorithm=SimpleNamespace(name="EC_SIGN_P256_SHA256"))

    key_version_name, algorithm = signing_pdf_digital_service._resolve_kms_key_version(
        _FakeKmsClient(),
        "projects/demo/locations/us/keyRings/signing/cryptoKeys/pdf",
    )

    assert key_version_name.endswith("/cryptoKeyVersions/9")
    assert algorithm == "EC_SIGN_P256_SHA256"


def test_async_validate_digital_pdf_signature_matches_sync_path(monkeypatch) -> None:
    _clear_signing_identity_env(monkeypatch)

    result = signing_pdf_digital_service.apply_digital_pdf_signature(
        pdf_bytes=_sample_pdf_bytes(),
        signer_name="Alex Signer",
        source_document_name="Test Packet",
    )
    expected_sha256 = hashlib.sha256(result.pdf_bytes).hexdigest()

    sync_validation = signing_pdf_digital_service.validate_digital_pdf_signature(
        result.pdf_bytes,
        expected_sha256=expected_sha256,
    )
    async_validation = asyncio.run(
        signing_pdf_digital_service.async_validate_digital_pdf_signature(
            result.pdf_bytes,
            expected_sha256=expected_sha256,
        )
    )

    assert async_validation == sync_validation
