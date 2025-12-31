from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Iterable, List

from ..combinedSrc.config import get_logger

logger = get_logger(__name__)


def _iter_analysis_dirs(output_root: Path) -> List[Path]:
    return sorted(
        [p for p in output_root.iterdir() if p.is_dir() and p.name.startswith("analysis_")]
    )


def _safe_destination(dest_dir: Path, name: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    candidate = dest_dir / name
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    idx = 1
    while True:
        alt = dest_dir / f"{stem}__dup{idx}{suffix}"
        if not alt.exists():
            return alt
        idx += 1


def _transfer_file(src: Path, dest: Path, *, mode: str, dry_run: bool) -> None:
    if dry_run:
        logger.info("[dry-run] %s -> %s", src, dest)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    if mode == "copy":
        shutil.copy2(src, dest)
    else:
        shutil.move(str(src), str(dest))


def _migrate_tree(src_root: Path, dest_root: Path, *, mode: str, dry_run: bool) -> int:
    moved = 0
    if not src_root.exists():
        return moved
    for path in sorted(src_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(src_root)
        dest_parent = dest_root / rel.parent
        dest = _safe_destination(dest_parent, rel.name)
        _transfer_file(path, dest, mode=mode, dry_run=dry_run)
        moved += 1
    return moved


def _cleanup_empty_dirs(paths: Iterable[Path], *, dry_run: bool) -> None:
    for base in paths:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if not path.is_dir():
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
    parser = argparse.ArgumentParser(
        description="Migrate legacy analysis_* artifact folders into outputArtifacts/json and outputArtifacts/overlays."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("backend/fieldDetecting"),
        help="Sandbox root directory (default: backend/fieldDetecting)",
    )
    parser.add_argument(
        "--mode",
        choices=["move", "copy"],
        default="move",
        help="Whether to move or copy artifacts into the new layout.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List migration steps without moving files.",
    )
    args = parser.parse_args()

    root = args.root
    output_root = root / "outputArtifacts"
    if not output_root.exists():
        raise SystemExit(f"outputArtifacts not found under: {root}")

    json_root = output_root / "json"
    overlays_root = output_root / "overlays"
    json_root.mkdir(parents=True, exist_ok=True)
    overlays_root.mkdir(parents=True, exist_ok=True)

    analysis_dirs = _iter_analysis_dirs(output_root)
    if not analysis_dirs:
        logger.info("No analysis_* folders found under %s", output_root)
        return

    total_files = 0
    for analysis_dir in analysis_dirs:
        name = analysis_dir.name
        logger.info("Migrating %s", name)
        json_src = analysis_dir / "json"
        overlays_src = analysis_dir / "overlays"
        raw_src = analysis_dir / "raw"

        dest_json = json_root / name
        dest_overlays = overlays_root / name
        dest_raw = dest_overlays / "raw"

        total_files += _migrate_tree(json_src, dest_json, mode=args.mode, dry_run=args.dry_run)
        total_files += _migrate_tree(overlays_src, dest_overlays, mode=args.mode, dry_run=args.dry_run)
        total_files += _migrate_tree(raw_src, dest_raw, mode=args.mode, dry_run=args.dry_run)

        if not args.dry_run and args.mode == "move":
            _cleanup_empty_dirs([analysis_dir], dry_run=False)
            try:
                analysis_dir.rmdir()
            except OSError:
                pass

    if args.dry_run:
        logger.info("[dry-run] Would migrate %s files", total_files)
    else:
        logger.info("Migration complete. Moved %s files.", total_files)


if __name__ == "__main__":
    main()
