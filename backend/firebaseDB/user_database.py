"""Firestore-backed user profile, billing role, and quota operations."""

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from firebase_admin import firestore as firebase_firestore

from backend.logging_config import get_logger
from ..time_utils import now_iso
from .firestore_query_utils import where_equals
from .firebase_service import RequestUser, get_firestore_client


logger = get_logger(__name__)

USERS_COLLECTION = "app_users"
ROLE_BASE = "base"
ROLE_PRO = "pro"
ROLE_GOD = "god"
ROLE_FIELD = "role"
RENAME_COUNT_FIELD = "rename_count"
BASE_RENAME_LIMIT = int(os.getenv("BASE_RENAME_LIMIT", "10"))
OPENAI_CREDITS_FIELD = "openai_credits_remaining"
BASE_OPENAI_CREDITS = int(os.getenv("BASE_OPENAI_CREDITS", "10"))
OPENAI_CREDITS_MONTHLY_FIELD = "openai_credits_monthly_remaining"
OPENAI_CREDITS_REFILL_FIELD = "openai_credits_refill_remaining"
OPENAI_CREDITS_MONTHLY_CYCLE_FIELD = "openai_credits_monthly_cycle_key"
PRO_MONTHLY_OPENAI_CREDITS = int(os.getenv("PRO_MONTHLY_OPENAI_CREDITS", "500"))
STRIPE_SUBSCRIPTION_ID_FIELD = "stripe_subscription_id"
STRIPE_CUSTOMER_ID_FIELD = "stripe_customer_id"
STRIPE_SUBSCRIPTION_STATUS_FIELD = "stripe_subscription_status"
STRIPE_SUBSCRIPTION_PRICE_ID_FIELD = "stripe_subscription_price_id"
STRIPE_CANCEL_AT_PERIOD_END_FIELD = "stripe_cancel_at_period_end"
STRIPE_CANCEL_AT_FIELD = "stripe_cancel_at"
STRIPE_CURRENT_PERIOD_END_FIELD = "stripe_current_period_end"
STRIPE_PROCESSED_EVENT_IDS_FIELD = "stripe_processed_event_ids"
# Billing event docs remain the primary idempotency record. This inline recent-id
# history is bounded so repeated billing activity cannot bloat the Firestore user
# document over time.
try:
    STRIPE_MAX_PROCESSED_EVENTS = int(os.getenv("STRIPE_MAX_PROCESSED_EVENTS", "256"))
except ValueError:
    STRIPE_MAX_PROCESSED_EVENTS = 256
if STRIPE_MAX_PROCESSED_EVENTS <= 0:
    STRIPE_MAX_PROCESSED_EVENTS = 256
DOWNGRADE_RETENTION_FIELD = "downgrade_retention"

CreditBreakdown = Dict[str, int]
_UNSET = object()


@dataclass(frozen=True)
class UserProfileRecord:
    uid: str
    email: Optional[str]
    display_name: Optional[str]
    role: str
    openai_credits_remaining: Optional[int]
    openai_credits_monthly_remaining: Optional[int] = None
    openai_credits_refill_remaining: Optional[int] = None
    openai_credits_available: Optional[int] = None
    refill_credits_locked: bool = False
    downgrade_retention: Optional["UserDowngradeRetentionRecord"] = None


@dataclass(frozen=True)
class UserBillingRecord:
    uid: str
    customer_id: Optional[str]
    subscription_id: Optional[str]
    subscription_status: Optional[str]
    subscription_price_id: Optional[str]
    cancel_at_period_end: Optional[bool] = None
    cancel_at: Optional[int] = None
    current_period_end: Optional[int] = None


@dataclass(frozen=True)
class UserDowngradeRetentionRecord:
    status: str
    policy_version: int
    downgraded_at: Optional[str]
    grace_ends_at: Optional[str]
    saved_forms_limit: int
    fill_links_active_limit: int
    kept_template_ids: List[str]
    pending_delete_template_ids: List[str]
    pending_delete_link_ids: List[str]
    billing_state_deferred: bool = False
    updated_at: Optional[str] = None


def normalize_role(value: Optional[str]) -> str:
    """Normalize role values to known constants.
    """
    raw = (value or "").strip().lower()
    if raw == ROLE_GOD:
        return ROLE_GOD
    if raw == ROLE_PRO:
        return ROLE_PRO
    return ROLE_BASE


def _coerce_non_negative_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else 0


def _coerce_optional_unix_timestamp(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _coerce_optional_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return bool(int(value))
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "on"}:
        return True
    if text in {"false", "0", "no", "n", "off"}:
        return False
    return None


