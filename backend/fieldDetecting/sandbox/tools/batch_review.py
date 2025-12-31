import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from ..combinedSrc.output_layout import ensure_output_layout, temp_prefix_from_pdf
from ..combinedSrc.pipeline_router import run_pipeline
from ..combinedSrc.text_layer import extract_text_layer_geometry
from ..debug.debug_overlay import draw_overlay


def _iter_pdfs(
    root: Path,
    *,
    pattern: str | None,
    limit: int | None,
    offset: int = 0,
) -> List[Path]:
    if not root.exists():
        raise SystemExit(f"PDF root not found: {root}")
    pdfs = sorted(root.rglob("*.pdf"))
    if pattern:
        pdfs = [p for p in pdfs if pattern in p.name]
    if offset:
        pdfs = pdfs[int(offset) :]
    if limit is not None:
        pdfs = pdfs[: max(0, int(limit))]
    return pdfs


def _prefix_for_pdf(pdf_path: Path, root: Path) -> str:
    rel = str(pdf_path.relative_to(root)).encode("utf-8", "ignore")
    digest = hashlib.sha1(rel).hexdigest()[:8]
    return f"{temp_prefix_from_pdf(pdf_path)}_{digest}"


def _labels_text(page_candidates: Dict[str, Any]) -> str:
    parts: List[str] = []
    for label in page_candidates.get("labels", []) or []:
        text = str(label.get("text") or "").strip()
        if text:
            parts.append(text)
    return " ".join(parts)


