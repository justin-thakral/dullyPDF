#!/usr/bin/env python3
"""Clean temporary artifacts under tmp/."""
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


def _clear_by_extension(extension: str, dry_run: bool) -> None:
    matches = [p for p in BASE_DIR.rglob(f"*{extension}") if p.is_file()]
    if not matches:
        print(f"skip: no *{extension} files in {BASE_DIR}")
        return
    for path in sorted(matches):
        _remove_path(path, dry_run)


def _remove_empty_dirs(dry_run: bool) -> None:
    for path in sorted(BASE_DIR.rglob("*"), reverse=True):
        if not path.is_dir():
            continue
        if path == BASE_DIR:
            continue
        try:
            next(path.iterdir())
            continue
        except StopIteration:
            if dry_run:
                print(f"dry-run: remove empty dir {path}")
                continue
            path.rmdir()
            print(f"removed: {path}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Clean temporary artifacts under tmp/.")
    parser.add_argument("--csvs", action="store_true", help="Remove *.csv files")
    parser.add_argument("--pdfs", action="store_true", help="Remove *.pdf files")
    parser.add_argument("--snapshots", action="store_true", help="Remove *.txt files")
    parser.add_argument("--all", action="store_true", help="Clear all tmp files")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without deleting anything",
    )

    args = parser.parse_args(argv)

    if args.all:
        _clear_all(args.dry_run)
        return 0

    if not any([args.csvs, args.pdfs, args.snapshots]):
        parser.print_help(sys.stderr)
        return 2

    if args.csvs:
        _clear_by_extension(".csv", args.dry_run)
    if args.pdfs:
        _clear_by_extension(".pdf", args.dry_run)
    if args.snapshots:
        _clear_by_extension(".txt", args.dry_run)

    _remove_empty_dirs(args.dry_run)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
