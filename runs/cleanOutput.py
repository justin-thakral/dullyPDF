#!/usr/bin/env python3
"""Clean run artifacts under runs/."""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


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
    parser = argparse.ArgumentParser(description="Clean run artifacts under runs/.")
    parser.add_argument("--detect", action="store_true", help="Clear runs/detect")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Clear all run artifacts (currently runs/detect)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without deleting anything",
    )

    args = parser.parse_args(argv)

    if args.all:
        args.detect = True

    if not args.detect:
        parser.print_help(sys.stderr)
        return 2

    if args.detect:
        _clear_dir(BASE_DIR / "detect", args.dry_run)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
