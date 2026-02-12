"""Firestore-backed user profile and quota operations."""

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from firebase_admin import firestore as firebase_firestore

from backend.logging_config import get_logger
from ..time_utils import now_iso
from .firebase_service import RequestUser, get_firestore_client


logger = get_logger(__name__)

USERS_COLLECTION = "app_users"
ROLE_BASE = "base"
ROLE_GOD = "god"
ROLE_FIELD = "role"
RENAME_COUNT_FIELD = "rename_count"
BASE_RENAME_LIMIT = int(os.getenv("BASE_RENAME_LIMIT", "10"))
OPENAI_CREDITS_FIELD = "openai_credits_remaining"
BASE_OPENAI_CREDITS = int(os.getenv("BASE_OPENAI_CREDITS", "10"))


@dataclass(frozen=True)
class UserProfileRecord:
    uid: str
    email: Optional[str]
    display_name: Optional[str]
    role: str
    openai_credits_remaining: Optional[int]


def normalize_role(value: Optional[str]) -> str:
    """Normalize role values to known constants.
    """
    raw = (value or "").strip().lower()
    if raw == ROLE_GOD:
        return ROLE_GOD
    return ROLE_BASE


def ensure_user(decoded: Dict[str, Any]) -> RequestUser:
    """
    Upsert the Firebase user into Firestore so template ownership is stable.
    """
    uid = decoded.get("uid") or decoded.get("user_id") or decoded.get("sub")
    if not uid:
        raise ValueError("Missing firebase uid")
    email = decoded.get("email")
    display_name = decoded.get("name") or decoded.get("displayName")
    role = normalize_role(decoded.get(ROLE_FIELD))
    client = get_firestore_client()
    doc_ref = client.collection(USERS_COLLECTION).document(uid)
    snapshot = doc_ref.get()
    timestamp = now_iso()

    if snapshot.exists:
        data = snapshot.to_dict() or {}
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


def consume_openai_credits(uid: str, *, credits: int, role: Optional[str] = None) -> tuple[int, bool]:
    """Atomically decrement OpenAI credits for a user.

    Credits are consumed per OpenAI action (rename or schema mapping), not per page.
    """
    if not uid:
        raise ValueError("Missing firebase uid")
    normalized_role = normalize_role(role)
    if normalized_role == ROLE_GOD:
        return -1, True
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
    def _update(txn: firebase_firestore.Transaction) -> tuple[int, bool]:
        snapshot = doc_ref.get(transaction=txn)
        data = snapshot.to_dict() or {}
        remaining = _resolve_openai_credits_remaining(data)
        if remaining < credits_required:
            return remaining, False
        new_remaining = remaining - credits_required
        updates = {
            OPENAI_CREDITS_FIELD: new_remaining,
            "updated_at": now_iso(),
        }
        txn.set(doc_ref, updates, merge=True)
        return new_remaining, True

    return _update(transaction)


def refund_openai_credits(uid: str, *, credits: int, role: Optional[str] = None) -> int:
    """Atomically refund OpenAI credits after a failed request."""
    if not uid:
        raise ValueError("Missing firebase uid")
    normalized_role = normalize_role(role)
    if normalized_role == ROLE_GOD:
        return -1
    try:
        credits_refund = int(credits)
    except (TypeError, ValueError):
        credits_refund = 1
    if credits_refund < 1:
        credits_refund = 1

    client = get_firestore_client()
    doc_ref = client.collection(USERS_COLLECTION).document(uid)
    transaction = client.transaction()

    @firebase_firestore.transactional
    def _update(txn: firebase_firestore.Transaction) -> int:
        snapshot = doc_ref.get(transaction=txn)
        data = snapshot.to_dict() or {}
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
    snapshot = client.collection(USERS_COLLECTION).document(uid).get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    role = normalize_role(data.get(ROLE_FIELD))
    email = data.get("email")
    display_name = data.get("displayName")
    credits: Optional[int]
    if role == ROLE_GOD:
        credits = None
    else:
        credits = _resolve_openai_credits_remaining(data)
    return UserProfileRecord(
        uid=uid,
        email=email,
        display_name=display_name,
        role=role,
        openai_credits_remaining=credits,
    )
