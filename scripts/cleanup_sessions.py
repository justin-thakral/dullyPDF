#!/usr/bin/env python3
"""Cleanup expired session artifacts in Firestore + GCS.

This is intended for a scheduled job to keep GCS session artifacts aligned with
`SANDBOX_SESSION_TTL_SECONDS`. Firestore TTL is not immediate and does not
delete GCS objects, so this script deletes expired session prefixes directly.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
from typing import Dict, Iterable, Set

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.firebaseDB.firebase_service import get_firestore_client, get_storage_bucket, init_firebase


SESSION_COLLECTION = "session_cache"


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError:
        return default


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_session_bucket_name() -> str:
    bucket_name = (
        os.getenv("SANDBOX_SESSION_BUCKET")
        or os.getenv("SESSION_BUCKET")
        or os.getenv("FORMS_BUCKET")
    )
    if not bucket_name:
        raise RuntimeError("Missing SANDBOX_SESSION_BUCKET, SESSION_BUCKET, or FORMS_BUCKET")
    return bucket_name


def _iter_expired_session_ids(now: datetime) -> Iterable[str]:
    client = get_firestore_client()
    query = client.collection(SESSION_COLLECTION).where("expires_at", "<=", now)
    for doc in query.stream():
        yield doc.id


def _load_active_session_ids(now: datetime) -> Set[str]:
    client = get_firestore_client()
    active: Set[str] = set()
    query = client.collection(SESSION_COLLECTION).where("expires_at", ">", now)
    for doc in query.stream():
        active.add(doc.id)
    return active


def _delete_session_prefix(bucket_name: str, session_id: str, *, execute: bool) -> int:
    bucket = get_storage_bucket(bucket_name)
    prefix = f"sessions/{session_id}/"
    blobs = list(bucket.list_blobs(prefix=prefix))
    if execute:
        for blob in blobs:
            blob.delete()
    return len(blobs)


def _delete_firestore_doc(session_id: str, *, execute: bool) -> None:
    if not execute:
        return
    client = get_firestore_client()
    client.collection(SESSION_COLLECTION).document(session_id).delete()


def _load_session_prefixes(bucket_name: str) -> Dict[str, datetime]:
    bucket = get_storage_bucket(bucket_name)
    sessions: Dict[str, datetime] = {}
    for blob in bucket.list_blobs(prefix="sessions/"):
        parts = blob.name.split("/", 2)
        if len(parts) < 3:
            continue
        session_id = parts[1]
        updated = blob.updated or blob.time_created
        if not updated:
            continue
        current = sessions.get(session_id)
        if current is None or updated > current:
            sessions[session_id] = updated
    return sessions


def main() -> int:
    parser = argparse.ArgumentParser(description="Cleanup expired session artifacts in Firestore + GCS.")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Delete Firestore docs and GCS objects. Default is dry-run.",
    )
    parser.add_argument(
        "--skip-docs",
        action="store_true",
        help="Skip deleting Firestore session documents.",
    )
    parser.add_argument(
        "--max-sessions",
        type=int,
        default=0,
        help="Maximum number of sessions to delete (0 = no limit).",
    )
    args = parser.parse_args()

    init_firebase()
    now = _now_utc()
    ttl_seconds = _int_env("SANDBOX_SESSION_TTL_SECONDS", 3600)
    if ttl_seconds <= 0:
        print("SANDBOX_SESSION_TTL_SECONDS is <= 0; session cleanup disabled.")
        return 0
    grace_seconds = _int_env("SESSION_CLEANUP_GRACE_SECONDS", 300)
    cutoff = now.timestamp() - float(ttl_seconds + grace_seconds)
    bucket_name = _resolve_session_bucket_name()
    execute = bool(args.execute)
    delete_docs = execute and not args.skip_docs

    expired_ids = list(_iter_expired_session_ids(now))
    deleted_sessions = 0
    deleted_objects = 0
    for session_id in expired_ids:
        if args.max_sessions and deleted_sessions >= args.max_sessions:
            break
        deleted_objects += _delete_session_prefix(bucket_name, session_id, execute=execute)
        if delete_docs:
            _delete_firestore_doc(session_id, execute=True)
        deleted_sessions += 1

    active_ids = _load_active_session_ids(now)
    session_prefixes = _load_session_prefixes(bucket_name)
    orphaned_sessions = []
    for session_id, updated_at in session_prefixes.items():
        if session_id in active_ids:
            continue
        if updated_at.timestamp() <= cutoff:
            orphaned_sessions.append(session_id)

    for session_id in orphaned_sessions:
        if args.max_sessions and deleted_sessions >= args.max_sessions:
            break
        deleted_objects += _delete_session_prefix(bucket_name, session_id, execute=execute)
        deleted_sessions += 1

    mode = "EXECUTE" if execute else "DRY-RUN"
    print(
        f"[{mode}] Deleted sessions={deleted_sessions} objects={deleted_objects} "
        f"bucket={bucket_name} ttl_seconds={ttl_seconds} grace_seconds={grace_seconds}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
