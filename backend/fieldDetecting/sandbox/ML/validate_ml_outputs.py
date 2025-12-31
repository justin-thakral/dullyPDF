from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Dict, List, Tuple

from ..combinedSrc.build_candidates import assemble_candidates
from ..combinedSrc.config import get_logger
from ..combinedSrc.coords import PageBox, pts_bbox_to_px_bbox
from ..debug.debug_overlay import draw_overlay
from ..combinedSrc.detect_geometry import detect_geometry
from ..combinedSrc.extract_labels import extract_labels
from ..combinedSrc.output_layout import ensure_output_layout, temp_prefix_from_pdf
from ..combinedSrc.render_pdf import render_pdf_to_images

logger = get_logger(__name__)


def _write_debug_outputs(
    out_dir: Path,
    rendered_pages: List[Dict],
    candidates: List[Dict],
    *,
    prefix: str,
) -> None:
    layout = ensure_output_layout(out_dir)
    (layout.json_dir / f"{prefix}_candidates.json").write_text(
        json.dumps({"candidates": candidates}, indent=2), encoding="utf-8"
    )
    for page in rendered_pages:
        page_idx = page["page_index"]
        page_candidates = next(c for c in candidates if c["page"] == page_idx)
        overlay_candidates = layout.overlays_dir / f"{prefix}_overlay_candidates_page_{page_idx}.png"
        draw_overlay(
            page["image"],
            page_candidates,
            [],
            overlay_candidates,
            draw_candidates=True,
            draw_fields=False,
        )


def _find_label_region(page: Dict, *, keywords: List[str], pad: float = 18.0) -> Tuple[float, float] | None:
    labels = page.get("labels") or []
    page_height = float(page.get("pageHeight") or 0.0)
    best = None
    for lbl in labels:
        text = (lbl.get("text") or "").upper()
        if not text:
            continue
        if all(keyword.upper() in text for keyword in keywords):
            best = lbl
            break
    if not best:
        return None
    bbox = best.get("bbox") or []
    if len(bbox) != 4:
        return None
    y0 = max(0.0, float(bbox[1]) - pad)
    y1 = min(page_height, float(bbox[3]) + pad)
    return y0, y1


def _checkboxes_in_region(page: Dict, region: Tuple[float, float]) -> int:
    y0, y1 = region
    count = 0
    for cb in page.get("checkboxCandidates") or []:
        bbox = cb.get("bbox") or []
        if len(bbox) != 4:
            continue
        y_mid = (float(bbox[1]) + float(bbox[3])) / 2.0
        if y0 <= y_mid <= y1:
            count += 1
    return count


def _ensure_bbox_px(cb: Dict, page: Dict) -> List[int] | None:
    bbox_px = cb.get("bboxPx") or []
    if len(bbox_px) == 4:
        return [int(round(v)) for v in bbox_px]
    bbox = cb.get("bbox") or []
    if len(bbox) != 4:
        return None
    image_w = int(page.get("imageWidthPx") or 0)
    image_h = int(page.get("imageHeightPx") or 0)
    if image_w <= 0 or image_h <= 0:
        return None
    page_box = PageBox(
        page_width=float(page.get("pageWidth") or 0.0),
        page_height=float(page.get("pageHeight") or 0.0),
        rotation=int(page.get("rotation") or 0),
    )
    px = pts_bbox_to_px_bbox(bbox, image_w, image_h, page_box)
    return [int(round(v)) for v in px]


