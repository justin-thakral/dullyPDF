from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import cv2
import numpy as np

from ..combinedSrc.config import get_logger
from ..combinedSrc.coords import PageBox, px_bbox_to_pts_bbox
from .tiling import iter_tiles

logger = get_logger(__name__)

EXPECTED_CLASS_NAMES = ["checkbox", "underline", "textbox"]


@dataclass(frozen=True)
class Detection:
    class_name: str
    score: float
    bbox_px: Tuple[float, float, float, float]  # x1, y1, x2, y2 in full-page pixels


_MODEL = None
_MODEL_PATH: Path | None = None
_MODEL_CLASS_MAP: Dict[int, str] | None = None


def _resolve_weights_path() -> Path:
    env_path = os.getenv("SANDBOX_ML_WEIGHTS")
    if env_path:
        return Path(env_path)
    return Path(__file__).resolve().parent / "weights" / "best.pt"


def _load_model() -> Tuple[object | None, Dict[int, str] | None]:
    """
    Lazily load the YOLO model so the sandbox can run without ML deps installed.
    """
    global _MODEL, _MODEL_PATH, _MODEL_CLASS_MAP
    weights_path = _resolve_weights_path()
    if _MODEL is not None and _MODEL_PATH == weights_path:
        return _MODEL, _MODEL_CLASS_MAP

    try:
        from ultralytics import YOLO  # type: ignore
    except Exception as exc:
        logger.error("ML detector unavailable (missing ultralytics): %s", exc)
        return None, None

    if not weights_path.exists():
        logger.error("ML detector weights not found at %s", weights_path)
        return None, None

    logger.info("Loading ML detector weights from %s", weights_path)
    model = YOLO(str(weights_path))

    names = getattr(model, "names", None)
    if names is None:
        names = getattr(getattr(model, "model", None), "names", None)

    if isinstance(names, dict):
        class_map = {int(k): str(v) for k, v in names.items()}
    elif isinstance(names, (list, tuple)):
        class_map = {idx: str(name) for idx, name in enumerate(names)}
    else:
        class_map = {}

    missing = [name for name in EXPECTED_CLASS_NAMES if name not in class_map.values()]
    if missing:
        logger.warning(
            "ML detector classes do not match expected names. Missing=%s names=%s",
            missing,
            class_map,
        )

    _MODEL = model
    _MODEL_PATH = weights_path
    _MODEL_CLASS_MAP = class_map
    return _MODEL, _MODEL_CLASS_MAP


def _tensor_to_numpy(value) -> np.ndarray:
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        return value.numpy()
    return np.asarray(value)


