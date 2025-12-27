import time
import uuid
from dataclasses import dataclass
from typing import Dict, Optional


DEFAULT_TTL_MS = 60 * 60 * 1000


@dataclass
class ConnectionRecord:
    id: str
    type: str
    config: dict
    schema: str
    view: str
    created_at: float
    expires_at: float


_connections: Dict[str, ConnectionRecord] = {}


def _now_ms() -> float:
    return time.time() * 1000


def _purge_expired() -> None:
    now = _now_ms()
    expired = [key for key, rec in _connections.items() if rec.expires_at <= now]
    for key in expired:
        _connections.pop(key, None)


def create(record: dict) -> ConnectionRecord:
    _purge_expired()
    ttl_ms = record.get("ttlMs")
    ttl = ttl_ms if isinstance(ttl_ms, (int, float)) and ttl_ms > 0 else DEFAULT_TTL_MS
    created_at = _now_ms()
    conn_id = str(uuid.uuid4())
    entry = ConnectionRecord(
        id=conn_id,
        type=record["type"],
        config=record["config"],
        schema=record["schema"],
        view=record["view"],
        created_at=created_at,
        expires_at=created_at + ttl,
    )
    _connections[conn_id] = entry
    return entry


def get(conn_id: str) -> Optional[ConnectionRecord]:
    _purge_expired()
    record = _connections.get(conn_id)
    if not record:
        return None
    if record.expires_at <= _now_ms():
        _connections.pop(conn_id, None)
        return None
    return record


def remove(conn_id: str) -> bool:
    return _connections.pop(conn_id, None) is not None
