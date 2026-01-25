#!/usr/bin/env python3
"""Clean frontend-generated artifacts."""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
TMP_DIR = BASE_DIR / "node_modules" / ".tmp"


def _is_within(base: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _clear_dir(path: Path, dry_run: bool) -> None:
    if not path.exists():
        print(f"skip: {path} does not exist")
        return
    if not _is_within(BASE_DIR, path):
        raise RuntimeError(f"Refusing to delete outside {BASE_DIR}: {path}")
    if dry_run:
        print(f"dry-run: remove contents of {path}")
        return
    shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    print(f"cleared: {path}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Clean frontend artifacts.")
    parser.add_argument(
        "--tmp",
        action="store_true",
        help="Clear frontend/node_modules/.tmp",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Clear all frontend artifacts (currently node_modules/.tmp)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without deleting anything",
    )

    args = parser.parse_args(argv)

    if args.all:
        args.tmp = True

    if not args.tmp:
        parser.print_help(sys.stderr)
        return 2

    _clear_dir(TMP_DIR, args.dry_run)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