def _iou(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    iw = max(0.0, ix2 - ix1)
    ih = max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    denom = area_a + area_b - inter
    if denom <= 0:
        return 0.0
    return inter / denom


def _nms(detections: List[Detection], *, iou_threshold: float) -> List[Detection]:
    """
    Greedy NMS on full-page pixel boxes.

    This keeps the highest-confidence detections when tiles overlap.
    """
    if not detections:
        return []
    ordered = sorted(detections, key=lambda d: float(d.score), reverse=True)
    kept: List[Detection] = []
    for det in ordered:
        if any(_iou(det.bbox_px, prev.bbox_px) >= iou_threshold for prev in kept):
            continue
        kept.append(det)
    return kept


def _hole_area_ratio_from_mask_bbox(
    text_mask: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
    *,
    pad_px: int = 2,
) -> float:
    """
    Estimate interior hole ratio inside a candidate checkbox bbox.

    This mirrors the OpenCV checkbox filter so ML outputs remain aligned.
    """
    if text_mask is None or text_mask.size == 0 or w <= 0 or h <= 0:
        return 0.0

    height, width = text_mask.shape[:2]
    pad = max(0, int(pad_px))
    x0 = max(0, int(x) - pad)
    y0 = max(0, int(y) - pad)
    x1 = min(width, int(x + w) + pad)
    y1 = min(height, int(y + h) + pad)
    roi = text_mask[y0:y1, x0:x1]
    if roi.size == 0:
        return 0.0

    ink = (roi > 0).astype(np.uint8)
    if int(np.count_nonzero(ink)) == 0:
        return 0.0

    bg = (1 - ink).astype(np.uint8)
    bg_padded = np.pad(bg, ((1, 1), (1, 1)), mode="constant", constant_values=1)
    mask = np.zeros((bg_padded.shape[0] + 2, bg_padded.shape[1] + 2), dtype=np.uint8)
    try:
        cv2.floodFill(bg_padded, mask, (0, 0), 0)
    except cv2.error:
        return 0.0

    holes = bg_padded[1:-1, 1:-1]
    hole_area = float(np.count_nonzero(holes))
    bbox_area = float(int(w) * int(h))
    return hole_area / bbox_area if bbox_area > 0.0 else 0.0


def _checkbox_edge_coverages(
    text_mask: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
) -> Tuple[float, float, float, float]:
    """
    Measure straight-edge coverage near each side of a candidate checkbox.
    """
    if text_mask is None or text_mask.size == 0 or w <= 2 or h <= 2:
        return 0.0, 0.0, 0.0, 0.0

    img_h, img_w = text_mask.shape[:2]
    x0 = max(0, min(img_w, int(x)))
    y0 = max(0, min(img_h, int(y)))
    x1 = max(0, min(img_w, int(x + w)))
    y1 = max(0, min(img_h, int(y + h)))
    if x1 <= x0 or y1 <= y0:
        return 0.0, 0.0, 0.0, 0.0

    pad = max(2, min(6, int(round(min(w, h) * 0.12))))
    top = text_mask[y0 : min(img_h, y0 + pad), x0:x1]
    bottom = text_mask[max(0, y1 - pad) : y1, x0:x1]
    left = text_mask[y0:y1, x0 : min(img_w, x0 + pad)]
    right = text_mask[y0:y1, max(0, x1 - pad) : x1]

    def _ratio(arr: np.ndarray) -> float:
        return float(np.count_nonzero(arr)) / float(arr.size) if arr.size else 0.0

    return _ratio(top), _ratio(bottom), _ratio(left), _ratio(right)


def _passes_checkbox_filters(
    text_mask: np.ndarray,
    bbox_px: Tuple[int, int, int, int],
) -> bool:
    """
    Guardrail filter to prevent "O/0/D" glyphs from becoming checkboxes.
    """
    x1, y1, x2, y2 = bbox_px
    w = max(0, x2 - x1)
    h = max(0, y2 - y1)
    if w <= 0 or h <= 0:
        return False

    top_cov, bottom_cov, left_cov, right_cov = _checkbox_edge_coverages(text_mask, x1, y1, w, h)
    edge_covs = [top_cov, bottom_cov, left_cov, right_cov]
    strong_edges = sum(1 for v in edge_covs if v >= 0.58)
    mean_edge = float(sum(edge_covs)) / 4.0

    hole_ratio = _hole_area_ratio_from_mask_bbox(text_mask, x1, y1, w, h, pad_px=2)
    min_hole_ratio = 0.26 if (strong_edges >= 3 and mean_edge >= 0.66) else 0.36
    if hole_ratio < min_hole_ratio:
        return False

    return True


def _build_text_mask(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return binary


def _predict_page_tiles(
    model: object,
    class_map: Dict[int, str],
    image: np.ndarray,
    *,
    tile_size: int,
    stride: int,
    conf: float,
    device: str | None,
    imgsz: int,
) -> List[Detection]:
    detections: List[Detection] = []
    image_h, image_w = image.shape[:2]
    tile_count = 0

    for tile_x, tile_y, tile_w, tile_h in iter_tiles(image_w, image_h, tile_size, stride):
        tile = image[tile_y : tile_y + tile_h, tile_x : tile_x + tile_w]
        tile_count += 1

        results = model.predict(
            tile,
            conf=conf,
            iou=0.7,
            imgsz=imgsz,
            device=device,
            verbose=False,
        )
        if not results:
            continue
        boxes = getattr(results[0], "boxes", None)
        if boxes is None or boxes.xyxy is None:
            continue

        xyxy = _tensor_to_numpy(boxes.xyxy)
        scores = _tensor_to_numpy(boxes.conf) if getattr(boxes, "conf", None) is not None else None
        classes = _tensor_to_numpy(boxes.cls) if getattr(boxes, "cls", None) is not None else None

        if scores is None or classes is None:
            continue

        for bbox, score, cls_id in zip(xyxy, scores, classes):
            class_name = class_map.get(int(cls_id))
            if class_name not in EXPECTED_CLASS_NAMES:
                continue
            x1, y1, x2, y2 = [float(v) for v in bbox]
            x1 = max(0.0, min(float(image_w), x1 + tile_x))
            y1 = max(0.0, min(float(image_h), y1 + tile_y))
            x2 = max(0.0, min(float(image_w), x2 + tile_x))
            y2 = max(0.0, min(float(image_h), y2 + tile_y))
            if x2 <= x1 or y2 <= y1:
                continue
            detections.append(
                Detection(
                    class_name=class_name,
                    score=float(score),
                    bbox_px=(x1, y1, x2, y2),
                )
            )

    logger.debug("ML detector tiles=%s raw_detections=%s", tile_count, len(detections))
    return detections


def detect_ml_geometry(page: Dict) -> Dict | None:
    """
    Run the ML detector on a rendered page and return geometry candidates.

    Returns None if the detector cannot run (missing deps/weights).
    """
    model, class_map = _load_model()
    if model is None or class_map is None:
        return None

    image = page["image"]
    image_h, image_w = image.shape[:2]
    page_box = PageBox(
        page_width=float(page["width_points"]),
        page_height=float(page["height_points"]),
        rotation=int(page.get("rotation", 0)),
    )

    tile_size = int(os.getenv("SANDBOX_ML_TILE_SIZE", "1024"))
    stride = int(os.getenv("SANDBOX_ML_TILE_STRIDE", "768"))
    conf = float(os.getenv("SANDBOX_ML_CONF", "0.10"))
    device = os.getenv("SANDBOX_ML_DEVICE") or None
    imgsz = int(os.getenv("SANDBOX_ML_IMGSZ", str(tile_size)))

    detections = _predict_page_tiles(
        model,
        class_map,
        image,
        tile_size=tile_size,
        stride=stride,
        conf=conf,
        device=device,
        imgsz=imgsz,
    )

    by_class: Dict[str, List[Detection]] = {name: [] for name in EXPECTED_CLASS_NAMES}
    for det in detections:
        by_class[det.class_name].append(det)

    nms_thresholds = {"checkbox": 0.5, "underline": 0.7, "textbox": 0.7}
    filtered: Dict[str, List[Detection]] = {}
    for name, dets in by_class.items():
        filtered[name] = _nms(dets, iou_threshold=nms_thresholds[name])

    text_mask = _build_text_mask(image)
    checkbox_filtered: List[Detection] = []
    for det in filtered["checkbox"]:
        x1, y1, x2, y2 = det.bbox_px
        bbox_px = (int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2)))
        if not _passes_checkbox_filters(text_mask, bbox_px):
            continue
        checkbox_filtered.append(det)
    filtered["checkbox"] = checkbox_filtered

    underline_filtered: List[Detection] = []
    max_underline = 0.92 * float(image_w)
    for det in filtered["underline"]:
        x1, _, x2, _ = det.bbox_px
        if float(x2 - x1) >= max_underline:
            continue
        underline_filtered.append(det)
    filtered["underline"] = underline_filtered

    line_candidates: List[Dict] = []
    box_candidates: List[Dict] = []
    checkbox_candidates: List[Dict] = []

    def _to_candidate(det: Detection) -> Dict:
        x1, y1, x2, y2 = det.bbox_px
        w = max(1.0, x2 - x1)
        h = max(1.0, y2 - y1)
        bbox_pts = px_bbox_to_pts_bbox((int(x1), int(y1), int(w), int(h)), image_w, image_h, page_box)
        return {
            "bbox": bbox_pts,
            "bboxPx": [int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))],
            "score": float(det.score),
            "detector": "ml_yolo",
        }

    for det in filtered["underline"]:
        line_candidates.append(_to_candidate(det))
    for det in filtered["textbox"]:
        box_candidates.append(_to_candidate(det))
    for det in filtered["checkbox"]:
        checkbox_candidates.append(_to_candidate(det))

    logger.debug(
        "ML page %s -> lines=%s boxes=%s checkboxes=%s",
        page.get("page_index"),
        len(line_candidates),
        len(box_candidates),
        len(checkbox_candidates),
    )

    return {
        "page_index": page["page_index"],
        "lineCandidates": line_candidates,
        "boxCandidates": box_candidates,
        "checkboxCandidates": checkbox_candidates,
    }
