#!/usr/bin/env python3
"""Clean test-results artifacts."""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
KEEP_NAMES = {"cleanOutput.py", "README.md"}


def _is_within(base: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _remove_path(path: Path, dry_run: bool) -> None:
    if not _is_within(BASE_DIR, path):
        raise RuntimeError(f"Refusing to delete outside {BASE_DIR}: {path}")
    if dry_run:
        print(f"dry-run: remove {path}")
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)
    print(f"removed: {path}")


def _clear_all(dry_run: bool) -> None:
    for entry in sorted(BASE_DIR.iterdir()):
        if entry.name in KEEP_NAMES:
            continue
        _remove_path(entry, dry_run)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Clean test-results artifacts.")
    parser.add_argument(
        "--last-run",
        action="store_true",
        help="Remove test-results/.last-run.json",
    )
    parser.add_argument("--all", action="store_true", help="Clear all test-results")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without deleting anything",
    )

    args = parser.parse_args(argv)

    if args.all:
        _clear_all(args.dry_run)
        return 0

    if not args.last_run:
        parser.print_help(sys.stderr)
        return 2

    target = BASE_DIR / ".last-run.json"
    if target.exists():
        _remove_path(target, args.dry_run)
    else:
        print(f"skip: {target} does not exist")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
