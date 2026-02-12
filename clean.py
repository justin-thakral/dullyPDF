#!/usr/bin/env python3
"""Clean generated artifacts across the repo using per-directory cleaners."""
from __future__ import annotations

import argparse
import shutil
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
    "field-detect-artifacts": REPO_ROOT / "backend" / "fieldDetecting" / "outputArtifacts" / "cleanOutput.py",
    "mcp-bug-logs": REPO_ROOT / "mcp" / "codexBugs" / "logs" / "cleanOutput.py",
    "frontend": REPO_ROOT / "frontend" / "cleanOutput.py",
}


def _is_within(base: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _script_exists(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Missing cleaner: {path}")


def _run_cleaner(path: Path, args: list[str]) -> int:
    _script_exists(path)
    cmd = [sys.executable, str(path), *args]
    print("running:", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=False).returncode


def _remove_path(path: Path, dry_run: bool) -> None:
    if not path.exists():
        print(f"skip: {path} does not exist")
        return
    if not _is_within(REPO_ROOT, path):
        raise RuntimeError(f"Refusing to delete outside {REPO_ROOT}: {path}")
    if dry_run:
        print(f"dry-run: remove {path}")
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)
    print(f"removed: {path}")


def _clear_dir_contents(path: Path, dry_run: bool, keep_names: set[str] | None = None) -> None:
    if not path.exists():
        print(f"skip: {path} does not exist")
        return
    if not path.is_dir():
        _remove_path(path, dry_run)
        return
    keep = keep_names or set()
    for entry in sorted(path.iterdir()):
        if entry.name in keep:
            continue
        _remove_path(entry, dry_run)


def _clear_coverage_files(dry_run: bool) -> None:
    targets = [REPO_ROOT / ".coverage", *sorted(REPO_ROOT.glob(".coverage.*"))]
    found_any = False
    for target in targets:
        if not target.exists():
            continue
        found_any = True
        _remove_path(target, dry_run)
    if not found_any:
        print("skip: no coverage artifacts found")


def _path_within_any(path: Path, roots: list[Path]) -> bool:
    return any(root.exists() and _is_within(root, path) for root in roots)


def _clear_backend_python_cache(dry_run: bool) -> None:
    backend_dir = REPO_ROOT / "backend"
    if not backend_dir.exists():
        print(f"skip: {backend_dir} does not exist")
        return

    excluded_roots = [backend_dir / ".venv", *backend_dir.glob(".venv-*")]
    cache_dirs = [
        p
        for p in backend_dir.rglob("__pycache__")
        if p.is_dir() and not _path_within_any(p, excluded_roots)
    ]
    pyc_files = [
        p
        for p in backend_dir.rglob("*.pyc")
        if p.is_file() and not _path_within_any(p, excluded_roots)
    ]
    pyo_files = [
        p
        for p in backend_dir.rglob("*.pyo")
        if p.is_file() and not _path_within_any(p, excluded_roots)
    ]
    targets = sorted(
        {*cache_dirs, *pyc_files, *pyo_files},
        key=lambda p: (len(p.parts), str(p)),
        reverse=True,
    )
    if not targets:
        print("skip: no backend python cache artifacts found")
        return

    for target in targets:
        _remove_path(target, dry_run)


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
        "--field-detect-artifacts",
        action="store_true",
        help="Run backend/fieldDetecting/outputArtifacts/cleanOutput.py",
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
    parser.add_argument(
        "--bug-reports",
        action="store_true",
        help="Clear all bug report directories across test and MCP folders",
    )
    parser.add_argument(
        "--test-bug-reports",
        action="store_true",
        help="Clear test/bugs report files (keeps templates/readme)",
    )
    parser.add_argument(
        "--backend-test-bug-reports",
        action="store_true",
        help="Clear backend/test/bugs report files",
    )
    parser.add_argument(
        "--mcp-bug-reports",
        action="store_true",
        help="Clear mcp/codexBugs/fixed and mcp/codexBugs/notfixedSuggestions",
    )
    parser.add_argument(
        "--mcp-security-bug-reports",
        action="store_true",
        help="Clear mcp/security-docs type report folders (keeps templates)",
    )
    parser.add_argument(
        "--mcp-security-logs",
        action="store_true",
        help="Clear mcp/security-docs/logs",
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Remove .coverage and .coverage.* files at repo root",
    )
    parser.add_argument(
        "--pytest-cache",
        action="store_true",
        help="Clear .pytest_cache",
    )
    parser.add_argument(
        "--python-cache",
        action="store_true",
        help="Clear backend __pycache__ directories and *.pyc/*.pyo outside virtualenvs",
    )
    parser.add_argument(
        "--frontend-dist",
        action="store_true",
        help="Clear frontend/dist build artifacts",
    )
    parser.add_argument(
        "--output",
        action="store_true",
        help="Clear output artifacts under output/",
    )
    parser.add_argument(
        "--repo-logs",
        action="store_true",
        help="Clear local logs under .logs/",
    )
    parser.add_argument(
        "--pipeline-improve",
        action="store_true",
        help="Clear mcp/debugging/pipeline-improve artifacts",
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
        "field-detect-artifacts": args.all or args.field_detect_artifacts,
        "mcp-bug-logs": args.all or args.bug_reports or args.mcp_bug_logs,
        "frontend": args.all or args.frontend_tmp,
        "test-bug-reports": args.all or args.bug_reports or args.test_bug_reports,
        "backend-test-bug-reports": args.all
        or args.bug_reports
        or args.backend_test_bug_reports,
        "mcp-bug-reports": args.all or args.bug_reports or args.mcp_bug_reports,
        "mcp-security-bug-reports": args.all
        or args.bug_reports
        or args.mcp_security_bug_reports,
        "mcp-security-logs": args.all or args.bug_reports or args.mcp_security_logs,
        "coverage": args.all or args.coverage,
        "pytest-cache": args.all or args.pytest_cache,
        "python-cache": args.all or args.python_cache,
        "frontend-dist": args.all or args.frontend_dist,
        "output": args.all or args.output,
        "repo-logs": args.all or args.repo_logs,
        "pipeline-improve": args.all or args.pipeline_improve,
    }

    if not any(selected.values()):
        selected = {key: True for key in selected}

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

    if selected["field-detect-artifacts"]:
        artifact_args = ["--all"]
        if args.dry_run:
            artifact_args.append("--dry-run")
        if _run_cleaner(CLEANERS["field-detect-artifacts"], artifact_args) != 0:
            failures += 1

    if selected["mcp-bug-logs"]:
        bug_args = ["--all" if (args.all or args.bug_reports) else "--sessions"]
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

    if selected["test-bug-reports"]:
        _clear_dir_contents(
            REPO_ROOT / "test" / "bugs",
            args.dry_run,
            keep_names={"README.md", "BUG_TEMPLATE.md"},
        )

    if selected["backend-test-bug-reports"]:
        _clear_dir_contents(REPO_ROOT / "backend" / "test" / "bugs", args.dry_run)

    if selected["mcp-bug-reports"]:
        _clear_dir_contents(
            REPO_ROOT / "mcp" / "codexBugs" / "fixed",
            args.dry_run,
            keep_names={".gitkeep"},
        )
        _clear_dir_contents(
            REPO_ROOT / "mcp" / "codexBugs" / "notfixedSuggestions",
            args.dry_run,
            keep_names={".gitkeep"},
        )

    if selected["mcp-security-bug-reports"]:
        _clear_dir_contents(
            REPO_ROOT / "mcp" / "security-docs" / "type-1-fixed",
            args.dry_run,
            keep_names={"REPORT_TEMPLATE.md"},
        )
        _clear_dir_contents(
            REPO_ROOT / "mcp" / "security-docs" / "type-2-notfixed",
            args.dry_run,
            keep_names={"REPORT_TEMPLATE.md"},
        )
        _clear_dir_contents(
            REPO_ROOT / "mcp" / "security-docs" / "type-3-needs-feedback",
            args.dry_run,
            keep_names={"REPORT_TEMPLATE.md"},
        )

    if selected["mcp-security-logs"]:
        _clear_dir_contents(REPO_ROOT / "mcp" / "security-docs" / "logs", args.dry_run)

    if selected["coverage"]:
        _clear_coverage_files(args.dry_run)

    if selected["pytest-cache"]:
        _clear_dir_contents(REPO_ROOT / ".pytest_cache", args.dry_run)

    if selected["python-cache"]:
        _clear_backend_python_cache(args.dry_run)

    if selected["frontend-dist"]:
        _clear_dir_contents(REPO_ROOT / "frontend" / "dist", args.dry_run)

    if selected["output"]:
        _clear_dir_contents(REPO_ROOT / "output", args.dry_run)

    if selected["repo-logs"]:
        _clear_dir_contents(REPO_ROOT / ".logs", args.dry_run)

    if selected["pipeline-improve"]:
        _clear_dir_contents(
            REPO_ROOT / "mcp" / "debugging" / "pipeline-improve",
            args.dry_run,
        )

    if failures:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
