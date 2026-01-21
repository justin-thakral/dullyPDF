#!/usr/bin/env python3
"""Firestore cleanup utilities for schema metadata and template mappings."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys
from typing import Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.firebaseDB.firebase_service import get_firestore_client, init_firebase


SCHEMA_COLLECTION = "schema_metadata"
MAPPING_COLLECTION = "template_mappings"
OPENAI_COLLECTIONS = ("openai_requests", "openai_rename_requests", "detection_requests")


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw)
    except ValueError:
        return default


def _parse_timestamp(value: object) -> Optional[datetime]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def _purge_collection(collection: str, *, execute: bool, max_docs: int) -> Tuple[int, int]:
    client = get_firestore_client()
    batch = client.batch()
    deleted = 0
    committed = 0
    for doc in client.collection(collection).stream():
        deleted += 1
        if execute:
            batch.delete(doc.reference)
        if execute and deleted % 500 == 0:
            batch.commit()
            committed += 1
            batch = client.batch()
        if max_docs and deleted >= max_docs:
            break
    if execute and deleted % 500 != 0:
        batch.commit()
        committed += 1
    return deleted, committed


def _backfill_schema_ttl(*, execute: bool, ttl_seconds: int, max_docs: int) -> Tuple[int, int]:
    client = get_firestore_client()
    batch = client.batch()
    updated = 0
    committed = 0
    now = datetime.now(timezone.utc)
    for doc in client.collection(SCHEMA_COLLECTION).stream():
        data = doc.to_dict() or {}
        if data.get("expires_at"):
            continue
        created_at = _parse_timestamp(data.get("created_at")) or now
        expires_at = created_at + timedelta(seconds=ttl_seconds)
        if execute:
            batch.update(doc.reference, {"expires_at": expires_at})
        updated += 1
        if execute and updated % 500 == 0:
            batch.commit()
            committed += 1
            batch = client.batch()
        if max_docs and updated >= max_docs:
            break
    if execute and updated % 500 != 0:
        batch.commit()
        committed += 1
    return updated, committed


def _backfill_log_ttl(*, execute: bool, ttl_seconds: int, max_docs: int) -> Tuple[int, int]:
    client = get_firestore_client()
    batch = client.batch()
    updated = 0
    committed = 0
    now = datetime.now(timezone.utc)
    for collection in OPENAI_COLLECTIONS:
        for doc in client.collection(collection).stream():
            data = doc.to_dict() or {}
            if data.get("expires_at"):
                continue
            created_at = _parse_timestamp(data.get("created_at")) or now
            expires_at = created_at + timedelta(seconds=ttl_seconds)
            if execute:
                batch.update(doc.reference, {"expires_at": expires_at})
            updated += 1
            if execute and updated % 500 == 0:
                batch.commit()
                committed += 1
                batch = client.batch()
            if max_docs and updated >= max_docs:
                return updated, committed
    if execute and updated % 500 != 0:
        batch.commit()
        committed += 1
    return updated, committed


def main() -> int:
    parser = argparse.ArgumentParser(description="Cleanup Firestore artifacts.")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply changes. Default is dry-run.",
    )
    parser.add_argument(
        "--purge-template-mappings",
        action="store_true",
        help="Delete all documents in the template_mappings collection.",
    )
    parser.add_argument(
        "--backfill-schema-ttl",
        action="store_true",
        help="Backfill expires_at for schema_metadata documents missing it.",
    )
    parser.add_argument(
        "--backfill-log-ttl",
        action="store_true",
        help="Backfill expires_at for OpenAI + detection log documents missing it.",
    )
    parser.add_argument(
        "--schema-ttl-seconds",
        type=int,
        default=_int_env("SANDBOX_SCHEMA_TTL_SECONDS", 3600),
        help="TTL seconds to apply when backfilling schema metadata.",
    )
    parser.add_argument(
        "--log-ttl-seconds",
        type=int,
        default=_int_env("SANDBOX_OPENAI_LOG_TTL_SECONDS", 2592000),
        help="TTL seconds to apply when backfilling OpenAI + detection logs.",
    )
    parser.add_argument(
        "--max-docs",
        type=int,
        default=0,
        help="Maximum number of documents to update/delete (0 = no limit).",
    )
    args = parser.parse_args()

    if (
        not args.purge_template_mappings
        and not args.backfill_schema_ttl
        and not args.backfill_log_ttl
    ):
        parser.error(
            "Specify --purge-template-mappings, --backfill-schema-ttl, and/or --backfill-log-ttl"
        )

    init_firebase()
    execute = bool(args.execute)
    mode = "EXECUTE" if execute else "DRY-RUN"

    if args.purge_template_mappings:
        deleted, commits = _purge_collection(
            MAPPING_COLLECTION,
            execute=execute,
            max_docs=args.max_docs,
        )
        print(f"[{mode}] Purge template_mappings: deleted={deleted} commits={commits}")

    if args.backfill_schema_ttl:
        updated, commits = _backfill_schema_ttl(
            execute=execute,
            ttl_seconds=args.schema_ttl_seconds,
            max_docs=args.max_docs,
        )
        print(f"[{mode}] Backfill schema TTL: updated={updated} commits={commits}")

    if args.backfill_log_ttl:
        updated, commits = _backfill_log_ttl(
            execute=execute,
            ttl_seconds=args.log_ttl_seconds,
            max_docs=args.max_docs,
        )
        print(f"[{mode}] Backfill log TTL: updated={updated} commits={commits}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
