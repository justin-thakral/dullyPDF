from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import cv2

from ..combinedSrc.config import get_logger
from .tiling import iter_tiles

logger = get_logger(__name__)

EXPECTED_CLASS_NAMES = ["checkbox", "underline", "textbox"]


@dataclass(frozen=True)
class CocoImage:
    image_id: int
    file_name: str
    width: int
    height: int


@dataclass(frozen=True)
class CocoAnnotation:
    annotation_id: int
    image_id: int
    category_id: int
    bbox: Tuple[float, float, float, float]  # x, y, w, h in full-page pixels


def _slugify_path(path: str) -> str:
    """
    Convert a relative file path into a stable slug for tile filenames.

    This keeps tile names unique across PDFs while remaining filesystem-safe.
    """
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", (path or "").strip())
    cleaned = cleaned.strip("_")
    return cleaned.lower() or "page"


def _infer_split(coco_path: Path) -> str:
    stem = coco_path.stem.lower()
    if "val" in stem or "valid" in stem or "validation" in stem:
        return "val"
    if "test" in stem:
        return "test"
    return "train"


def _load_coco(coco_path: Path) -> Tuple[List[CocoImage], List[CocoAnnotation], Dict[int, str]]:
    payload = json.loads(coco_path.read_text(encoding="utf-8"))
    images = [
        CocoImage(
            image_id=int(img["id"]),
            file_name=str(img["file_name"]),
            width=int(img.get("width") or 0),
            height=int(img.get("height") or 0),
        )
        for img in payload.get("images", [])
    ]
    annotations = [
        CocoAnnotation(
            annotation_id=int(ann["id"]),
            image_id=int(ann["image_id"]),
            category_id=int(ann["category_id"]),
            bbox=(
                float(ann["bbox"][0]),
                float(ann["bbox"][1]),
                float(ann["bbox"][2]),
                float(ann["bbox"][3]),
            ),
        )
        for ann in payload.get("annotations", [])
    ]
    categories = {int(cat["id"]): str(cat["name"]) for cat in payload.get("categories", [])}
    return images, annotations, categories


def _build_category_map(categories: Dict[int, str]) -> Dict[int, int]:
    """
    Map COCO category ids to YOLO class indices.

    We enforce the expected class names so downstream training stays consistent.
    """
    name_to_idx = {name: idx for idx, name in enumerate(EXPECTED_CLASS_NAMES)}
    cat_map: Dict[int, int] = {}
    missing = []
    for cat_id, name in categories.items():
        if name not in name_to_idx:
            continue
        cat_map[cat_id] = name_to_idx[name]
    for expected in EXPECTED_CLASS_NAMES:
        if expected not in categories.values():
            missing.append(expected)
    if missing:
        raise ValueError(f"COCO categories missing required names: {missing}")
    return cat_map


def _center_in_tile(xc: float, yc: float, tile_x: int, tile_y: int, tile_w: int, tile_h: int) -> bool:
    return tile_x <= xc < tile_x + tile_w and tile_y <= yc < tile_y + tile_h


def _clip_bbox_to_tile(
    bbox: Tuple[float, float, float, float],
    tile_x: int,
    tile_y: int,
    tile_w: int,
    tile_h: int,
) -> Tuple[float, float, float, float]:
    x, y, w, h = bbox
    x1 = max(tile_x, x)
    y1 = max(tile_y, y)
    x2 = min(tile_x + tile_w, x + w)
    y2 = min(tile_y + tile_h, y + h)
    return x1 - tile_x, y1 - tile_y, max(0.0, x2 - x1), max(0.0, y2 - y1)


def _write_dataset_yaml(out_dir: Path) -> None:
    images_dir = out_dir / "images"
    train_dir = images_dir / "train"
    val_dir = images_dir / "val"
    train_key = "images/train" if train_dir.exists() else "images"
    val_key = "images/val" if val_dir.exists() else train_key

    content = "\n".join(
        [
            f"path: {out_dir.resolve()}",
            f"train: {train_key}",
            f"val: {val_key}",
            "names:",
            "  0: checkbox",
            "  1: underline",
            "  2: textbox",
            "",
        ]
    )
    (out_dir / "dataset.yaml").write_text(content, encoding="utf-8")


