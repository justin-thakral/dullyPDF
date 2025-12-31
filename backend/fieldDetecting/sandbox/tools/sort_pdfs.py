import argparse
import os
import shutil
from pathlib import Path
from typing import Iterable, List, Tuple

from ..combinedSrc.concurrency import resolve_workers, run_threaded_map
from ..combinedSrc.config import get_logger
from ..combinedSrc.text_layer import is_native_text_layer, summarize_text_layer

logger = get_logger(__name__)


def _iter_pdfs(root: Path, *, exclude_dirs: Iterable[Path]) -> List[Path]:
    """
    Return a list of PDF files under `root`, skipping any excluded directories.

    Data structure: we return a concrete list to preserve deterministic ordering
    when applying threaded classification later.
    """
    exclude_set = {p.resolve() for p in exclude_dirs}
    pdfs: List[Path] = []
    for path in sorted(root.rglob("*.pdf")):
        resolved = path.resolve()
        if any(excluded in resolved.parents for excluded in exclude_set):
            continue
        pdfs.append(path)
    return pdfs


def _classify_pdf(path: Path) -> Tuple[Path, bool]:
    """
    Classify a single PDF as native or scanned using text-layer heuristics.

    Returns (path, is_native).
    """
    pdf_bytes = path.read_bytes()
    stats = summarize_text_layer(pdf_bytes)
    return path, is_native_text_layer(stats)


def _stage_file(
    src: Path,
    *,
    root: Path,
    dest_root: Path,
    mode: str,
) -> Path:
    """
    Copy or move a file into a destination root, preserving the source relative path.

    We keep the relative path to avoid filename collisions when many PDFs share the
    same basename.
    """
    rel = src.relative_to(root)
    dest = dest_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        logger.warning("Skipping %s -> %s (already exists)", src, dest)
        return dest
    if mode == "move":
        shutil.move(str(src), str(dest))
    else:
        shutil.copy2(src, dest)
    return dest


def _split_group(
    files: List[Path],
    *,
    root: Path,
    native_dir: Path,
    scanned_dir: Path,
    mode: str,
    workers: int,
    label: str,
) -> None:
    if not files:
        logger.warning("No PDFs found for %s", label)
        return
    results = run_threaded_map(
        files,
        _classify_pdf,
        max_workers=workers,
        label=label,
    )
    native_count = 0
    scanned_count = 0
    for path, is_native in results:
        target = native_dir if is_native else scanned_dir
        _stage_file(path, root=root, dest_root=target, mode=mode)
        if is_native:
            native_count += 1
        else:
            scanned_count += 1
    logger.info(
        "%s split complete -> native=%s scanned=%s", label, native_count, scanned_count
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Classify PDFs into native/scanned groups and stage them into output folders."
    )
    parser.add_argument(
        "--pdfs-dir",
        type=Path,
        default=Path("backend/fieldDetecting/pdfs"),
        help="Root directory containing input PDFs to classify.",
    )
    parser.add_argument(
        "--forms-dir",
        type=Path,
        default=None,
        help="Optional root directory containing fillable form PDFs to classify.",
    )
    parser.add_argument(
        "--pdfs-output-root",
        type=Path,
        default=Path("backend/fieldDetecting/pdfs"),
        help="Destination root for native/scanned output.",
    )
    parser.add_argument(
        "--forms-output-root",
        type=Path,
        default=Path("backend/fieldDetecting/forms"),
        help="Destination root for native/scanned forms output.",
    )
    parser.add_argument(
        "--mode",
        choices=["copy", "move"],
        default="move",
        help="Whether to copy or move PDFs into the destination groups.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Override worker count (defaults to SANDBOX_SORT_WORKERS or 4).",
    )
    args = parser.parse_args()

    pdfs_root = args.pdfs_dir
    forms_root = args.forms_dir
    pdfs_out = args.pdfs_output_root
    forms_out = args.forms_output_root
    workers = args.workers or int(os.getenv("SANDBOX_SORT_WORKERS", "4"))
    workers = max(1, workers)

    native_pdfs_dir = pdfs_out / "native"
    scanned_pdfs_dir = pdfs_out / "scanned"
    native_forms_dir = forms_out / "native"
    scanned_forms_dir = forms_out / "scanned"

    pdfs = _iter_pdfs(pdfs_root, exclude_dirs=[native_pdfs_dir, scanned_pdfs_dir])
    _split_group(
        pdfs,
        root=pdfs_root,
        native_dir=native_pdfs_dir,
        scanned_dir=scanned_pdfs_dir,
        mode=args.mode,
        workers=resolve_workers("sort", default=workers),
        label="pdfs",
    )

    if forms_root:
        forms = _iter_pdfs(forms_root, exclude_dirs=[native_forms_dir, scanned_forms_dir])
        _split_group(
            forms,
            root=forms_root,
            native_dir=native_forms_dir,
            scanned_dir=scanned_forms_dir,
            mode=args.mode,
            workers=resolve_workers("sort", default=workers),
            label="forms",
        )


if __name__ == "__main__":
    main()
