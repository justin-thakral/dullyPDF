from __future__ import annotations

import argparse
import io
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

import cv2
import fitz

from ..combinedSrc.config import DEFAULT_DPI, get_logger
from ..combinedSrc.render_pdf import render_pdf_to_images

logger = get_logger(__name__)


def _slugify_pdf_name(name: str) -> str:
    """
    Normalize PDF names into safe directory names.

    We use a simple regex-based slug so folder names are stable and portable across filesystems.
    """
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", (name or "").strip()).strip("_")
    return cleaned.lower() or "pdf"


def _build_meta_payload(
    *,
    source_pdf: str,
    source_pdf_path: str,
    slug: str,
    page: Dict,
    dpi: int,
    image_rel_path: str,
) -> Dict:
    """
    Assemble a flat metadata dict for each page.

    This keeps all fields on one level so downstream scripts can load them quickly without
    structural assumptions.
    """
    return {
        "source_pdf": source_pdf,
        "source_pdf_path": source_pdf_path,
        "slug": slug,
        "page_index": int(page.get("page_index", 0)),
        "width_points": float(page.get("width_points", 0.0)),
        "height_points": float(page.get("height_points", 0.0)),
        "rotation": int(page.get("rotation", 0)),
        "scale": float(page.get("scale", 0.0)),
        "image_width_px": int(page.get("image_width_px", 0)),
        "image_height_px": int(page.get("image_height_px", 0)),
        "render_dpi": int(dpi),
        "image_path": image_rel_path,
    }


def render_pdfs_to_dataset(
    pdf_paths: List[Path],
    *,
    out_dir: Path,
    dpi: int,
    overwrite: bool,
    max_pages: Optional[int] = None,
) -> None:
    """
    Render each PDF to page images and write per-page metadata.

    Data layout:
      <out_dir>/images/<slug>/page_0001.png
      <out_dir>/meta/<slug>/page_0001.json
    """
    images_root = out_dir / "images"
    meta_root = out_dir / "meta"
    images_root.mkdir(parents=True, exist_ok=True)
    meta_root.mkdir(parents=True, exist_ok=True)

    for pdf_path in pdf_paths:
        if not pdf_path.exists():
            logger.warning("Skipping missing PDF: %s", pdf_path)
            continue

        pdf_bytes = pdf_path.read_bytes()
        if max_pages is not None:
            try:
                with fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf") as doc:
                    if doc.page_count > max_pages:
                        logger.warning(
                            "Skipping %s: %s pages exceeds max_pages=%s",
                            pdf_path,
                            doc.page_count,
                            max_pages,
                        )
                        continue
            except Exception as exc:
                logger.warning("Failed to inspect %s: %s", pdf_path, exc)
                continue
        slug = _slugify_pdf_name(pdf_path.stem)
        logger.info("Rendering %s (slug=%s)", pdf_path, slug)
        try:
            pages = render_pdf_to_images(pdf_bytes, dpi=dpi)
        except Exception as exc:
            logger.warning("Failed to render %s: %s", pdf_path, exc)
            continue

        for page in pages:
            page_index = int(page.get("page_index", 0))
            image_name = f"page_{page_index:04d}.png"
            meta_name = f"page_{page_index:04d}.json"
            image_dir = images_root / slug
            meta_dir = meta_root / slug
            image_path = image_dir / image_name
            meta_path = meta_dir / meta_name

            if not overwrite and image_path.exists() and meta_path.exists():
                logger.info("Skipping existing page %s for %s", page_index, pdf_path.name)
                continue

            image_dir.mkdir(parents=True, exist_ok=True)
            meta_dir.mkdir(parents=True, exist_ok=True)

            image = page.get("image")
            if image is None:
                logger.warning("No rendered image for page %s in %s", page_index, pdf_path)
                continue
            ok = cv2.imwrite(str(image_path), image)
            if not ok:
                logger.warning("Failed to write image %s", image_path)
                continue

            image_rel_path = str(Path("images") / slug / image_name)
            meta_payload = _build_meta_payload(
                source_pdf=pdf_path.name,
                source_pdf_path=str(pdf_path),
                slug=slug,
                page=page,
                dpi=dpi,
                image_rel_path=image_rel_path,
            )
            meta_path.write_text(json.dumps(meta_payload, indent=2), encoding="utf-8")
            logger.debug("Wrote %s", meta_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render raw PDFs into the sandbox ML dataset layout."
    )
    parser.add_argument(
        "pdfs",
        nargs="+",
        type=Path,
        help="Paths to PDFs to render into the dataset.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "data" / "raw",
        help="Dataset root where images/ and meta/ will be written.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=DEFAULT_DPI,
        help="Render DPI (should match the sandbox pipeline).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing images and metadata.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Skip PDFs with more than this many pages (avoids memory spikes).",
    )
    args = parser.parse_args()

    render_pdfs_to_dataset(
        args.pdfs,
        out_dir=args.out_dir,
        dpi=int(args.dpi),
        overwrite=bool(args.overwrite),
        max_pages=args.max_pages,
    )


if __name__ == "__main__":
    main()
