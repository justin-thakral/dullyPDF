#!/usr/bin/env python3

"""Generate demo name maps for swapping overlays without swapping PDFs.

We keep the raw PDF rendered (no widgets), then show overlays extracted from the
CommonForms/base detections PDF and apply OpenAI Rename / Remap names by mapping
widget rectangles between PDFs.

This script scrapes widget names using pypdf and writes JSON maps under
frontend/public/demo/generated/ so the frontend can apply name swaps instantly
without parsing multiple PDFs in the browser.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from pypdf import PdfReader


@dataclass(frozen=True)
class Widget:
    page: int
    rect: Tuple[float, float, float, float]
    name: str


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _rect_key(rect: Tuple[float, float, float, float], decimals: int) -> Tuple[float, float, float, float]:
    # Use rounding to keep the key stable across minor float / serialization differences.
    return tuple(round(float(v), decimals) for v in rect)  # type: ignore[return-value]


def _widget_name(annot: object) -> Optional[str]:
    # pypdf returns a DictionaryObject-like structure.
    try:
        name = annot.get("/T")
    except Exception:
        return None

    if name is None:
        try:
            parent = annot.get("/Parent")
        except Exception:
            parent = None
        if parent is not None:
            try:
                parent_obj = parent.get_object()
                name = parent_obj.get("/T")
            except Exception:
                name = None

    if name is None:
        return None

    return str(name)


def extract_widgets(pdf_path: Path) -> List[Widget]:
    reader = PdfReader(str(pdf_path))
    widgets: List[Widget] = []

    for page_idx, page in enumerate(reader.pages, start=1):
        annots = page.get("/Annots")
        if not annots:
            continue

        try:
            annots = annots.get_object()
        except Exception:
            pass

        for annot_ref in list(annots):
            try:
                annot = annot_ref.get_object()
            except Exception:
                annot = annot_ref

            try:
                subtype = annot.get("/Subtype")
            except Exception:
                subtype = None
            if subtype != "/Widget":
                continue

            try:
                rect = annot.get("/Rect")
            except Exception:
                rect = None
            if rect is None or len(rect) != 4:
                continue

            name = _widget_name(annot)
            if not name:
                continue

            rect_tuple = (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))
            widgets.append(Widget(page=page_idx, rect=rect_tuple, name=name))

    return widgets


def build_name_map(
    base_widgets: Iterable[Widget],
    next_widgets: Iterable[Widget],
    *,
    rect_round_decimals: int,
) -> Tuple[Dict[str, str], List[str]]:
    """Match widgets by (page, rect) and map base_name -> next_name.

    Complexity: O(n) to index + O(n) to build mapping.

    Returns:
    - mapping dict
    - list of warning strings
    """

    warnings: List[str] = []

    index: Dict[Tuple[int, Tuple[float, float, float, float]], str] = {}
    for w in next_widgets:
        key = (w.page, _rect_key(w.rect, rect_round_decimals))
        if key in index and index[key] != w.name:
            warnings.append(f"Duplicate rect key in next PDF on page {w.page}: {key[1]} => {index[key]} vs {w.name}")
        index[key] = w.name

    mapping: Dict[str, str] = {}
    missing = 0
    for w in base_widgets:
        key = (w.page, _rect_key(w.rect, rect_round_decimals))
        next_name = index.get(key)
        if next_name is None:
            missing += 1
            continue
        mapping[w.name] = next_name

    if missing:
        warnings.append(f"Missing matches for {missing} base widgets.")

    return mapping, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate demo widget name maps")
    parser.add_argument(
        "--base",
        default="frontend/public/demo/baseFieldDetections.pdf",
        help="Base widget PDF (CommonForms detections)",
    )
    parser.add_argument(
        "--rename",
        default="frontend/public/demo/openAiRename.pdf",
        help="OpenAI rename PDF",
    )
    parser.add_argument(
        "--remap",
        default="frontend/public/demo/openAiRemap.pdf",
        help="OpenAI remap PDF",
    )
    parser.add_argument(
        "--out-dir",
        default="frontend/public/demo/generated",
        help="Output directory (served by Vite)",
    )
    parser.add_argument(
        "--rect-round-decimals",
        type=int,
        default=2,
        help="Decimals to round rect coordinates for matching",
    )

    args = parser.parse_args()
    base_path = Path(args.base)
    rename_path = Path(args.rename)
    remap_path = Path(args.remap)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    base_widgets = extract_widgets(base_path)
    rename_widgets = extract_widgets(rename_path)
    remap_widgets = extract_widgets(remap_path)

    base_sha = _sha256_file(base_path)
    rename_sha = _sha256_file(rename_path)
    remap_sha = _sha256_file(remap_path)

    rename_map, rename_warnings = build_name_map(
        base_widgets,
        rename_widgets,
        rect_round_decimals=args.rect_round_decimals,
    )
    remap_map, remap_warnings = build_name_map(
        base_widgets,
        remap_widgets,
        rect_round_decimals=args.rect_round_decimals,
    )

    generated_at = datetime.now(timezone.utc).isoformat()

    outputs = [
        (
            "baseToOpenAiRenameNameMap.json",
            {
                "generatedAt": generated_at,
                "rectRoundDecimals": args.rect_round_decimals,
                "base": {
                    "path": str(base_path),
                    "sha256": base_sha,
                    "widgets": len(base_widgets),
                },
                "next": {
                    "path": str(rename_path),
                    "sha256": rename_sha,
                    "widgets": len(rename_widgets),
                },
                "warnings": rename_warnings,
                "map": rename_map,
            },
        ),
        (
            "baseToOpenAiRemapNameMap.json",
            {
                "generatedAt": generated_at,
                "rectRoundDecimals": args.rect_round_decimals,
                "base": {
                    "path": str(base_path),
                    "sha256": base_sha,
                    "widgets": len(base_widgets),
                },
                "next": {
                    "path": str(remap_path),
                    "sha256": remap_sha,
                    "widgets": len(remap_widgets),
                },
                "warnings": remap_warnings,
                "map": remap_map,
            },
        ),
    ]

    for filename, payload in outputs:
        out_path = out_dir / filename
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"Wrote {len(outputs)} maps to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
