"""Health endpoints."""

from __future__ import annotations

from typing import Dict

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@router.get("/api/health")
async def api_health() -> Dict[str, str]:
    return {"status": "ok"}
