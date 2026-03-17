"""Purge Fill By Link Firestore collections for one or more projects.

This script intentionally targets only the Fill By Link collections:

- ``fill_links``
- ``fill_link_responses``
- ``fill_link_state``

Run without ``--execute`` first to inspect document counts before deletion.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Iterable, Sequence

from google.cloud import firestore


DEFAULT_COLLECTIONS = (
    "fill_links",
    "fill_link_responses",
    "fill_link_state",
)

DEFAULT_BATCH_SIZE = 400


@dataclass(frozen=True)
class CollectionPurgeSummary:
    project: str
    collection: str
    before_count: int
    deleted_count: int
    after_count: int


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Purge Fill By Link Firestore collections from explicit GCP projects.",
    )
    parser.add_argument(
        "--project",
        dest="projects",
        action="append",
        required=True,
        help="Firestore project id to target. Repeat for multiple projects.",
    )
    parser.add_argument(
        "--collection",
        dest="collections",
        action="append",
        help=(
            "Optional collection override. Defaults to fill_links, fill_link_responses, and fill_link_state. "
            "Repeat to target a subset."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Delete batch size per commit. Defaults to {DEFAULT_BATCH_SIZE}.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete documents. Without this flag the script performs a dry-run only.",
    )
    return parser


def _normalize_sequence(values: Iterable[str] | None, fallback: Sequence[str]) -> list[str]:
    deduped: list[str] = []
    for value in values or fallback:
        normalized = str(value or "").strip()
        if not normalized or normalized in deduped:
            continue
        deduped.append(normalized)
    return deduped


def _count_collection(client: firestore.Client, collection_name: str) -> int:
    count = 0
    for _ in client.collection(collection_name).stream():
        count += 1
    return count


def _delete_collection(
    client: firestore.Client,
    collection_name: str,
    *,
    batch_size: int,
) -> int:
    deleted = 0
    while True:
        docs = list(client.collection(collection_name).limit(batch_size).stream())
        if not docs:
            break
        batch = client.batch()
        for doc in docs:
            batch.delete(doc.reference)
        batch.commit()
        deleted += len(docs)
    return deleted


def _purge_project(
    project: str,
    *,
    collections: Sequence[str],
    batch_size: int,
    execute: bool,
) -> list[CollectionPurgeSummary]:
    client = firestore.Client(project=project)
    summaries: list[CollectionPurgeSummary] = []
    for collection_name in collections:
        before_count = _count_collection(client, collection_name)
        deleted_count = 0
        after_count = before_count
        if execute and before_count:
            deleted_count = _delete_collection(
                client,
                collection_name,
                batch_size=batch_size,
            )
            after_count = _count_collection(client, collection_name)
        summaries.append(
            CollectionPurgeSummary(
                project=project,
                collection=collection_name,
                before_count=before_count,
                deleted_count=deleted_count,
                after_count=after_count,
            ),
        )
    return summaries


def _print_summary(summary: CollectionPurgeSummary, *, execute: bool) -> None:
    if execute:
        print(
            f"project={summary.project} collection={summary.collection} "
            f"before={summary.before_count} deleted={summary.deleted_count} after={summary.after_count}",
        )
        return
    print(
        f"dry-run project={summary.project} collection={summary.collection} "
        f"count={summary.before_count}",
    )


def main() -> int:
    args = _build_parser().parse_args()
    projects = _normalize_sequence(args.projects, ())
    collections = _normalize_sequence(args.collections, DEFAULT_COLLECTIONS)
    batch_size = max(1, min(int(args.batch_size), 450))

    failed_projects = 0
    for project in projects:
        try:
            summaries = _purge_project(
                project,
                collections=collections,
                batch_size=batch_size,
                execute=bool(args.execute),
            )
        except Exception as exc:  # pragma: no cover - operational script
            failed_projects += 1
            print(f"failed project={project} error={exc}")
            continue
        for summary in summaries:
            _print_summary(summary, execute=bool(args.execute))

    if args.execute:
        print(
            f"completed projects={len(projects)} failed={failed_projects} execute=true collections={','.join(collections)}",
        )
    else:
        print(
            f"completed projects={len(projects)} failed={failed_projects} execute=false collections={','.join(collections)}",
        )
    return 1 if failed_projects else 0


if __name__ == "__main__":
    raise SystemExit(main())