def prepare_tiled_dataset(
    coco_paths: List[Path],
    *,
    images_root: Path,
    out_dir: Path,
    tile_size: int,
    stride: int,
    min_box_size: int,
    skip_empty: bool,
    split_override: str | None,
) -> None:
    out_images = out_dir / "images"
    out_labels = out_dir / "labels"
    out_images.mkdir(parents=True, exist_ok=True)
    out_labels.mkdir(parents=True, exist_ok=True)

    manifest = {
        "tileSize": int(tile_size),
        "stride": int(stride),
        "minBoxSize": int(min_box_size),
        "imagesRoot": str(images_root),
        "generatedAt": datetime.now(tz=timezone.utc).isoformat(),
        "splits": {},
    }

    for coco_path in coco_paths:
        split = split_override or _infer_split(coco_path)
        logger.info("Processing COCO %s (split=%s)", coco_path, split)

        images, annotations, categories = _load_coco(coco_path)
        cat_map = _build_category_map(categories)
        annotations_by_image: Dict[int, List[CocoAnnotation]] = {}
        for ann in annotations:
            annotations_by_image.setdefault(ann.image_id, []).append(ann)

        split_images_dir = out_images / split
        split_labels_dir = out_labels / split
        split_images_dir.mkdir(parents=True, exist_ok=True)
        split_labels_dir.mkdir(parents=True, exist_ok=True)

        split_manifest = manifest["splits"].setdefault(
            split,
            {"tiles": [], "classCounts": {name: 0 for name in EXPECTED_CLASS_NAMES}},
        )

        for img in images:
            img_path = images_root / img.file_name
            image = cv2.imread(str(img_path))
            if image is None:
                logger.warning("Skipping unreadable image: %s", img_path)
                continue
            image_h, image_w = image.shape[:2]
            if img.width and img.height and (img.width != image_w or img.height != image_h):
                logger.debug(
                    "Image size mismatch for %s: coco=%sx%s actual=%sx%s",
                    img.file_name,
                    img.width,
                    img.height,
                    image_w,
                    image_h,
                )

            base_slug = _slugify_path(Path(img.file_name).with_suffix("").as_posix())
            anns = annotations_by_image.get(img.image_id, [])

            for tile_x, tile_y, tile_w, tile_h in iter_tiles(image_w, image_h, tile_size, stride):
                tile_labels: List[str] = []
                ann_ids: List[int] = []
                for ann in anns:
                    if ann.category_id not in cat_map:
                        continue
                    x, y, w, h = ann.bbox
                    if w <= 0 or h <= 0:
                        continue
                    xc = x + w / 2.0
                    yc = y + h / 2.0
                    if not _center_in_tile(xc, yc, tile_x, tile_y, tile_w, tile_h):
                        continue

                    clip_x, clip_y, clip_w, clip_h = _clip_bbox_to_tile(
                        ann.bbox,
                        tile_x,
                        tile_y,
                        tile_w,
                        tile_h,
                    )
                    if clip_w < min_box_size or clip_h < min_box_size:
                        continue
                    class_id = cat_map[ann.category_id]
                    x_center = (clip_x + clip_w / 2.0) / float(tile_w)
                    y_center = (clip_y + clip_h / 2.0) / float(tile_h)
                    norm_w = clip_w / float(tile_w)
                    norm_h = clip_h / float(tile_h)
                    tile_labels.append(
                        f"{class_id} {x_center:.6f} {y_center:.6f} {norm_w:.6f} {norm_h:.6f}"
                    )
                    ann_ids.append(ann.annotation_id)
                    split_manifest["classCounts"][EXPECTED_CLASS_NAMES[class_id]] += 1

                if skip_empty and not tile_labels:
                    continue

                tile_name = f"{base_slug}__x{tile_x:04d}_y{tile_y:04d}.png"
                tile_rel_image = Path("images") / split / tile_name
                tile_rel_label = Path("labels") / split / tile_name.replace(".png", ".txt")
                tile_path = out_dir / tile_rel_image
                label_path = out_dir / tile_rel_label

                tile = image[tile_y : tile_y + tile_h, tile_x : tile_x + tile_w]
                cv2.imwrite(str(tile_path), tile)
                label_path.write_text("\n".join(tile_labels), encoding="utf-8")

                split_manifest["tiles"].append(
                    {
                        "tile": str(tile_rel_image),
                        "label": str(tile_rel_label),
                        "sourceImage": img.file_name,
                        "sourceImageId": img.image_id,
                        "tileX": int(tile_x),
                        "tileY": int(tile_y),
                        "tileWidth": int(tile_w),
                        "tileHeight": int(tile_h),
                        "imageWidth": int(image_w),
                        "imageHeight": int(image_h),
                        "annotationIds": ann_ids,
                    }
                )

        logger.info(
            "Split %s -> tiles=%s classCounts=%s",
            split,
            len(split_manifest["tiles"]),
            split_manifest["classCounts"],
        )

    _write_dataset_yaml(out_dir)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("Wrote dataset.yaml and manifest.json to %s", out_dir)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert COCO full-page annotations into a tiled YOLO dataset."
    )
    parser.add_argument(
        "--coco",
        type=Path,
        action="append",
        required=True,
        help="Path to a COCO JSON file (repeatable).",
    )
    parser.add_argument(
        "--images-root",
        type=Path,
        required=True,
        help="Root directory that contains the page images referenced by COCO file_name.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "data" / "tiles",
        help="Output directory for tiled images/labels and dataset.yaml.",
    )
    parser.add_argument("--tile-size", type=int, default=1024, help="Tile size in pixels.")
    parser.add_argument("--stride", type=int, default=768, help="Tile stride in pixels.")
    parser.add_argument(
        "--min-box-size",
        type=int,
        default=4,
        help="Minimum box size (pixels) after clipping to keep.",
    )
    parser.add_argument(
        "--skip-empty",
        action="store_true",
        help="Skip tiles that contain no labels.",
    )
    parser.add_argument(
        "--split",
        type=str,
        help="Override split name (train/val/test). Not allowed with multiple --coco inputs.",
    )
    args = parser.parse_args()

    if args.split and len(args.coco) > 1:
        raise SystemExit("--split cannot be used when passing multiple --coco files.")

    prepare_tiled_dataset(
        coco_paths=args.coco,
        images_root=args.images_root,
        out_dir=args.out_dir,
        tile_size=int(args.tile_size),
        stride=int(args.stride),
        min_box_size=int(args.min_box_size),
        skip_empty=bool(args.skip_empty),
        split_override=args.split,
    )


if __name__ == "__main__":
    main()
