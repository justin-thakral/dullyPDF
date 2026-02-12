"""Firestore-backed schema metadata operations.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
from typing import Any, Dict, List, Optional

from backend.logging_config import get_logger
from .firebase_service import get_firestore_client
from .log_utils import log_expires_at, now_iso


logger = get_logger(__name__)

SCHEMAS_COLLECTION = "schema_metadata"
OPENAI_REQUESTS_COLLECTION = "openai_requests"
OPENAI_RENAME_REQUESTS_COLLECTION = "openai_rename_requests"
try:
    _SCHEMA_TTL_SECONDS = int(os.getenv("SANDBOX_SCHEMA_TTL_SECONDS", "3600"))
except ValueError:
    _SCHEMA_TTL_SECONDS = 3600


@dataclass(frozen=True)
class SchemaRecord:
    id: str
    name: Optional[str]
    fields: List[Dict[str, Any]]
    owner_user_id: str
    created_at: Optional[str]
    updated_at: Optional[str]
    source: Optional[str]
    sample_count: Optional[int]


def _schema_expires_at() -> Optional[datetime]:
    """Return expiration timestamp for schema metadata."""
    if _SCHEMA_TTL_SECONDS <= 0:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=_SCHEMA_TTL_SECONDS)


def _is_expired(data: Dict[str, Any]) -> bool:
    expires_at = data.get("expires_at")
    if not expires_at:
        return False
    if isinstance(expires_at, datetime):
        return expires_at <= datetime.now(timezone.utc)
    if isinstance(expires_at, str):
        try:
            return datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc)
        except ValueError:
            return False
    return False


def _serialize_schema(doc) -> SchemaRecord:
    data = doc.to_dict() or {}
    return SchemaRecord(
        id=doc.id,
        name=data.get("name"),
        fields=list(data.get("fields") or []),
        owner_user_id=data.get("owner_user_id") or "",
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
        source=data.get("source"),
        sample_count=data.get("sample_count"),
    )


def create_schema(
    *,
    user_id: str,
    fields: List[Dict[str, Any]],
    name: Optional[str] = None,
    source: Optional[str] = None,
    sample_count: Optional[int] = None,
) -> SchemaRecord:
    """Persist a schema metadata record (headers/types only).
    """
    if not user_id:
        raise ValueError("user_id is required")
    if not fields:
        raise ValueError("Schema fields are required")
    client = get_firestore_client()
    doc_ref = client.collection(SCHEMAS_COLLECTION).document()
    timestamp = now_iso()
    payload = {
        "owner_user_id": user_id,
        "name": name or None,
        "fields": fields,
        "source": source or None,
        "sample_count": sample_count,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    expires_at = _schema_expires_at()
    if expires_at:
        payload["expires_at"] = expires_at
    doc_ref.set(payload)
    logger.debug("Stored schema metadata: %s", doc_ref.id)
    return _serialize_schema(doc_ref.get())


def list_schemas(user_id: str) -> List[SchemaRecord]:
    """Fetch schemas owned by a user.
    """
    if not user_id:
        return []
    client = get_firestore_client()
    snapshot = client.collection(SCHEMAS_COLLECTION).where("owner_user_id", "==", user_id).get()
    records = []
    for doc in snapshot:
        data = doc.to_dict() or {}
        if _is_expired(data):
            continue
        records.append(_serialize_schema(doc))
    records.sort(key=lambda rec: rec.created_at or "", reverse=True)
    return records


def get_schema(schema_id: str, user_id: str) -> Optional[SchemaRecord]:
    """Fetch a schema record if the user owns it.
    """
    if not schema_id or not user_id:
        return None
    client = get_firestore_client()
    doc_ref = client.collection(SCHEMAS_COLLECTION).document(schema_id)
    snapshot = doc_ref.get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    if data.get("owner_user_id") != user_id:
        logger.debug("Schema ownership mismatch blocked: %s", schema_id)
        return None
    if _is_expired(data):
        logger.debug("Schema expired: %s", schema_id)
        return None
    return _serialize_schema(snapshot)


def record_openai_request(
    *,
    request_id: str,
    user_id: str,
    schema_id: str,
    template_id: Optional[str],
) -> None:
    """Store minimal metadata for an OpenAI mapping call.
    """
    if not request_id or not user_id or not schema_id:
        raise ValueError("Missing required OpenAI request metadata")
    client = get_firestore_client()
    doc_ref = client.collection(OPENAI_REQUESTS_COLLECTION).document(request_id)
    payload = {
        "request_id": request_id,
        "user_id": user_id,
        "schema_id": schema_id,
        "template_id": template_id or None,
        "created_at": now_iso(),
    }
    expires_at = log_expires_at()
    if expires_at:
        payload["expires_at"] = expires_at
    doc_ref.set(payload)


def record_openai_rename_request(
    *,
    request_id: str,
    user_id: str,
    session_id: str,
    schema_id: Optional[str] = None,
) -> None:
    """Store minimal metadata for an OpenAI rename call.
    """
    if not request_id or not user_id or not session_id:
        raise ValueError("Missing required OpenAI rename metadata")
    client = get_firestore_client()
    doc_ref = client.collection(OPENAI_RENAME_REQUESTS_COLLECTION).document(request_id)
    payload = {
        "request_id": request_id,
        "user_id": user_id,
        "schema_id": schema_id or None,
        "session_id": session_id,
        "created_at": now_iso(),
    }
    expires_at = log_expires_at()
    if expires_at:
        payload["expires_at"] = expires_at
    doc_ref.set(payload)
