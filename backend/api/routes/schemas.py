"""Schema metadata endpoints."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException

from backend.ai.schema_mapping import build_allowlist_payload, validate_payload_size
from backend.api.schemas import SchemaCreateRequest
from backend.firebaseDB.schema_database import create_schema, list_schemas
from backend.services.auth_service import require_user

router = APIRouter()


@router.post("/api/schemas")
async def create_schema_endpoint(
    payload: SchemaCreateRequest,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Create a schema record containing only headers and inferred types."""
    user = require_user(authorization)
    raw_fields = [field.model_dump() for field in payload.fields]
    allowlist = build_allowlist_payload(raw_fields, [])
    schema_fields = allowlist.get("schemaFields") or []
    if not schema_fields:
        raise HTTPException(status_code=400, detail="Schema fields are required")
    try:
        validate_payload_size(allowlist)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    record = create_schema(
        user_id=user.app_user_id,
        fields=schema_fields,
        name=payload.name,
        source=payload.source,
        sample_count=payload.sampleCount,
    )
    return {
        "success": True,
        "schemaId": record.id,
        "name": record.name,
        "fieldCount": len(record.fields),
        "fields": record.fields,
        "createdAt": record.created_at,
    }


@router.get("/api/schemas")
async def list_schemas_endpoint(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    """List schemas owned by the caller."""
    user = require_user(authorization)
    records = list_schemas(user.app_user_id)
    return {
        "schemas": [
            {
                "id": record.id,
                "name": record.name,
                "fieldCount": len(record.fields),
                "fields": record.fields,
                "createdAt": record.created_at,
            }
            for record in records
        ]
    }