def _rows_with_two_columns(
    boxes_px: List[List[int]],
    *,
    image_width: int,
    image_height: int,
) -> int:
    if not boxes_px:
        return 0
    y_tol = max(10, int(image_height * 0.0025))
    x_tol = max(100, int(image_width * 0.02))

    rows: List[Dict] = []
    for x1, y1, x2, y2 in sorted(boxes_px, key=lambda b: (b[1] + b[3]) / 2.0):
        y_mid = (float(y1) + float(y2)) / 2.0
        x_mid = (float(x1) + float(x2)) / 2.0
        if not rows or abs(y_mid - rows[-1]["y"]) > y_tol:
            rows.append({"y": y_mid, "xs": [x_mid]})
        else:
            row = rows[-1]
            row["xs"].append(x_mid)
            row["y"] = sum(row["xs"]) / float(len(row["xs"]))

    def _cluster_x(xs: List[float]) -> List[float]:
        clusters: List[float] = []
        for x in sorted(xs):
            if not clusters or abs(x - clusters[-1]) > x_tol:
                clusters.append(x)
            else:
                clusters[-1] = (clusters[-1] + x) / 2.0
        return clusters

    row_count = 0
    for row in rows:
        clusters = _cluster_x(row["xs"])
        if len(clusters) >= 2:
            row_count += 1
    return row_count


def _run_pipeline(
    pdf_path: Path,
    *,
    out_dir: Path | None,
    write_overlays: bool,
    prefix: str,
) -> List[Dict]:
    pdf_bytes = pdf_path.read_bytes()
    rendered_pages = render_pdf_to_images(pdf_bytes)
    geometry = detect_geometry(rendered_pages)
    labels = extract_labels(pdf_bytes, rendered_pages=rendered_pages)
    candidates = assemble_candidates(rendered_pages, geometry, labels)

    if out_dir and write_overlays:
        _write_debug_outputs(out_dir, rendered_pages, candidates, prefix=prefix)

    return candidates


def _count_ml_candidates(candidates: List[Dict]) -> int:
    count = 0
    for page in candidates:
        for key in ("lineCandidates", "boxCandidates", "checkboxCandidates"):
            for cand in page.get(key) or []:
                if cand.get("detector") == "ml_yolo":
                    count += 1
    return count


