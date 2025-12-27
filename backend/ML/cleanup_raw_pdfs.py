from __future__ import annotations

import argparse
import csv
import io
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import fitz
import numpy as np
import cv2

from ..combinedSrc.config import get_logger
from ..combinedSrc.detect_geometry import detect_geometry


logger = get_logger(__name__)


@dataclass
class CleanupDecision:
    slug: str
    category: str
    pdf_path: Path
    reason: Optional[str]
    moved_to: Optional[Path]
    page_count: int
    candidate_total: int
    max_candidates_per_page: int
    has_acroform_fields: bool


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _data_root() -> Path:
    return Path(__file__).resolve().parent / "data" / "raw"


def _iter_pdf_paths(pdf_root: Path) -> List[Path]:
    paths: List[Path] = []
    for path in pdf_root.rglob("*.pdf"):
        if "solutions" in path.parts or "removed" in path.parts:
            continue
        paths.append(path)
    return sorted(paths)


def _read_sources(csv_path: Path) -> List[Dict[str, str]]:
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def _write_sources(csv_path: Path, rows: List[Dict[str, str]]) -> None:
    if not rows:
        return
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0].keys()),
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_cleanup_log(log_path: Path, rows: List[Dict[str, str]]) -> None:
    if not rows:
        return
    write_header = not log_path.exists()
    with log_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def _load_logged_slugs(log_path: Path) -> set[str]:
    if not log_path.exists():
        return set()
    with log_path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return {(row.get("slug") or "").strip() for row in reader if row.get("slug")}


def _form_widget_count(pdf_path: Path) -> Optional[int]:
    try:
        with fitz.open(pdf_path) as doc:
            count = 0
            for page in doc:
                widgets = page.widgets()
                if widgets is None:
                    continue
                for _ in widgets:
                    count += 1
                    if count:
                        return count
        return 0
    except Exception as exc:
        logger.warning("Failed to inspect widgets for %s: %s", pdf_path, exc)
        return None


