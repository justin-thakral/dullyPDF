"""Signing policy helpers, public token handling, and serialization utilities."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import getaddresses
import hashlib
import hmac
import ipaddress
import re
import secrets
import time
from typing import Any, Dict, List, Optional

from backend.env_utils import env_value as _env_value, int_env as _int_env
from backend.logging_config import get_logger
from backend.services.pdf_service import sanitize_basename_segment


logger = get_logger(__name__)

_PUBLIC_TOKEN_PREFIX = "v1"
_SESSION_TOKEN_PREFIX = "s1"
_ARTIFACT_TOKEN_PREFIX = "a1"
_VALIDATION_TOKEN_PREFIX = "sv1"
_DEV_SIGNING_TOKEN_SECRET = "dullypdf-dev-signing-link-secret-local-only"
_WARNED_DEV_SIGNING_TOKEN_SECRET = False
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

SIGNING_STATUS_DRAFT = "draft"
SIGNING_STATUS_INVALIDATED = "invalidated"
SIGNING_STATUS_SENT = "sent"
SIGNING_STATUS_COMPLETED = "completed"

SIGNING_MODE_SIGN = "sign"
SIGNING_MODE_FILL_AND_SIGN = "fill_and_sign"
SIGNING_MODES = frozenset({SIGNING_MODE_SIGN, SIGNING_MODE_FILL_AND_SIGN})

SIGNATURE_MODE_BUSINESS = "business"
SIGNATURE_MODE_CONSUMER = "consumer"
SIGNATURE_MODES = frozenset({SIGNATURE_MODE_BUSINESS, SIGNATURE_MODE_CONSUMER})

SIGNATURE_ADOPTED_MODE_DEFAULT = "default"
SIGNATURE_ADOPTED_MODE_TYPED = "typed"
SIGNATURE_ADOPTED_MODE_DRAWN = "drawn"
SIGNATURE_ADOPTED_MODE_UPLOADED = "uploaded"
SIGNATURE_ADOPTED_MODES = frozenset(
    {
        SIGNATURE_ADOPTED_MODE_DEFAULT,
        SIGNATURE_ADOPTED_MODE_TYPED,
        SIGNATURE_ADOPTED_MODE_DRAWN,
        SIGNATURE_ADOPTED_MODE_UPLOADED,
    }
)

SIGNING_DISCLOSURE_VERSION_BUSINESS = "us-esign-business-v1"
SIGNING_DISCLOSURE_VERSION_CONSUMER = "us-esign-consumer-v1"

SIGNING_EVENT_SESSION_STARTED = "session_started"
SIGNING_EVENT_OPENED = "opened"
SIGNING_EVENT_REVIEW_CONFIRMED = "review_confirmed"
SIGNING_EVENT_CONSENT_ACCEPTED = "consent_accepted"
SIGNING_EVENT_SIGNATURE_ADOPTED = "signature_adopted"
SIGNING_EVENT_MANUAL_FALLBACK_REQUESTED = "manual_fallback_requested"
SIGNING_EVENT_CONSENT_WITHDRAWN = "consent_withdrawn"
SIGNING_EVENT_COMPLETED = "completed"
SIGNING_EVENT_DOCUMENT_ACCESSED = "document_accessed"
SIGNING_EVENT_REQUEST_CREATED = "request_created"
SIGNING_EVENT_REQUEST_SENT = "request_sent"
SIGNING_EVENT_INVITE_SENT = "invite_sent"
SIGNING_EVENT_INVITE_FAILED = "invite_failed"
SIGNING_EVENT_INVITE_SKIPPED = "invite_skipped"
SIGNING_EVENT_MANUAL_LINK_SHARED = "manual_link_shared"
SIGNING_EVENT_LINK_REVOKED = "link_revoked"
SIGNING_EVENT_LINK_REISSUED = "link_reissued"
SIGNING_EVENT_VERIFICATION_STARTED = "verification_started"
SIGNING_EVENT_VERIFICATION_RESENT = "verification_resent"
SIGNING_EVENT_VERIFICATION_FAILED = "verification_failed"
SIGNING_EVENT_VERIFICATION_PASSED = "verification_passed"
SIGNING_EVENT_CONSUMER_ACCESS_FAILED = "consumer_access_failed"

SIGNING_INVITE_METHOD_EMAIL = "email"
SIGNING_INVITE_METHOD_MANUAL_LINK = "manual_link"
SIGNING_SIGNER_CONTACT_METHOD_EMAIL = "email"
SIGNING_SIGNER_CONTACT_METHODS = frozenset({SIGNING_SIGNER_CONTACT_METHOD_EMAIL})

SIGNING_ARTIFACT_SIGNED_PDF = "signed_pdf"
SIGNING_ARTIFACT_SOURCE_PDF = "source_pdf"
SIGNING_ARTIFACT_AUDIT_MANIFEST = "audit_manifest"
SIGNING_ARTIFACT_AUDIT_RECEIPT = "audit_receipt"
SIGNING_ARTIFACT_KEYS = frozenset(
    {
        SIGNING_ARTIFACT_SOURCE_PDF,
        SIGNING_ARTIFACT_SIGNED_PDF,
        SIGNING_ARTIFACT_AUDIT_MANIFEST,
        SIGNING_ARTIFACT_AUDIT_RECEIPT,
    }
)

SIGNING_EXCLUDED_DOCUMENT_CATEGORIES: Dict[str, Dict[str, str]] = {
    "will_trust_estate": {
        "label": "Wills, codicils, or testamentary trusts",
        "reason": "E-sign is blocked for estate-planning categories in DullyPDF v1.",
    },
    "family_law": {
        "label": "Adoption, divorce, or family law",
        "reason": "Family-law categories require separate legal review and are blocked in DullyPDF v1.",
    },
    "court_document": {
        "label": "Court orders, notices, or court documents",
        "reason": "Court-facing document categories are blocked in DullyPDF v1.",
    },
    "ucc_governed_record": {
        "label": "UCC-governed records outside the Articles 2 and 2A carve-outs",
        "reason": "Most UCC-governed records are excluded from DullyPDF's U.S. e-sign flow.",
    },
    "utility_termination": {
        "label": "Utility termination notices",
        "reason": "Utility termination notices are excluded from DullyPDF e-sign workflows.",
    },
    "foreclosure_eviction_primary_residence": {
        "label": "Foreclosure, eviction, repossession, or right-to-cure notices for a primary residence",
        "reason": "Primary-residence foreclosure and eviction notices are blocked in DullyPDF v1.",
    },
    "insurance_benefit_cancellation": {
        "label": "Health or life insurance cancellation or termination notices",
        "reason": "Insurance cancellation notices are blocked in DullyPDF v1.",
    },
    "product_recall_or_material_failure": {
        "label": "Product recall or material-failure notices affecting health or safety",
        "reason": "Product-recall and material-failure notices are excluded from DullyPDF e-sign workflows.",
    },
    "hazardous_material_transport": {
        "label": "Hazardous, pesticide, toxic, or dangerous-material transport documents",
        "reason": "Dangerous-material transport and handling documents are blocked in DullyPDF v1.",
    },
    "notarization_required": {
        "label": "Documents requiring notarization or acknowledgment",
        "reason": "Notarized workflows are out of scope for DullyPDF v1.",
    },
}

SIGNING_ALLOWED_DOCUMENT_CATEGORIES: Dict[str, str] = {
    "ordinary_business_form": "Ordinary business form",
    "client_intake_form": "Client intake form",
    "authorization_consent_form": "Authorization or consent form",
    "acknowledgment_receipt": "Acknowledgment or receipt",
    "vendor_service_agreement": "Vendor or service agreement",
    "employment_internal_form": "Internal employment form",
}

SIGNING_DISCLOSURE_TEXTS: Dict[str, List[str]] = {
    SIGNING_DISCLOSURE_VERSION_CONSUMER: [
        "You may request paper or manual handling instead of signing electronically.",
        "You may withdraw electronic consent before completion. If you do, this electronic signing request stops and you must use a paper or manual alternative.",
        "This consent applies only to this signing request and the records tied to it.",
        "If your email or contact information changes before completion, contact the sender and request a fresh invitation.",
        "You may request a paper copy after consenting. DullyPDF does not charge a platform fee for that request workflow.",
        "You need a device, browser, and PDF-capable software that can open, display, print, and save PDF records.",
    ],
    SIGNING_DISCLOSURE_VERSION_BUSINESS: [
        "By proceeding you agree to sign this document electronically under the US ESIGN Act and applicable state UETA provisions.",
    ],
}

SIGNING_VERIFICATION_METHOD_EMAIL_OTP = "email_otp"
SIGNING_SIGNER_AUTH_METHOD_NONE = "none"
SIGNING_SIGNER_AUTH_METHODS = frozenset(
    {
        SIGNING_VERIFICATION_METHOD_EMAIL_OTP,
        SIGNING_SIGNER_AUTH_METHOD_NONE,
    }
)
SIGNING_VERIFICATION_SUPPORTED_SOURCE_TYPES = frozenset({"workspace", "fill_link_response", "uploaded_pdf"})
_DEFAULT_SIGNING_VERIFICATION_SOURCE_TYPES = SIGNING_VERIFICATION_SUPPORTED_SOURCE_TYPES
SIGNING_MIN_RETENTION_DAYS = 2555
SIGNING_CONSUMER_CONSENT_SCOPE_DEFAULT = (
    "This consent applies only to this signing request and its related electronic records."
)
SIGNING_CONSUMER_HARDWARE_SOFTWARE = [
    "A current web browser that can load this signing page over the internet.",
    "Software or browser support that can open, display, print, and save PDF files.",
    "A device with enough storage or printing capability to retain a copy of the records.",
]


@dataclass(frozen=True)
class SigningCategoryOption:
    key: str
    label: str
    blocked: bool
    reason: Optional[str] = None


@dataclass(frozen=True)
class SigningSignerTransport:
    signer_contact_method: str
    signer_auth_method: str
    invite_method: Optional[str]
    verification_required: bool
    verification_method: Optional[str]


def _urlsafe_b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _urlsafe_b64decode(value: str) -> bytes:
    padded = value + ("=" * ((4 - (len(value) % 4)) % 4))
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _normalize_key(value: Optional[str]) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    return _NON_ALNUM_RE.sub("_", raw).strip("_")


def _is_prod_env() -> bool:
    return (_env_value("ENV") or "").strip().lower() in {"prod", "production"}


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    return max(minimum, _int_env(name, default))


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def signing_token_secret_is_weak(secret: Optional[str]) -> bool:
    normalized = (secret or "").strip()
    if not normalized:
        return True
    if normalized in {
        "change_me_prod_signing_token_secret",
        "dullypdf-signing-dev-secret",
        "signing-secret",
    }:
        return True
    return len(normalized) < 32


def _resolve_signing_token_secret() -> str:
    global _WARNED_DEV_SIGNING_TOKEN_SECRET
    secret = (_env_value("SIGNING_LINK_TOKEN_SECRET") or "").strip()
    if secret and not (_is_prod_env() and signing_token_secret_is_weak(secret)):
        return secret
    if _is_prod_env():
        raise RuntimeError("SIGNING_LINK_TOKEN_SECRET must be unique and at least 32 characters in production")
    fallback_secret = (_env_value("FILL_LINK_TOKEN_SECRET") or "").strip()
    if fallback_secret:
        if not _WARNED_DEV_SIGNING_TOKEN_SECRET:
            logger.warning(
                "SIGNING_LINK_TOKEN_SECRET is unset outside production; reusing FILL_LINK_TOKEN_SECRET as a stable "
                "local signing-token fallback. Set SIGNING_LINK_TOKEN_SECRET explicitly if you need a separate dev secret."
            )
            _WARNED_DEV_SIGNING_TOKEN_SECRET = True
        return fallback_secret
    if not _WARNED_DEV_SIGNING_TOKEN_SECRET:
        logger.warning(
            "SIGNING_LINK_TOKEN_SECRET is unset outside production; using a built-in stable dev fallback secret. "
            "Set SIGNING_LINK_TOKEN_SECRET explicitly if you need a separate local signing secret."
        )
        _WARNED_DEV_SIGNING_TOKEN_SECRET = True
    return _DEV_SIGNING_TOKEN_SECRET


def normalize_signing_public_link_version(value: Any) -> int:
    try:
        normalized = int(str(value or "").strip() or "1")
    except (TypeError, ValueError):
        return 1
    return normalized if normalized > 0 else 1


def resolve_signing_public_link_version(record) -> int:
    return normalize_signing_public_link_version(getattr(record, "public_link_version", None))


def _legacy_signing_request_signature(request_id: str) -> str:
    digest = hmac.new(
        _resolve_signing_token_secret().encode("utf-8"),
        f"signing_request:{request_id}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _urlsafe_b64encode(digest)


def _signing_request_signature(request_id: str, public_link_version: int) -> str:
    digest = hmac.new(
        _resolve_signing_token_secret().encode("utf-8"),
        f"signing_request:{request_id}:{int(public_link_version)}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _urlsafe_b64encode(digest)


def _signing_validation_signature(request_id: str) -> str:
    digest = hmac.new(
        _resolve_signing_token_secret().encode("utf-8"),
        f"signing_validation:{request_id}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _urlsafe_b64encode(digest)


def build_signing_public_token(request_id: str, public_link_version: Optional[int] = None) -> str:
    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id:
        raise ValueError("request_id is required")
    normalized_link_version = normalize_signing_public_link_version(public_link_version)
    payload = _urlsafe_b64encode(f"{normalized_request_id}:{normalized_link_version}".encode("utf-8"))
    return ".".join(
        [
            _PUBLIC_TOKEN_PREFIX,
            payload,
            _signing_request_signature(normalized_request_id, normalized_link_version),
        ]
    )


def build_signing_validation_token(request_id: str) -> str:
    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id:
        raise ValueError("request_id is required")
    payload = _urlsafe_b64encode(normalized_request_id.encode("utf-8"))
    return ".".join(
        [
            _VALIDATION_TOKEN_PREFIX,
            payload,
            _signing_validation_signature(normalized_request_id),
        ]
    )


def parse_signing_public_token_payload(token: Optional[str]) -> Optional[tuple[str, int]]:
    normalized = re.sub(r"[^A-Za-z0-9_.-]", "", str(token or "").strip())
    if not normalized:
        return None
    parts = normalized.split(".")
    if len(parts) != 3 or parts[0] != _PUBLIC_TOKEN_PREFIX:
        return None
    try:
        payload = _urlsafe_b64decode(parts[1]).decode("utf-8").strip()
    except Exception:
        return None
    if not payload:
        return None

    if ":" in payload:
        request_id, version_text = payload.rsplit(":", 1)
        request_id = request_id.strip()
        if not request_id:
            return None
        try:
            public_link_version = normalize_signing_public_link_version(int(version_text))
        except (TypeError, ValueError):
            return None
        expected_signature = _signing_request_signature(request_id, public_link_version)
        if not hmac.compare_digest(parts[2], expected_signature):
            return None
        return request_id, public_link_version

    request_id = payload
    expected_signature = _legacy_signing_request_signature(request_id)
    if not hmac.compare_digest(parts[2], expected_signature):
        return None
    return request_id, 1


def parse_signing_validation_token(token: Optional[str]) -> Optional[str]:
    normalized = re.sub(r"[^A-Za-z0-9_.-]", "", str(token or "").strip())
    if not normalized:
        return None
    parts = normalized.split(".")
    if len(parts) != 3 or parts[0] != _VALIDATION_TOKEN_PREFIX:
        return None
    try:
        request_id = _urlsafe_b64decode(parts[1]).decode("utf-8").strip()
    except Exception:
        return None
    if not request_id:
        return None
    expected_signature = _signing_validation_signature(request_id)
    if not hmac.compare_digest(parts[2], expected_signature):
        return None
    return request_id


def parse_signing_public_token(token: Optional[str]) -> Optional[str]:
    parsed = parse_signing_public_token_payload(token)
    if parsed is None:
        return None
    return parsed[0]


def build_signing_public_path(request_id: str, public_link_version: Optional[int] = None) -> str:
    return f"/sign/{build_signing_public_token(request_id, public_link_version)}"


def build_signing_validation_path(request_id: str) -> str:
    return f"/verify-signing/{build_signing_validation_token(request_id)}"


def _signing_session_signature(request_id: str, session_id: str, expires_at_epoch: int) -> str:
    digest = hmac.new(
        _resolve_signing_token_secret().encode("utf-8"),
        f"signing_session:{request_id}:{session_id}:{int(expires_at_epoch)}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _urlsafe_b64encode(digest)


def build_signing_public_session_token(request_id: str, session_id: str, expires_at_epoch: int) -> str:
    normalized_request_id = str(request_id or "").strip()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_request_id or not normalized_session_id:
        raise ValueError("request_id and session_id are required")
    expiry = int(expires_at_epoch)
    if expiry <= 0:
        raise ValueError("expires_at_epoch must be positive")
    return ".".join(
        [
            _SESSION_TOKEN_PREFIX,
            _urlsafe_b64encode(normalized_request_id.encode("utf-8")),
            _urlsafe_b64encode(normalized_session_id.encode("utf-8")),
            str(expiry),
            _signing_session_signature(normalized_request_id, normalized_session_id, expiry),
        ]
    )


def parse_signing_public_session_token(token: Optional[str]) -> Optional[tuple[str, str, int]]:
    normalized = re.sub(r"[^A-Za-z0-9_.-]", "", str(token or "").strip())
    if not normalized:
        return None
    parts = normalized.split(".")
    if len(parts) != 5 or parts[0] != _SESSION_TOKEN_PREFIX:
        return None
    try:
        request_id = _urlsafe_b64decode(parts[1]).decode("utf-8").strip()
        session_id = _urlsafe_b64decode(parts[2]).decode("utf-8").strip()
        expires_at_epoch = int(parts[3])
    except Exception:
        return None
    if not request_id or not session_id or expires_at_epoch <= 0:
        return None
    expected_signature = _signing_session_signature(request_id, session_id, expires_at_epoch)
    if not hmac.compare_digest(parts[4], expected_signature):
        return None
    if expires_at_epoch < int(time.time()):
        return None
    return request_id, session_id, expires_at_epoch


def _signing_artifact_signature(
    request_id: str,
    session_id: str,
    artifact_key: str,
    expires_at_epoch: int,
) -> str:
    digest = hmac.new(
        _resolve_signing_token_secret().encode("utf-8"),
        f"signing_artifact:{request_id}:{session_id}:{artifact_key}:{int(expires_at_epoch)}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _urlsafe_b64encode(digest)


def build_signing_public_artifact_token(
    request_id: str,
    session_id: str,
    artifact_key: str,
    expires_at_epoch: int,
) -> str:
    normalized_request_id = str(request_id or "").strip()
    normalized_session_id = str(session_id or "").strip()
    normalized_artifact_key = normalize_signing_artifact_key(artifact_key)
    expiry = int(expires_at_epoch)
    if not normalized_request_id or not normalized_session_id:
        raise ValueError("request_id and session_id are required")
    if expiry <= 0:
        raise ValueError("expires_at_epoch must be positive")
    return ".".join(
        [
            _ARTIFACT_TOKEN_PREFIX,
            _urlsafe_b64encode(normalized_request_id.encode("utf-8")),
            _urlsafe_b64encode(normalized_session_id.encode("utf-8")),
            _urlsafe_b64encode(normalized_artifact_key.encode("utf-8")),
            str(expiry),
            _signing_artifact_signature(
                normalized_request_id,
                normalized_session_id,
                normalized_artifact_key,
                expiry,
            ),
        ]
    )


def parse_signing_public_artifact_token(token: Optional[str]) -> Optional[tuple[str, str, str, int]]:
    normalized = re.sub(r"[^A-Za-z0-9_.-]", "", str(token or "").strip())
    if not normalized:
        return None
    parts = normalized.split(".")
    if len(parts) != 6 or parts[0] != _ARTIFACT_TOKEN_PREFIX:
        return None
    try:
        request_id = _urlsafe_b64decode(parts[1]).decode("utf-8").strip()
        session_id = _urlsafe_b64decode(parts[2]).decode("utf-8").strip()
        artifact_key = _urlsafe_b64decode(parts[3]).decode("utf-8").strip()
        expires_at_epoch = int(parts[4])
    except Exception:
        return None
    if not request_id or not session_id or expires_at_epoch <= 0:
        return None
    try:
        normalized_artifact_key = normalize_signing_artifact_key(artifact_key)
    except ValueError:
        return None
    expected_signature = _signing_artifact_signature(
        request_id,
        session_id,
        normalized_artifact_key,
        expires_at_epoch,
    )
    if not hmac.compare_digest(parts[5], expected_signature):
        return None
    if expires_at_epoch < int(time.time()):
        return None
    return request_id, session_id, normalized_artifact_key, expires_at_epoch


def sha256_hex_for_bytes(raw_bytes: bytes) -> str:
    return hashlib.sha256(raw_bytes or b"").hexdigest()


def build_signing_link_token_id(token: Optional[str]) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]", "", str(token or "").strip())
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def resolve_signing_session_ttl_seconds() -> int:
    return _env_int("SIGNING_SESSION_TTL_SECONDS", 3600, minimum=300)


def resolve_signing_artifact_token_ttl_seconds() -> int:
    return _env_int("SIGNING_ARTIFACT_TOKEN_TTL_SECONDS", 300, minimum=30)


def resolve_signing_request_ttl_days() -> int:
    return _env_int("SIGNING_REQUEST_TTL_DAYS", 30, minimum=1)


def resolve_signing_verification_source_types() -> set[str]:
    raw = str(_env_value("SIGNING_VERIFICATION_SOURCE_TYPES") or "").strip()
    if not raw:
        return set(_DEFAULT_SIGNING_VERIFICATION_SOURCE_TYPES)

    normalized_values = {_normalize_key(part) for part in raw.replace(";", ",").split(",")}
    normalized_values.discard("")
    if not normalized_values:
        return set(_DEFAULT_SIGNING_VERIFICATION_SOURCE_TYPES)
    if normalized_values & {"none", "disabled", "off"}:
        return set()
    if normalized_values & {"all", "default", "all_email_signing_requests", "email_signing_requests"}:
        return set(_DEFAULT_SIGNING_VERIFICATION_SOURCE_TYPES)

    valid_values = normalized_values & SIGNING_VERIFICATION_SUPPORTED_SOURCE_TYPES
    invalid_values = sorted(normalized_values - SIGNING_VERIFICATION_SUPPORTED_SOURCE_TYPES)
    if invalid_values:
        logger.warning(
            "Ignoring unsupported SIGNING_VERIFICATION_SOURCE_TYPES entries: %s",
            ", ".join(invalid_values),
        )
    if valid_values:
        return set(valid_values)

    logger.warning(
        "SIGNING_VERIFICATION_SOURCE_TYPES did not include any supported source types; defaulting to %s",
        ", ".join(sorted(_DEFAULT_SIGNING_VERIFICATION_SOURCE_TYPES)),
    )
    return set(_DEFAULT_SIGNING_VERIFICATION_SOURCE_TYPES)


def resolve_signing_verification_send_rate_limits() -> tuple[int, int, int]:
    return (
        _env_int("SIGNING_VERIFICATION_SEND_RATE_WINDOW_SECONDS", 300, minimum=60),
        _env_int("SIGNING_VERIFICATION_SEND_RATE_PER_IP", 5, minimum=1),
        _env_int("SIGNING_VERIFICATION_SEND_RATE_GLOBAL", 0, minimum=0),
    )


def resolve_signing_verification_verify_rate_limits() -> tuple[int, int, int]:
    return (
        _env_int("SIGNING_VERIFICATION_VERIFY_RATE_WINDOW_SECONDS", 300, minimum=60),
        _env_int("SIGNING_VERIFICATION_VERIFY_RATE_PER_IP", 15, minimum=1),
        _env_int("SIGNING_VERIFICATION_VERIFY_RATE_GLOBAL", 0, minimum=0),
    )


def resolve_signing_verification_code_ttl_seconds() -> int:
    return _env_int("SIGNING_VERIFICATION_CODE_TTL_SECONDS", 600, minimum=60)


def resolve_signing_verification_resend_cooldown_seconds() -> int:
    return _env_int("SIGNING_VERIFICATION_RESEND_COOLDOWN_SECONDS", 60, minimum=15)


def resolve_signing_verification_max_attempts() -> int:
    return _env_int("SIGNING_VERIFICATION_MAX_ATTEMPTS", 5, minimum=1)


def resolve_signing_consumer_access_rate_limits() -> tuple[int, int, int]:
    return (
        _env_int("SIGNING_CONSUMER_ACCESS_RATE_WINDOW_SECONDS", 300, minimum=60),
        _env_int("SIGNING_CONSUMER_ACCESS_RATE_PER_IP", 10, minimum=1),
        _env_int("SIGNING_CONSUMER_ACCESS_RATE_GLOBAL", 0, minimum=0),
    )


def resolve_signing_consumer_access_max_attempts() -> int:
    return _env_int("SIGNING_CONSUMER_ACCESS_MAX_ATTEMPTS", 5, minimum=1)


def resolve_signing_request_expires_at(*, sent_at: Optional[str] = None) -> str:
    baseline = _parse_iso_datetime(sent_at) or datetime.now(timezone.utc)
    return (baseline + timedelta(days=resolve_signing_request_ttl_days())).isoformat()


def signing_request_is_expired(record, *, as_of: Optional[datetime] = None) -> bool:
    expires_at = _parse_iso_datetime(getattr(record, "expires_at", None))
    if expires_at is None:
        return False
    current = as_of or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return expires_at <= current.astimezone(timezone.utc)


def signing_request_is_public_link_revoked(record) -> bool:
    return bool(normalize_optional_text(getattr(record, "public_link_revoked_at", None)))


def normalize_signing_signer_contact_method(value: Optional[str]) -> str:
    normalized = _normalize_key(value) or SIGNING_SIGNER_CONTACT_METHOD_EMAIL
    if normalized not in SIGNING_SIGNER_CONTACT_METHODS:
        raise ValueError("Unsupported signer contact method.")
    return normalized


def normalize_signing_signer_auth_method(value: Optional[str]) -> str:
    normalized = _normalize_key(value) or SIGNING_SIGNER_AUTH_METHOD_NONE
    if normalized not in SIGNING_SIGNER_AUTH_METHODS:
        raise ValueError("Unsupported signer auth method.")
    return normalized


def resolve_signing_signer_contact_method(record_or_value: Any = None) -> str:
    if isinstance(record_or_value, str) or record_or_value is None:
        candidate = record_or_value
    else:
        candidate = getattr(record_or_value, "signer_contact_method", None)
    return normalize_signing_signer_contact_method(candidate)


def resolve_signing_signer_auth_method(record_or_value: Any = None) -> str:
    if isinstance(record_or_value, str):
        candidate = record_or_value
    elif record_or_value is None:
        candidate = None
    else:
        candidate = (
            getattr(record_or_value, "signer_auth_method", None)
            or getattr(record_or_value, "verification_method", None)
            or SIGNING_SIGNER_AUTH_METHOD_NONE
        )
    return normalize_signing_signer_auth_method(candidate)


def resolve_signing_signer_transport(
    source_type: Optional[str],
    *,
    signer_contact_method: Optional[str] = None,
) -> SigningSignerTransport:
    normalized_contact_method = resolve_signing_signer_contact_method(signer_contact_method)
    verification_required, verification_method = resolve_signing_verification_policy(
        source_type,
        signer_contact_method=normalized_contact_method,
    )
    signer_auth_method = (
        normalize_signing_signer_auth_method(verification_method)
        if verification_method
        else SIGNING_SIGNER_AUTH_METHOD_NONE
    )
    invite_method = (
        SIGNING_INVITE_METHOD_EMAIL
        if normalized_contact_method == SIGNING_SIGNER_CONTACT_METHOD_EMAIL
        else None
    )
    return SigningSignerTransport(
        signer_contact_method=normalized_contact_method,
        signer_auth_method=signer_auth_method,
        invite_method=invite_method,
        verification_required=verification_required,
        verification_method=verification_method,
    )


def resolve_signing_verification_policy(
    source_type: Optional[str],
    *,
    signer_contact_method: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    if resolve_signing_signer_contact_method(signer_contact_method) != SIGNING_SIGNER_CONTACT_METHOD_EMAIL:
        return False, None
    normalized_source_type = _normalize_key(source_type) or "workspace"
    if normalized_source_type in resolve_signing_verification_source_types():
        return True, SIGNING_VERIFICATION_METHOD_EMAIL_OTP
    return False, None


def signing_record_requires_verification(record) -> bool:
    return bool(getattr(record, "verification_required", False)) and (
        resolve_signing_signer_auth_method(record) == SIGNING_VERIFICATION_METHOD_EMAIL_OTP
    )


def normalize_signing_email_otp_code(value: Optional[str]) -> str:
    normalized = "".join(str(value or "").strip().split())
    if not re.fullmatch(r"\d{6}", normalized):
        raise ValueError("Verification code must be exactly 6 digits.")
    return normalized


def generate_signing_email_otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def build_signing_email_otp_hash(session_id: str, code: str) -> str:
    normalized_session_id = str(session_id or "").strip()
    normalized_code = normalize_signing_email_otp_code(code)
    if not normalized_session_id:
        raise ValueError("session_id is required")
    return hmac.new(
        _resolve_signing_token_secret().encode("utf-8"),
        f"signing_email_otp:{normalized_session_id}:{normalized_code}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def resolve_signing_view_rate_limits() -> tuple[int, int, int]:
    return (
        _env_int("SIGNING_VIEW_RATE_WINDOW_SECONDS", 60, minimum=1),
        _env_int("SIGNING_VIEW_RATE_PER_IP", 30, minimum=1),
        _env_int("SIGNING_VIEW_RATE_GLOBAL", 0, minimum=0),
    )


def resolve_signing_action_rate_limits() -> tuple[int, int, int]:
    return (
        _env_int("SIGNING_ACTION_RATE_WINDOW_SECONDS", 300, minimum=1),
        _env_int("SIGNING_ACTION_RATE_PER_IP", 20, minimum=1),
        _env_int("SIGNING_ACTION_RATE_GLOBAL", 0, minimum=0),
    )


def resolve_signing_document_rate_limits() -> tuple[int, int, int]:
    return (
        _env_int("SIGNING_DOCUMENT_RATE_WINDOW_SECONDS", 300, minimum=1),
        _env_int("SIGNING_DOCUMENT_RATE_PER_IP", 40, minimum=1),
        _env_int("SIGNING_DOCUMENT_RATE_GLOBAL", 0, minimum=0),
    )


def list_signing_category_options() -> List[SigningCategoryOption]:
    allowed = [
        SigningCategoryOption(key=key, label=label, blocked=False)
        for key, label in SIGNING_ALLOWED_DOCUMENT_CATEGORIES.items()
    ]
    blocked = [
        SigningCategoryOption(
            key=key,
            label=entry["label"],
            blocked=True,
            reason=entry["reason"],
        )
        for key, entry in SIGNING_EXCLUDED_DOCUMENT_CATEGORIES.items()
    ]
    return [*allowed, *blocked]


def normalize_signing_mode(value: Optional[str]) -> str:
    normalized = _normalize_key(value)
    if normalized not in SIGNING_MODES:
        raise ValueError("Signing mode must be sign or fill_and_sign")
    return normalized


def validate_signing_source_type(
    *,
    mode: Optional[str],
    source_type: Optional[str],
    source_id: Optional[str] = None,
) -> str:
    normalized_mode = normalize_signing_mode(mode)
    normalized_source_type = _normalize_key(source_type) or "workspace"
    if normalized_source_type not in {"workspace", "fill_link_response", "uploaded_pdf"}:
        raise ValueError("Signing source type must be workspace, fill_link_response, or uploaded_pdf")
    if normalized_mode == SIGNING_MODE_FILL_AND_SIGN and normalized_source_type == "uploaded_pdf":
        raise ValueError("Fill and Sign must start from reviewed workspace values or a Fill By Link response.")
    if normalized_source_type == "fill_link_response" and not normalize_optional_text(source_id, maximum_length=160):
        raise ValueError("Fill By Link signing requests must include the response id in sourceId.")
    return normalized_source_type


def build_signing_source_version(
    *,
    source_type: str,
    source_id: Optional[str] = None,
    source_template_id: Optional[str] = None,
    source_pdf_sha256: Optional[str] = None,
) -> Optional[str]:
    normalized_source_type = str(source_type or "").strip().lower()
    normalized_hash = normalize_optional_sha256(source_pdf_sha256)
    if not normalized_source_type or not normalized_hash:
        return None
    # Prefer the concrete source record id first so fill-link response signing stays tied to the
    # exact submitted response instead of collapsing multiple respondents under one template id.
    stable_source_id = normalize_optional_text(source_id or source_template_id, maximum_length=160)
    hash_prefix = normalized_hash[:12]
    if stable_source_id:
        return f"{normalized_source_type}:{stable_source_id}:{hash_prefix}"
    return f"{normalized_source_type}:{hash_prefix}"


def build_signing_source_pdf_object_path(
    *,
    user_id: str,
    request_id: str,
    source_document_name: Optional[str],
    timestamp_ms: Optional[int] = None,
) -> str:
    normalized_user_id = normalize_optional_text(user_id, maximum_length=160)
    normalized_request_id = normalize_optional_text(request_id, maximum_length=160)
    if not normalized_user_id or not normalized_request_id:
        raise ValueError("user_id and request_id are required")
    safe_name = sanitize_basename_segment(source_document_name or "signing-source", "signing-source")
    if safe_name.lower().endswith(".pdf"):
        safe_name = safe_name[:-4]
    stamp = int(timestamp_ms if timestamp_ms is not None else time.time() * 1000)
    return f"users/{normalized_user_id}/signing/{normalized_request_id}/source/{stamp}-{safe_name}.pdf"


def _build_signing_artifact_object_path(
    *,
    user_id: str,
    request_id: str,
    source_document_name: Optional[str],
    artifact_key: str,
    extension: str,
    timestamp_ms: Optional[int] = None,
) -> str:
    normalized_user_id = normalize_optional_text(user_id, maximum_length=160)
    normalized_request_id = normalize_optional_text(request_id, maximum_length=160)
    normalized_artifact_key = normalize_signing_artifact_key(artifact_key)
    normalized_extension = str(extension or "").strip().lower().lstrip(".")
    if not normalized_user_id or not normalized_request_id:
        raise ValueError("user_id and request_id are required")
    if not normalized_extension:
        raise ValueError("Artifact extension is required")
    safe_name = sanitize_basename_segment(source_document_name or "signing-document", "signing-document")
    if safe_name.lower().endswith(".pdf"):
        safe_name = safe_name[:-4]
    stamp = int(timestamp_ms if timestamp_ms is not None else time.time() * 1000)
    return (
        f"users/{normalized_user_id}/signing/{normalized_request_id}/artifacts/"
        f"{normalized_artifact_key}/{stamp}-{safe_name}-{normalized_artifact_key}.{normalized_extension}"
    )


def build_signing_signed_pdf_object_path(
    *,
    user_id: str,
    request_id: str,
    source_document_name: Optional[str],
    timestamp_ms: Optional[int] = None,
) -> str:
    return _build_signing_artifact_object_path(
        user_id=user_id,
        request_id=request_id,
        source_document_name=source_document_name,
        artifact_key=SIGNING_ARTIFACT_SIGNED_PDF,
        extension="pdf",
        timestamp_ms=timestamp_ms,
    )


def build_signing_audit_manifest_object_path(
    *,
    user_id: str,
    request_id: str,
    source_document_name: Optional[str],
    timestamp_ms: Optional[int] = None,
) -> str:
    return _build_signing_artifact_object_path(
        user_id=user_id,
        request_id=request_id,
        source_document_name=source_document_name,
        artifact_key=SIGNING_ARTIFACT_AUDIT_MANIFEST,
        extension="json",
        timestamp_ms=timestamp_ms,
    )


def build_signing_audit_receipt_object_path(
    *,
    user_id: str,
    request_id: str,
    source_document_name: Optional[str],
    timestamp_ms: Optional[int] = None,
) -> str:
    return _build_signing_artifact_object_path(
        user_id=user_id,
        request_id=request_id,
        source_document_name=source_document_name,
        artifact_key=SIGNING_ARTIFACT_AUDIT_RECEIPT,
        extension="pdf",
        timestamp_ms=timestamp_ms,
    )


def normalize_signature_mode(value: Optional[str]) -> str:
    normalized = _normalize_key(value) or SIGNATURE_MODE_BUSINESS
    if normalized not in SIGNATURE_MODES:
        raise ValueError("Signature mode must be business or consumer")
    return normalized


def validate_document_category(value: Optional[str]) -> str:
    normalized = _normalize_key(value)
    if normalized in SIGNING_EXCLUDED_DOCUMENT_CATEGORIES:
        raise ValueError(SIGNING_EXCLUDED_DOCUMENT_CATEGORIES[normalized]["reason"])
    if normalized not in SIGNING_ALLOWED_DOCUMENT_CATEGORIES:
        raise ValueError("Select one of the supported DullyPDF signing categories")
    return normalized


def validate_esign_eligibility_confirmation(value: Any) -> bool:
    if value is True:
        return True
    raise ValueError(
        "Confirm that this document is eligible for DullyPDF's U.S. e-sign flow and is not a blocked court, family-law, UCC-excluded, recall/safety, primary-residence notice, or similar excluded category."
    )


def signing_record_has_esign_eligibility_attestation(record) -> bool:
    return bool(normalize_optional_text(getattr(record, "esign_eligibility_confirmed_at", None), maximum_length=80))


def resolve_document_category_label(value: Optional[str]) -> str:
    normalized = _normalize_key(value)
    if normalized in SIGNING_ALLOWED_DOCUMENT_CATEGORIES:
        return SIGNING_ALLOWED_DOCUMENT_CATEGORIES[normalized]
    if normalized in SIGNING_EXCLUDED_DOCUMENT_CATEGORIES:
        return SIGNING_EXCLUDED_DOCUMENT_CATEGORIES[normalized]["label"]
    return "Unknown category"


def validate_signer_email(value: Optional[str]) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("Signer email is required")
    if any(ch in normalized for ch in "\r\n,;<>\""):
        raise ValueError("Signer email must be a single valid email address")
    parsed = getaddresses([normalized])
    if len(parsed) != 1:
        raise ValueError("Signer email must be a single valid email address")
    addr = str(parsed[0][1] or "").strip()
    if addr != normalized:
        raise ValueError("Signer email must be a single valid email address")
    if addr.count("@") != 1 or addr.startswith("@") or addr.endswith("@"):
        raise ValueError("Signer email must be a valid email address")
    return addr


def validate_optional_contact_email(value: Optional[str]) -> Optional[str]:
    normalized = normalize_optional_text(value, maximum_length=200)
    if not normalized:
        return None
    return validate_signer_email(normalized)


def validate_signer_name(value: Optional[str]) -> str:
    normalized = " ".join(str(value or "").strip().split())
    if not normalized:
        raise ValueError("Signer name is required")
    if len(normalized) > 200:
        raise ValueError("Signer name must be 200 characters or fewer")
    return normalized


def resolve_signing_consumer_disclosure_fields(
    *,
    signature_mode: Optional[str],
    sender_display_name: Optional[str] = None,
    sender_email: Optional[str] = None,
    sender_contact_email: Optional[str] = None,
    paper_copy_procedure: Optional[str] = None,
    paper_copy_fee_description: Optional[str] = None,
    withdrawal_procedure: Optional[str] = None,
    withdrawal_consequences: Optional[str] = None,
    contact_update_procedure: Optional[str] = None,
    consent_scope_description: Optional[str] = None,
    require_complete: bool = False,
) -> Dict[str, Optional[str]]:
    normalized_mode = normalize_signature_mode(signature_mode)
    resolved_sender_email = validate_optional_contact_email(sender_email)
    resolved_sender_contact_email = (
        validate_optional_contact_email(sender_contact_email)
        or resolved_sender_email
    )
    resolved_sender_display_name = normalize_optional_text(sender_display_name, maximum_length=200)
    if not resolved_sender_display_name:
        resolved_sender_display_name = resolved_sender_contact_email or resolved_sender_email
    resolved_scope = normalize_optional_text(consent_scope_description, maximum_length=500)
    resolved_payload = {
        "sender_display_name": resolved_sender_display_name,
        "sender_contact_email": resolved_sender_contact_email,
        "paper_copy_procedure": normalize_optional_text(paper_copy_procedure, maximum_length=500),
        "paper_copy_fee_description": normalize_optional_text(paper_copy_fee_description, maximum_length=300),
        "withdrawal_procedure": normalize_optional_text(withdrawal_procedure, maximum_length=500),
        "withdrawal_consequences": normalize_optional_text(withdrawal_consequences, maximum_length=500),
        "contact_update_procedure": normalize_optional_text(contact_update_procedure, maximum_length=500),
        "consent_scope_description": resolved_scope,
    }
    if normalized_mode != SIGNATURE_MODE_CONSUMER:
        return resolved_payload
    resolved_payload["consent_scope_description"] = (
        resolved_payload["consent_scope_description"] or SIGNING_CONSUMER_CONSENT_SCOPE_DEFAULT
    )
    missing_fields = [
        label
        for label, value in (
            ("sender contact email", resolved_sender_contact_email),
            ("paper-copy procedure", resolved_payload["paper_copy_procedure"]),
            ("paper-copy fee disclosure", resolved_payload["paper_copy_fee_description"]),
            ("withdrawal procedure", resolved_payload["withdrawal_procedure"]),
            ("withdrawal consequences", resolved_payload["withdrawal_consequences"]),
            ("contact-update procedure", resolved_payload["contact_update_procedure"]),
        )
        if not value
    ]
    if missing_fields:
        if require_complete:
            raise ValueError(
                "Consumer signing requests must include "
                + ", ".join(missing_fields)
                + "."
            )
    sender_label = resolved_sender_display_name or resolved_sender_contact_email or "the sender"
    sender_contact = f"{sender_label} at {resolved_sender_contact_email}" if resolved_sender_contact_email else sender_label
    if not resolved_payload["paper_copy_procedure"]:
        resolved_payload["paper_copy_procedure"] = (
            f"Contact {sender_contact} to request a paper copy or offline processing for this request."
        )
    if not resolved_payload["paper_copy_fee_description"]:
        resolved_payload["paper_copy_fee_description"] = (
            "The sender did not disclose a paper-copy fee through DullyPDF. Contact the sender before consenting if you need pricing."
        )
    if not resolved_payload["withdrawal_procedure"]:
        resolved_payload["withdrawal_procedure"] = (
            f"Use Withdraw electronic consent before completion or contact {sender_contact} to stop the electronic process."
        )
    if not resolved_payload["withdrawal_consequences"]:
        resolved_payload["withdrawal_consequences"] = (
            "Withdrawing consent ends this electronic signing flow for this request and requires paper or manual follow-up."
        )
    if not resolved_payload["contact_update_procedure"]:
        resolved_payload["contact_update_procedure"] = (
            f"If your email address or other contact details change before completion, contact {sender_contact} and request a fresh invitation."
        )
    return resolved_payload


def validate_adopted_signature_name(value: Optional[str]) -> str:
    normalized = " ".join(str(value or "").strip().split())
    if not normalized:
        raise ValueError("Adopted signature name is required")
    if len(normalized) > 200:
        raise ValueError("Adopted signature name must be 200 characters or fewer")
    return normalized


def normalize_signature_adopted_mode(value: Optional[str]) -> str:
    normalized = _normalize_key(value)
    if not normalized:
        return SIGNATURE_ADOPTED_MODE_DEFAULT
    if normalized not in SIGNATURE_ADOPTED_MODES:
        raise ValueError("Signature type must be default, typed, drawn, or uploaded.")
    return normalized


def resolve_signature_adoption_payload(
    *,
    signer_name: str,
    signature_type: Optional[str],
    adopted_name: Optional[str],
    signature_image_data_url: Optional[str],
) -> tuple[str, str, Optional[str]]:
    normalized_signer_name = validate_adopted_signature_name(signer_name)
    normalized_mode = normalize_signature_adopted_mode(
        signature_type or (SIGNATURE_ADOPTED_MODE_TYPED if normalize_optional_text(adopted_name) else None)
    )
    normalized_image_data = normalize_optional_text(signature_image_data_url, maximum_length=400000)
    if normalized_mode == SIGNATURE_ADOPTED_MODE_DEFAULT:
        return normalized_mode, normalized_signer_name, None
    if normalized_mode == SIGNATURE_ADOPTED_MODE_TYPED:
        return normalized_mode, validate_adopted_signature_name(adopted_name), None
    if not normalized_image_data:
        raise ValueError("Draw or upload a visible signature mark before continuing.")
    return normalized_mode, validate_adopted_signature_name(adopted_name or normalized_signer_name), normalized_image_data


def validate_source_document_name(value: Optional[str]) -> str:
    normalized = " ".join(str(value or "").strip().split())
    if not normalized:
        raise ValueError("Source document name is required")
    return normalized


def normalize_optional_text(value: Optional[str], *, maximum_length: int = 200) -> Optional[str]:
    normalized = " ".join(str(value or "").strip().split())
    if not normalized:
        return None
    return normalized[:maximum_length]


def normalize_optional_sha256(value: Optional[str]) -> Optional[str]:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    if not re.fullmatch(r"[0-9a-f]{64}", normalized):
        raise ValueError("Source PDF SHA-256 must be a 64-character lowercase hex string")
    return normalized


def normalize_signing_artifact_key(value: Optional[str]) -> str:
    normalized = _normalize_key(value)
    if normalized not in SIGNING_ARTIFACT_KEYS:
        raise ValueError("Artifact key must be source_pdf, signed_pdf, audit_manifest, or audit_receipt")
    return normalized


def normalize_anchor_kind(value: Optional[str]) -> str:
    normalized = _normalize_key(value)
    if normalized not in {"signature", "signed_date", "initials"}:
        raise ValueError("Anchor kind must be signature, signed_date, or initials")
    return normalized


def resolve_signing_disclosure_version(signature_mode: str) -> str:
    normalized_mode = normalize_signature_mode(signature_mode)
    if normalized_mode == SIGNATURE_MODE_CONSUMER:
        return SIGNING_DISCLOSURE_VERSION_CONSUMER
    return SIGNING_DISCLOSURE_VERSION_BUSINESS


def normalize_signing_user_agent(value: Optional[str]) -> Optional[str]:
    return normalize_optional_text(value, maximum_length=500)


def build_signing_session_ip_scope(value: Optional[str]) -> Optional[str]:
    normalized = normalize_optional_text(value, maximum_length=64)
    if not normalized:
        return None
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return None
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or getattr(address, "is_unspecified", False)
    ):
        return None
    prefix = 24 if address.version == 4 else 56
    return str(ipaddress.ip_network(f"{address}/{prefix}", strict=False))


def build_signing_user_agent_fingerprint(value: Optional[str]) -> Optional[str]:
    normalized = normalize_signing_user_agent(value)
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def resolve_signing_public_status_message(
    status: Optional[str],
    invalidation_reason: Optional[str] = None,
    *,
    expires_at: Optional[str] = None,
) -> str:
    normalized_status = _normalize_key(status)
    parsed_expires_at = _parse_iso_datetime(expires_at)
    if normalized_status == SIGNING_STATUS_SENT and parsed_expires_at:
        if parsed_expires_at <= datetime.now(timezone.utc):
            return "This signing request has expired. Contact the sender for a fresh signing link."
    if normalized_status == SIGNING_STATUS_SENT:
        return "This signing request is ready for review and signature."
    if normalized_status == SIGNING_STATUS_COMPLETED:
        return "This signing request has already been completed."
    if normalized_status == SIGNING_STATUS_INVALIDATED:
        return invalidation_reason or "This signing request is no longer valid."
    if normalized_status == SIGNING_STATUS_DRAFT:
        return "This signing request has not been sent yet."
    return "This signing request is not available."


def validate_signing_sendable_record(record, *, owner_review_confirmed: bool = False) -> None:
    if record is None:
        raise ValueError("Signing request not found")
    if record.status == SIGNING_STATUS_INVALIDATED:
        raise ValueError(record.invalidation_reason or "Signing request was invalidated and must be recreated.")
    if record.status != SIGNING_STATUS_DRAFT:
        raise ValueError("Only draft signing requests can be sent")
    validate_document_category(getattr(record, "document_category", None))
    if not signing_record_has_esign_eligibility_attestation(record):
        raise ValueError(
            "Recreate this signing request after confirming the document is eligible for DullyPDF's U.S. e-sign flow."
        )
    if normalize_signature_mode(getattr(record, "signature_mode", None)) == SIGNATURE_MODE_CONSUMER:
        try:
            resolve_signing_consumer_disclosure_fields(
                signature_mode=getattr(record, "signature_mode", None),
                sender_display_name=getattr(record, "sender_display_name", None),
                sender_email=getattr(record, "sender_email", None),
                sender_contact_email=getattr(record, "sender_contact_email", None),
                paper_copy_procedure=getattr(record, "consumer_paper_copy_procedure", None),
                paper_copy_fee_description=getattr(record, "consumer_paper_copy_fee_description", None),
                withdrawal_procedure=getattr(record, "consumer_withdrawal_procedure", None),
                withdrawal_consequences=getattr(record, "consumer_withdrawal_consequences", None),
                contact_update_procedure=getattr(record, "consumer_contact_update_procedure", None),
                consent_scope_description=getattr(record, "consumer_consent_scope_override", None),
                require_complete=True,
            )
        except ValueError as exc:
            raise ValueError(
                "This consumer signing draft predates the current disclosure requirements. Recreate it before sending."
            ) from exc
    normalized_mode = normalize_signing_mode(record.mode)
    if not normalize_optional_sha256(record.source_pdf_sha256):
        raise ValueError("Signing draft is missing a source PDF hash. Recreate the draft before sending.")
    has_signature_anchor = any(
        normalize_anchor_kind(entry.get("kind")) == "signature"
        for entry in (record.anchors or [])
        if isinstance(entry, dict) and entry.get("kind")
    )
    if not has_signature_anchor:
        raise ValueError("Add at least one signature anchor before sending this request.")
    if normalized_mode == SIGNING_MODE_FILL_AND_SIGN and not owner_review_confirmed and not record.owner_review_confirmed_at:
        raise ValueError("Review the filled PDF and confirm the freeze step before sending this Fill and Sign request.")


def validate_signing_reissuable_record(record) -> None:
    if record is None:
        raise ValueError("Signing request not found")
    if record.status == SIGNING_STATUS_COMPLETED:
        raise ValueError("Completed signing requests cannot be reissued.")
    validate_document_category(getattr(record, "document_category", None))
    if not signing_record_has_esign_eligibility_attestation(record):
        raise ValueError(
            "This signing request predates the current eligibility attestation. Recreate it before issuing a fresh signer link."
        )
    if not normalize_optional_text(getattr(record, "source_pdf_bucket_path", None), maximum_length=500):
        raise ValueError("Only sent signing requests with an immutable source PDF can be reissued.")
    if record.status == SIGNING_STATUS_SENT:
        return
    if record.status == SIGNING_STATUS_INVALIDATED and signing_request_is_public_link_revoked(record):
        return
    raise ValueError("Only active, expired, or sender-revoked signing links can be reissued.")


def validate_public_signing_actionable_record(record) -> None:
    if record is None:
        raise ValueError("Signing request not found")
    if record.status == SIGNING_STATUS_INVALIDATED:
        raise ValueError(record.invalidation_reason or "This signing request is no longer valid.")
    if record.status == SIGNING_STATUS_COMPLETED:
        raise ValueError("This signing request has already been completed.")
    if record.manual_fallback_requested_at:
        raise ValueError(
            "Paper/manual fallback was requested for this signing request. Contact the sender instead of signing electronically."
        )
    if getattr(record, "consent_withdrawn_at", None):
        raise ValueError(
            "Electronic consent was withdrawn for this signing request. Contact the sender to proceed."
        )
    if signing_request_is_expired(record):
        raise ValueError("This signing request has expired. Contact the sender for a fresh signing link.")
    if record.status != SIGNING_STATUS_SENT:
        raise ValueError("This signing request is not ready for signer actions.")


def validate_public_signing_document_record(record) -> None:
    if record is None:
        raise ValueError("Signing request not found")
    if record.status == SIGNING_STATUS_COMPLETED:
        return
    validate_public_signing_actionable_record(record)
    if normalize_signature_mode(record.signature_mode) == SIGNATURE_MODE_CONSUMER and not record.consented_at:
        raise ValueError("Consumer e-consent is required before the document can be opened.")


def validate_public_signing_reviewable_record(record) -> None:
    validate_public_signing_actionable_record(record)
    if normalize_signature_mode(record.signature_mode) == SIGNATURE_MODE_CONSUMER and not record.consented_at:
        raise ValueError("Consumer e-consent is required before the document can be reviewed.")


def validate_public_signing_adoptable_record(record) -> None:
    validate_public_signing_reviewable_record(record)
    if not record.reviewed_at:
        raise ValueError("Review the document before adopting a signature.")


def validate_public_signing_completable_record(record) -> None:
    validate_public_signing_adoptable_record(record)
    if not record.signature_adopted_at or not record.signature_adopted_name:
        raise ValueError("Adopt a signature before completing this signing request.")
    adopted_mode = normalize_signature_adopted_mode(getattr(record, "signature_adopted_mode", None))
    if adopted_mode in {SIGNATURE_ADOPTED_MODE_DRAWN, SIGNATURE_ADOPTED_MODE_UPLOADED} and not getattr(
        record,
        "signature_adopted_image_data_url",
        None,
    ):
        raise ValueError("The adopted signature image is missing for this signing request.")


def validate_public_signing_consent_withdrawable_record(record) -> None:
    validate_public_signing_actionable_record(record)
    if normalize_signature_mode(record.signature_mode) != SIGNATURE_MODE_CONSUMER:
        raise ValueError("Consent withdrawal is only available for consumer signing requests.")
    if not record.consented_at:
        raise ValueError("No electronic consent has been given to withdraw.")
    if record.consent_withdrawn_at:
        raise ValueError("Electronic consent has already been withdrawn for this request.")


def resolve_disclosure_text(disclosure_version: Optional[str]) -> List[str]:
    normalized = str(disclosure_version or "").strip()
    return list(SIGNING_DISCLOSURE_TEXTS.get(normalized, []))


def build_signing_consumer_access_code(request_id: str) -> str:
    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id:
        raise ValueError("request_id is required")
    digest = hmac.new(
        _resolve_signing_token_secret().encode("utf-8"),
        f"consumer_access:{normalized_request_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest[:6].upper()


def mask_signing_email(value: Optional[str]) -> Optional[str]:
    normalized = str(value or "").strip()
    if not normalized or "@" not in normalized:
        return None
    local_part, domain = normalized.split("@", 1)
    domain_label = domain.strip()
    if not domain_label:
        return None
    visible_local = (local_part[:1] or "").strip() or "*"
    return f"{visible_local}{'*' * max(3, len(local_part) - 1)}@{domain_label}"


def resolve_signing_disclosure_payload(
    disclosure_version: Optional[str],
    *,
    request_id: Optional[str] = None,
    sender_display_name: Optional[str] = None,
    sender_email: Optional[str] = None,
    sender_contact_email: Optional[str] = None,
    manual_fallback_enabled: bool = True,
    paper_copy_procedure: Optional[str] = None,
    paper_copy_fee_description: Optional[str] = None,
    withdrawal_procedure: Optional[str] = None,
    withdrawal_consequences: Optional[str] = None,
    contact_update_procedure: Optional[str] = None,
    consent_scope_description: Optional[str] = None,
) -> Dict[str, Any]:
    normalized = str(disclosure_version or "").strip()
    if normalized == SIGNING_DISCLOSURE_VERSION_CONSUMER:
        disclosure_fields = resolve_signing_consumer_disclosure_fields(
            signature_mode=SIGNATURE_MODE_CONSUMER,
            sender_display_name=sender_display_name,
            sender_email=sender_email,
            sender_contact_email=sender_contact_email,
            paper_copy_procedure=paper_copy_procedure,
            paper_copy_fee_description=paper_copy_fee_description,
            withdrawal_procedure=withdrawal_procedure,
            withdrawal_consequences=withdrawal_consequences,
            contact_update_procedure=contact_update_procedure,
            consent_scope_description=consent_scope_description,
        )
        summary_lines = [
            line
            for line in (
                disclosure_fields["paper_copy_procedure"],
                disclosure_fields["withdrawal_procedure"],
                disclosure_fields["withdrawal_consequences"],
                disclosure_fields["consent_scope_description"],
                disclosure_fields["contact_update_procedure"],
                (
                    f"Paper-copy fees and charges: {disclosure_fields['paper_copy_fee_description']}"
                    if disclosure_fields["paper_copy_fee_description"]
                    else None
                ),
            )
            if line
        ]
        paper_option = None
        if manual_fallback_enabled:
            sender_label = (
                disclosure_fields["sender_display_name"]
                or disclosure_fields["sender_contact_email"]
                or "the sender"
            )
            paper_option = {
                "instructions": (
                    "Use the paper/manual fallback option on this page to notify "
                    f"{sender_label} and stop the electronic signing ceremony."
                ),
                "fees": disclosure_fields["paper_copy_fee_description"],
            }
        payload: Dict[str, Any] = {
            "version": normalized,
            "summaryLines": summary_lines,
            "sender": {
                "displayName": disclosure_fields["sender_display_name"],
                "contactEmail": disclosure_fields["sender_contact_email"],
            },
            "paperOption": paper_option,
            "withdrawal": {
                "instructions": disclosure_fields["withdrawal_procedure"],
                "consequences": disclosure_fields["withdrawal_consequences"],
            },
            "scope": disclosure_fields["consent_scope_description"],
            "contactUpdates": disclosure_fields["contact_update_procedure"],
            "paperCopy": disclosure_fields["paper_copy_procedure"],
            "hardwareSoftware": list(SIGNING_CONSUMER_HARDWARE_SOFTWARE),
            "accessCheck": {
                "required": True,
                "format": "pdf",
                "instructions": "Open the PDF access check file and enter the 6-character code shown there to demonstrate you can access PDF records electronically.",
            },
        }
        if request_id:
            payload["accessCheck"] = {
                **dict(payload["accessCheck"]),
                "codeLength": len(build_signing_consumer_access_code(request_id)),
            }
        return payload
    return {
        "version": normalized,
        "summaryLines": resolve_disclosure_text(normalized),
    }


def resolve_signing_disclosure_payload_for_record(record, *, request_id: Optional[str] = None) -> Dict[str, Any]:
    return resolve_signing_disclosure_payload(
        getattr(record, "disclosure_version", None),
        request_id=request_id or getattr(record, "id", None),
        sender_display_name=getattr(record, "sender_display_name", None),
        sender_email=getattr(record, "sender_email", None),
        sender_contact_email=getattr(record, "sender_contact_email", None),
        manual_fallback_enabled=bool(getattr(record, "manual_fallback_enabled", True)),
        paper_copy_procedure=getattr(record, "consumer_paper_copy_procedure", None),
        paper_copy_fee_description=getattr(record, "consumer_paper_copy_fee_description", None),
        withdrawal_procedure=getattr(record, "consumer_withdrawal_procedure", None),
        withdrawal_consequences=getattr(record, "consumer_withdrawal_consequences", None),
        contact_update_procedure=getattr(record, "consumer_contact_update_procedure", None),
        consent_scope_description=getattr(record, "consumer_consent_scope_override", None),
    )


def serialize_signing_ceremony_state(record) -> Dict[str, Any]:
    return {
        "signerContactMethod": resolve_signing_signer_contact_method(record),
        "signerAuthMethod": resolve_signing_signer_auth_method(record),
        "verificationRequired": bool(getattr(record, "verification_required", False)),
        "verificationMethod": getattr(record, "verification_method", None),
        "verificationCompletedAt": getattr(record, "verification_completed_at", None),
        "openedAt": record.opened_at,
        "reviewedAt": record.reviewed_at,
        "consentedAt": record.consented_at,
        "consumerDisclosurePresentedAt": getattr(record, "consumer_disclosure_presented_at", None),
        "consumerConsentScope": getattr(record, "consumer_consent_scope", None),
        "consumerAccessDemonstratedAt": getattr(record, "consumer_access_demonstrated_at", None),
        "consumerAccessDemonstrationMethod": getattr(record, "consumer_access_demonstration_method", None),
        "consentWithdrawnAt": getattr(record, "consent_withdrawn_at", None),
        "signatureAdoptedAt": record.signature_adopted_at,
        "signatureAdoptedName": record.signature_adopted_name,
        "signatureAdoptedMode": normalize_signature_adopted_mode(getattr(record, "signature_adopted_mode", None)),
        "signatureAdoptedImageDataUrl": getattr(record, "signature_adopted_image_data_url", None),
        "manualFallbackRequestedAt": record.manual_fallback_requested_at,
    }


def serialize_signing_sender_provenance(record) -> Dict[str, Any]:
    return {
        "ownerUserId": getattr(record, "user_id", None),
        "senderDisplayName": getattr(record, "sender_display_name", None),
        "senderEmail": getattr(record, "sender_email", None),
        "senderContactEmail": getattr(record, "sender_contact_email", None),
        "inviteMethod": getattr(record, "invite_method", None),
        "inviteProvider": getattr(record, "invite_provider", None),
        "inviteProviderMessageId": getattr(record, "invite_message_id", None),
        "inviteDeliveryStatus": getattr(record, "invite_delivery_status", None),
        "inviteLastAttemptAt": getattr(record, "invite_last_attempt_at", None),
        "inviteSentAt": getattr(record, "invite_sent_at", None),
        "inviteDeliveryErrorCode": getattr(record, "invite_delivery_error_code", None),
        "inviteDeliveryErrorSummary": getattr(record, "invite_delivery_error", None),
        "manualLinkSharedAt": getattr(record, "manual_link_shared_at", None),
    }


def resolve_signing_retention_days() -> int:
    return _env_int("SIGNING_RETENTION_DAYS", SIGNING_MIN_RETENTION_DAYS, minimum=SIGNING_MIN_RETENTION_DAYS)


def resolve_signing_retention_until(started_at: Optional[str] = None) -> str:
    retention_days = resolve_signing_retention_days()
    baseline = _parse_iso_datetime(started_at) or datetime.now(timezone.utc)
    return (baseline + timedelta(days=retention_days)).isoformat()


def serialize_signing_category_options() -> List[Dict[str, Any]]:
    return [
        {
            "key": entry.key,
            "label": entry.label,
            "blocked": entry.blocked,
            "reason": entry.reason,
        }
        for entry in list_signing_category_options()
    ]
