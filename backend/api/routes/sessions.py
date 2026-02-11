"""Session maintenance endpoints."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Header

from backend.services.auth_service import require_user
from backend.sessions.session_store import touch_session_entry as _touch_session_entry

router = APIRouter()


@router.post("/api/sessions/{session_id}/touch")
async def touch_session(
    session_id: str,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Refresh the session TTL so long-lived editor sessions are not cleaned up."""
    user = require_user(authorization)
    _touch_session_entry(session_id, user)
    return {"success": True, "sessionId": session_id}