def _coerce_string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    deduped: List[str] = []
    for item in value:
        normalized = str(item or "").strip()
        if not normalized or normalized in deduped:
            continue
        deduped.append(normalized)
    return deduped


def _coerce_positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _current_month_cycle_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _resolve_pro_monthly_credits_remaining(data: Dict[str, Any]) -> int:
    raw = data.get(OPENAI_CREDITS_MONTHLY_FIELD)
    if raw is None:
        return PRO_MONTHLY_OPENAI_CREDITS
    return _coerce_non_negative_int(raw, default=PRO_MONTHLY_OPENAI_CREDITS)


def _resolve_pro_refill_credits_remaining(data: Dict[str, Any]) -> int:
    raw = data.get(OPENAI_CREDITS_REFILL_FIELD)
    if raw is None:
        return 0
    return _coerce_non_negative_int(raw, default=0)


def _normalize_stripe_event_id(value: Optional[str]) -> str:
    return (value or "").strip()


def _resolve_processed_stripe_event_ids(data: Dict[str, Any]) -> list[str]:
    raw = data.get(STRIPE_PROCESSED_EVENT_IDS_FIELD)
    if not isinstance(raw, list):
        return []
    normalized: list[str] = []
    for item in raw:
        if item is None:
            continue
        event_id = _normalize_stripe_event_id(str(item))
        if not event_id or event_id in normalized:
            continue
        normalized.append(event_id)
    return normalized


def _apply_processed_stripe_event_id(processed_ids: list[str], event_id: Optional[str]) -> tuple[list[str], bool]:
    normalized_event_id = _normalize_stripe_event_id(event_id)
    if not normalized_event_id:
        return processed_ids, False
    if normalized_event_id in processed_ids:
        return processed_ids, True
    next_processed = [*processed_ids, normalized_event_id]
    if STRIPE_MAX_PROCESSED_EVENTS > 0 and len(next_processed) > STRIPE_MAX_PROCESSED_EVENTS:
        next_processed = next_processed[-STRIPE_MAX_PROCESSED_EVENTS:]
    return next_processed, False


def _normalize_credit_breakdown(raw: Optional[Dict[str, Any]]) -> CreditBreakdown:
    payload = raw if isinstance(raw, dict) else {}
    return {
        "base": _coerce_non_negative_int(payload.get("base"), default=0),
        "monthly": _coerce_non_negative_int(payload.get("monthly"), default=0),
        "refill": _coerce_non_negative_int(payload.get("refill"), default=0),
    }


def _normalize_downgrade_retention(raw: Any) -> Optional[UserDowngradeRetentionRecord]:
    if not isinstance(raw, dict):
        return None
    status = str(raw.get("status") or "").strip().lower()
    if not status:
        return None
    return UserDowngradeRetentionRecord(
        status=status,
        policy_version=_coerce_positive_int(raw.get("policy_version"), default=1),
        downgraded_at=str(raw.get("downgraded_at") or "").strip() or None,
        grace_ends_at=str(raw.get("grace_ends_at") or "").strip() or None,
        saved_forms_limit=_coerce_positive_int(raw.get("saved_forms_limit"), default=1),
        fill_links_active_limit=_coerce_positive_int(raw.get("fill_links_active_limit"), default=1),
        kept_template_ids=_coerce_string_list(raw.get("kept_template_ids")),
        pending_delete_template_ids=_coerce_string_list(raw.get("pending_delete_template_ids")),
        pending_delete_link_ids=_coerce_string_list(raw.get("pending_delete_link_ids")),
        billing_state_deferred=bool(_coerce_optional_bool(raw.get("billing_state_deferred"))),
        updated_at=str(raw.get("updated_at") or "").strip() or None,
    )


def _resolve_pro_monthly_pool(data: Dict[str, Any]) -> Tuple[int, str, bool]:
    cycle_key = str(data.get(OPENAI_CREDITS_MONTHLY_CYCLE_FIELD) or "").strip()
    monthly_remaining = _resolve_pro_monthly_credits_remaining(data)
    current_cycle = _current_month_cycle_key()
    if cycle_key != current_cycle:
        return PRO_MONTHLY_OPENAI_CREDITS, current_cycle, True
    return monthly_remaining, cycle_key, False


