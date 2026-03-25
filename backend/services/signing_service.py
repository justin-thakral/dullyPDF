"""Signing policy helpers, public token handling, and serialization utilities."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from email.utils import getaddresses
import hashlib
import hmac
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
_DEV_SIGNING_TOKEN_SECRET = secrets.token_urlsafe(48)
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

SIGNING_DISCLOSURE_VERSION_BUSINESS = "us-esign-business-v1"
SIGNING_DISCLOSURE_VERSION_CONSUMER = "us-esign-consumer-v1"

SIGNING_EVENT_SESSION_STARTED = "session_started"
SIGNING_EVENT_OPENED = "opened"
SIGNING_EVENT_REVIEW_CONFIRMED = "review_confirmed"
SIGNING_EVENT_CONSENT_ACCEPTED = "consent_accepted"
SIGNING_EVENT_SIGNATURE_ADOPTED = "signature_adopted"
SIGNING_EVENT_MANUAL_FALLBACK_REQUESTED = "manual_fallback_requested"
SIGNING_EVENT_COMPLETED = "completed"

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
    "hazardous_material_transport": {
        "label": "Hazardous-material transport documents",
        "reason": "Hazardous-material transport documents are blocked in DullyPDF v1.",
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


@dataclass(frozen=True)
class SigningCategoryOption:
    key: str
    label: str
    blocked: bool
    reason: Optional[str] = None


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
    secret = (_env_value("SIGNING_LINK_TOKEN_SECRET") or "").strip()
    if secret and not (_is_prod_env() and signing_token_secret_is_weak(secret)):
        return secret
    if _is_prod_env():
        raise RuntimeError("SIGNING_LINK_TOKEN_SECRET must be unique and at least 32 characters in production")
    global _WARNED_DEV_SIGNING_TOKEN_SECRET
    if not _WARNED_DEV_SIGNING_TOKEN_SECRET:
        logger.warning(
            "SIGNING_LINK_TOKEN_SECRET is unset outside production; using a process-local ephemeral secret. "
            "Public signing tokens created in this process will stop working after the backend restarts."
        )
        _WARNED_DEV_SIGNING_TOKEN_SECRET = True
    return _DEV_SIGNING_TOKEN_SECRET


def _signing_request_signature(request_id: str) -> str:
    digest = hmac.new(
        _resolve_signing_token_secret().encode("utf-8"),
        f"signing_request:{request_id}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _urlsafe_b64encode(digest)


def build_signing_public_token(request_id: str) -> str:
    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id:
        raise ValueError("request_id is required")
    return ".".join(
        [
            _PUBLIC_TOKEN_PREFIX,
            _urlsafe_b64encode(normalized_request_id.encode("utf-8")),
            _signing_request_signature(normalized_request_id),
        ]
    )


def parse_signing_public_token(token: Optional[str]) -> Optional[str]:
    normalized = re.sub(r"[^A-Za-z0-9_.-]", "", str(token or "").strip())
    if not normalized:
        return None
    parts = normalized.split(".")
    if len(parts) != 3 or parts[0] != _PUBLIC_TOKEN_PREFIX:
        return None
    try:
        request_id = _urlsafe_b64decode(parts[1]).decode("utf-8").strip()
    except Exception:
        return None
    if not request_id:
        return None
    expected_signature = _signing_request_signature(request_id)
    if not hmac.compare_digest(parts[2], expected_signature):
        return None
    return request_id


def build_signing_public_path(request_id: str) -> str:
    return f"/sign/{build_signing_public_token(request_id)}"


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


def sha256_hex_for_bytes(raw_bytes: bytes) -> str:
    return hashlib.sha256(raw_bytes or b"").hexdigest()


def build_signing_link_token_id(token: Optional[str]) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]", "", str(token or "").strip())
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def resolve_signing_session_ttl_seconds() -> int:
    return _env_int("SIGNING_SESSION_TTL_SECONDS", 3600, minimum=300)


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


def validate_signer_name(value: Optional[str]) -> str:
    normalized = " ".join(str(value or "").strip().split())
    if not normalized:
        raise ValueError("Signer name is required")
    return normalized


def validate_adopted_signature_name(value: Optional[str]) -> str:
    normalized = " ".join(str(value or "").strip().split())
    if not normalized:
        raise ValueError("Adopted signature name is required")
    return normalized


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


def resolve_signing_public_status_message(status: Optional[str], invalidation_reason: Optional[str] = None) -> str:
    normalized_status = _normalize_key(status)
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
    if record.status != SIGNING_STATUS_SENT:
        raise ValueError("This signing request is not ready for signer actions.")


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


def serialize_signing_ceremony_state(record) -> Dict[str, Any]:
    return {
        "openedAt": record.opened_at,
        "reviewedAt": record.reviewed_at,
        "consentedAt": record.consented_at,
        "signatureAdoptedAt": record.signature_adopted_at,
        "signatureAdoptedName": record.signature_adopted_name,
        "manualFallbackRequestedAt": record.manual_fallback_requested_at,
    }


def resolve_signing_retention_days() -> int:
    return _env_int("SIGNING_RETENTION_DAYS", 2555, minimum=30)


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
