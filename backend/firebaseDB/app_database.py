from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..fieldDetecting.sandbox.combinedSrc.config import get_logger
from .firebase_service import RequestUser, get_firestore_client


logger = get_logger(__name__)

USERS_COLLECTION = "app_users"
TEMPLATES_COLLECTION = "user_templates"


@dataclass(frozen=True)
class TemplateRecord:
    id: str
    pdf_bucket_path: Optional[str]
    template_bucket_path: Optional[str]
    metadata: Optional[Dict[str, Any]]
    created_at: Optional[str]
    updated_at: Optional[str]
    name: Optional[str]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    timestamp = _now_iso()

    if snapshot.exists:
        data = snapshot.to_dict() or {}
        updates: Dict[str, Any] = {}
        if email and email != data.get("email"):
            updates["email"] = email
        if (display_name or None) != data.get("displayName"):
            updates["displayName"] = display_name or None
        if updates:
            updates["updated_at"] = timestamp
            doc_ref.update(updates)
            logger.debug("Updated Firestore user record: %s", uid)
        return RequestUser(
            uid=uid,
            app_user_id=uid,
            email=updates.get("email") or data.get("email") or email,
            display_name=updates.get("displayName") or data.get("displayName") or display_name,
        )

    payload = {
        "firebase_uid": uid,
        "email": email or None,
        "displayName": display_name or None,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    doc_ref.set(payload)
    logger.debug("Created Firestore user record: %s", uid)
    return RequestUser(
        uid=uid,
        app_user_id=uid,
        email=email,
        display_name=display_name,
    )


def _serialize_template(doc) -> TemplateRecord:
    data = doc.to_dict() or {}
    metadata = data.get("metadata")
    return TemplateRecord(
        id=doc.id,
        pdf_bucket_path=data.get("pdf_bucket_path"),
        template_bucket_path=data.get("template_bucket_path"),
        metadata=metadata if isinstance(metadata, dict) else None,
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
        name=(metadata or {}).get("name") if isinstance(metadata, dict) else None,
    )


def list_templates(user_id: str) -> List[TemplateRecord]:
    if not user_id:
        return []
    client = get_firestore_client()
    snapshot = (
        client.collection(TEMPLATES_COLLECTION)
        .where("user_id", "==", user_id)
        .get()
    )
    records = [_serialize_template(doc) for doc in snapshot]
    records.sort(key=lambda rec: rec.created_at or "", reverse=True)
    logger.debug("Fetched templates: user=%s count=%s", user_id, len(records))
    return records


def get_template(template_id: str, user_id: str) -> Optional[TemplateRecord]:
    if not template_id or not user_id:
        return None
    client = get_firestore_client()
    doc_ref = client.collection(TEMPLATES_COLLECTION).document(template_id)
    snapshot = doc_ref.get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict() or {}
    if data.get("user_id") != user_id:
        logger.debug("Template ownership mismatch blocked: %s", template_id)
        return None
    return _serialize_template(snapshot)


def create_template(
    user_id: str,
    pdf_path: str,
    template_path: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> TemplateRecord:
    if not user_id:
        raise ValueError("user_id is required")
    if not pdf_path or not template_path:
        raise ValueError("pdf_path and template_path are required")
    client = get_firestore_client()
    doc_ref = client.collection(TEMPLATES_COLLECTION).document()
    timestamp = _now_iso()
    payload = {
        "user_id": user_id,
        "pdf_bucket_path": pdf_path,
        "template_bucket_path": template_path,
        "metadata": metadata or None,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    doc_ref.set(payload)
    logger.debug("Stored template mapping: %s", doc_ref.id)
    return _serialize_template(doc_ref.get())


def delete_template(template_id: str, user_id: str) -> bool:
    if not template_id or not user_id:
        return False
    client = get_firestore_client()
    doc_ref = client.collection(TEMPLATES_COLLECTION).document(template_id)
    snapshot = doc_ref.get()
    if not snapshot.exists:
        return False
    data = snapshot.to_dict() or {}
    if data.get("user_id") != user_id:
        logger.debug("Prevented deletion of template owned by another user: %s", template_id)
        return False
    doc_ref.delete()
    logger.debug("Deleted template: %s", template_id)
    return True