def _apply_subscription_updates(
    updates: Dict[str, Any],
    *,
    customer_id: Optional[str] = None,
    subscription_id: Optional[str] = None,
    subscription_status: Optional[str] = None,
    subscription_price_id: Optional[str] = None,
    cancel_at_period_end: Any = _UNSET,
    cancel_at: Any = _UNSET,
    current_period_end: Any = _UNSET,
) -> None:
    if customer_id is not None:
        updates[STRIPE_CUSTOMER_ID_FIELD] = (customer_id or "").strip() or None
    if subscription_id is not None:
        updates[STRIPE_SUBSCRIPTION_ID_FIELD] = (subscription_id or "").strip() or None
    if subscription_status is not None:
        updates[STRIPE_SUBSCRIPTION_STATUS_FIELD] = (subscription_status or "").strip() or None
    if subscription_price_id is not None:
        updates[STRIPE_SUBSCRIPTION_PRICE_ID_FIELD] = (subscription_price_id or "").strip() or None
    if cancel_at_period_end is not _UNSET:
        updates[STRIPE_CANCEL_AT_PERIOD_END_FIELD] = _coerce_optional_bool(cancel_at_period_end)
    if cancel_at is not _UNSET:
        updates[STRIPE_CANCEL_AT_FIELD] = _coerce_optional_unix_timestamp(cancel_at)
    if current_period_end is not _UNSET:
        updates[STRIPE_CURRENT_PERIOD_END_FIELD] = _coerce_optional_unix_timestamp(current_period_end)


def _role_from_claim_or_stored(decoded: Dict[str, Any], stored_role: Optional[str]) -> str:
    """Resolve role with Firestore as source of truth for paid tiers.

    Custom claims remain authoritative for privileged admin access (`god`), but
    paid tier roles (`pro`) are persisted and managed from billing state in
    Firestore to avoid stale-token role resurrection after downgrade.
    """
    stored_normalized = normalize_role(stored_role)
    raw_claim = decoded.get(ROLE_FIELD)
    if raw_claim is None:
        return stored_normalized if stored_role is not None else ROLE_BASE
    claim_text = str(raw_claim).strip()
    if not claim_text:
        return stored_normalized if stored_role is not None else ROLE_BASE
    claim_normalized = normalize_role(claim_text)
    if claim_normalized == ROLE_GOD:
        return ROLE_GOD
    if stored_role is None:
        return ROLE_BASE
    return stored_normalized


