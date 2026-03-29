"""Cryptographic PDF signing and validation helpers for completed signing requests.

The signing path is O(pdf_bytes) because pyHanko applies one incremental update
to embed a CMS signature into the already-rendered PDF. Validation is also
O(pdf_bytes) because the validator must hash the signed byte ranges before
checking the embedded CMS payload.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

from asn1crypto import x509 as asn1_x509
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import load_pem_public_key, pkcs12
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign import fields, signers
from pyhanko.sign.timestamps import HTTPTimeStamper
from pyhanko.sign.validation import async_validate_pdf_signature, validate_pdf_signature
from pyhanko_certvalidator import ValidationContext
from pyhanko_certvalidator.registry import SimpleCertificateStore

from backend.env_utils import env_value as _env_value
from backend.services.app_config import is_prod
from backend.services.cloud_kms_service import resolve_kms_asymmetric_signing_key_version

SIGNING_PDF_PKCS12_B64_ENV = "SIGNING_PDF_PKCS12_B64"
SIGNING_PDF_PKCS12_PASSWORD_ENV = "SIGNING_PDF_PKCS12_PASSWORD"
SIGNING_PDF_P12_BASE64_ENV = "SIGNING_PDF_P12_BASE64"
SIGNING_PDF_P12_PATH_ENV = "SIGNING_PDF_P12_PATH"
SIGNING_PDF_P12_PASSWORD_ENV = "SIGNING_PDF_P12_PASSWORD"
SIGNING_PDF_CERT_PEM_ENV = "SIGNING_PDF_CERT_PEM"
SIGNING_PDF_CERT_PEM_BASE64_ENV = "SIGNING_PDF_CERT_PEM_BASE64"
SIGNING_PDF_CERT_PATH_ENV = "SIGNING_PDF_CERT_PATH"
SIGNING_PDF_CERT_CHAIN_PEM_ENV = "SIGNING_PDF_CERT_CHAIN_PEM"
SIGNING_PDF_CERT_CHAIN_PEM_BASE64_ENV = "SIGNING_PDF_CERT_CHAIN_PEM_BASE64"
SIGNING_PDF_CERT_CHAIN_PATH_ENV = "SIGNING_PDF_CERT_CHAIN_PATH"
SIGNING_PDF_KMS_KEY_ENV = "SIGNING_PDF_KMS_KEY"
SIGNING_PDF_TSA_URL_ENV = "SIGNING_PDF_TSA_URL"
SIGNING_PDF_USE_BUNDLED_DEV_CERT_ENV = "SIGNING_PDF_USE_BUNDLED_DEV_CERT"
SIGNING_PDF_DIGITAL_SIGNATURE_FIELD_NAME = "DullyPDFDigitalSignature"
SIGNING_PDF_SIGNATURE_LOCATION = "DullyPDF"

SIGNING_PDF_DIGITAL_SIGNATURE_SUBFILTER = fields.SigSeedSubFilter.PADES.value
SIGNING_PDF_DIGITAL_SIGNATURE_METHOD_PKCS12 = "pkcs12"
SIGNING_PDF_DIGITAL_SIGNATURE_METHOD_GCP_KMS = "gcp_kms"
SIGNING_PDF_DIGITAL_SIGNATURE_METHOD_DEV_PEM = "dev_pem"
SIGNING_PDF_DIGITAL_SIGNATURE_METHOD_NONE = "none"

_DEV_ASSET_DIR = Path(__file__).resolve().parent / "dev_assets"
_DEV_CERT_PATH = _DEV_ASSET_DIR / "signing_pdf_dev_cert.pem"
_DEV_KEY_PATH = _DEV_ASSET_DIR / "signing_pdf_dev_key.pem"


@dataclass(frozen=True)
class PdfDigitalSignatureInfo:
    field_name: Optional[str]
    certificate_subject: Optional[str]
    certificate_issuer: Optional[str]
    certificate_serial_number: Optional[str]
    certificate_fingerprint_sha256: Optional[str]
    digest_algorithm: Optional[str]
    subfilter: Optional[str]
    identity_source: Optional[str]
    signature_method: Optional[str]
    signature_algorithm: Optional[str]
    timestamped: bool


@dataclass(frozen=True)
class PdfDigitalSigningResult:
    pdf_bytes: bytes
    signature_info: PdfDigitalSignatureInfo


@dataclass(frozen=True)
class PdfDigitalSignatureValidation:
    present: bool
    valid: bool
    intact: bool
    trusted: bool
    summary: str
    signature_count: int
    field_name: Optional[str]
    subfilter: Optional[str]
    coverage: Optional[str]
    modification_level: Optional[str]
    timestamp_present: bool
    timestamp_valid: Optional[bool]
    certificate_subject: Optional[str]
    certificate_issuer: Optional[str]
    certificate_serial_number: Optional[str]
    certificate_fingerprint_sha256: Optional[str]
    expected_sha256_matches: Optional[bool]
    actual_sha256: str


@dataclass(frozen=True)
class _ResolvedPdfSigningIdentity:
    signer: Any
    identity_source: str
    signature_method: str
    signature_algorithm: Optional[str]
    certificate_subject: Optional[str]
    certificate_issuer: Optional[str]
    certificate_serial_number: Optional[str]
    certificate_fingerprint_sha256: Optional[str]
    digest_algorithm: str
    tsa_url: Optional[str]


def _optional_env(name: str) -> Optional[str]:
    normalized = str(_env_value(name) or "").strip()
    return normalized or None


def _optional_env_flag(name: str) -> Optional[bool]:
    value = _optional_env(name)
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _optional_multiline_env(name: str) -> Optional[str]:
    raw = _env_value(name)
    if raw is None:
        return None
    text = str(raw)
    return text if text.strip() else None


def _first_present(*names: str) -> Optional[str]:
    for name in names:
        value = _optional_env(name)
        if value:
            return value
    return None


def _read_optional_base64_bytes(*names: str) -> Optional[bytes]:
    raw = _first_present(*names)
    if not raw:
        return None
    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError(f"{names[0]} must contain valid base64 data.") from exc


def _read_optional_path_bytes(*names: str) -> Optional[bytes]:
    path = _first_present(*names)
    if not path:
        return None
    with open(path, "rb") as handle:
        return handle.read()


def _read_optional_text(*env_names: str, path_names: tuple[str, ...] = ()) -> Optional[str]:
    for env_name in env_names:
        inline = _optional_multiline_env(env_name)
        if inline:
            return inline
    for path_name in path_names:
        path = _optional_env(path_name)
        if path:
            with open(path, "r", encoding="utf-8") as handle:
                return handle.read()
    return None


def _kms_digest_for_algorithm(kms_algorithm: str) -> str:
    normalized = str(kms_algorithm or "").strip().upper()
    if normalized.endswith("SHA256"):
        return "sha256"
    if normalized.endswith("SHA384"):
        return "sha384"
    if normalized.endswith("SHA512"):
        return "sha512"
    raise RuntimeError(f"Unsupported Cloud KMS digest algorithm for PDF signing: {kms_algorithm}")


def _kms_prefer_pss(kms_algorithm: str) -> bool:
    return str(kms_algorithm or "").strip().upper().startswith("RSA_SIGN_PSS_")


def _kms_placeholder_size(kms_algorithm: str) -> int:
    normalized = str(kms_algorithm or "").strip().upper()
    if "2048" in normalized:
        return 256
    if "3072" in normalized:
        return 384
    if "4096" in normalized:
        return 512
    if normalized.startswith("EC_SIGN_P256"):
        return 96
    if normalized.startswith("EC_SIGN_P384"):
        return 132
    return 512


def _require_kms_module():
    try:
        from google.cloud import kms  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on optional install.
        raise RuntimeError("google-cloud-kms is required for Cloud KMS PDF signing") from exc
    return kms


def _resolve_kms_key_version(client, key_name: str) -> tuple[str, str]:
    return resolve_kms_asymmetric_signing_key_version(
        client,
        key_name,
        required_env_name=f"{SIGNING_PDF_KMS_KEY_ENV} or SIGNING_AUDIT_KMS_KEY",
        usage_label="PDF signing",
    )


def _load_pem_certificates(pem_text: str) -> list[asn1_x509.Certificate]:
    loaded = x509.load_pem_x509_certificates(pem_text.encode("utf-8"))
    return [
        asn1_x509.Certificate.load(cert.public_bytes(serialization.Encoding.DER))
        for cert in loaded
    ]


def _certificate_metadata(cert: asn1_x509.Certificate) -> tuple[str, str, str, str]:
    return (
        cert.subject.human_friendly,
        cert.issuer.human_friendly,
        format(cert.serial_number, "x"),
        hashlib.sha256(cert.dump()).hexdigest(),
    )


def _signature_algorithm_for_certificate(cert: asn1_x509.Certificate, *, digest_algorithm: str) -> str:
    public_key_info = getattr(cert, "public_key", None)
    public_key_algorithm = str(getattr(public_key_info, "algorithm", "") or "").strip().lower()
    normalized_digest = str(digest_algorithm or "").strip().lower() or "sha256"
    if public_key_algorithm == "rsa":
        return f"rsa_{normalized_digest}"
    if public_key_algorithm in {"ec", "ecdsa"}:
        return f"ecdsa_{normalized_digest}"
    return normalized_digest


class _GoogleKmsPdfSigner(signers.ExternalSigner):
    """pyHanko signer adapter backed by Cloud KMS asymmetric signing."""

    def __init__(
        self,
        *,
        kms_client,
        key_version_name: str,
        signing_cert: asn1_x509.Certificate,
        cert_registry,
        kms_algorithm: str,
    ) -> None:
        super().__init__(
            signing_cert=signing_cert,
            cert_registry=cert_registry,
            signature_value=_kms_placeholder_size(kms_algorithm),
            prefer_pss=_kms_prefer_pss(kms_algorithm),
        )
        self._kms_client = kms_client
        self._key_version_name = key_version_name
        self._kms_algorithm = kms_algorithm

    def sign_raw(self, data: bytes, digest_algorithm: str) -> bytes:
        digest_name = str(digest_algorithm or "").strip().lower()
        if digest_name not in {"sha256", "sha384", "sha512"}:
            raise RuntimeError(f"Unsupported digest algorithm for Cloud KMS PDF signing: {digest_algorithm}")
        digest_bytes = hashlib.new(digest_name, data).digest()
        response = self._kms_client.asymmetric_sign(
            request={
                "name": self._key_version_name,
                "digest": {digest_name: digest_bytes},
            }
        )
        return bytes(response.signature or b"")


def _resolve_pdf_signing_mode() -> str:
    if _first_present(SIGNING_PDF_KMS_KEY_ENV, "SIGNING_AUDIT_KMS_KEY"):
        cert_present = any(
            [
                _optional_multiline_env(SIGNING_PDF_CERT_PEM_ENV),
                _optional_env(SIGNING_PDF_CERT_PEM_BASE64_ENV),
                _optional_env(SIGNING_PDF_CERT_PATH_ENV),
            ]
        )
        if cert_present:
            return SIGNING_PDF_DIGITAL_SIGNATURE_METHOD_GCP_KMS
    if any(
        [
            _optional_env(SIGNING_PDF_PKCS12_B64_ENV),
            _optional_env(SIGNING_PDF_P12_BASE64_ENV),
            _optional_env(SIGNING_PDF_P12_PATH_ENV),
        ]
    ):
        return SIGNING_PDF_DIGITAL_SIGNATURE_METHOD_PKCS12
    bundled_dev_cert_enabled = _optional_env_flag(SIGNING_PDF_USE_BUNDLED_DEV_CERT_ENV)
    if (
        not is_prod()
        and (bundled_dev_cert_enabled is None or bundled_dev_cert_enabled)
        and _DEV_CERT_PATH.exists()
        and _DEV_KEY_PATH.exists()
    ):
        return SIGNING_PDF_DIGITAL_SIGNATURE_METHOD_DEV_PEM
    return SIGNING_PDF_DIGITAL_SIGNATURE_METHOD_NONE


def pdf_signing_certificate_configured() -> bool:
    return _resolve_pdf_signing_mode() != SIGNING_PDF_DIGITAL_SIGNATURE_METHOD_NONE


def ensure_pdf_signing_certificate_configuration() -> None:
    if pdf_signing_certificate_configured():
        return
    if is_prod():
        raise RuntimeError(
            "Digital PDF signing is not configured. Set a PKCS#12 bundle via "
            f"{SIGNING_PDF_PKCS12_B64_ENV}/{SIGNING_PDF_P12_BASE64_ENV} or a Cloud KMS certificate/key via "
            f"{SIGNING_PDF_CERT_PEM_ENV}/{SIGNING_PDF_CERT_PEM_BASE64_ENV} and {SIGNING_PDF_KMS_KEY_ENV} "
            "before completing production signing requests."
        )


@lru_cache(maxsize=1)
def _resolve_pdf_signing_identity() -> _ResolvedPdfSigningIdentity:
    mode = _resolve_pdf_signing_mode()
    tsa_url = _optional_env(SIGNING_PDF_TSA_URL_ENV)

    if mode == SIGNING_PDF_DIGITAL_SIGNATURE_METHOD_NONE:
        return _ResolvedPdfSigningIdentity(
            signer=None,
            identity_source=SIGNING_PDF_DIGITAL_SIGNATURE_METHOD_NONE,
            signature_method=SIGNING_PDF_DIGITAL_SIGNATURE_METHOD_NONE,
            signature_algorithm=None,
            certificate_subject=None,
            certificate_issuer=None,
            certificate_serial_number=None,
            certificate_fingerprint_sha256=None,
            digest_algorithm="sha256",
            tsa_url=tsa_url,
        )

    if mode == SIGNING_PDF_DIGITAL_SIGNATURE_METHOD_DEV_PEM:
        signer = signers.SimpleSigner.load(
            str(_DEV_KEY_PATH),
            str(_DEV_CERT_PATH),
            key_passphrase=None,
        )
        if signer is None or signer.signing_cert is None:
            raise RuntimeError("Bundled development PDF signing identity could not be loaded.")
        subject, issuer, serial_number, fingerprint = _certificate_metadata(signer.signing_cert)
        return _ResolvedPdfSigningIdentity(
            signer=signer,
            identity_source="bundled_dev_fallback",
            signature_method=SIGNING_PDF_DIGITAL_SIGNATURE_METHOD_DEV_PEM,
            signature_algorithm=_signature_algorithm_for_certificate(
                signer.signing_cert,
                digest_algorithm=str(_optional_env("SIGNING_PDF_MD_ALGORITHM") or "sha256").lower(),
            ),
            certificate_subject=subject,
            certificate_issuer=issuer,
            certificate_serial_number=serial_number,
            certificate_fingerprint_sha256=fingerprint,
            digest_algorithm=str(_optional_env("SIGNING_PDF_MD_ALGORITHM") or "sha256").lower(),
            tsa_url=tsa_url,
        )

    if mode == SIGNING_PDF_DIGITAL_SIGNATURE_METHOD_PKCS12:
        pkcs12_bytes = _read_optional_base64_bytes(
            SIGNING_PDF_PKCS12_B64_ENV,
            SIGNING_PDF_P12_BASE64_ENV,
        ) or _read_optional_path_bytes(SIGNING_PDF_P12_PATH_ENV)
        password = _first_present(SIGNING_PDF_PKCS12_PASSWORD_ENV, SIGNING_PDF_P12_PASSWORD_ENV)
        if not pkcs12_bytes or password is None:
            raise RuntimeError(
                "PKCS#12 PDF signing requires PKCS#12 data and a password. Configure "
                f"{SIGNING_PDF_PKCS12_B64_ENV}/{SIGNING_PDF_P12_BASE64_ENV} or {SIGNING_PDF_P12_PATH_ENV} "
                f"together with {SIGNING_PDF_PKCS12_PASSWORD_ENV}/{SIGNING_PDF_P12_PASSWORD_ENV}."
            )
        signer = signers.SimpleSigner.load_pkcs12_data(
            pkcs12_bytes,
            other_certs=[],
            passphrase=password.encode("utf-8"),
        )
        subject, issuer, serial_number, fingerprint = _certificate_metadata(signer.signing_cert)
        return _ResolvedPdfSigningIdentity(
            signer=signer,
            identity_source="pkcs12_env",
            signature_method=SIGNING_PDF_DIGITAL_SIGNATURE_METHOD_PKCS12,
            signature_algorithm=(
                str(getattr(signer.signature_mechanism, "signature_algo", "") or "").strip()
                or _signature_algorithm_for_certificate(
                    signer.signing_cert,
                    digest_algorithm=str(_optional_env("SIGNING_PDF_MD_ALGORITHM") or "sha256").lower(),
                )
            ),
            certificate_subject=subject,
            certificate_issuer=issuer,
            certificate_serial_number=serial_number,
            certificate_fingerprint_sha256=fingerprint,
            digest_algorithm=str(_optional_env("SIGNING_PDF_MD_ALGORITHM") or "sha256").lower(),
            tsa_url=tsa_url,
        )

    cert_pem_text = _read_optional_text(
        SIGNING_PDF_CERT_PEM_ENV,
        path_names=(SIGNING_PDF_CERT_PATH_ENV,),
    )
    cert_pem_b64 = _optional_env(SIGNING_PDF_CERT_PEM_BASE64_ENV)
    if not cert_pem_text and cert_pem_b64:
        cert_pem_text = base64.b64decode(cert_pem_b64.encode("ascii"), validate=True).decode("utf-8")
    if not cert_pem_text:
        raise RuntimeError(
            f"{SIGNING_PDF_CERT_PEM_ENV}, {SIGNING_PDF_CERT_PEM_BASE64_ENV}, or {SIGNING_PDF_CERT_PATH_ENV} "
            "must be configured for Cloud KMS PDF signing."
        )
    chain_pem_text = _read_optional_text(
        SIGNING_PDF_CERT_CHAIN_PEM_ENV,
        path_names=(SIGNING_PDF_CERT_CHAIN_PATH_ENV,),
    )
    chain_pem_b64 = _optional_env(SIGNING_PDF_CERT_CHAIN_PEM_BASE64_ENV)
    if not chain_pem_text and chain_pem_b64:
        chain_pem_text = base64.b64decode(chain_pem_b64.encode("ascii"), validate=True).decode("utf-8")

    signing_certs = _load_pem_certificates(cert_pem_text)
    if not signing_certs:
        raise RuntimeError("Could not parse the configured PDF signing certificate.")
    signing_cert = signing_certs[0]
    extra_certs = _load_pem_certificates(chain_pem_text) if chain_pem_text else []
    cert_store = SimpleCertificateStore()
    for extra_cert in extra_certs:
        cert_store.register(extra_cert)

    kms = _require_kms_module()
    kms_client = kms.KeyManagementServiceClient()
    key_name = _first_present(SIGNING_PDF_KMS_KEY_ENV, "SIGNING_AUDIT_KMS_KEY")
    key_version_name, kms_algorithm = _resolve_kms_key_version(kms_client, key_name or "")
    kms_public = load_pem_public_key(str(kms_client.get_public_key(name=key_version_name).pem or "").encode("utf-8"))
    cert_public = x509.load_der_x509_certificate(signing_cert.dump()).public_key()
    if cert_public.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ) != kms_public.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ):
        raise RuntimeError("The configured PDF signing certificate does not match the Cloud KMS signing key")

    signer = _GoogleKmsPdfSigner(
        kms_client=kms_client,
        key_version_name=key_version_name,
        signing_cert=signing_cert,
        cert_registry=cert_store,
        kms_algorithm=kms_algorithm,
    )
    subject, issuer, serial_number, fingerprint = _certificate_metadata(signing_cert)
    return _ResolvedPdfSigningIdentity(
        signer=signer,
        identity_source="gcp_kms",
        signature_method=SIGNING_PDF_DIGITAL_SIGNATURE_METHOD_GCP_KMS,
        signature_algorithm=kms_algorithm,
        certificate_subject=subject,
        certificate_issuer=issuer,
        certificate_serial_number=serial_number,
        certificate_fingerprint_sha256=fingerprint,
        digest_algorithm=_kms_digest_for_algorithm(kms_algorithm),
        tsa_url=tsa_url,
    )


def export_pdf_signing_certificate_pem() -> bytes:
    """Return the active signing certificate in PEM form for validation tooling."""

    mode = _resolve_pdf_signing_mode()
    if mode == SIGNING_PDF_DIGITAL_SIGNATURE_METHOD_PKCS12:
        pkcs12_bytes = _read_optional_base64_bytes(
            SIGNING_PDF_PKCS12_B64_ENV,
            SIGNING_PDF_P12_BASE64_ENV,
        ) or _read_optional_path_bytes(SIGNING_PDF_P12_PATH_ENV)
        password = _first_present(SIGNING_PDF_PKCS12_PASSWORD_ENV, SIGNING_PDF_P12_PASSWORD_ENV)
        if not pkcs12_bytes or password is None:
            raise RuntimeError("Active PKCS#12 PDF signing identity is incomplete.")
        _key, cert, _cas = pkcs12.load_key_and_certificates(pkcs12_bytes, password.encode("utf-8"))
        if cert is None:
            raise RuntimeError("Active PKCS#12 PDF signing identity does not include a certificate.")
        return cert.public_bytes(serialization.Encoding.PEM)

    cert_pem_text = _read_optional_text(
        SIGNING_PDF_CERT_PEM_ENV,
        path_names=(SIGNING_PDF_CERT_PATH_ENV,),
    )
    cert_pem_b64 = _optional_env(SIGNING_PDF_CERT_PEM_BASE64_ENV)
    if cert_pem_text:
        return cert_pem_text.encode("utf-8")
    if cert_pem_b64:
        return base64.b64decode(cert_pem_b64.encode("ascii"), validate=True)
    if _resolve_pdf_signing_mode() == SIGNING_PDF_DIGITAL_SIGNATURE_METHOD_DEV_PEM and _DEV_CERT_PATH.exists():
        return _DEV_CERT_PATH.read_bytes()
    raise RuntimeError("No PDF signing certificate is configured.")


def _extract_self_signed_validation_root_from_pem(pem_bytes: bytes) -> Optional[asn1_x509.Certificate]:
    try:
        certs = _load_pem_certificates(pem_bytes.decode("utf-8"))
    except Exception:
        return None
    for cert in certs:
        if cert.subject == cert.issuer:
            return cert
    return None


def _build_local_signer_validation_context(embedded_signature: Any) -> Optional[ValidationContext]:
    """Trust matching local self-signed signing identities outside production.

    Local development commonly uses a bundled or ad hoc self-signed signing
    certificate. pyHanko logs those as path-building failures unless the caller
    explicitly trusts the signing certificate. Restrict the override to
    non-production validation and only when the embedded signer matches a local
    self-signed identity we control, so prod validation semantics still reflect
    the real certificate chain.
    """

    if is_prod():
        return None

    signer_cert = getattr(embedded_signature, "signer_cert", None)
    if signer_cert is None:
        return None

    candidate_roots: list[asn1_x509.Certificate] = []
    if _DEV_CERT_PATH.exists():
        bundled_root = _extract_self_signed_validation_root_from_pem(_DEV_CERT_PATH.read_bytes())
        if bundled_root is not None:
            candidate_roots.append(bundled_root)

    try:
        active_cert_pem = export_pdf_signing_certificate_pem()
    except Exception:
        active_cert_pem = b""
    if active_cert_pem:
        active_root = _extract_self_signed_validation_root_from_pem(active_cert_pem)
        if active_root is not None and all(active_root.dump() != root.dump() for root in candidate_roots):
            candidate_roots.append(active_root)

    for root in candidate_roots:
        if signer_cert.dump() == root.dump():
            return ValidationContext(trust_roots=[root])
    return None


def _build_signature_reason(source_document_name: str) -> str:
    normalized_name = " ".join(str(source_document_name or "").strip().split()) or "document"
    return f"DullyPDF electronic signature for {normalized_name}"[:180]


def _build_unsigned_pdf_digital_signing_result(pdf_bytes: bytes) -> PdfDigitalSigningResult:
    return PdfDigitalSigningResult(
        pdf_bytes=bytes(pdf_bytes or b""),
        signature_info=PdfDigitalSignatureInfo(
            field_name=None,
            certificate_subject=None,
            certificate_issuer=None,
            certificate_serial_number=None,
            certificate_fingerprint_sha256=None,
            digest_algorithm=None,
            subfilter=None,
            identity_source=None,
            signature_method=None,
            signature_algorithm=None,
            timestamped=False,
        ),
    )


def _prepare_pdf_signing_execution(
    *,
    pdf_bytes: bytes,
    signer_name: str,
    source_document_name: str,
) -> tuple[_ResolvedPdfSigningIdentity, Any, IncrementalPdfFileWriter, BytesIO] | None:
    identity = _resolve_pdf_signing_identity()
    if identity.signer is None:
        # Embedded PDF signatures are optional. Completion should still
        # finalize the retained signed artifact when no signing identity is
        # configured, and downstream validation already treats the missing
        # embedded signature as informational rather than fatal.
        return None

    signer_display_name = " ".join(str(signer_name or "").strip().split()) or "Signer"
    metadata = signers.PdfSignatureMetadata(
        field_name=SIGNING_PDF_DIGITAL_SIGNATURE_FIELD_NAME,
        md_algorithm=identity.digest_algorithm,
        location=SIGNING_PDF_SIGNATURE_LOCATION,
        reason=_build_signature_reason(source_document_name),
        name=signer_display_name[:200],
        subfilter=fields.SigSeedSubFilter.PADES,
    )
    # Some valid PDFs produced by lightweight generators use cross-reference
    # details that pyHanko treats strictly by default. Signing should accept
    # those files and preserve them via an incremental update rather than
    # rejecting the ceremony at completion time.
    writer = IncrementalPdfFileWriter(BytesIO(bytes(pdf_bytes or b"")), strict=False)
    fields.append_signature_field(
        writer,
        fields.SigFieldSpec(
            sig_field_name=SIGNING_PDF_DIGITAL_SIGNATURE_FIELD_NAME,
            on_page=0,
            box=(0, 0, 0, 0),
        ),
    )
    output = BytesIO()
    timestamper = HTTPTimeStamper(identity.tsa_url) if identity.tsa_url else None
    pdf_signer = signers.PdfSigner(metadata, signer=identity.signer, timestamper=timestamper)
    return identity, pdf_signer, writer, output


def _build_pdf_digital_signing_result(
    *,
    pdf_bytes: bytes,
    identity: _ResolvedPdfSigningIdentity,
) -> PdfDigitalSigningResult:
    return PdfDigitalSigningResult(
        pdf_bytes=pdf_bytes,
        signature_info=PdfDigitalSignatureInfo(
            field_name=SIGNING_PDF_DIGITAL_SIGNATURE_FIELD_NAME,
            certificate_subject=identity.certificate_subject,
            certificate_issuer=identity.certificate_issuer,
            certificate_serial_number=identity.certificate_serial_number,
            certificate_fingerprint_sha256=identity.certificate_fingerprint_sha256,
            digest_algorithm=identity.digest_algorithm,
            subfilter=SIGNING_PDF_DIGITAL_SIGNATURE_SUBFILTER,
            identity_source=identity.identity_source,
            signature_method=identity.signature_method,
            signature_algorithm=identity.signature_algorithm,
            timestamped=bool(identity.tsa_url),
        ),
    )


def apply_digital_pdf_signature(
    *,
    pdf_bytes: bytes,
    signer_name: str,
    source_document_name: str,
) -> PdfDigitalSigningResult:
    execution = _prepare_pdf_signing_execution(
        pdf_bytes=pdf_bytes,
        signer_name=signer_name,
        source_document_name=source_document_name,
    )
    if execution is None:
        return _build_unsigned_pdf_digital_signing_result(pdf_bytes)
    identity, pdf_signer, writer, output = execution
    pdf_signer.sign_pdf(writer, output=output)
    return _build_pdf_digital_signing_result(
        pdf_bytes=output.getvalue(),
        identity=identity,
    )


async def async_apply_digital_pdf_signature(
    *,
    pdf_bytes: bytes,
    signer_name: str,
    source_document_name: str,
) -> PdfDigitalSigningResult:
    execution = _prepare_pdf_signing_execution(
        pdf_bytes=pdf_bytes,
        signer_name=signer_name,
        source_document_name=source_document_name,
    )
    if execution is None:
        return _build_unsigned_pdf_digital_signing_result(pdf_bytes)
    identity, pdf_signer, writer, output = execution
    await pdf_signer.async_sign_pdf(writer, output=output)
    return _build_pdf_digital_signing_result(
        pdf_bytes=output.getvalue(),
        identity=identity,
    )


def validate_digital_pdf_signature(
    pdf_bytes: bytes,
    *,
    expected_sha256: Optional[str] = None,
) -> PdfDigitalSignatureValidation:
    validation_target = _prepare_pdf_signature_validation_target(
        pdf_bytes,
        expected_sha256=expected_sha256,
    )
    if isinstance(validation_target, PdfDigitalSignatureValidation):
        return validation_target

    embedded_signature, signature_count, expected_matches, actual_sha256, signer_validation_context = validation_target
    status = validate_pdf_signature(
        embedded_signature,
        signer_validation_context=signer_validation_context,
    )
    return _build_pdf_signature_validation_result(
        status=status,
        embedded_signature=embedded_signature,
        signature_count=signature_count,
        expected_matches=expected_matches,
        actual_sha256=actual_sha256,
    )


async def async_validate_digital_pdf_signature(
    pdf_bytes: bytes,
    *,
    expected_sha256: Optional[str] = None,
) -> PdfDigitalSignatureValidation:
    # pyHanko's sync validator wraps the async path with ``asyncio.run()``,
    # which is incompatible with the FastAPI request event loop that drives the
    # public validation route.
    validation_target = _prepare_pdf_signature_validation_target(
        pdf_bytes,
        expected_sha256=expected_sha256,
    )
    if isinstance(validation_target, PdfDigitalSignatureValidation):
        return validation_target

    embedded_signature, signature_count, expected_matches, actual_sha256, signer_validation_context = validation_target
    status = await async_validate_pdf_signature(
        embedded_signature,
        signer_validation_context=signer_validation_context,
    )
    return _build_pdf_signature_validation_result(
        status=status,
        embedded_signature=embedded_signature,
        signature_count=signature_count,
        expected_matches=expected_matches,
        actual_sha256=actual_sha256,
    )


def _prepare_pdf_signature_validation_target(
    pdf_bytes: bytes,
    *,
    expected_sha256: Optional[str],
) -> PdfDigitalSignatureValidation | tuple[Any, int, Optional[bool], str, Optional[ValidationContext]]:
    actual_sha256 = hashlib.sha256(bytes(pdf_bytes or b"")).hexdigest()
    expected_matches = None
    if expected_sha256:
        expected_matches = str(expected_sha256).strip().lower() == actual_sha256

    if not pdf_bytes:
        return _build_absent_pdf_signature_validation(
            summary="missing_pdf",
            expected_matches=expected_matches,
            actual_sha256=actual_sha256,
        )

    reader = PdfFileReader(BytesIO(pdf_bytes), strict=False)
    embedded_signatures = list(reader.embedded_signatures)
    if not embedded_signatures:
        return _build_absent_pdf_signature_validation(
            summary="missing_signature",
            expected_matches=expected_matches,
            actual_sha256=actual_sha256,
        )

    embedded_signature = embedded_signatures[-1]
    signer_validation_context = _build_local_signer_validation_context(embedded_signature)
    return embedded_signature, len(embedded_signatures), expected_matches, actual_sha256, signer_validation_context


def _build_absent_pdf_signature_validation(
    *,
    summary: str,
    expected_matches: Optional[bool],
    actual_sha256: str,
) -> PdfDigitalSignatureValidation:
    return PdfDigitalSignatureValidation(
        present=False,
        valid=False,
        intact=False,
        trusted=False,
        summary=summary,
        signature_count=0,
        field_name=None,
        subfilter=None,
        coverage=None,
        modification_level=None,
        timestamp_present=False,
        timestamp_valid=None,
        certificate_subject=None,
        certificate_issuer=None,
        certificate_serial_number=None,
        certificate_fingerprint_sha256=None,
        expected_sha256_matches=expected_matches,
        actual_sha256=actual_sha256,
    )


def _build_pdf_signature_validation_result(
    *,
    status: Any,
    embedded_signature: Any,
    signature_count: int,
    expected_matches: Optional[bool],
    actual_sha256: str,
) -> PdfDigitalSignatureValidation:
    timestamp_status = getattr(status, "timestamp_validity", None)
    signer_cert = embedded_signature.signer_cert
    try:
        subfilter = str(embedded_signature.sig_object.get("/SubFilter"))
    except Exception:
        subfilter = None
    return PdfDigitalSignatureValidation(
        present=True,
        valid=bool(getattr(status, "valid", False)),
        intact=bool(getattr(status, "intact", False)),
        trusted=bool(getattr(status, "trusted", False)),
        summary=str(status.summary()),
        signature_count=signature_count,
        field_name=getattr(embedded_signature, "field_name", None),
        subfilter=subfilter,
        coverage=getattr(getattr(status, "coverage", None), "name", None),
        modification_level=getattr(getattr(status, "modification_level", None), "name", None),
        timestamp_present=timestamp_status is not None,
        timestamp_valid=(bool(timestamp_status.valid) if timestamp_status is not None else None),
        certificate_subject=(signer_cert.subject.human_friendly if signer_cert is not None else None),
        certificate_issuer=(signer_cert.issuer.human_friendly if signer_cert is not None else None),
        certificate_serial_number=(format(signer_cert.serial_number, "x") if signer_cert is not None else None),
        certificate_fingerprint_sha256=(
            hashlib.sha256(signer_cert.dump()).hexdigest() if signer_cert is not None else None
        ),
        expected_sha256_matches=expected_matches,
        actual_sha256=actual_sha256,
    )
