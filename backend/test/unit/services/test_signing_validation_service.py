"""Unit coverage for public signing validation payloads."""

from __future__ import annotations

import asyncio
import hashlib
import json
from types import SimpleNamespace

from backend.services import signing_validation_service


def test_build_signing_validation_payload_includes_pdf_digital_signature_checks(mocker) -> None:
    envelope_payload = {
        "manifest": {
            "events": [{"eventType": "completed"}],
            "documentEvidence": {
                "sourcePdfSha256": "a" * 64,
                "signedPdfSha256": "b" * 64,
            },
        },
        "signature": {
            "method": "cloud_kms_asymmetric_sign",
            "algorithm": "EC_SIGN_P256_SHA256",
            "keyVersionName": "projects/test/locations/us-east4/keyRings/ring/cryptoKeys/key/cryptoKeyVersions/1",
            "digestSha256": "e" * 64,
        },
    }
    envelope_bytes = json.dumps(envelope_payload).encode("utf-8")
    audit_manifest_sha256 = hashlib.sha256(envelope_bytes).hexdigest()

    record = SimpleNamespace(
        id="req-1",
        status="completed",
        title="Bravo Packet",
        source_document_name="Bravo Packet.pdf",
        source_version="workspace:form-alpha:abc123",
        document_category="ordinary_business_form",
        completed_at="2026-03-28T10:00:00+00:00",
        retention_until="2033-03-28T10:00:00+00:00",
        sender_display_name="Owner",
        sender_contact_email="owner@example.com",
        sender_email="owner@example.com",
        signer_name="Alex Signer",
        signature_adopted_name="Alex Signer",
        source_pdf_sha256="a" * 64,
        signed_pdf_sha256="b" * 64,
        audit_manifest_sha256=audit_manifest_sha256,
        audit_receipt_sha256="d" * 64,
        audit_receipt_bucket_path="gs://signing/receipt.pdf",
        audit_manifest_bucket_path="gs://signing/manifest.json",
        signed_pdf_bucket_path="gs://signing/signed.pdf",
    )
    mocker.patch.object(
        signing_validation_service,
        "download_storage_bytes",
        side_effect=lambda bucket_path: (
            envelope_bytes
            if bucket_path.endswith("manifest.json")
            else b"%PDF-1.7 digitally signed"
        ),
    )
    mocker.patch.object(signing_validation_service, "verify_signing_audit_envelope", return_value=True)
    mocker.patch.object(
        signing_validation_service,
        "async_validate_digital_pdf_signature",
        return_value=SimpleNamespace(
            present=True,
            valid=False,
            intact=True,
            trusted=False,
            summary="INTACT:UNTRUSTED,UNTOUCHED",
            signature_count=1,
            field_name="DullyPDFDigitalSignature",
            subfilter="/ETSI.CAdES.detached",
            coverage="ENTIRE_FILE",
            modification_level="NONE",
            timestamp_present=True,
            timestamp_valid=True,
            certificate_subject="CN=DullyPDF Test Signer",
            certificate_issuer="CN=DullyPDF Test Issuer",
            certificate_serial_number="01",
            certificate_fingerprint_sha256="f" * 64,
            expected_sha256_matches=True,
            actual_sha256="b" * 64,
        ),
    )

    payload = asyncio.run(signing_validation_service.build_signing_validation_payload(record))

    assert payload["available"] is True
    assert payload["valid"] is True
    assert payload["digitalSignature"]["present"] is True
    assert payload["digitalSignature"]["trusted"] is False
    assert payload["digitalSignature"]["timestampPresent"] is True
    check_keys = {check["key"] for check in payload["checks"]}
    assert "pdf_digital_signature_integrity" in check_keys
    assert "pdf_digital_signature_hash" in check_keys


def test_build_signing_validation_payload_reads_retained_artifacts_through_storage_fallback(mocker) -> None:
    envelope_payload = {
        "manifest": {
            "events": [{"eventType": "completed"}],
            "documentEvidence": {
                "sourcePdfSha256": "a" * 64,
                "signedPdfSha256": "b" * 64,
            },
        },
        "signature": {
            "method": "cloud_kms_asymmetric_sign",
            "algorithm": "EC_SIGN_P256_SHA256",
            "keyVersionName": "projects/test/locations/us-east4/keyRings/ring/cryptoKeys/key/cryptoKeyVersions/1",
            "digestSha256": "e" * 64,
        },
    }
    envelope_bytes = json.dumps(envelope_payload).encode("utf-8")
    audit_manifest_sha256 = hashlib.sha256(envelope_bytes).hexdigest()
    record = SimpleNamespace(
        id="req-2",
        status="completed",
        title="Fallback Packet",
        source_document_name="Fallback Packet.pdf",
        source_version="workspace:form-beta:def456",
        document_category="ordinary_business_form",
        completed_at="2026-03-28T10:00:00+00:00",
        retention_until="2033-03-28T10:00:00+00:00",
        sender_display_name="Owner",
        sender_contact_email="owner@example.com",
        sender_email="owner@example.com",
        signer_name="Alex Signer",
        signature_adopted_name="Alex Signer",
        source_pdf_sha256="a" * 64,
        signed_pdf_sha256="b" * 64,
        audit_manifest_sha256=audit_manifest_sha256,
        audit_receipt_sha256="d" * 64,
        audit_receipt_bucket_path="gs://signing/receipt.pdf",
        audit_manifest_bucket_path="gs://signing/manifest.json",
        signed_pdf_bucket_path="gs://signing/signed.pdf",
    )
    resolve_mock = mocker.patch.object(
        signing_validation_service,
        "resolve_signing_storage_read_bucket_path",
        side_effect=lambda bucket_path, *, retain_until=None: (
            bucket_path.replace("gs://signing/", "gs://signing-staging/_staging/")
        ),
    )
    mocker.patch.object(
        signing_validation_service,
        "download_storage_bytes",
        side_effect=lambda bucket_path: (
            envelope_bytes
            if bucket_path.endswith("manifest.json")
            else b"%PDF-1.7 staged signed artifact"
        ),
    )
    mocker.patch.object(signing_validation_service, "verify_signing_audit_envelope", return_value=True)
    mocker.patch.object(
        signing_validation_service,
        "async_validate_digital_pdf_signature",
        return_value=SimpleNamespace(
            present=False,
            valid=False,
            intact=False,
            trusted=False,
            summary="",
            signature_count=0,
            field_name=None,
            subfilter=None,
            coverage=None,
            modification_level=None,
            timestamp_present=False,
            timestamp_valid=False,
            certificate_subject=None,
            certificate_issuer=None,
            certificate_serial_number=None,
            certificate_fingerprint_sha256=None,
            expected_sha256_matches=None,
            actual_sha256=None,
        ),
    )

    payload = asyncio.run(signing_validation_service.build_signing_validation_payload(record))

    assert payload["available"] is True
    assert payload["valid"] is True
    assert resolve_mock.call_args_list[0].args == ("gs://signing/manifest.json",)
    assert resolve_mock.call_args_list[0].kwargs == {"retain_until": "2033-03-28T10:00:00+00:00"}
    assert resolve_mock.call_args_list[1].args == ("gs://signing/signed.pdf",)