def ensure_user(decoded: Dict[str, Any]) -> RequestUser:
    """
    Upsert the Firebase user into Firestore so template ownership is stable.
    """
    uid = decoded.get("uid") or decoded.get("user_id") or decoded.get("sub")
    if not uid:
        raise ValueError("Missing firebase uid")
    email = decoded.get("email")
    display_name = decoded.get("name") or decoded.get("displayName")
    client = get_firestore_client()
    doc_ref = client.collection(USERS_COLLECTION).document(uid)
    snapshot = doc_ref.get()
    timestamp = now_iso()

    if snapshot.exists:
        data = snapshot.to_dict() or {}
        role = _role_from_claim_or_stored(decoded, data.get(ROLE_FIELD))
        updates: Dict[str, Any] = {}
        if email and email != data.get("email"):
            updates["email"] = email
        if (display_name or None) != data.get("displayName"):
            updates["displayName"] = display_name or None
        if data.get(ROLE_FIELD) != role:
            updates[ROLE_FIELD] = role
        if RENAME_COUNT_FIELD not in data:
            updates[RENAME_COUNT_FIELD] = 0
        if role == ROLE_BASE and OPENAI_CREDITS_FIELD not in data:
            updates[OPENAI_CREDITS_FIELD] = BASE_OPENAI_CREDITS
        if role == ROLE_PRO:
            monthly_remaining, cycle_key, monthly_reset = _resolve_pro_monthly_pool(data)
            if monthly_reset or OPENAI_CREDITS_MONTHLY_FIELD not in data:
                updates[OPENAI_CREDITS_MONTHLY_FIELD] = monthly_remaining
            if monthly_reset or data.get(OPENAI_CREDITS_MONTHLY_CYCLE_FIELD) != cycle_key:
                updates[OPENAI_CREDITS_MONTHLY_CYCLE_FIELD] = cycle_key
            if OPENAI_CREDITS_REFILL_FIELD not in data:
                updates[OPENAI_CREDITS_REFILL_FIELD] = 0
        if updates:
            updates["updated_at"] = timestamp
            doc_ref.update(updates)
            logger.debug("Updated Firestore user record: %s", uid)
        return RequestUser(
            uid=uid,
            app_user_id=uid,
            email=updates.get("email") or data.get("email") or email,
            display_name=updates.get("displayName") or data.get("displayName") or display_name,
            role=role,
        )

    role = _role_from_claim_or_stored(decoded, None)
    payload = {
        "firebase_uid": uid,
        "email": email or None,
        "displayName": display_name or None,
        ROLE_FIELD: role,
        RENAME_COUNT_FIELD: 0,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    if role == ROLE_BASE:
        payload[OPENAI_CREDITS_FIELD] = BASE_OPENAI_CREDITS
    if role == ROLE_PRO:
        payload[OPENAI_CREDITS_MONTHLY_FIELD] = PRO_MONTHLY_OPENAI_CREDITS
        payload[OPENAI_CREDITS_REFILL_FIELD] = 0
        payload[OPENAI_CREDITS_MONTHLY_CYCLE_FIELD] = _current_month_cycle_key()
    doc_ref.set(payload)
    logger.debug("Created Firestore user record: %s", uid)
    return RequestUser(
        uid=uid,
        app_user_id=uid,
        email=email,
        display_name=display_name,
        role=role,
    )


def _resolve_openai_credits_remaining(data: Dict[str, Any]) -> int:
    """
    Resolve credits remaining from a Firestore payload.

    Important: a stored value of 0 is valid and must not fall back to the default.
    """
    raw = data.get(OPENAI_CREDITS_FIELD)
    if raw is None:
        return BASE_OPENAI_CREDITS
    try:
        return int(raw)
    except (TypeError, ValueError):
        return BASE_OPENAI_CREDITS


def consume_openai_credits(
    uid: str,
    *,
    credits: int,
    role: Optional[str] = None,
    include_breakdown: bool = False,
) -> Union[tuple[int, bool], tuple[int, bool, CreditBreakdown]]:
    """Atomically decrement OpenAI credits for a user.

    Credits are consumed per OpenAI action (rename or schema mapping), not per page.
    """
    if not uid:
        raise ValueError("Missing firebase uid")
    try:
        credits_required = int(credits)
    except (TypeError, ValueError):
        credits_required = 1
    if credits_required < 1:
        credits_required = 1

    client = get_firestore_client()
    doc_ref = client.collection(USERS_COLLECTION).document(uid)
    transaction = client.transaction()

    @firebase_firestore.transactional
    def _update(txn: firebase_firestore.Transaction) -> tuple[int, bool, CreditBreakdown]:
        snapshot = doc_ref.get(transaction=txn)
        data = snapshot.to_dict() or {}
        stored_role = normalize_role(data.get(ROLE_FIELD))
        normalized_role = stored_role

        if normalized_role == ROLE_GOD:
            return -1, True, {"base": 0, "monthly": 0, "refill": 0}

        if normalized_role == ROLE_PRO:
            monthly_remaining, cycle_key, _ = _resolve_pro_monthly_pool(data)
            refill_remaining = _resolve_pro_refill_credits_remaining(data)
            available = monthly_remaining + refill_remaining
            if available < credits_required:
                return available, False, {"base": 0, "monthly": 0, "refill": 0}

            consume_monthly = min(monthly_remaining, credits_required)
            consume_refill = credits_required - consume_monthly
            next_monthly = monthly_remaining - consume_monthly
            next_refill = refill_remaining - consume_refill
            txn.set(
                doc_ref,
                {
                    ROLE_FIELD: ROLE_PRO,
                    OPENAI_CREDITS_MONTHLY_FIELD: next_monthly,
                    OPENAI_CREDITS_REFILL_FIELD: next_refill,
                    OPENAI_CREDITS_MONTHLY_CYCLE_FIELD: cycle_key,
                    "updated_at": now_iso(),
                },
                merge=True,
            )
            return next_monthly + next_refill, True, {
                "base": 0,
                "monthly": consume_monthly,
                "refill": consume_refill,
            }

        remaining = _resolve_openai_credits_remaining(data)
        if remaining < credits_required:
            return remaining, False, {"base": 0, "monthly": 0, "refill": 0}
        new_remaining = remaining - credits_required
        updates = {
            OPENAI_CREDITS_FIELD: new_remaining,
            "updated_at": now_iso(),
        }
        txn.set(doc_ref, updates, merge=True)
        return new_remaining, True, {
            "base": credits_required,
            "monthly": 0,
            "refill": 0,
        }

    remaining, allowed, breakdown = _update(transaction)
    if not include_breakdown:
        return remaining, allowed
    return remaining, allowed, breakdown


def refund_openai_credits(
    uid: str,
    *,
    credits: int,
    role: Optional[str] = None,
    credit_breakdown: Optional[Dict[str, Any]] = None,
) -> int:
    """Atomically refund OpenAI credits after a failed request."""
    if not uid:
        raise ValueError("Missing firebase uid")
    try:
        credits_refund = int(credits)
    except (TypeError, ValueError):
        credits_refund = 1
    if credits_refund < 1:
        credits_refund = 1

    client = get_firestore_client()
    doc_ref = client.collection(USERS_COLLECTION).document(uid)
    transaction = client.transaction()
    normalized_breakdown = _normalize_credit_breakdown(credit_breakdown)

    @firebase_firestore.transactional
    def _update(txn: firebase_firestore.Transaction) -> int:
        snapshot = doc_ref.get(transaction=txn)
        data = snapshot.to_dict() or {}
        stored_role = normalize_role(data.get(ROLE_FIELD))
        charged_role = normalize_role(role) if role is not None else stored_role
        if charged_role == ROLE_GOD:
            return -1

        base_refund = normalized_breakdown.get("base", 0)
        monthly_refund = normalized_breakdown.get("monthly", 0)
        refill_refund = normalized_breakdown.get("refill", 0)
        if base_refund > 0 or monthly_refund > 0 or refill_refund > 0:
            updates: Dict[str, Any] = {"updated_at": now_iso()}
            total_available = 0

            if base_refund > 0:
                current_base = _resolve_openai_credits_remaining(data)
                current_base += base_refund
                updates[OPENAI_CREDITS_FIELD] = current_base
                total_available += current_base

            if monthly_refund > 0 or refill_refund > 0:
                monthly_remaining, cycle_key, _ = _resolve_pro_monthly_pool(data)
                next_monthly = monthly_remaining + monthly_refund
                next_refill = _resolve_pro_refill_credits_remaining(data) + refill_refund
                updates[OPENAI_CREDITS_MONTHLY_FIELD] = next_monthly
                updates[OPENAI_CREDITS_REFILL_FIELD] = next_refill
                updates[OPENAI_CREDITS_MONTHLY_CYCLE_FIELD] = cycle_key
                total_available += next_monthly + next_refill
            elif stored_role == ROLE_PRO:
                monthly_remaining, _, _ = _resolve_pro_monthly_pool(data)
                total_available += monthly_remaining + _resolve_pro_refill_credits_remaining(data)
            elif total_available == 0:
                total_available = _resolve_openai_credits_remaining(data)

            txn.set(doc_ref, updates, merge=True)
            return total_available

        if charged_role == ROLE_PRO:
            monthly_remaining, cycle_key, _ = _resolve_pro_monthly_pool(data)
            refill_remaining = _resolve_pro_refill_credits_remaining(data)

            if monthly_refund + refill_refund <= 0:
                # Fallback path for older callers that do not send pool breakdown.
                # Refunding into refill avoids accidental month-boundary inflation.
                refill_refund = credits_refund

            next_monthly = monthly_remaining + monthly_refund
            next_refill = refill_remaining + refill_refund
            txn.set(
                doc_ref,
                {
                    OPENAI_CREDITS_MONTHLY_FIELD: next_monthly,
                    OPENAI_CREDITS_REFILL_FIELD: next_refill,
                    OPENAI_CREDITS_MONTHLY_CYCLE_FIELD: cycle_key,
                    "updated_at": now_iso(),
                },
                merge=True,
            )
            return next_monthly + next_refill

        remaining = _resolve_openai_credits_remaining(data)
        new_remaining = remaining + credits_refund
        updates = {
            OPENAI_CREDITS_FIELD: new_remaining,
            "updated_at": now_iso(),
        }
        txn.set(doc_ref, updates, merge=True)
        return new_remaining

    return _update(transaction)


def set_user_role(uid: str, role: str) -> None:
    """Update the role field on the Firestore user document.
    """
    if not uid:
        raise ValueError("Missing firebase uid")
    normalized = normalize_role(role)
    client = get_firestore_client()
    doc_ref = client.collection(USERS_COLLECTION).document(uid)
    doc_ref.set(
        {
            ROLE_FIELD: normalized,
            "updated_at": now_iso(),
        },
        merge=True,
    )


def activate_pro_membership_with_subscription(
    uid: str,
    *,
    stripe_event_id: Optional[str] = None,
    customer_id: Optional[str] = None,
    subscription_id: Optional[str] = None,
    subscription_status: Optional[str] = None,
    subscription_price_id: Optional[str] = None,
    cancel_at_period_end: Any = _UNSET,
    cancel_at: Any = _UNSET,
    current_period_end: Any = _UNSET,
) -> bool:
    """Promote a user to pro and atomically persist subscription metadata.

    Returns True when the promotion was applied for this call. When a Stripe
    event id is supplied and has already been processed for the user, this is a
    no-op for membership reset and returns False. Subscription metadata updates
    are still applied when provided, which allows retries to heal partial
    records from older releases.
    """
    if not uid:
        raise ValueError("Missing firebase uid")
    client = get_firestore_client()
    doc_ref = client.collection(USERS_COLLECTION).document(uid)
    transaction = client.transaction()

    @firebase_firestore.transactional
    def _update(txn: firebase_firestore.Transaction) -> bool:
        snapshot = doc_ref.get(transaction=txn)
        data = snapshot.to_dict() or {}
        processed_ids = _resolve_processed_stripe_event_ids(data)
        next_processed_ids, already_applied = _apply_processed_stripe_event_id(processed_ids, stripe_event_id)
        updates: Dict[str, Any] = {}
        if not already_applied:
            updates.update(
                {
                    ROLE_FIELD: ROLE_PRO,
                    OPENAI_CREDITS_MONTHLY_FIELD: PRO_MONTHLY_OPENAI_CREDITS,
                    OPENAI_CREDITS_MONTHLY_CYCLE_FIELD: _current_month_cycle_key(),
                    OPENAI_CREDITS_REFILL_FIELD: _resolve_pro_refill_credits_remaining(data),
                }
            )
        updates[DOWNGRADE_RETENTION_FIELD] = firebase_firestore.DELETE_FIELD
        _apply_subscription_updates(
            updates,
            customer_id=customer_id,
            subscription_id=subscription_id,
            subscription_status=subscription_status,
            subscription_price_id=subscription_price_id,
            cancel_at_period_end=cancel_at_period_end,
            cancel_at=cancel_at,
            current_period_end=current_period_end,
        )
        if _normalize_stripe_event_id(stripe_event_id) and not already_applied:
            updates[STRIPE_PROCESSED_EVENT_IDS_FIELD] = next_processed_ids
        if not updates:
            return False
        updates["updated_at"] = now_iso()
        txn.set(doc_ref, updates, merge=True)
        return not already_applied

    return _update(transaction)


def activate_pro_membership(uid: str, *, stripe_event_id: Optional[str] = None) -> bool:
    """Promote a user to pro and reset their monthly credit pool."""
    return activate_pro_membership_with_subscription(uid, stripe_event_id=stripe_event_id)


def downgrade_to_base_membership(uid: str) -> None:
    """Downgrade a user to base while retaining refill balance for future pro upgrades."""
    set_user_role(uid, ROLE_BASE)


def add_refill_openai_credits(
    uid: str,
    *,
    credits: int,
    stripe_event_id: Optional[str] = None,
) -> int:
    """Increment non-expiring pro refill credits and return the new refill balance."""
    if not uid:
        raise ValueError("Missing firebase uid")
    try:
        credits_to_add = int(credits)
    except (TypeError, ValueError):
        credits_to_add = 0
    if credits_to_add <= 0:
        raise ValueError("credits must be a positive integer")
    client = get_firestore_client()
    doc_ref = client.collection(USERS_COLLECTION).document(uid)
    transaction = client.transaction()

    @firebase_firestore.transactional
    def _update(txn: firebase_firestore.Transaction) -> int:
        snapshot = doc_ref.get(transaction=txn)
        data = snapshot.to_dict() or {}
        processed_ids = _resolve_processed_stripe_event_ids(data)
        next_processed_ids, already_applied = _apply_processed_stripe_event_id(processed_ids, stripe_event_id)
        refill_remaining = _resolve_pro_refill_credits_remaining(data)
        if already_applied:
            return refill_remaining
        next_refill = refill_remaining + credits_to_add
        updates: Dict[str, Any] = {
            OPENAI_CREDITS_REFILL_FIELD: next_refill,
            "updated_at": now_iso(),
        }
        if _normalize_stripe_event_id(stripe_event_id):
            updates[STRIPE_PROCESSED_EVENT_IDS_FIELD] = next_processed_ids
        txn.set(doc_ref, updates, merge=True)
        return next_refill

    return _update(transaction)


def set_user_billing_subscription(
    uid: str,
    *,
    customer_id: Optional[str] = None,
    subscription_id: Optional[str] = None,
    subscription_status: Optional[str] = None,
    subscription_price_id: Optional[str] = None,
    cancel_at_period_end: Any = _UNSET,
    cancel_at: Any = _UNSET,
    current_period_end: Any = _UNSET,
) -> None:
    """Store Stripe subscription identifiers for webhook reconciliation."""
    if not uid:
        raise ValueError("Missing firebase uid")
    updates: Dict[str, Any] = {}
    _apply_subscription_updates(
        updates,
        customer_id=customer_id,
        subscription_id=subscription_id,
        subscription_status=subscription_status,
        subscription_price_id=subscription_price_id,
        cancel_at_period_end=cancel_at_period_end,
        cancel_at=cancel_at,
        current_period_end=current_period_end,
    )
    if not updates:
        return
    updates["updated_at"] = now_iso()
    client = get_firestore_client()
    client.collection(USERS_COLLECTION).document(uid).set(updates, merge=True)


def get_user_downgrade_retention(uid: str) -> Optional[UserDowngradeRetentionRecord]:
    normalized_uid = (uid or "").strip()
    if not normalized_uid:
        return None
    client = get_firestore_client()
    snapshot = client.collection(USERS_COLLECTION).document(normalized_uid).get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    return _normalize_downgrade_retention(data.get(DOWNGRADE_RETENTION_FIELD))


def set_user_downgrade_retention(
    uid: str,
    *,
    status: str,
    policy_version: int,
    downgraded_at: Optional[str],
    grace_ends_at: Optional[str],
    saved_forms_limit: int,
    fill_links_active_limit: int,
    kept_template_ids: List[str],
    pending_delete_template_ids: List[str],
    pending_delete_link_ids: List[str],
    billing_state_deferred: bool = False,
) -> None:
    if not uid:
        raise ValueError("Missing firebase uid")
    payload = {
        DOWNGRADE_RETENTION_FIELD: {
            "status": (status or "").strip().lower() or "grace_period",
            "policy_version": max(1, int(policy_version or 1)),
            "downgraded_at": (downgraded_at or "").strip() or None,
            "grace_ends_at": (grace_ends_at or "").strip() or None,
            "saved_forms_limit": max(1, int(saved_forms_limit)),
            "fill_links_active_limit": max(1, int(fill_links_active_limit)),
            "kept_template_ids": _coerce_string_list(kept_template_ids),
            "pending_delete_template_ids": _coerce_string_list(pending_delete_template_ids),
            "pending_delete_link_ids": _coerce_string_list(pending_delete_link_ids),
            "billing_state_deferred": bool(billing_state_deferred),
            "updated_at": now_iso(),
        },
        "updated_at": now_iso(),
    }
    client = get_firestore_client()
    client.collection(USERS_COLLECTION).document(uid).set(payload, merge=True)


def clear_user_downgrade_retention(uid: str) -> None:
    if not uid:
        raise ValueError("Missing firebase uid")
    client = get_firestore_client()
    client.collection(USERS_COLLECTION).document(uid).set(
        {
            DOWNGRADE_RETENTION_FIELD: firebase_firestore.DELETE_FIELD,
            "updated_at": now_iso(),
        },
        merge=True,
    )


def find_user_id_by_subscription_id(subscription_id: str) -> Optional[str]:
    """Resolve an app user id from a Stripe subscription id."""
    normalized = (subscription_id or "").strip()
    if not normalized:
        return None
    client = get_firestore_client()
    matches = where_equals(
        client.collection(USERS_COLLECTION),
        STRIPE_SUBSCRIPTION_ID_FIELD,
        normalized,
    ).get()
    if not matches:
        return None
    first = matches[0]
    user_id = (first.id or "").strip()
    return user_id or None


def get_user_billing_record(uid: str) -> Optional[UserBillingRecord]:
    """Fetch Stripe customer/subscription metadata for a user profile."""
    normalized_uid = (uid or "").strip()
    if not normalized_uid:
        return None
    client = get_firestore_client()
    snapshot = client.collection(USERS_COLLECTION).document(normalized_uid).get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    customer_id = (str(data.get(STRIPE_CUSTOMER_ID_FIELD) or "").strip() or None)
    subscription_id = (str(data.get(STRIPE_SUBSCRIPTION_ID_FIELD) or "").strip() or None)
    subscription_status = (str(data.get(STRIPE_SUBSCRIPTION_STATUS_FIELD) or "").strip() or None)
    subscription_price_id = (str(data.get(STRIPE_SUBSCRIPTION_PRICE_ID_FIELD) or "").strip() or None)
    cancel_at_period_end = _coerce_optional_bool(data.get(STRIPE_CANCEL_AT_PERIOD_END_FIELD))
    cancel_at = _coerce_optional_unix_timestamp(data.get(STRIPE_CANCEL_AT_FIELD))
    current_period_end = _coerce_optional_unix_timestamp(data.get(STRIPE_CURRENT_PERIOD_END_FIELD))
    return UserBillingRecord(
        uid=normalized_uid,
        customer_id=customer_id,
        subscription_id=subscription_id,
        subscription_status=subscription_status,
        subscription_price_id=subscription_price_id,
        cancel_at_period_end=cancel_at_period_end,
        cancel_at=cancel_at,
        current_period_end=current_period_end,
    )


def consume_rename_quota(uid: str, *, limit: Optional[int] = None) -> tuple[int, bool]:
    """Atomically increment rename usage and enforce limits.
    """
    if not uid:
        raise ValueError("Missing firebase uid")
    limit_val = int(limit or BASE_RENAME_LIMIT)
    client = get_firestore_client()
    doc_ref = client.collection(USERS_COLLECTION).document(uid)
    transaction = client.transaction()

    @firebase_firestore.transactional
    def _update(txn: firebase_firestore.Transaction) -> tuple[int, bool]:
        snapshot = doc_ref.get(transaction=txn)
        data = snapshot.to_dict() or {}
        try:
            count = int(data.get(RENAME_COUNT_FIELD) or 0)
        except (TypeError, ValueError):
            count = 0
        if count >= limit_val:
            return count, False
        new_count = count + 1
        updates = {
            RENAME_COUNT_FIELD: new_count,
            "updated_at": now_iso(),
        }
        if not snapshot.exists:
            updates.setdefault("firebase_uid", uid)
            updates.setdefault("created_at", now_iso())
        txn.set(doc_ref, updates, merge=True)
        return new_count, True

    return _update(transaction)


def get_user_profile(uid: str) -> Optional[UserProfileRecord]:
    """Fetch user metadata for profile display.
    """
    if not uid:
        return None
    client = get_firestore_client()
    doc_ref = client.collection(USERS_COLLECTION).document(uid)
    snapshot = doc_ref.get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    role = normalize_role(data.get(ROLE_FIELD))
    downgrade_retention = _normalize_downgrade_retention(data.get(DOWNGRADE_RETENTION_FIELD))
    email = data.get("email")
    display_name = data.get("displayName")
    credits: Optional[int]
    monthly_credits: Optional[int] = None
    refill_credits: Optional[int] = None
    available_credits: Optional[int] = None
    refill_locked = False
    if role == ROLE_GOD:
        credits = None
    elif role == ROLE_PRO:
        monthly_credits, cycle_key, reset_applied = _resolve_pro_monthly_pool(data)
        refill_credits = _resolve_pro_refill_credits_remaining(data)
        available_credits = monthly_credits + refill_credits
        credits = available_credits
        if reset_applied:
            # Use a transaction so concurrent requests at the month boundary
            # cannot overwrite credits that were consumed after our initial read.
            transaction = client.transaction()

            @firebase_firestore.transactional
            def _apply_monthly_reset(txn: firebase_firestore.Transaction) -> None:
                live_snapshot = doc_ref.get(transaction=txn)
                live_data = live_snapshot.to_dict() or {}
                _, live_cycle, still_needs_reset = _resolve_pro_monthly_pool(live_data)
                if not still_needs_reset:
                    return
                txn.set(
                    doc_ref,
                    {
                        OPENAI_CREDITS_MONTHLY_FIELD: PRO_MONTHLY_OPENAI_CREDITS,
                        OPENAI_CREDITS_MONTHLY_CYCLE_FIELD: live_cycle,
                        "updated_at": now_iso(),
                    },
                    merge=True,
                )

            try:
                _apply_monthly_reset(transaction)
            except Exception:
                # Non-critical: the reset will be retried on the next profile load.
                pass
    else:
        credits = _resolve_openai_credits_remaining(data)
        refill_credits = _resolve_pro_refill_credits_remaining(data)
        available_credits = credits
        refill_locked = refill_credits > 0
    return UserProfileRecord(
        uid=uid,
        email=email,
        display_name=display_name,
        role=role,
        openai_credits_remaining=credits,
        openai_credits_monthly_remaining=monthly_credits,
        openai_credits_refill_remaining=refill_credits,
        openai_credits_available=available_credits,
        refill_credits_locked=refill_locked,
        downgrade_retention=downgrade_retention,
    )
