#!/usr/bin/env python3
"""Clean MCP-generated artifacts under mcp/debugging.

Run with flags, e.g.:
  python3 mcp/cleanOutput.py --logs --screenshots
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DEBUG_DIR = BASE_DIR / "debugging"


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
    if not _is_within(DEBUG_DIR, path):
        raise RuntimeError(f"Refusing to delete outside {DEBUG_DIR}: {path}")
    if dry_run:
        print(f"dry-run: remove contents of {path}")
        return
    shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    print(f"cleared: {path}")


def _clear_sessions(pattern: str, dry_run: bool) -> None:
    if not DEBUG_DIR.exists():
        print(f"skip: {DEBUG_DIR} does not exist")
        return
    matches = sorted(DEBUG_DIR.glob(pattern))
    if not matches:
        print(f"skip: no session files matching {pattern}")
        return
    for session_file in matches:
        if not _is_within(DEBUG_DIR, session_file):
            raise RuntimeError(f"Refusing to delete outside {DEBUG_DIR}: {session_file}")
        if dry_run:
            print(f"dry-run: remove {session_file}")
            continue
        session_file.unlink()
        print(f"removed: {session_file}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Clean MCP-generated artifacts under mcp/debugging."
    )
    parser.add_argument("--logs", action="store_true", help="Clear mcp/debugging/logs")
    parser.add_argument(
        "--screenshots",
        action="store_true",
        help="Clear mcp/debugging/mcp-screenshots",
    )
    parser.add_argument(
        "--snapshots",
        action="store_true",
        help="Clear mcp/debugging/snapshots",
    )
    parser.add_argument(
        "--sessions",
        action="store_true",
        help="Remove chrome debug session env files in mcp/debugging",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Clear logs, screenshots, snapshots, and session files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without deleting anything",
    )

    args = parser.parse_args(argv)

    if args.all:
        args.logs = True
        args.screenshots = True
        args.snapshots = True
        args.sessions = True

    if not any([args.logs, args.screenshots, args.snapshots, args.sessions]):
        parser.print_help(sys.stderr)
        return 2

    if args.logs:
        _clear_dir(DEBUG_DIR / "logs", args.dry_run)
    if args.screenshots:
        _clear_dir(DEBUG_DIR / "mcp-screenshots", args.dry_run)
    if args.snapshots:
        _clear_dir(DEBUG_DIR / "snapshots", args.dry_run)
    if args.sessions:
        _clear_sessions("chrome-debug-session*.env", args.dry_run)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
