"""Authenticated named group endpoints for saved templates."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException

from backend.api.schemas import TemplateGroupCreateRequest, TemplateGroupUpdateRequest
from backend.firebaseDB.group_database import (
    create_group,
    delete_group,
    get_group,
    list_groups,
    normalize_group_name,
    update_group,
)
from backend.firebaseDB.fill_link_database import (
    close_fill_link,
    close_fill_links_for_group,
    get_fill_link_for_group,
    update_fill_link,
)
from backend.firebaseDB.template_database import list_templates
from backend.services.auth_service import require_user

router = APIRouter()


def _serialize_group(record, template_lookup: Dict[str, Any]) -> Dict[str, Any]:
    templates: List[Dict[str, Any]] = []
    for template_id in record.template_ids:
        template = template_lookup.get(template_id)
        if not template:
            continue
        templates.append(
            {
                "id": template.id,
                "name": template.name or template.pdf_bucket_path or "Saved form",
                "createdAt": template.created_at,
            }
        )
    templates.sort(key=lambda entry: (entry["name"].lower(), entry["id"]))
    return {
        "id": record.id,
        "name": record.name,
        "templateIds": [entry["id"] for entry in templates],
        "templateCount": len(templates),
        "templates": templates,
        "createdAt": record.created_at,
        "updatedAt": record.updated_at,
    }


def _sync_group_fill_link_after_update(previous_group, next_group, user_id: str) -> None:
    existing_link = get_fill_link_for_group(next_group.id, user_id)
    if not existing_link:
        return

    if list(previous_group.template_ids) != list(next_group.template_ids):
        if existing_link.status == "active":
            close_fill_link(existing_link.id, user_id, closed_reason="group_updated")
        return

    if previous_group.name == next_group.name:
        return

    next_title = next_group.name if (existing_link.title or "").strip() == (previous_group.name or "").strip() else None
    update_fill_link(
        existing_link.id,
        user_id,
        group_name=next_group.name,
        title=next_title,
    )


@router.get("/api/groups")
async def list_owner_groups(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    user = require_user(authorization)
    templates = list_templates(user.app_user_id)
    template_lookup = {template.id: template for template in templates}
    groups = list_groups(user.app_user_id)
    return {"groups": [_serialize_group(group, template_lookup) for group in groups]}


@router.post("/api/groups")
async def create_owner_group(
    payload: TemplateGroupCreateRequest,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    user = require_user(authorization)
    templates = list_templates(user.app_user_id)
    template_lookup = {template.id: template for template in templates}
    missing = [template_id for template_id in payload.templateIds if template_id not in template_lookup]
    if missing:
        raise HTTPException(status_code=404, detail="One or more saved forms were not found")

    normalized_name = normalize_group_name(payload.name)
    existing = list_groups(user.app_user_id)
    if any(group.normalized_name == normalized_name for group in existing):
        raise HTTPException(status_code=409, detail="A group with this name already exists")

    group = create_group(
        user.app_user_id,
        name=payload.name,
        template_ids=payload.templateIds,
    )
    return {
        "success": True,
        "group": _serialize_group(group, template_lookup),
    }


@router.get("/api/groups/{group_id}")
async def get_owner_group(
    group_id: str,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    user = require_user(authorization)
    group = get_group(group_id, user.app_user_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    templates = list_templates(user.app_user_id)
    template_lookup = {template.id: template for template in templates}
    return {"group": _serialize_group(group, template_lookup)}


@router.patch("/api/groups/{group_id}")
async def update_owner_group(
    group_id: str,
    payload: TemplateGroupUpdateRequest,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    user = require_user(authorization)
    existing_group = get_group(group_id, user.app_user_id)
    if not existing_group:
        raise HTTPException(status_code=404, detail="Group not found")

    templates = list_templates(user.app_user_id)
    template_lookup = {template.id: template for template in templates}
    missing = [template_id for template_id in payload.templateIds if template_id not in template_lookup]
    if missing:
        raise HTTPException(status_code=404, detail="One or more saved forms were not found")

    normalized_name = normalize_group_name(payload.name)
    existing = list_groups(user.app_user_id)
    if any(group.id != group_id and group.normalized_name == normalized_name for group in existing):
        raise HTTPException(status_code=409, detail="A group with this name already exists")

    group = update_group(
        group_id,
        user.app_user_id,
        name=payload.name,
        template_ids=payload.templateIds,
    )
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    _sync_group_fill_link_after_update(existing_group, group, user.app_user_id)
    return {
        "success": True,
        "group": _serialize_group(group, template_lookup),
    }


@router.delete("/api/groups/{group_id}")
async def delete_owner_group(
    group_id: str,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    user = require_user(authorization)
    existing_group = get_group(group_id, user.app_user_id)
    if not existing_group:
        raise HTTPException(status_code=404, detail="Group not found")
    close_fill_links_for_group(existing_group.id, user.app_user_id, closed_reason="group_deleted")
    deleted = delete_group(group_id, user.app_user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Group not found")
    return {"success": True}
