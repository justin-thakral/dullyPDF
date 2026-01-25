#!/usr/bin/env python3
"""Clean generated artifacts across the repo using per-directory cleaners."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
CLEANERS = {
    "mcp": REPO_ROOT / "mcp" / "cleanOutput.py",
    "runs": REPO_ROOT / "runs" / "cleanOutput.py",
    "test-results": REPO_ROOT / "test-results" / "cleanOutput.py",
    "tmp": REPO_ROOT / "tmp" / "cleanOutput.py",
    "field-detect-logs": REPO_ROOT / "backend" / "fieldDetecting" / "logs" / "cleanOutput.py",
    "mcp-bug-logs": REPO_ROOT / "mcp" / "codexBugs" / "logs" / "cleanOutput.py",
    "frontend": REPO_ROOT / "frontend" / "cleanOutput.py",
}


def _script_exists(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Missing cleaner: {path}")


def _run_cleaner(path: Path, args: list[str]) -> int:
    _script_exists(path)
    cmd = [sys.executable, str(path), *args]
    print("running:", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=False).returncode


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Run per-directory cleanup scripts from a single entrypoint."
    )
    parser.add_argument("--all", action="store_true", help="Run all cleaners")
    parser.add_argument("--dry-run", action="store_true", help="Preview actions only")

    parser.add_argument("--mcp", action="store_true", help="Run mcp/cleanOutput.py")
    parser.add_argument("--mcp-logs", action="store_true")
    parser.add_argument("--mcp-screenshots", action="store_true")
    parser.add_argument("--mcp-snapshots", action="store_true")
    parser.add_argument("--mcp-sessions", action="store_true")

    parser.add_argument("--runs", action="store_true", help="Run runs/cleanOutput.py")
    parser.add_argument("--runs-detect", action="store_true")

    parser.add_argument(
        "--test-results",
        dest="test_results",
        action="store_true",
        help="Run test-results/cleanOutput.py",
    )
    parser.add_argument("--test-results-last-run", action="store_true")

    parser.add_argument("--tmp", action="store_true", help="Run tmp/cleanOutput.py")
    parser.add_argument("--tmp-csvs", action="store_true")
    parser.add_argument("--tmp-pdfs", action="store_true")
    parser.add_argument("--tmp-snapshots", action="store_true")

    parser.add_argument(
        "--field-detect-logs",
        action="store_true",
        help="Run backend/fieldDetecting/logs/cleanOutput.py",
    )

    parser.add_argument(
        "--mcp-bug-logs",
        action="store_true",
        help="Run mcp/codexBugs/logs/cleanOutput.py",
    )

    parser.add_argument(
        "--frontend-tmp",
        action="store_true",
        help="Run frontend/cleanOutput.py (node_modules/.tmp)",
    )

    args = parser.parse_args(argv)

    mcp_specific = any(
        [args.mcp_logs, args.mcp_screenshots, args.mcp_snapshots, args.mcp_sessions]
    )
    runs_specific = args.runs_detect
    test_results_specific = args.test_results_last_run
    tmp_specific = any([args.tmp_csvs, args.tmp_pdfs, args.tmp_snapshots])

    selected = {
        "mcp": args.all or args.mcp or mcp_specific,
        "runs": args.all or args.runs or runs_specific,
        "test-results": args.all or args.test_results or test_results_specific,
        "tmp": args.all or args.tmp or tmp_specific,
        "field-detect-logs": args.all or args.field_detect_logs,
        "mcp-bug-logs": args.all or args.mcp_bug_logs,
        "frontend": args.all or args.frontend_tmp,
    }

    if not any(selected.values()):
        parser.print_help(sys.stderr)
        return 2

    failures = 0

    if selected["mcp"]:
        mcp_args = []
        if mcp_specific:
            if args.mcp_logs:
                mcp_args.append("--logs")
            if args.mcp_screenshots:
                mcp_args.append("--screenshots")
            if args.mcp_snapshots:
                mcp_args.append("--snapshots")
            if args.mcp_sessions:
                mcp_args.append("--sessions")
        else:
            mcp_args.append("--all")
        if args.dry_run:
            mcp_args.append("--dry-run")
        if _run_cleaner(CLEANERS["mcp"], mcp_args) != 0:
            failures += 1

    if selected["runs"]:
        runs_args = []
        if runs_specific:
            runs_args.append("--detect")
        else:
            runs_args.append("--all")
        if args.dry_run:
            runs_args.append("--dry-run")
        if _run_cleaner(CLEANERS["runs"], runs_args) != 0:
            failures += 1

    if selected["test-results"]:
        test_args = []
        if test_results_specific:
            test_args.append("--last-run")
        else:
            test_args.append("--all")
        if args.dry_run:
            test_args.append("--dry-run")
        if _run_cleaner(CLEANERS["test-results"], test_args) != 0:
            failures += 1

    if selected["tmp"]:
        tmp_args = []
        if tmp_specific:
            if args.tmp_csvs:
                tmp_args.append("--csvs")
            if args.tmp_pdfs:
                tmp_args.append("--pdfs")
            if args.tmp_snapshots:
                tmp_args.append("--snapshots")
        else:
            tmp_args.append("--all")
        if args.dry_run:
            tmp_args.append("--dry-run")
        if _run_cleaner(CLEANERS["tmp"], tmp_args) != 0:
            failures += 1

    if selected["field-detect-logs"]:
        field_args = ["--all"]
        if args.dry_run:
            field_args.append("--dry-run")
        if _run_cleaner(CLEANERS["field-detect-logs"], field_args) != 0:
            failures += 1

    if selected["mcp-bug-logs"]:
        bug_args = ["--sessions"]
        if args.dry_run:
            bug_args.append("--dry-run")
        if _run_cleaner(CLEANERS["mcp-bug-logs"], bug_args) != 0:
            failures += 1

    if selected["frontend"]:
        frontend_args = ["--tmp"]
        if args.dry_run:
            frontend_args.append("--dry-run")
        if _run_cleaner(CLEANERS["frontend"], frontend_args) != 0:
            failures += 1

    if failures:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
