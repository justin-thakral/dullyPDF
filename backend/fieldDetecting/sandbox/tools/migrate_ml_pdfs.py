import argparse
import os
import shutil
from pathlib import Path
from typing import Dict, List, Tuple

from ..combinedSrc.config import get_logger
from ..combinedSrc.text_layer import is_native_text_layer, summarize_text_layer

logger = get_logger(__name__)


CATEGORY_ALIASES: Dict[str, str] = {
    "hipaa": "hippa",
    "hippa": "hippa",
    "consent": "consent",
    "intake": "intake",
}


def _infer_category(parts: List[str]) -> Tuple[str, int | None]:
    """
    Choose the category bucket based on path segments.

    Returns (category, index_of_category_in_parts). If no category is found, defaults
    to consent and returns None for the index.
    """
    for idx, part in enumerate(parts):
        key = part.lower()
        if key in CATEGORY_ALIASES:
            return CATEGORY_ALIASES[key], idx
    return "consent", None


def _subpath_after_category(parts: List[str], category_idx: int | None) -> List[str]:
    """
    Preserve subfolders around the category to avoid filename collisions.

    - If a category is found, keep the leading segments before it (e.g., "solutions")
      and the trailing segments after it (the filename). This keeps provenance.
    - If no category is found, keep all parts and rely on the default category.
    """
    if category_idx is None:
        return parts
    return parts[:category_idx] + parts[category_idx + 1 :]


def _classify_native(pdf_path: Path) -> bool:
    pdf_bytes = pdf_path.read_bytes()
    stats = summarize_text_layer(pdf_bytes)
    return is_native_text_layer(stats)


def _move_pdf(
    pdf_path: Path,
    *,
    root: Path,
    dest_root: Path,
    mode: str,
) -> Path:
    rel_parts = list(pdf_path.relative_to(root).parts)
    category, idx = _infer_category(rel_parts)
    subpath = _subpath_after_category(rel_parts, idx)
    if idx is None:
        logger.warning(
            "Defaulting category to consent for %s (path=%s)",
            pdf_path.name,
            "/".join(rel_parts),
        )
    dest_dir = dest_root / category
    dest_path = dest_dir.joinpath(*subpath)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    if dest_path.exists():
        logger.warning("Skipping %s -> %s (already exists)", pdf_path, dest_path)
        return dest_path

    if mode == "move":
        shutil.move(str(pdf_path), str(dest_path))
    else:
        shutil.copy2(str(pdf_path), str(dest_path))
    return dest_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Move ML PDF corpus into the sandbox pdfs/native|scanned buckets."
    )
    parser.add_argument(
        "--ml-root",
        type=Path,
        default=Path("backend/fieldDetecting/sandbox/ML/data/raw/pdfs"),
        help="Root directory containing ML PDFs.",
    )
    parser.add_argument(
        "--pdfs-root",
        type=Path,
        default=Path("backend/fieldDetecting/pdfs"),
        help="Destination pdfs root that contains native/ and scanned/.",
    )
    parser.add_argument(
        "--mode",
        choices=["move", "copy"],
        default="move",
        help="Whether to move or copy PDFs into the destination buckets.",
    )
    args = parser.parse_args()

    ml_root = args.ml_root
    pdfs_root = args.pdfs_root
    native_root = pdfs_root / "native"
    scanned_root = pdfs_root / "scanned"

    pdf_paths = sorted(ml_root.rglob("*.pdf"))
    if not pdf_paths:
        logger.warning("No PDFs found under %s", ml_root)
        return

    native_count = 0
    scanned_count = 0

    for pdf_path in pdf_paths:
        is_native = _classify_native(pdf_path)
        dest_root = native_root if is_native else scanned_root
        _move_pdf(pdf_path, root=ml_root, dest_root=dest_root, mode=args.mode)
        if is_native:
            native_count += 1
        else:
            scanned_count += 1

    logger.info(
        "ML migration complete -> native=%s scanned=%s total=%s",
        native_count,
        scanned_count,
        native_count + scanned_count,
    )


if __name__ == "__main__":
    main()
