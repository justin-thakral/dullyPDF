import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List

from .build_candidates import (
    assemble_candidates,
    filter_checkbox_candidates_by_char_overlap,
    filter_line_candidates_by_char_overlap,
    inject_checkbox_glyph_candidates,
    inject_line_glyph_candidates,
    inject_vector_checkbox_candidates,
    inject_vector_line_candidates,
)
from .calibration import compute_label_height_calibration
from .config import DEFAULT_THRESHOLDS, get_logger
from .detect_geometry import detect_geometry
from .extract_labels import extract_labels
from .form_fields import extract_form_fields, merge_form_fields
from ..nativeSrc.pipeline import resolve_native_pipeline
from .pdf_repair import maybe_repair_pdf
from .render_pdf import render_pdf_to_images
from ..scannedSrc.pipeline import resolve_scanned_pipeline
from .text_layer import (
    TextLayerStats,
    extract_text_layer_geometry,
    is_native_text_layer,
    is_reliable_text_layer,
    summarize_text_layer,
)

logger = get_logger(__name__)


@dataclass
class PipelineArtifacts:
    """
    Shared artifacts produced by geometry + label detection.

    These are reused by both the native and scanned resolvers so we avoid
    duplicating expensive rendering/detection work across pipelines.
    """

    rendered_pages: List[Dict[str, Any]]
    candidates: List[Dict[str, Any]]
    labels_by_page: Dict[int, List[Dict[str, Any]]]
    calibrations: Dict[int, Dict[str, Any]]
    text_layer_stats: TextLayerStats


@dataclass
class PipelineRun:
    result: Dict[str, Any]
    pipeline: str
    artifacts: PipelineArtifacts


def _choose_pipeline(stats: TextLayerStats, override: str | None) -> str:
    if override in {"native", "scanned"}:
        return override
    return "native" if is_native_text_layer(stats) else "scanned"


def build_artifacts(pdf_bytes: bytes) -> PipelineArtifacts:
    """
    Build shared, page-aligned artifacts for both native and scanned pipelines.

    Data structures:
    - rendered_pages: list of per-page images + geometry metadata.
    - geometry/labels/candidates: per-page lists keyed by page_index.
    - calibrations: median label height per page for stable rect sizing.

    Runtime: dominated by render + OpenCV passes; linear in page count.
    """
    rendered_pages = render_pdf_to_images(pdf_bytes)
    geometry = detect_geometry(rendered_pages)
    labels = extract_labels(pdf_bytes, rendered_pages=rendered_pages)
    candidates = assemble_candidates(rendered_pages, geometry, labels)
    calibrations = compute_label_height_calibration(labels)
    text_layer_stats = summarize_text_layer(pdf_bytes)
    return PipelineArtifacts(
        rendered_pages=rendered_pages,
        candidates=candidates,
        labels_by_page=labels,
        calibrations=calibrations,
        text_layer_stats=text_layer_stats,
    )


def run_pipeline(
    pdf_bytes: bytes,
    *,
    session_id: str,
    source_pdf: str,
    pipeline: str = "auto",
) -> PipelineRun:
    """
    Build shared artifacts and run the appropriate resolver.

    `pipeline` supports: auto | native | scanned.
    """
    pdf_bytes_for_pipeline = maybe_repair_pdf(pdf_bytes, source=source_pdf)
    artifacts = build_artifacts(pdf_bytes_for_pipeline)
    chosen = _choose_pipeline(artifacts.text_layer_stats, None if pipeline == "auto" else pipeline)

    logger.info(
        "Pipeline routing: %s (text_words=%s avg=%.2f)",
        chosen,
        artifacts.text_layer_stats.total_words,
        artifacts.text_layer_stats.avg_words_per_page,
    )

    use_text_layer = is_native_text_layer(artifacts.text_layer_stats) and is_reliable_text_layer(
        artifacts.text_layer_stats
    )
    if chosen == "native" and use_text_layer:
        overlap_threshold = float(
            os.getenv("SANDBOX_NATIVE_CHECKBOX_CHAR_OVERLAP", "0.45")
        )
        line_overlap_threshold = float(
            os.getenv("SANDBOX_NATIVE_LINE_CHAR_OVERLAP", "0.96")
        )
        glyph_overlap = float(
            os.getenv("SANDBOX_NATIVE_GLYPH_CHECKBOX_OVERLAP", "0.60")
        )
        vector_overlap = float(
            os.getenv("SANDBOX_NATIVE_VECTOR_CHECKBOX_OVERLAP", "0.60")
        )
        vector_line_overlap = float(
            os.getenv("SANDBOX_NATIVE_VECTOR_LINE_OVERLAP", "0.60")
        )
        glyph_line_overlap = float(
            os.getenv("SANDBOX_NATIVE_GLYPH_LINE_OVERLAP", "0.60")
        )
        text_geometry = extract_text_layer_geometry(pdf_bytes_for_pipeline)
        char_bboxes = text_geometry.char_bboxes_by_page
        rect_bboxes = text_geometry.rect_bboxes_by_page
        inject_checkbox_glyph_candidates(
            artifacts.candidates,
            char_bboxes,
            overlap_threshold=glyph_overlap,
        )
        inject_line_glyph_candidates(
            artifacts.candidates,
            char_bboxes,
            overlap_threshold=glyph_line_overlap,
        )
        inject_vector_checkbox_candidates(
            artifacts.candidates,
            rect_bboxes,
            overlap_threshold=vector_overlap,
        )
        inject_vector_line_candidates(
            artifacts.candidates,
            rect_bboxes,
            overlap_threshold=vector_line_overlap,
        )
        filter_line_candidates_by_char_overlap(
            artifacts.candidates,
            char_bboxes,
            overlap_threshold=line_overlap_threshold,
        )
        filter_checkbox_candidates_by_char_overlap(
            artifacts.candidates,
            char_bboxes,
            overlap_threshold=overlap_threshold,
        )
    elif chosen == "native" and not use_text_layer:
        logger.info(
            "Skipping native text-layer filters due to low alpha ratio (alpha_ratio=%.2f)",
            artifacts.text_layer_stats.alpha_ratio,
        )

    meta = {
        "session_id": session_id,
        "source_pdf": source_pdf,
        "thresholds": DEFAULT_THRESHOLDS,
        "calibrations": artifacts.calibrations,
    }

    if chosen == "native":
        result = resolve_native_pipeline(
            artifacts.candidates,
            meta,
            artifacts.labels_by_page,
            artifacts.calibrations,
        )
    else:
        result = resolve_scanned_pipeline(
            artifacts.candidates,
            meta,
            artifacts.labels_by_page,
            artifacts.calibrations,
        )

    form_fields = extract_form_fields(pdf_bytes_for_pipeline)
    if form_fields:
        merge_form_fields(result.setdefault("fields", []), form_fields)

    if "generatedAt" not in result:
        result["generatedAt"] = datetime.now(tz=timezone.utc).isoformat()

    return PipelineRun(result=result, pipeline=chosen, artifacts=artifacts)
