"""Firestore-backed named template groups."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from backend.logging_config import get_logger
from backend.time_utils import now_iso
from .firestore_query_utils import where_equals
from .firebase_service import get_firestore_client


logger = get_logger(__name__)

GROUPS_COLLECTION = "template_groups"


@dataclass(frozen=True)
class TemplateGroupRecord:
    id: str
    user_id: str
    name: str
    normalized_name: str
    template_ids: List[str]
    created_at: Optional[str]
    updated_at: Optional[str]


def normalize_group_name(value: Optional[str]) -> str:
    return " ".join(str(value or "").strip().split()).lower()


def _coerce_template_ids(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    deduped: List[str] = []
    for entry in value:
        template_id = str(entry or "").strip()
        if not template_id or template_id in deduped:
            continue
        deduped.append(template_id)
    return deduped


def _serialize_group(doc) -> TemplateGroupRecord:
    data = doc.to_dict() or {}
    name = " ".join(str(data.get("name") or "").strip().split()) or "Untitled group"
    normalized_name = normalize_group_name(data.get("normalized_name") or name)
    return TemplateGroupRecord(
        id=doc.id,
        user_id=str(data.get("user_id") or "").strip(),
        name=name,
        normalized_name=normalized_name,
        template_ids=_coerce_template_ids(data.get("template_ids")),
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
    )


def list_groups(user_id: str) -> List[TemplateGroupRecord]:
    if not user_id:
        return []
    client = get_firestore_client()
    snapshot = where_equals(client.collection(GROUPS_COLLECTION), "user_id", user_id).get()
    records = [_serialize_group(doc) for doc in snapshot]
    records.sort(key=lambda record: (record.name.lower(), record.created_at or "", record.id))
    return records


def get_group(group_id: str, user_id: str) -> Optional[TemplateGroupRecord]:
    if not group_id or not user_id:
        return None
    client = get_firestore_client()
    doc_ref = client.collection(GROUPS_COLLECTION).document(group_id)
    snapshot = doc_ref.get()
    if not snapshot.exists:
        return None
    record = _serialize_group(snapshot)
    if record.user_id != user_id:
        logger.debug("Template group ownership mismatch blocked: %s", group_id)
        return None
    return record


def create_group(user_id: str, *, name: str, template_ids: List[str]) -> TemplateGroupRecord:
    if not user_id:
        raise ValueError("user_id is required")
    cleaned_name = " ".join(str(name or "").strip().split())
    if not cleaned_name:
        raise ValueError("name is required")
    deduped_template_ids = _coerce_template_ids(template_ids)
    if not deduped_template_ids:
        raise ValueError("template_ids are required")
    client = get_firestore_client()
    doc_ref = client.collection(GROUPS_COLLECTION).document()
    timestamp = now_iso()
    payload = {
        "user_id": user_id,
        "name": cleaned_name,
        "normalized_name": normalize_group_name(cleaned_name),
        "template_ids": deduped_template_ids,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    doc_ref.set(payload)
    logger.debug("Created template group: user=%s group=%s templates=%s", user_id, doc_ref.id, len(deduped_template_ids))
    return _serialize_group(doc_ref.get())


def update_group(
    group_id: str,
    user_id: str,
    *,
    name: str,
    template_ids: List[str],
) -> Optional[TemplateGroupRecord]:
    if not group_id or not user_id:
        return None
    cleaned_name = " ".join(str(name or "").strip().split())
    if not cleaned_name:
        raise ValueError("name is required")
    deduped_template_ids = _coerce_template_ids(template_ids)
    if not deduped_template_ids:
        raise ValueError("template_ids are required")
    client = get_firestore_client()
    doc_ref = client.collection(GROUPS_COLLECTION).document(group_id)
    snapshot = doc_ref.get()
    if not snapshot.exists:
        return None
    record = _serialize_group(snapshot)
    if record.user_id != user_id:
        logger.debug("Template group ownership mismatch blocked: %s", group_id)
        return None
    doc_ref.set(
        {
            "name": cleaned_name,
            "normalized_name": normalize_group_name(cleaned_name),
            "template_ids": deduped_template_ids,
            "updated_at": now_iso(),
        },
        merge=True,
    )
    logger.debug(
        "Updated template group: user=%s group=%s templates=%s",
        user_id,
        group_id,
        len(deduped_template_ids),
    )
    return _serialize_group(doc_ref.get())


def delete_group(group_id: str, user_id: str) -> bool:
    if not group_id or not user_id:
        return False
    client = get_firestore_client()
    doc_ref = client.collection(GROUPS_COLLECTION).document(group_id)
    snapshot = doc_ref.get()
    if not snapshot.exists:
        return False
    record = _serialize_group(snapshot)
    if record.user_id != user_id:
        logger.debug("Template group ownership mismatch blocked on delete: %s", group_id)
        return False
    doc_ref.delete()
    logger.debug("Deleted template group: user=%s group=%s", user_id, group_id)
    return True


def remove_template_from_all_groups(template_id: str, user_id: str) -> int:
    if not template_id or not user_id:
        return 0
    client = get_firestore_client()
    snapshot = where_equals(client.collection(GROUPS_COLLECTION), "user_id", user_id).get()
    removed_count = 0
    for doc in snapshot:
        record = _serialize_group(doc)
        if template_id not in record.template_ids:
            continue
        doc_ref = client.collection(GROUPS_COLLECTION).document(record.id)
        next_template_ids = [entry for entry in record.template_ids if entry != template_id]
        if next_template_ids:
            doc_ref.set(
                {
                    "template_ids": next_template_ids,
                    "updated_at": now_iso(),
                },
                merge=True,
            )
        else:
            doc_ref.delete()
        removed_count += 1
    if removed_count:
        logger.debug("Removed template from groups: user=%s template=%s groups=%s", user_id, template_id, removed_count)
    return removed_count
