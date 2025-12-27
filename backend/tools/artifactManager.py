from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Iterable, List

from ..combinedSrc.config import get_logger

logger = get_logger(__name__)


def _iter_temp_paths(root: Path, *, prefix: str) -> List[Path]:
    targets: List[Path] = []
    for base in (root / "outputArtifacts", root / "forms"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.name.startswith(prefix):
                targets.append(path)
    return targets


def _delete_paths(paths: Iterable[Path], *, dry_run: bool) -> None:
    deleted_files = 0
    deleted_dirs = 0
    for path in sorted(paths, key=lambda p: len(p.parts), reverse=True):
        if not path.exists():
            continue
        if dry_run:
            logger.info("[dry-run] Would remove %s", path)
            continue
        if path.is_dir():
            shutil.rmtree(path)
            deleted_dirs += 1
        else:
            path.unlink()
            deleted_files += 1
    if dry_run:
        logger.info("[dry-run] Completed temp scan")
    else:
        logger.info("Deleted %s files and %s directories", deleted_files, deleted_dirs)


def _prune_empty_dirs(base: Path, *, dry_run: bool) -> None:
    if not base.exists():
        return
    # Walk deepest-first so parent dirs are removed after their children.
    for path in sorted(base.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if not path.is_dir():
            continue
        if path == base:
            continue
        try:
            next(path.iterdir())
            continue
        except StopIteration:
            pass
        if dry_run:
            logger.info("[dry-run] Would remove empty dir %s", path)
        else:
            path.rmdir()


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove temp-prefixed sandbox artifacts.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("backend"),
        help="Sandbox root directory (default: backend)",
    )
    parser.add_argument(
        "--prefix",
        type=str,
        default="temp",
        help="Filename prefix to delete (default: temp)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files to remove without deleting.",
    )
    args = parser.parse_args()

    root = args.root
    if not root.exists():
        raise SystemExit(f"Root does not exist: {root}")

    targets = _iter_temp_paths(root, prefix=args.prefix)
    if not targets:
        logger.info("No temp artifacts found under %s", root)
        return

    _delete_paths(targets, dry_run=args.dry_run)
    for base in (root / "outputArtifacts", root / "forms"):
        _prune_empty_dirs(base, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
