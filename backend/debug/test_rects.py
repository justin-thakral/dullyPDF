import argparse
import json
from pathlib import Path

from ..combinedSrc.build_candidates import assemble_candidates
from ..combinedSrc.calibration import compute_label_height_calibration
from .debug_overlay import draw_overlay
from ..combinedSrc.detect_geometry import detect_geometry
from ..combinedSrc.extract_labels import extract_labels
from ..combinedSrc.heuristic_resolver import resolve_fields_heuristically
from ..combinedSrc.output_layout import ensure_output_layout, temp_prefix_from_pdf
from ..combinedSrc.pdf_repair import maybe_repair_pdf
from ..combinedSrc.render_pdf import render_pdf_to_images
from ..combinedSrc.config import DEFAULT_THRESHOLDS, get_logger

logger = get_logger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Generate rect overlays for debugging.")
    parser.add_argument("pdf", type=Path, help="Input PDF")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Root directory for json/ and overlays/ (defaults to backend/outputArtifacts).",
    )
    parser.add_argument(
        "--candidates-only",
        action="store_true",
        help="Only show geometry candidates (no final fields).",
    )
    args = parser.parse_args()

    output_root = args.output_dir or Path("backend/outputArtifacts")
    layout = ensure_output_layout(output_root)
    prefix = temp_prefix_from_pdf(args.pdf)

    pdf_bytes = args.pdf.read_bytes()
    pdf_bytes = maybe_repair_pdf(pdf_bytes, source=args.pdf.name)
    rendered_pages = render_pdf_to_images(pdf_bytes)
    geometry = detect_geometry(rendered_pages)
    labels = extract_labels(pdf_bytes, rendered_pages=rendered_pages)
    candidates = assemble_candidates(rendered_pages, geometry, labels)
    calibrations = compute_label_height_calibration(labels)

    if args.candidates_only:
        fields = []
        resolved = {"fields": fields}
    else:
        resolved = resolve_fields_heuristically(
            candidates,
            {
                "session_id": "overlay",
                "source_pdf": args.pdf.name,
                "thresholds": DEFAULT_THRESHOLDS,
                "calibrations": calibrations,
            },
            labels,
            calibrations,
        )
        fields = resolved.get("fields", [])
        logger.info("Resolver produced %s fields", len(fields))

    (layout.json_dir / f"{prefix}_candidates.json").write_text(
        json.dumps({"candidates": candidates}, indent=2)
    )
    (layout.json_dir / f"{prefix}_fields.json").write_text(
        json.dumps({"fields": fields}, indent=2)
    )

    # Draw overlays per page.
    for page in rendered_pages:
        page_idx = page["page_index"]
        page_candidates = next(c for c in candidates if c["page"] == page_idx)
        img = page["image"]
        out_path = layout.overlays_dir / f"{prefix}_page_{page_idx}.png"
        draw_overlay(img, page_candidates, fields, out_path)


if __name__ == "__main__":
    main()
