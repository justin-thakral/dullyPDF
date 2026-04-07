#!/usr/bin/env python3
"""
Dump everything sent to OpenAI for the rename pipeline into a directory.

For each page, outputs:
  - system_prompt.txt          (the full system message)
  - page_N_user_prompt.txt     (the full user message with field list)
  - page_N_clean.jpg           (clean page image, as sent)
  - page_N_overlay.png         (overlay with field IDs, as sent)
  - page_N_prev_crop.jpg       (previous page crop, if applicable)
  - page_N_overlay_fields.json (overlay field list with label hints)
  - page_N_candidates.json     (page candidates: labels, lines, boxes, checkboxes)
  - page_N_payload_meta.json   (detail levels, image sizes, budget metrics)

Usage:
    python3 dump_openai_rename_payload.py <pdf_path> [--out-dir "./openAI_overlays_exmaple"]
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

import cv2
import numpy as np

from fieldDetecting.rename_pipeline.combinedSrc.render_pdf import render_pdf_to_images
from fieldDetecting.rename_pipeline.combinedSrc.extract_labels import extract_labels
from fieldDetecting.rename_pipeline.combinedSrc.checkbox_label_hints import (
    normalize_checkbox_hint_text,
    pick_best_checkbox_label,
)
from fieldDetecting.rename_pipeline.combinedSrc.field_overlay import draw_overlay
from fieldDetecting.rename_pipeline.combinedSrc.prompt_builder import build_prompt
from fieldDetecting.rename_pipeline.combinedSrc.rename_resolver import (
    _attach_checkbox_label_hints as _attach_checkbox_label_hints_real,
)
from fieldDetecting.rename_pipeline.combinedSrc.vision_utils import image_bgr_to_data_url
from fieldDetecting.rename_pipeline.combinedSrc.coords import PageBox

try:
    from fieldDetecting.commonforms.commonForm import detect_commonforms_fields
    HAS_COMMONFORMS = True
except Exception:
    HAS_COMMONFORMS = False

import hashlib
import random

# ── Reproduce the overlay ID generation exactly as rename_resolver does ────────
BASE32_TAG_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
BASE32_TAGS = tuple(
    a + b + c
    for a in BASE32_TAG_ALPHABET
    for b in BASE32_TAG_ALPHABET
    for c in BASE32_TAG_ALPHABET
)


def _stable_seed(value: str) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _generate_base32_tags(count: int, *, seed: int) -> List[str]:
    if count <= 0:
        return []
    rng = random.Random(seed)
    return rng.sample(BASE32_TAGS, count)


def _field_sort_key(field: Dict[str, Any]) -> Tuple[int, float, float, str]:
    rect = field.get("rect") or [0, 0, 0, 0]
    page = int(field.get("page") or 1)
    y1 = float(rect[1]) if len(rect) == 4 else 0.0
    x1 = float(rect[0]) if len(rect) == 4 else 0.0
    return (page, y1, x1, str(field.get("name") or ""))


def _build_overlay_fields(
    page_idx: int,
    page_fields: List[Tuple[int, Dict[str, Any]]],
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    overlay_fields: List[Dict[str, Any]] = []
    overlay_map: Dict[str, int] = {}
    seed = _stable_seed(f"{page_idx}:{len(page_fields)}")
    tags = _generate_base32_tags(len(page_fields), seed=seed)
    for (field_index, field), display in zip(page_fields, tags):
        overlay_map[display] = field_index
        overlay_fields.append({
            "page": int(field.get("page") or 1),
            "rect": field.get("rect"),
            "type": field.get("type") or "text",
            "name": display,
            "displayName": display,
        })
    return overlay_fields, overlay_map


def _attach_checkbox_label_hints(
    overlay_fields: List[Dict[str, Any]],
    *,
    page_candidates: Dict[str, Any],
) -> List[Dict[str, Any]]:
    return _attach_checkbox_label_hints_real(overlay_fields, page_candidates=page_candidates)


def _build_candidates(
    rendered_pages: List[Dict[str, Any]],
    labels_by_page: Dict[int, List[Dict[str, Any]]],
    detector_candidates_by_page: Dict[int, Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for page in rendered_pages:
        page_idx = int(page.get("page_index") or 1)
        page_det = (detector_candidates_by_page or {}).get(page_idx) or {}
        candidates.append({
            "page": page_idx,
            "pageWidth": float(page.get("width_points") or 0.0),
            "pageHeight": float(page.get("height_points") or 0.0),
            "rotation": int(page.get("rotation") or 0),
            "imageWidthPx": int(page.get("image_width_px") or 0),
            "imageHeightPx": int(page.get("image_height_px") or 0),
            "labels": labels_by_page.get(page_idx, []),
            "lineCandidates": list(page_det.get("lineCandidates") or []),
            "boxCandidates": list(page_det.get("boxCandidates") or []),
            "checkboxCandidates": list(page_det.get("checkboxCandidates") or []),
        })
    return candidates


def _downscale_for_model(image_bgr, *, max_dim: int):
    if not max_dim or max_dim <= 0:
        return image_bgr
    h, w = image_bgr.shape[:2]
    largest = max(h, w)
    if largest <= max_dim:
        return image_bgr
    scale = max_dim / float(largest)
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    return cv2.resize(image_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)


def _data_url_to_bytes(data_url: str) -> bytes:
    """Extract raw image bytes from a data URL."""
    _, _, payload = data_url.partition(",")
    return base64.b64decode(payload)


def _crop_prev_page_context(image_bgr, *, fraction: float):
    if image_bgr is None or image_bgr.size == 0:
        return image_bgr
    if fraction <= 0 or fraction > 1:
        return image_bgr
    height = image_bgr.shape[0]
    crop_height = max(1, int(round(height * fraction)))
    start = max(0, height - crop_height)
    return image_bgr[start:height, :].copy()


def _should_include_prev_context(
    page_fields: List[Tuple[int, Dict[str, Any]]],
    *,
    page_height: float,
    top_fraction: float,
) -> bool:
    if not page_fields or page_height <= 0 or top_fraction <= 0:
        return False
    threshold = page_height * top_fraction
    for _idx, field in page_fields:
        rect = field.get("rect")
        if not isinstance(rect, list) or len(rect) != 4:
            continue
        try:
            y1 = float(rect[1])
        except (TypeError, ValueError):
            continue
        if y1 <= threshold:
            return True
    return False


def main():
    parser = argparse.ArgumentParser(description="Dump everything sent to OpenAI for rename")
    parser.add_argument("pdf", help="Path to PDF file")
    parser.add_argument("--out-dir", default="./openAI_overlays_exmaple", help="Output directory")
    parser.add_argument("--fields-json", default=None, help="Pre-detected fields JSON")
    parser.add_argument("--dpi", type=int, default=500, help="Render DPI (default 500, matches prod)")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"ERROR: {pdf_path} not found", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pdf_bytes = pdf_path.read_bytes()

    # ── Step 1: Render pages ───────────────────────────────────────────────
    print(f"Rendering {pdf_path.name} at {args.dpi} DPI...")
    rendered_pages = render_pdf_to_images(pdf_bytes, dpi=args.dpi, max_workers=1)

    # ── Step 2: Extract labels ─────────────────────────────────────────────
    print("Extracting labels...")
    labels_by_page = extract_labels(pdf_bytes, rendered_pages, max_workers=1)

    # ── Step 3: Detect fields ──────────────────────────────────────────────
    fields: List[Dict[str, Any]] = []
    detector_candidates_by_page: Dict[int, Dict[str, Any]] = {}

    if args.fields_json:
        fields = json.loads(Path(args.fields_json).read_text())
        print(f"Loaded {len(fields)} fields from {args.fields_json}")
    elif HAS_COMMONFORMS:
        print("Running CommonForms detection...")
        try:
            result = detect_commonforms_fields(pdf_path)
            fields = result.get("fields") or []
            raw_det = result.get("detectorCandidatesByPage") or {}
            for page_key, payload in raw_det.items():
                try:
                    page_idx = int(page_key)
                except (TypeError, ValueError):
                    continue
                if isinstance(payload, dict):
                    detector_candidates_by_page[page_idx] = {
                        "lineCandidates": list(payload.get("lineCandidates") or []),
                        "boxCandidates": list(payload.get("boxCandidates") or []),
                        "checkboxCandidates": list(payload.get("checkboxCandidates") or []),
                    }
            cb_count = sum(1 for f in fields if f.get("type") == "checkbox")
            print(f"Detected {len(fields)} fields ({cb_count} checkboxes)")
        except Exception as e:
            print(f"CommonForms detection failed: {e}")
            sys.exit(1)
    else:
        print("ERROR: No fields available. Pass --fields-json or install commonforms.", file=sys.stderr)
        sys.exit(1)

    # ── Step 4: Build candidates ───────────────────────────────────────────
    candidates = _build_candidates(rendered_pages, labels_by_page, detector_candidates_by_page)
    candidates_by_page = {int(c["page"]): c for c in candidates}

    # ── Step 5: Index fields by page ───────────────────────────────────────
    fields_by_page: Dict[int, List[Tuple[int, Dict[str, Any]]]] = {}
    for idx, field in enumerate(fields):
        page = int(field.get("page") or 1)
        fields_by_page.setdefault(page, []).append((idx, field))

    rendered_by_page = {int(p["page_index"]): p for p in rendered_pages}

    # ── Production-matching defaults (commonforms profile) ─────────────────
    overlay_quality = 96
    overlay_max_dim = 7000
    overlay_format = "png"
    overlay_detail = "high"
    clean_quality = 84
    clean_max_dim = 3200
    clean_format = "jpg"
    clean_detail = "low"
    label_max_dist_pts = 140.0
    prev_page_fraction = 0.2
    prev_page_top_fraction = 0.15

    CHECKBOX_RULES_START = "BEGIN_CHECKBOX_RULES_JSON"
    CHECKBOX_RULES_END = "END_CHECKBOX_RULES_JSON"

    system_message_written = False

    for page in rendered_pages:
        page_idx = int(page["page_index"])
        page_fields = fields_by_page.get(page_idx, [])
        if not page_fields:
            print(f"Page {page_idx}: no fields, skipping")
            continue

        page_fields_sorted = sorted(page_fields, key=lambda item: _field_sort_key(item[1]))
        page_candidates = candidates_by_page.get(page_idx)
        if page_candidates is None:
            continue

        # ── Build overlay fields + attach hints ────────────────────────────
        overlay_fields, overlay_map = _build_overlay_fields(page_idx, page_fields_sorted)
        overlay_fields = _attach_checkbox_label_hints(overlay_fields, page_candidates=page_candidates)

        # ── Render overlay image ───────────────────────────────────────────
        overlay_path = out_dir / f"page_{page_idx}_overlay_raw.png"
        overlay = draw_overlay(
            page["image"],
            page_candidates,
            overlay_fields,
            overlay_path,
            draw_candidates=False,
            field_labels_inside=True,
            label_max_dist_pts=label_max_dist_pts,
            highlight_checkbox_labels=False,
            checkbox_tag_scale=1.6,
            return_image=True,
        )

        # ── Encode images exactly as sent to OpenAI ────────────────────────
        # Clean page
        clean_model = _downscale_for_model(page["image"], max_dim=clean_max_dim)
        clean_url = image_bgr_to_data_url(clean_model, format=clean_format, quality=clean_quality)
        clean_bytes = _data_url_to_bytes(clean_url)
        clean_path = out_dir / f"page_{page_idx}_clean.{clean_format}"
        clean_path.write_bytes(clean_bytes)

        # Overlay
        overlay_model = _downscale_for_model(overlay, max_dim=overlay_max_dim)
        overlay_url = image_bgr_to_data_url(overlay_model, format=overlay_format, quality=overlay_quality)
        overlay_bytes = _data_url_to_bytes(overlay_url)
        overlay_img_path = out_dir / f"page_{page_idx}_overlay.{overlay_format}"
        overlay_img_path.write_bytes(overlay_bytes)

        # Previous page crop (if applicable)
        prev_crop_path = None
        has_prev = False
        if page_idx > 1 and prev_page_fraction > 0:
            prev_page = rendered_by_page.get(page_idx - 1)
            if prev_page is not None:
                include_prev = _should_include_prev_context(
                    page_fields_sorted,
                    page_height=float(page_candidates.get("pageHeight") or 0.0),
                    top_fraction=prev_page_top_fraction,
                )
                if include_prev:
                    prev_crop = _crop_prev_page_context(prev_page["image"], fraction=prev_page_fraction)
                    prev_model = _downscale_for_model(prev_crop, max_dim=clean_max_dim)
                    prev_url = image_bgr_to_data_url(prev_model, format="jpg", quality=clean_quality)
                    prev_bytes = _data_url_to_bytes(prev_url)
                    prev_crop_path = out_dir / f"page_{page_idx}_prev_crop.jpg"
                    prev_crop_path.write_bytes(prev_bytes)
                    has_prev = True

        # ── Build prompt text ──────────────────────────────────────────────
        system_message, user_message = build_prompt(
            page_idx,
            overlay_fields,
            page_candidates=page_candidates,
            confidence_profile="commonforms",
            database_fields=None,
            database_total_fields=None,
            database_fields_truncated=False,
            checkbox_rules_start=CHECKBOX_RULES_START,
            checkbox_rules_end=CHECKBOX_RULES_END,
            commonforms_thresholds=(0.60, 0.30),
        )

        # ── Write system prompt (same for all pages, write once) ───────────
        if not system_message_written:
            sys_path = out_dir / "system_prompt.txt"
            sys_path.write_text(system_message, encoding="utf-8")
            print(f"  -> {sys_path} ({len(system_message)} chars)")
            system_message_written = True

        # ── Write user prompt ──────────────────────────────────────────────
        user_path = out_dir / f"page_{page_idx}_user_prompt.txt"
        user_path.write_text(user_message, encoding="utf-8")

        # ── Write overlay fields JSON (with label hints) ───────────────────
        fields_json_path = out_dir / f"page_{page_idx}_overlay_fields.json"
        fields_json_path.write_text(
            json.dumps(overlay_fields, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # ── Write page candidates JSON ─────────────────────────────────────
        # Strip the image arrays (not serializable), keep everything else
        cand_dump = {k: v for k, v in page_candidates.items()}
        cand_path = out_dir / f"page_{page_idx}_candidates.json"
        cand_path.write_text(json.dumps(cand_dump, indent=2, ensure_ascii=False), encoding="utf-8")

        # ── Write payload metadata ─────────────────────────────────────────
        meta = {
            "page": page_idx,
            "field_count": len(page_fields_sorted),
            "checkbox_count": sum(1 for _, f in page_fields_sorted if f.get("type") == "checkbox"),
            "label_count": len(page_candidates.get("labels") or []),
            "images_sent": {
                "clean_page": {
                    "file": clean_path.name,
                    "detail": clean_detail,
                    "max_dim": clean_max_dim,
                    "quality": clean_quality,
                    "format": clean_format,
                    "size_bytes": len(clean_bytes),
                },
                "overlay": {
                    "file": overlay_img_path.name,
                    "detail": overlay_detail,
                    "max_dim": overlay_max_dim,
                    "quality": overlay_quality,
                    "format": overlay_format,
                    "size_bytes": len(overlay_bytes),
                },
            },
            "system_prompt_chars": len(system_message),
            "user_prompt_chars": len(user_message),
            "total_prompt_chars": len(system_message) + len(user_message),
            "overlay_map": {tag: idx for tag, idx in overlay_map.items()},
        }
        if has_prev:
            meta["images_sent"]["prev_page_crop"] = {
                "file": prev_crop_path.name,
                "detail": "low",
                "format": "jpg",
            }
        meta_path = out_dir / f"page_{page_idx}_payload_meta.json"
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

        # ── Summary ────────────────────────────────────────────────────────
        images_sent = 2 + (1 if has_prev else 0)
        print(
            f"Page {page_idx}: {len(page_fields_sorted)} fields, "
            f"{images_sent} images, {len(user_message)} chars user prompt"
        )
        print(f"  -> {clean_path.name}, {overlay_img_path.name}, {user_path.name}")
        if has_prev:
            print(f"  -> {prev_crop_path.name}")

    # ── Write a README ─────────────────────────────────────────────────────
    readme = out_dir / "README.txt"
    readme.write_text(
        f"OpenAI Rename Payload Dump\n"
        f"Source PDF: {pdf_path.name}\n"
        f"DPI: {args.dpi}\n"
        f"Confidence profile: commonforms\n\n"
        f"For each page, OpenAI receives:\n"
        f"  1. system_prompt.txt - system message (same for all pages)\n"
        f"  2. page_N_user_prompt.txt - user message with field list\n"
        f"  3. page_N_clean.jpg - clean page image (detail=low)\n"
        f"  4. page_N_overlay_sent.png - overlay with field IDs (detail=high)\n"
        f"  5. page_N_prev_crop.jpg - previous page bottom crop (if applicable, detail=low)\n\n"
        f"Supporting data:\n"
        f"  - page_N_overlay_fields.json - field objects with labelHintText\n"
        f"  - page_N_candidates.json - OCR labels, line/box/checkbox candidates\n"
        f"  - page_N_payload_meta.json - image profiles, sizes, overlay ID map\n",
        encoding="utf-8",
    )

    print(f"\nDone. All payloads saved to: {out_dir}/")


if __name__ == "__main__":
    main()