def _strip_fields(pdf_path: Path, out_path: Path, remove_script: Path) -> bool:
    if _strip_fields_with_pymupdf(pdf_path, out_path):
        return True
    result = subprocess.run(
        ["node", str(remove_script), str(pdf_path), str(out_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        logger.warning("Field removal failed for %s: %s", pdf_path, result.stderr.strip())
        return False
    return True


def _strip_fields_with_pymupdf(pdf_path: Path, out_path: Path) -> bool:
    try:
        with fitz.open(pdf_path) as doc:
            removed = 0
            for page in doc:
                widgets = list(page.widgets() or [])
                for widget in widgets:
                    page.delete_widget(widget)
                    removed += 1
            if removed == 0:
                return False
            tmp_path = out_path
            if out_path.exists():
                tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
            doc.save(tmp_path, garbage=4, deflate=True, clean=True)
            if tmp_path != out_path:
                tmp_path.replace(out_path)
        return True
    except Exception as exc:
        logger.warning("PyMuPDF field removal failed for %s: %s", pdf_path, exc)
        return False


def _render_pages_for_scan(
    pdf_bytes: bytes,
    *,
    dpi: int,
    max_pages: int,
    max_dim_px: Optional[int],
) -> List[Dict]:
    scale = dpi / 72.0
    pages: List[Dict] = []
    with fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf") as doc:
        for idx in range(min(doc.page_count, max_pages)):
            page = doc.load_page(idx)
            matrix = fitz.Matrix(scale, scale)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            image = np.frombuffer(pixmap.samples, dtype=np.uint8)
            image = image.reshape(pixmap.height, pixmap.width, pixmap.n)
            if pixmap.n == 4:
                image = cv2.cvtColor(image, cv2.COLOR_RGBA2RGB)
            elif pixmap.n == 1:
                image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
            image_height_px = pixmap.height
            image_width_px = pixmap.width
            scale_used = scale
            if max_dim_px and max_dim_px > 0:
                max_dim = max(image_height_px, image_width_px)
                if max_dim > max_dim_px:
                    ratio = max_dim_px / float(max_dim)
                    image = cv2.resize(
                        image,
                        dsize=None,
                        fx=ratio,
                        fy=ratio,
                        interpolation=cv2.INTER_AREA,
                    )
                    image_height_px, image_width_px = image.shape[:2]
                    scale_used = scale * ratio
            pages.append(
                {
                    "page_index": idx + 1,
                    "width_points": float(page.cropbox.width),
                    "height_points": float(page.cropbox.height),
                    "rotation": page.rotation,
                    "scale": scale_used,
                    "image_width_px": image_width_px,
                    "image_height_px": image_height_px,
                    "image": image,
                }
            )
    return pages


def _candidate_stats(geometry: List[Dict]) -> Tuple[int, int]:
    total = 0
    max_per_page = 0
    for page in geometry:
        count = (
            len(page.get("lineCandidates") or [])
            + len(page.get("boxCandidates") or [])
            + len(page.get("checkboxCandidates") or [])
        )
        total += count
        max_per_page = max(max_per_page, count)
    return total, max_per_page


def _remove_related_assets(data_root: Path, slug: str) -> None:
    shutil.rmtree(data_root / "images" / slug, ignore_errors=True)
    shutil.rmtree(data_root / "meta" / slug, ignore_errors=True)


def _cleanup_pdf(
    *,
    pdf_path: Path,
    category: str,
    solutions_root: Path,
    remove_script: Path,
    scan_dpi: int,
    scan_pages: int,
    confirm_dpi: int,
    max_dim_px: Optional[int],
    confirm_max_dim_px: Optional[int],
    max_pages: int,
    max_candidates_total: int,
    max_candidates_per_page: int,
) -> CleanupDecision:
    slug = pdf_path.stem
    widget_count = _form_widget_count(pdf_path)
    has_acroform_fields = bool(widget_count and widget_count > 0)

    if has_acroform_fields:
        dest_dir = solutions_root / category
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / pdf_path.name
        if not dest_path.exists():
            shutil.move(str(pdf_path), str(dest_path))
        stripped_ok = _strip_fields(dest_path, pdf_path, remove_script)
        if not stripped_ok:
            return CleanupDecision(
                slug=slug,
                category=category,
                pdf_path=pdf_path,
                reason="field_removal_failed",
                moved_to=dest_path,
                page_count=0,
                candidate_total=0,
                max_candidates_per_page=0,
                has_acroform_fields=True,
            )

    try:
        pdf_bytes = pdf_path.read_bytes()
        with fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf") as doc:
            page_count = int(doc.page_count)
    except Exception as exc:
        logger.warning("Failed to open %s: %s", pdf_path, exc)
        return CleanupDecision(
            slug=slug,
            category=category,
            pdf_path=pdf_path,
            reason="invalid_pdf",
            moved_to=None,
            page_count=0,
            candidate_total=0,
            max_candidates_per_page=0,
            has_acroform_fields=has_acroform_fields,
        )

    if page_count > max_pages:
        return CleanupDecision(
            slug=slug,
            category=category,
            pdf_path=pdf_path,
            reason="too_many_pages",
            moved_to=None,
            page_count=page_count,
            candidate_total=0,
            max_candidates_per_page=0,
            has_acroform_fields=has_acroform_fields,
        )

    if has_acroform_fields:
        return CleanupDecision(
            slug=slug,
            category=category,
            pdf_path=pdf_path,
            reason=None,
            moved_to=dest_path if has_acroform_fields else None,
            page_count=page_count,
            candidate_total=0,
            max_candidates_per_page=0,
            has_acroform_fields=True,
        )

    rendered = _render_pages_for_scan(
        pdf_bytes,
        dpi=scan_dpi,
        max_pages=scan_pages,
        max_dim_px=max_dim_px,
    )
    geometry = detect_geometry(rendered) if rendered else []
    candidate_total, max_per_page = _candidate_stats(geometry)

    if candidate_total == 0 and confirm_dpi and confirm_dpi > scan_dpi:
        confirm_rendered = _render_pages_for_scan(
            pdf_bytes,
            dpi=confirm_dpi,
            max_pages=scan_pages,
            max_dim_px=confirm_max_dim_px,
        )
        confirm_geometry = detect_geometry(confirm_rendered) if confirm_rendered else []
        candidate_total, max_per_page = _candidate_stats(confirm_geometry)

    if candidate_total == 0:
        reason = "no_input_fields"
    elif candidate_total > max_candidates_total or max_per_page > max_candidates_per_page:
        reason = "too_many_candidates"
    else:
        reason = None

    return CleanupDecision(
        slug=slug,
        category=category,
        pdf_path=pdf_path,
        reason=reason,
        moved_to=None,
        page_count=page_count,
        candidate_total=candidate_total,
        max_candidates_per_page=max_per_page,
        has_acroform_fields=has_acroform_fields,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean raw PDFs by removing non-forms and handling fillables.")
    parser.add_argument(
        "--pdf-root",
        type=Path,
        default=_data_root() / "pdfs",
        help="Root folder containing raw PDFs.",
    )
    parser.add_argument(
        "--solutions-root",
        type=Path,
        default=_data_root() / "pdfs" / "solutions",
        help="Destination for fillable originals.",
    )
    parser.add_argument(
        "--removed-root",
        type=Path,
        default=_data_root() / "pdfs" / "removed",
        help="Destination for PDFs removed from training.",
    )
    parser.add_argument(
        "--sources",
        type=Path,
        default=_data_root() / "sources.csv",
        help="Source ledger to update when PDFs are removed.",
    )
    parser.add_argument(
        "--scan-dpi",
        type=int,
        default=100,
        help="DPI to use for geometry scanning (lower than full render for speed).",
    )
    parser.add_argument(
        "--scan-pages",
        type=int,
        default=1,
        help="Number of pages to scan per PDF when determining form-likeness.",
    )
    parser.add_argument(
        "--confirm-dpi",
        type=int,
        default=200,
        help="Second-pass DPI to confirm pages with zero detected candidates.",
    )
    parser.add_argument(
        "--max-dim-px",
        type=int,
        default=2000,
        help="Downscale scan renders so the largest image dimension stays within this size.",
    )
    parser.add_argument(
        "--confirm-max-dim-px",
        type=int,
        default=2600,
        help="Max dimension for confirm renders (larger than scan pass by default).",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=40,
        help="Remove PDFs with more pages than this threshold.",
    )
    parser.add_argument(
        "--max-candidates-total",
        type=int,
        default=600,
        help="Remove PDFs with more than this many geometry candidates across scanned pages.",
    )
    parser.add_argument(
        "--max-candidates-per-page",
        type=int,
        default=400,
        help="Remove PDFs with more than this many candidates on a single page.",
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=0,
        help="Start index into the sorted PDF list (for batched runs).",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Maximum number of PDFs to process in this run.",
    )
    parser.add_argument(
        "--log-path",
        type=Path,
        default=_data_root() / "cleanup_log.csv",
        help="CSV log file used to resume processing.",
    )
    parser.add_argument(
        "--ignore-log",
        action="store_true",
        help="Process PDFs even if they already exist in the log file.",
    )
    args = parser.parse_args()

    data_root = args.pdf_root.parent
    remove_script = _repo_root() / "backend" / "scripts" / "remove_pdf_fields.js"

    sources = _read_sources(args.sources)
    sources_by_slug: Dict[str, List[Dict[str, str]]] = {}
    for row in sources:
        slug = (row.get("slug") or "").strip()
        if not slug:
            continue
        sources_by_slug.setdefault(slug, []).append(row)

    removed_slugs: set[str] = set()
    removed_log: List[Dict[str, str]] = []
    logged_slugs = set() if args.ignore_log else _load_logged_slugs(args.log_path)

    pdf_paths = _iter_pdf_paths(args.pdf_root)
    start = max(0, int(args.start_index))
    if args.max_files is None:
        batch = pdf_paths[start:]
    else:
        batch = pdf_paths[start : start + int(args.max_files)]

    for pdf_path in batch:
        slug = pdf_path.stem
        if slug in logged_slugs:
            logger.debug("Skipping already-logged PDF: %s", pdf_path.name)
            continue
        category = pdf_path.parent.name
        decision = _cleanup_pdf(
            pdf_path=pdf_path,
            category=category,
            solutions_root=args.solutions_root,
            remove_script=remove_script,
            scan_dpi=args.scan_dpi,
            scan_pages=args.scan_pages,
            confirm_dpi=args.confirm_dpi,
            max_dim_px=args.max_dim_px,
            confirm_max_dim_px=args.confirm_max_dim_px,
            max_pages=args.max_pages,
            max_candidates_total=args.max_candidates_total,
            max_candidates_per_page=args.max_candidates_per_page,
        )

        if decision.reason:
            dest_path = decision.moved_to
            if decision.reason != "field_removal_failed":
                dest_dir = args.removed_root / category
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_path = dest_dir / decision.pdf_path.name
                if decision.pdf_path.exists() and not dest_path.exists():
                    shutil.move(str(decision.pdf_path), str(dest_path))
            _remove_related_assets(data_root, decision.slug)
            removed_slugs.add(decision.slug)
            removed_log.append(
                {
                    "slug": decision.slug,
                    "category": decision.category,
                    "status": "error" if decision.reason == "field_removal_failed" else "removed",
                    "reason": decision.reason,
                    "page_count": str(decision.page_count),
                    "candidate_total": str(decision.candidate_total),
                    "max_candidates_per_page": str(decision.max_candidates_per_page),
                    "has_acroform_fields": "true" if decision.has_acroform_fields else "false",
                    "removed_at": datetime.now(tz=timezone.utc).isoformat(),
                    "moved_to": "" if not dest_path else str(dest_path),
                }
            )
            _write_cleanup_log(args.log_path, removed_log[-1:])
            logger.info(
                "Removed %s (%s): %s",
                decision.pdf_path.name,
                decision.reason,
                dest_path or "no-move",
            )
            continue

        logger.info(
            "Kept %s (candidates=%s, max_page=%s, pages=%s, fillable=%s)",
            decision.pdf_path.name,
            decision.candidate_total,
            decision.max_candidates_per_page,
            decision.page_count,
            decision.has_acroform_fields,
        )
        status = "fillable_stripped" if decision.has_acroform_fields else "kept"
        _write_cleanup_log(
            args.log_path,
            [
                {
                    "slug": decision.slug,
                    "category": decision.category,
                    "status": status,
                    "reason": "",
                    "page_count": str(decision.page_count),
                    "candidate_total": str(decision.candidate_total),
                    "max_candidates_per_page": str(decision.max_candidates_per_page),
                    "has_acroform_fields": "true" if decision.has_acroform_fields else "false",
                    "removed_at": "",
                    "moved_to": "" if not decision.moved_to else str(decision.moved_to),
                }
            ],
        )

    cleaned = [row for row in sources if (row.get("slug") or "").strip() not in removed_slugs]
    if cleaned and cleaned != sources:
        _write_sources(args.sources, cleaned)
    if removed_log:
        log_path = args.sources.parent / "cleanup_log.csv"
        _write_cleanup_log(log_path, removed_log)


if __name__ == "__main__":
    main()
