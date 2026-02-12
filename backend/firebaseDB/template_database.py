"""Firestore-backed template metadata operations."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from backend.logging_config import get_logger
from ..time_utils import now_iso
from .firebase_service import get_firestore_client


logger = get_logger(__name__)

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


def _serialize_template(doc) -> TemplateRecord:
    """Convert a Firestore document into a TemplateRecord.
    """
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
    """Fetch and sort templates owned by a given user.
    """
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
    """Fetch a template record if the user owns it.
    """
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
    """Persist a new template mapping record.
    """
    if not user_id:
        raise ValueError("user_id is required")
    if not pdf_path or not template_path:
        raise ValueError("pdf_path and template_path are required")
    client = get_firestore_client()
    doc_ref = client.collection(TEMPLATES_COLLECTION).document()
    timestamp = now_iso()
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


def update_template(
    template_id: str,
    user_id: str,
    *,
    pdf_path: Optional[str] = None,
    template_path: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[TemplateRecord]:
    """Update a template record if the user owns it.
    """
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
    payload: Dict[str, Any] = {"updated_at": now_iso()}
    if pdf_path is not None:
        payload["pdf_bucket_path"] = pdf_path
    if template_path is not None:
        payload["template_bucket_path"] = template_path
    if metadata is not None:
        payload["metadata"] = metadata
    doc_ref.set(payload, merge=True)
    logger.debug("Updated template mapping: %s", template_id)
    return _serialize_template(doc_ref.get())


def delete_template(template_id: str, user_id: str) -> bool:
    """Delete a template record if it belongs to the caller.
    """
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
