"""Authentication and admin override helpers."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import HTTPException
from firebase_admin import auth as firebase_auth

from backend.fieldDetecting.rename_pipeline.debug_flags import debug_enabled, get_debug_password
from backend.firebaseDB.app_database import ensure_user
from backend.firebaseDB.firebase_service import RequestUser, verify_id_token

from .app_config import is_prod


def is_password_sign_in(decoded: Dict[str, Any]) -> bool:
    """Return True when the token originated from email/password sign-in."""
    firebase_claims = decoded.get("firebase") if isinstance(decoded, dict) else {}
    if not isinstance(firebase_claims, dict):
        return False
    provider = str(firebase_claims.get("sign_in_provider") or "").strip().lower()
    return provider in {"password", "emaillink", "email_link"}


def enforce_email_verification(decoded: Dict[str, Any]) -> None:
    """Reject password users until their email is verified."""
    if not is_password_sign_in(decoded):
        return
    if decoded.get("email_verified") is True:
        return
    raise HTTPException(status_code=403, detail="Email verification required")


def verify_token(authorization: Optional[str]) -> Dict[str, Any]:
    """Validate Firebase auth headers and return decoded token."""
    try:
        decoded = verify_id_token(authorization)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Missing Authorization token") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail="Firebase authentication is not configured") from exc
    except firebase_auth.RevokedIdTokenError as exc:
        raise HTTPException(status_code=401, detail="Authorization token revoked") from exc
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid Authorization token") from exc
    enforce_email_verification(decoded)
    return decoded


def sync_request_user(auth_payload: Dict[str, Any]) -> RequestUser:
    """Resolve and upsert the current request user from decoded Firebase token."""
    try:
        return ensure_user(auth_payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to synchronize user profile") from exc


def require_user(authorization: Optional[str]) -> RequestUser:
    """Resolve the current user from Authorization header."""
    decoded = verify_token(authorization)
    return sync_request_user(decoded)


def has_admin_override(authorization: Optional[str], x_admin_token: Optional[str]) -> bool:
    """Return True when request includes a valid admin override token."""
    if is_prod():
        return False
    allow_override = os.getenv("SANDBOX_ALLOW_ADMIN_OVERRIDE", "").strip().lower()
    if allow_override and allow_override not in {"1", "true", "yes"}:
        return False
    token = os.getenv("ADMIN_TOKEN")
    if not token and debug_enabled():
        token = get_debug_password()
    if not token:
        return False
    bearer = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization.split(" ", 1)[1].strip()
    return bool(bearer == token or (x_admin_token and x_admin_token == token))
