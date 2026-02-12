"""L1 in-process LRU session cache."""

import threading
import time
from collections import OrderedDict
from typing import Any, Dict

from ..env_utils import int_env as _int_env

SessionEntry = Dict[str, Any]

_SESSION_VERSION = 1

_API_SESSION_CACHE: "OrderedDict[str, SessionEntry]" = OrderedDict()
_SESSION_CACHE_LOCK = threading.Lock()

_SESSION_TTL_SECONDS = _int_env("SANDBOX_SESSION_TTL_SECONDS", 7200)
_SESSION_SWEEP_INTERVAL_SECONDS = _int_env("SANDBOX_SESSION_SWEEP_INTERVAL_SECONDS", 300)
_SESSION_MAX_ENTRIES = max(0, _int_env("SANDBOX_SESSION_MAX_ENTRIES", 200))
_SESSION_L2_TOUCH_SECONDS = max(0, _int_env("SANDBOX_SESSION_L2_TOUCH_SECONDS", 300))
_LAST_SESSION_SWEEP = 0.0


def _session_now() -> float:
    return time.monotonic()


def _session_last_access(entry: SessionEntry) -> float:
    raw = entry.get("last_access") or entry.get("created_at") or 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _prune_session_cache(now: float) -> None:
    global _LAST_SESSION_SWEEP
    if _SESSION_TTL_SECONDS <= 0:
        return
    if _SESSION_SWEEP_INTERVAL_SECONDS > 0 and (now - _LAST_SESSION_SWEEP) < _SESSION_SWEEP_INTERVAL_SECONDS:
        return
    cutoff = now - _SESSION_TTL_SECONDS
    expired_ids = [
        session_id
        for session_id, entry in _API_SESSION_CACHE.items()
        if _session_last_access(entry) < cutoff
    ]
    for session_id in expired_ids:
        _API_SESSION_CACHE.pop(session_id, None)
    _LAST_SESSION_SWEEP = now


def _trim_session_cache_size() -> None:
    if _SESSION_MAX_ENTRIES <= 0:
        return
    while len(_API_SESSION_CACHE) > _SESSION_MAX_ENTRIES:
        _API_SESSION_CACHE.popitem(last=False)


def _store_l1_entry(session_id: str, entry: SessionEntry) -> None:
    now = _session_now()
    entry["created_at"] = now
    entry["last_access"] = now
    with _SESSION_CACHE_LOCK:
        _prune_session_cache(now)
        _API_SESSION_CACHE[session_id] = entry
        _API_SESSION_CACHE.move_to_end(session_id)
        _trim_session_cache_size()
