"""OpenAI rename pipeline orchestration for CommonForms sessions."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..fieldDetecting.rename_pipeline.combinedSrc.config import get_logger
from ..fieldDetecting.rename_pipeline.combinedSrc.extract_labels import extract_labels
from ..fieldDetecting.rename_pipeline.combinedSrc.rename_resolver import run_openai_rename_pipeline
from ..fieldDetecting.rename_pipeline.combinedSrc.render_pdf import render_pdf_to_images
from ..fieldDetecting.rename_pipeline.debug_flags import debug_enabled


logger = get_logger(__name__)


def _build_candidates(
    rendered_pages: List[Dict[str, Any]],
    labels_by_page: Dict[int, List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """
    Build per-page candidate payloads for overlay rendering.
    """
    candidates: List[Dict[str, Any]] = []
    for page in rendered_pages:
        page_idx = int(page.get("page_index") or 1)
        candidates.append(
            {
                "page": page_idx,
                "pageWidth": float(page.get("width_points") or 0.0),
                "pageHeight": float(page.get("height_points") or 0.0),
                "rotation": int(page.get("rotation") or 0),
                "imageWidthPx": int(page.get("image_width_px") or 0),
                "imageHeightPx": int(page.get("image_height_px") or 0),
                "labels": labels_by_page.get(page_idx, []),
            }
        )
    return candidates


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    """
    Write JSON artifacts for debug usage only.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2)


def run_openai_rename_on_pdf(
    *,
    pdf_bytes: bytes,
    pdf_name: str,
    fields: List[Dict[str, Any]],
    database_fields: List[str] | None = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Render PDF pages, extract labels, and run the OpenAI rename pipeline.
    """
    rendered_pages = render_pdf_to_images(pdf_bytes)
    labels_by_page = extract_labels(pdf_bytes, rendered_pages)
    candidates = _build_candidates(rendered_pages, labels_by_page)
    rename_report: Dict[str, Any]
    renamed_fields: List[Dict[str, Any]]

    with tempfile.TemporaryDirectory(prefix="dullypdf-openai-rename-") as temp_dir:
        temp_root = Path(temp_dir)
        overlay_dir = temp_root / "overlays"

        rename_report, renamed_fields = run_openai_rename_pipeline(
            rendered_pages,
            candidates,
            fields,
            output_dir=overlay_dir,
            confidence_profile="commonforms",
            database_fields=database_fields,
        )

        if debug_enabled():
            _write_json(temp_root / "renames.json", rename_report)
            _write_json(
                temp_root / "fields_renamed.json",
                {"fields": renamed_fields},
            )

    return rename_report, renamed_fields