def _summarize_candidates(candidates: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    totals = {"lines": 0, "boxes": 0, "checkboxes": 0, "labels": 0}
    for page in candidates:
        totals["lines"] += len(page.get("lineCandidates") or [])
        totals["boxes"] += len(page.get("boxCandidates") or [])
        totals["checkboxes"] += len(page.get("checkboxCandidates") or [])
        totals["labels"] += len(page.get("labels") or [])
    return totals


def _has_checkbox_glyphs(label_text: str) -> bool:
    strong_glyphs = {
        "\\u2610",
        "\\u2611",
        "\\u2612",
        "\\u2751",
        "\\u2752",
    }
    weak_glyphs = {
        "\\u25a1",
        "\\u25a0",
        "\\u25a2",
        "\\u25a3",
        "\\u25aa",
        "\\u25ab",
        "\\u25fb",
        "\\u25fc",
        "\\u25cf",
        "\\u25cb",
        "\\u25c9",
        "\\u25ef",
        "\\u2b1c",
        "\\u2b1b",
    }
    for token in strong_glyphs:
        if token.encode("utf-8").decode("unicode_escape") in label_text:
            return True
    weak_count = 0
    for token in weak_glyphs:
        glyph = token.encode("utf-8").decode("unicode_escape")
        weak_count += label_text.count(glyph)
        if weak_count >= 2:
            return True
    return False


def _has_vector_checkbox_rects(pdf_bytes: bytes) -> bool:
    geometry = extract_text_layer_geometry(pdf_bytes)
    for rects in geometry.rect_bboxes_by_page.values():
        count = 0
        for rect in rects:
            bbox = rect.get("bbox") if isinstance(rect, dict) else None
            if not bbox or len(bbox) != 4:
                continue
            width = float(bbox[2]) - float(bbox[0])
            height = float(bbox[3]) - float(bbox[1])
            if width <= 0.0 or height <= 0.0:
                continue
            aspect = width / max(height, 0.01)
            if width < 4.0 or height < 4.0 or width > 22.0 or height > 22.0:
                continue
            if not (0.70 <= aspect <= 1.35):
                continue
            count += 1
            if count >= 2:
                return True
    return False


def _has_small_square_box_candidates(candidates: Sequence[Dict[str, Any]]) -> bool:
    count = 0
    for page in candidates:
        for box in page.get("boxCandidates") or []:
            bbox = box.get("bbox") if isinstance(box, dict) else None
            if not bbox or len(bbox) != 4:
                continue
            width = float(bbox[2]) - float(bbox[0])
            height = float(bbox[3]) - float(bbox[1])
            if width <= 0.0 or height <= 0.0:
                continue
            aspect = width / max(height, 0.01)
            if width < 4.0 or height < 4.0 or width > 24.0 or height > 24.0:
                continue
            if not (0.70 <= aspect <= 1.35):
                continue
            count += 1
            if count >= 2:
                return True
    return False


def _flag_issues(
    *,
    candidates: Sequence[Dict[str, Any]],
    fields_count: int,
    total_words: int,
    label_text: str,
    checkbox_evidence: bool,
) -> List[str]:
    totals = _summarize_candidates(candidates)
    flags: List[str] = []

    if fields_count == 0:
        flags.append("zero_fields")
    if totals["checkboxes"] == 0 and any(
        token in label_text for token in ("checkbox", "check", "yes", "no", "select")
    ):
        if checkbox_evidence:
            flags.append("no_checkboxes_with_check_labels")
    if fields_count < 4 and (totals["lines"] + totals["boxes"]) >= 12:
        flags.append("low_fields_vs_geometry")
    if total_words >= 150 and fields_count < 5:
        flags.append("text_dense_low_fields")
    return flags


def _write_overlays(
    *,
    rendered_pages: Sequence[Dict[str, Any]],
    candidates: Sequence[Dict[str, Any]],
    fields: Sequence[Dict[str, Any]],
    overlay_root: Path,
    prefix: str,
) -> None:
    for page in rendered_pages:
        page_idx = page["page_index"]
        page_candidates = next(c for c in candidates if c["page"] == page_idx)
        out_path = overlay_root / f"{prefix}_page_{page_idx}.png"
        draw_overlay(page["image"], page_candidates, list(fields), out_path)


def _write_json(
    *,
    json_root: Path,
    prefix: str,
    candidates: Sequence[Dict[str, Any]],
    fields: Sequence[Dict[str, Any]],
) -> None:
    (json_root / f"{prefix}_candidates.json").write_text(
        json.dumps({"candidates": candidates}, indent=2)
    )
    (json_root / f"{prefix}_fields.json").write_text(
        json.dumps({"fields": fields}, indent=2)
    )


def run_batch(
    pdfs: Sequence[Path],
    *,
    output_root: Path,
    pipeline: str,
    overlays: str,
    save_json: bool,
    pdf_root: Path,
) -> List[Dict[str, Any]]:
    layout = ensure_output_layout(output_root)
    report: List[Dict[str, Any]] = []
    for pdf_path in pdfs:
        pdf_bytes = pdf_path.read_bytes()
        run = run_pipeline(
            pdf_bytes,
            session_id=f"batch-{pdf_path.stem}",
            source_pdf=pdf_path.name,
            pipeline=pipeline,
        )
        fields = run.result.get("fields", [])
        candidates = run.artifacts.candidates
        totals = _summarize_candidates(candidates)
        label_text = " ".join(_labels_text(page) for page in candidates)
        label_text_lower = label_text.lower()
        checkbox_evidence = False
        if totals["checkboxes"] == 0 and any(
            token in label_text_lower for token in ("checkbox", "check", "yes", "no", "select")
        ):
            checkbox_evidence = (
                _has_checkbox_glyphs(label_text)
                or _has_vector_checkbox_rects(pdf_bytes)
                or _has_small_square_box_candidates(candidates)
            )

        flags = _flag_issues(
            candidates=candidates,
            fields_count=len(fields),
            total_words=int(run.artifacts.text_layer_stats.total_words or 0),
            label_text=label_text_lower,
            checkbox_evidence=checkbox_evidence,
        )
        prefix = _prefix_for_pdf(pdf_path, pdf_root)
        if save_json:
            _write_json(
                json_root=layout.json_dir,
                prefix=prefix,
                candidates=candidates,
                fields=fields,
            )
        if overlays == "all" or (overlays == "issues" and flags):
            _write_overlays(
                rendered_pages=run.artifacts.rendered_pages,
                candidates=candidates,
                fields=fields,
                overlay_root=layout.overlays_dir,
                prefix=prefix,
            )

        report.append(
            {
                "pdf": str(pdf_path),
                "pipeline": run.pipeline,
                "pages": len(candidates),
                "fields": len(fields),
                "lines": totals["lines"],
                "boxes": totals["boxes"],
                "checkboxes": totals["checkboxes"],
                "labels": totals["labels"],
                "flags": flags,
            }
        )
    return report


def _write_report(report: Sequence[Dict[str, Any]], output_root: Path) -> None:
    layout = ensure_output_layout(output_root)
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = layout.json_dir / f"batch_report_{timestamp}.json"
    csv_path = layout.json_dir / f"batch_report_{timestamp}.csv"

    json_path.write_text(json.dumps(list(report), indent=2))

    with csv_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["pdf", "pipeline", "pages", "fields", "lines", "boxes", "checkboxes", "labels", "flags"]
        )
        for row in report:
            writer.writerow(
                [
                    row.get("pdf"),
                    row.get("pipeline"),
                    row.get("pages"),
                    row.get("fields"),
                    row.get("lines"),
                    row.get("boxes"),
                    row.get("checkboxes"),
                    row.get("labels"),
                    "|".join(row.get("flags") or []),
                ]
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch-run the field detection pipeline and summarize results."
    )
    parser.add_argument(
        "--pdfs-dir",
        type=Path,
        default=Path("backend/fieldDetecting/pdfs/native/hippa"),
        help="Root directory containing PDFs to process.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("backend/fieldDetecting/outputArtifacts"),
        help="Root output directory for json/ and overlays/.",
    )
    parser.add_argument(
        "--pipeline",
        choices=["auto", "native", "scanned"],
        default="auto",
        help="Pipeline routing override.",
    )
    parser.add_argument(
        "--pattern",
        help="Substring filter for PDF filenames (simple contains match).",
    )
    parser.add_argument(
        "--max",
        type=int,
        help="Limit the number of PDFs processed.",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Skip the first N PDFs in the sorted list.",
    )
    parser.add_argument(
        "--overlays",
        choices=["none", "all", "issues"],
        default="issues",
        help="Write overlays for all PDFs or only those with flags.",
    )
    parser.add_argument(
        "--save-json",
        action="store_true",
        help="Write per-PDF candidates/fields JSON alongside the batch report.",
    )
    args = parser.parse_args()

    pdfs = _iter_pdfs(
        args.pdfs_dir,
        pattern=args.pattern,
        limit=args.max,
        offset=args.offset,
    )
    report = run_batch(
        pdfs,
        output_root=args.output_dir,
        pipeline=args.pipeline,
        overlays=args.overlays,
        save_json=args.save_json,
        pdf_root=args.pdfs_dir,
    )
    _write_report(report, args.output_dir)


if __name__ == "__main__":
    main()