def validate(
    hipaa_path: Path,
    medical_history_path: Path,
    patient_intake_path: Path,
    *,
    hipaa_page2_min: int,
    hipaa_page2_max: int,
    patient_intake_min_rows: int,
    out_root: Path | None,
    write_overlays: bool,
) -> None:
    os.environ["SANDBOX_USE_ML_DETECTOR"] = "1"

    failures: List[str] = []

    hipaa_slug = temp_prefix_from_pdf(hipaa_path)
    hipaa_out = out_root if out_root else None
    hipaa_candidates = _run_pipeline(
        hipaa_path, out_dir=hipaa_out, write_overlays=write_overlays, prefix=hipaa_slug
    )
    ml_candidates_seen = _count_ml_candidates(hipaa_candidates)
    hipaa_page1 = next((p for p in hipaa_candidates if int(p.get("page") or 0) == 1), None)
    if hipaa_page1:
        region = _find_label_region(
            hipaa_page1,
            keywords=["PROTECTED", "HEALTH", "INFORMATION"],
            pad=20.0,
        )
        if region is None:
            failures.append("HIPAA: could not locate the PROTECTED HEALTH INFORMATION header label.")
        else:
            header_count = _checkboxes_in_region(hipaa_page1, region)
            if header_count != 0:
                failures.append(
                    f"HIPAA page 1: expected 0 header checkboxes near PROTECTED label, got {header_count}."
                )
    else:
        failures.append("HIPAA: missing page 1 candidates.")

    hipaa_page2 = next((p for p in hipaa_candidates if int(p.get("page") or 0) == 2), None)
    if hipaa_page2:
        cb_count = len(hipaa_page2.get("checkboxCandidates") or [])
        if cb_count < hipaa_page2_min or cb_count > hipaa_page2_max:
            failures.append(
                f"HIPAA page 2: checkbox count {cb_count} outside expected range "
                f"[{hipaa_page2_min}, {hipaa_page2_max}]."
            )
    else:
        failures.append("HIPAA: missing page 2 candidates.")

    if medical_history_path.exists():
        medical_slug = temp_prefix_from_pdf(medical_history_path)
        medical_out = out_root if out_root else None
        medical_candidates = _run_pipeline(
            medical_history_path,
            out_dir=medical_out,
            write_overlays=write_overlays,
            prefix=medical_slug,
        )
        ml_candidates_seen += _count_ml_candidates(medical_candidates)

    patient_slug = temp_prefix_from_pdf(patient_intake_path)
    patient_out = out_root if out_root else None
    patient_candidates = _run_pipeline(
        patient_intake_path,
        out_dir=patient_out,
        write_overlays=write_overlays,
        prefix=patient_slug,
    )
    ml_candidates_seen += _count_ml_candidates(patient_candidates)
    patient_page3 = next((p for p in patient_candidates if int(p.get("page") or 0) == 3), None)
    if patient_page3:
        image_w = int(patient_page3.get("imageWidthPx") or 0)
        image_h = int(patient_page3.get("imageHeightPx") or 0)
        checkboxes = patient_page3.get("checkboxCandidates") or []
        table_cells = [cb for cb in checkboxes if cb.get("detector") == "table_cells"]
        target_boxes: List[List[int]] = []
        source = table_cells if len(table_cells) >= 6 else checkboxes
        for cb in source:
            bbox_px = _ensure_bbox_px(cb, patient_page3)
            if bbox_px:
                target_boxes.append(bbox_px)
        row_count = _rows_with_two_columns(
            target_boxes,
            image_width=image_w,
            image_height=image_h,
        )
        if row_count < patient_intake_min_rows:
            failures.append(
                f"Patient intake page 3: expected at least {patient_intake_min_rows} Y/N rows, got {row_count}."
            )
    else:
        failures.append("Patient intake: missing page 3 candidates.")

    if failures:
        for failure in failures:
            logger.error("Validation failure: %s", failure)
        raise SystemExit(1)

    if ml_candidates_seen == 0:
        raise SystemExit(
            "ML validation did not detect any ml_yolo candidates. "
            "Check SANDBOX_ML_WEIGHTS and ultralytics installation."
        )

    logger.info("ML validation checks passed.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate ML geometry on golden PDFs.")
    parser.add_argument(
        "--hipaa",
        type=Path,
        default=Path("backend/fieldDetecting/pdfs/native/HIPPA.pdf"),
        help="Path to the HIPAA release PDF.",
    )
    parser.add_argument(
        "--medical-history",
        type=Path,
        default=Path("backend/fieldDetecting/pdfs/scanned/medical-history-intake-form.pdf"),
        help="Path to the medical history intake PDF.",
    )
    parser.add_argument(
        "--patient-intake",
        type=Path,
        default=Path("backend/fieldDetecting/pdfs/native/patient-Intake-pdf.pdf"),
        help="Path to the patient intake PDF.",
    )
    parser.add_argument("--hipaa-page2-min", type=int, default=20)
    parser.add_argument("--hipaa-page2-max", type=int, default=45)
    parser.add_argument("--patient-intake-min-rows", type=int, default=4)
    parser.add_argument(
        "--out-root",
        type=Path,
        default=Path("backend/fieldDetecting/outputArtifacts"),
        help="Where to write overlay outputs.",
    )
    parser.add_argument(
        "--skip-overlays",
        action="store_true",
        help="Skip writing overlay images.",
    )
    args = parser.parse_args()

    validate(
        hipaa_path=args.hipaa,
        medical_history_path=args.medical_history,
        patient_intake_path=args.patient_intake,
        hipaa_page2_min=int(args.hipaa_page2_min),
        hipaa_page2_max=int(args.hipaa_page2_max),
        patient_intake_min_rows=int(args.patient_intake_min_rows),
        out_root=args.out_root,
        write_overlays=not args.skip_overlays,
    )


if __name__ == "__main__":
    main()
