"""Delete downgrade-queued saved forms after the grace period expires."""

from __future__ import annotations

import argparse
from typing import Iterable

from backend.services.downgrade_retention_service import (
    delete_user_downgrade_retention_now,
    list_users_with_expired_downgrade_retention,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Delete saved forms and dependent Fill By Link records still queued after a downgrade grace period expires."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the user ids that would be purged without deleting anything.",
    )
    return parser


def _print_user_ids(user_ids: Iterable[str]) -> None:
    for user_id in user_ids:
        print(user_id)


def main() -> int:
    args = _build_parser().parse_args()
    expired_user_ids = list_users_with_expired_downgrade_retention()
    if args.dry_run:
        _print_user_ids(expired_user_ids)
        print(f"dry-run users={len(expired_user_ids)}")
        return 0

    deleted_templates = 0
    deleted_links = 0
    failed_users = 0
    for user_id in expired_user_ids:
        try:
            result = delete_user_downgrade_retention_now(user_id)
        except Exception as exc:
            failed_users += 1
            print(f"failed user={user_id} error={exc}")
            continue
        deleted_templates += len(result.get("deletedTemplateIds") or [])
        deleted_links += len(result.get("deletedLinkIds") or [])
        print(
            f"purged user={user_id} templates={len(result.get('deletedTemplateIds') or [])} "
            f"links={len(result.get('deletedLinkIds') or [])}",
        )

    print(
        f"completed users={len(expired_user_ids)} templates={deleted_templates} "
        f"links={deleted_links} failed={failed_users}",
    )
    return 1 if failed_users else 0


if __name__ == "__main__":
    raise SystemExit(main())
