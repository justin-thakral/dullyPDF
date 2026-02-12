"""
CommonForms ML detector integration for PDF field detection.

This module wraps the CommonForms library, converts model outputs into the
canonical field schema, and optionally writes fillable PDFs for debugging.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from pypdf import PdfReader

from ..rename_pipeline.combinedSrc.config import get_logger
from ..rename_pipeline.combinedSrc.form_filler import inject_fields_from_template
from ..rename_pipeline.combinedSrc.output_layout import ensure_output_layout, temp_prefix_from_pdf

logger = get_logger(__name__)

DEFAULT_MODEL = os.getenv("COMMONFORMS_MODEL", "FFDNet-L")
DEFAULT_CONFIDENCE = float(os.getenv("COMMONFORMS_CONFIDENCE", "0.3"))
DEFAULT_IMAGE_SIZE = int(os.getenv("COMMONFORMS_IMAGE_SIZE", "1600"))
DEFAULT_DEVICE = os.getenv("COMMONFORMS_DEVICE", "cpu")
DEFAULT_FAST = os.getenv("COMMONFORMS_FAST", "false").lower() == "true"
DEFAULT_MULTILINE = os.getenv("COMMONFORMS_MULTILINE", "false").lower() == "true"
DEFAULT_BATCH_SIZE = int(os.getenv("COMMONFORMS_BATCH_SIZE", "4"))
COMMONFORMS_CONFIDENCE_GREEN = float(os.getenv("COMMONFORMS_CONFIDENCE_GREEN", "0.8"))
COMMONFORMS_CONFIDENCE_YELLOW = float(os.getenv("COMMONFORMS_CONFIDENCE_YELLOW", "0.65"))


@dataclass(frozen=True)
class DetectedWidget:
    """
    Lightweight detection record produced by CommonForms.

    Data structures:
    - bounding_box is a normalized (0..1) box in image coordinates.
    """

    widget_type: str
    bounding_box: Any
    page_idx: int
    confidence: float


def _import_commonforms():
    """
    Import CommonForms modules with runtime guards for optional backends.
    """
    # Prevent optional backends from loading if present in the environment.
    os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
    os.environ.setdefault("USE_TF", "0")
    os.environ.setdefault("TRANSFORMERS_NO_FLAX", "1")
    os.environ.setdefault("USE_FLAX", "0")
    os.environ.setdefault("USE_TORCH", "1")

    disable_tensorboard = os.getenv("SANDBOX_DISABLE_TENSORBOARD", "true").lower() in {
        "1",
        "true",
        "yes",
    }
    if disable_tensorboard and "torch.utils.tensorboard" not in sys.modules:
        module = types.ModuleType("torch.utils.tensorboard")

        class _NoopWriter:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            def add_scalar(self, *args: Any, **kwargs: Any) -> None:
                pass

            def add_image(self, *args: Any, **kwargs: Any) -> None:
                pass

            def add_histogram(self, *args: Any, **kwargs: Any) -> None:
                pass

            def add_text(self, *args: Any, **kwargs: Any) -> None:
                pass

            def flush(self) -> None:
                pass

            def close(self) -> None:
                pass

        module.SummaryWriter = _NoopWriter
        module.FileWriter = _NoopWriter
        sys.modules["torch.utils.tensorboard"] = module
    try:
        from commonforms.exceptions import EncryptedPdfError  # type: ignore
        from commonforms.inference import FFDetrDetector, FFDNetDetector, render_pdf  # type: ignore
        from commonforms.utils import BoundingBox  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "CommonForms import failed. Ensure `commonforms` and its torch/ultralytics "
            "deps are installed and compatible with your Python environment."
        ) from exc
    return (
        FFDetrDetector,
        FFDNetDetector,
        render_pdf,
        BoundingBox,
        EncryptedPdfError,
    )


def _parse_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _parse_gcs_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise ValueError(f"Invalid GCS URI: {uri}")
    parts = uri[5:].split("/", 1)
    bucket = parts[0]
    object_name = parts[1] if len(parts) > 1 else ""
    if not bucket or not object_name:
        raise ValueError(f"Invalid GCS URI: {uri}")
    return bucket, object_name


def _safe_cache_key(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]", "_", value.strip())
    return cleaned or "model"


def _acquire_download_lock(lock_path: Path, timeout_seconds: int) -> None:
    start = time.monotonic()
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return
        except FileExistsError:
            try:
                lock_age = time.time() - lock_path.stat().st_mtime
            except FileNotFoundError:
                lock_age = 0.0
            if lock_age > timeout_seconds:
                lock_path.unlink(missing_ok=True)
                continue
            if time.monotonic() - start >= timeout_seconds:
                raise TimeoutError("Timed out waiting for CommonForms weights download lock")
            time.sleep(1)


def _download_gcs_blob(bucket_name: str, object_name: str, dest: Path) -> None:
    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_name)
    if not blob.exists():
        raise FileNotFoundError(f"GCS object not found: gs://{bucket_name}/{object_name}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Streaming download is linear in the size of the weight file.
    blob.download_to_filename(str(dest))


def _ensure_gcs_model(gcs_uri: str, model_hint: str) -> Path:
    bucket, object_name = _parse_gcs_uri(gcs_uri)
    cache_root = os.getenv("COMMONFORMS_WEIGHTS_CACHE_DIR", "/tmp/commonforms-models").strip()
    cache_dir = Path(cache_root) / _safe_cache_key(model_hint or object_name)
    cache_dir.mkdir(parents=True, exist_ok=True)
    local_path = cache_dir / Path(object_name).name
    if local_path.exists() and local_path.stat().st_size > 0:
        return local_path

    lock_timeout = _parse_int_env("COMMONFORMS_WEIGHTS_LOCK_TIMEOUT_SECONDS", 600)
    lock_path = cache_dir / ".download.lock"
    _acquire_download_lock(lock_path, lock_timeout)
    try:
        if local_path.exists() and local_path.stat().st_size > 0:
            return local_path
        logger.info("Downloading CommonForms weights from %s", gcs_uri)
        _download_gcs_blob(bucket, object_name, local_path)
    finally:
        lock_path.unlink(missing_ok=True)
    return local_path


def _resolve_commonforms_model(model: str) -> tuple[str, str]:
    gcs_uri = os.getenv("COMMONFORMS_MODEL_GCS_URI", "").strip()
    if not gcs_uri and model.startswith("gs://"):
        gcs_uri = model
    if not gcs_uri:
        return model, model
    local_path = _ensure_gcs_model(gcs_uri, model)
    return model, str(local_path)


def _category_for_confidence(confidence: float) -> str:
    """
    Map a confidence score into green/yellow/red buckets.
    """
    high = COMMONFORMS_CONFIDENCE_GREEN
    medium = COMMONFORMS_CONFIDENCE_YELLOW
    if medium > high:
        medium = high
    if confidence >= high:
        return "green"
    if confidence >= medium:
        return "yellow"
    return "red"


def _batch(items: List[Any], size: int) -> Iterable[List[Any]]:
    """
    Yield fixed-size batches from a list for model inference.
    """
    for idx in range(0, len(items), size):
        yield items[idx : idx + size]


def _sort_detected_widgets(widgets: List[DetectedWidget]) -> List[DetectedWidget]:
    """
    Sort widgets top-to-bottom, left-to-right for stable downstream ordering.

    We first sort by y/x, then regroup widgets into scanline-like rows.
    """
    if not widgets:
        return []
    sorted_widgets = sorted(
        widgets,
        key=lambda w: (round(float(w.bounding_box.y0), 3), float(w.bounding_box.x0)),
    )

    y_threshold = 0.01
    lines: List[List[DetectedWidget]] = []
    current_line: List[DetectedWidget] = []

    for widget in sorted_widgets:
        if (
            not current_line
            or abs(float(widget.bounding_box.y0) - float(current_line[0].bounding_box.y0))
            < y_threshold
        ):
            current_line.append(widget)
        else:
            current_line.sort(key=lambda w: float(w.bounding_box.x0))
            lines.append(current_line)
            current_line = [widget]

    if current_line:
        current_line.sort(key=lambda w: float(w.bounding_box.x0))
        lines.append(current_line)

    return [widget for line in lines for widget in line]


def _detect_ffdetr(
    detector: Any,
    pages: List[Any],
    *,
    confidence: float,
    batch_size: int,
    bounding_box_cls: Any,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Dict[int, List[DetectedWidget]]:
    """
    Run FFDetr detection and return widgets grouped by page index.
    """
    results: List[Any] = []
    images = [p.image for p in pages]
    for batch in _batch(images, size=batch_size):
        predictions = detector.model.predict(batch, threshold=confidence)
        if len(pages) == 1 or batch_size == 1:
            predictions = [predictions]
        results.extend(predictions)

    widgets: Dict[int, List[DetectedWidget]] = {}
    total_pages = len(pages)
    for page_ix, detections in enumerate(results):
        if detections is None:
            continue
        detections = detections.with_nms(threshold=0.1, class_agnostic=True)
        page_widgets: List[DetectedWidget] = []
        page_image = pages[page_ix].image
        image_width = float(page_image.width)
        image_height = float(page_image.height)

        for box, class_id, score in zip(
            detections.xyxy, detections.class_id, detections.confidence
        ):
            x0, y0, x1, y1 = [float(v) for v in box]
            widget_type = detector.id_to_cls.get(int(class_id), "TextBox")
            bounding_box = bounding_box_cls(
                x0=x0 / image_width,
                y0=y0 / image_height,
                x1=x1 / image_width,
                y1=y1 / image_height,
            )
            page_widgets.append(
                DetectedWidget(
                    widget_type=widget_type,
                    bounding_box=bounding_box,
                    page_idx=page_ix,
                    confidence=float(score),
                )
            )

        widgets[page_ix] = _sort_detected_widgets(page_widgets)
        if progress_callback:
            try:
                progress_callback(page_ix + 1, total_pages)
            except Exception:
                pass

    return widgets


def _detect_ffdnet(
    detector: Any,
    pages: List[Any],
    *,
    confidence: float,
    image_size: int,
    bounding_box_cls: Any,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Dict[int, List[DetectedWidget]]:
    """
    Run FFDNet detection and return widgets grouped by page index.
    """
    total_pages = len(pages)
    if detector.fast:
        results = []
        for page_ix, page in enumerate(pages):
            results.append(
                detector.model.predict(
                    page.image,
                    iou=1,
                    conf=confidence,
                    augment=False,
                    imgsz=1216,
                    device=detector.device,
                )
            )
            if progress_callback:
                try:
                    progress_callback(page_ix + 1, total_pages)
                except Exception:
                    pass
    else:
        results = detector.model.predict(
            [p.image for p in pages],
            iou=0.1,
            conf=confidence,
            augment=True,
            imgsz=image_size,
            device=detector.device,
        )

    widgets: Dict[int, List[DetectedWidget]] = {}
    for page_ix, result in enumerate(results):
        if isinstance(result, list):
            result = result[0]
        if result is None or result.boxes is None or len(result.boxes) == 0:
            continue

        boxes = result.boxes
        page_widgets: List[DetectedWidget] = []
        for i in range(len(boxes)):
            xywhn = boxes.xywhn[i]
            x, y, w, h = [float(v) for v in xywhn.tolist()]
            cls_id = int(boxes.cls[i].item())
            score = float(boxes.conf[i].item()) if boxes.conf is not None else 1.0
            widget_type = detector.id_to_cls.get(cls_id, "TextBox")

            page_widgets.append(
                DetectedWidget(
                    widget_type=widget_type,
                    bounding_box=bounding_box_cls.from_yolo(cx=x, cy=y, w=w, h=h),
                    page_idx=page_ix,
                    confidence=score,
                )
            )

        widgets[page_ix] = _sort_detected_widgets(page_widgets)
        if progress_callback and not detector.fast:
            try:
                progress_callback(page_ix + 1, total_pages)
            except Exception:
                pass

    return widgets


def _page_sizes(pdf_path: Path) -> Dict[int, tuple[float, float]]:
    """
    Read page dimensions from the PDF for bbox conversion.
    """
    reader = PdfReader(str(pdf_path))
    sizes: Dict[int, tuple[float, float]] = {}
    for idx, page in enumerate(reader.pages):
        box = page.cropbox if page.cropbox is not None else page.mediabox
        sizes[idx] = (float(box.width), float(box.height))
    return sizes


def _bbox_to_rect(
    bounding_box: Any,
    page_width: float,
    page_height: float,
) -> List[float]:
    """
    Convert a normalized (0..1) bounding box into originTop PDF points.
    """
    x0 = max(0.0, min(1.0, float(bounding_box.x0))) * page_width
    x1 = max(0.0, min(1.0, float(bounding_box.x1))) * page_width
    y0 = max(0.0, min(1.0, float(bounding_box.y0))) * page_height
    y1 = max(0.0, min(1.0, float(bounding_box.y1))) * page_height
    return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]


def _field_type(widget_type: str, *, use_signature_fields: bool) -> str:
    """
    Normalize CommonForms widget types into the field schema.
    """
    if widget_type == "TextBox":
        return "text"
    if widget_type == "ChoiceButton":
        return "checkbox"
    if widget_type == "Signature":
        return "signature" if use_signature_fields else "text"
    return "text"


def _build_fields(
    widgets_by_page: Dict[int, List[DetectedWidget]],
    *,
    page_sizes: Dict[int, tuple[float, float]],
    model: str,
    use_signature_fields: bool,
) -> List[Dict[str, Any]]:
    """
    Build field dicts from detected widgets and page sizes.
    """
    fields: List[Dict[str, Any]] = []

    for page_idx in sorted(widgets_by_page.keys()):
        widgets = widgets_by_page.get(page_idx, [])
        if not widgets:
            continue
        page_width, page_height = page_sizes.get(page_idx, (0.0, 0.0))
        page_number = page_idx + 1

        for idx, widget in enumerate(widgets, start=1):
            rect = _bbox_to_rect(widget.bounding_box, page_width, page_height)
            confidence = float(widget.confidence)
            field_type = _field_type(widget.widget_type, use_signature_fields=use_signature_fields)
            fields.append(
                {
                    "name": f"commonforms_{field_type}_p{page_number}_{idx}",
                    "type": field_type,
                    "page": page_number,
                    "rect": rect,
                    "confidence": confidence,
                    "category": _category_for_confidence(confidence),
                    "source": "commonforms",
                    "model": model,
                    "candidateId": f"commonforms_{page_number}_{idx}",
                }
            )

    return fields


def detect_commonforms_fields(
    pdf_path: Path,
    *,
    output_pdf: Path | None = None,
    model: str = DEFAULT_MODEL,
    confidence: float = DEFAULT_CONFIDENCE,
    image_size: int = DEFAULT_IMAGE_SIZE,
    device: str = DEFAULT_DEVICE,
    fast: bool = DEFAULT_FAST,
    multiline: bool = DEFAULT_MULTILINE,
    keep_existing_fields: bool = False,
    use_signature_fields: bool = False,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Dict[str, Any]:
    """
    Run CommonForms detection and return the standardized field payload.
    """
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    (
        FFDetrDetector,
        FFDNetDetector,
        render_pdf,
        BoundingBox,
        EncryptedPdfError,
    ) = _import_commonforms()

    model_label, resolved_model = _resolve_commonforms_model(model)
    model_upper = model_label.upper()

    try:
        pages = render_pdf(str(pdf_path))
    except EncryptedPdfError as exc:
        raise RuntimeError("CommonForms cannot open encrypted PDFs.") from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise RuntimeError("CommonForms failed to render the PDF.") from exc

    if "FFDNET" in model_upper:
        detector = FFDNetDetector(resolved_model, device=device, fast=fast)
        widgets_by_page = _detect_ffdnet(
            detector,
            pages,
            confidence=confidence,
            image_size=image_size,
            bounding_box_cls=BoundingBox,
            progress_callback=progress_callback,
        )
    elif "FFDETR" in model_upper:
        detector = FFDetrDetector(resolved_model, device=device)
        widgets_by_page = _detect_ffdetr(
            detector,
            pages,
            confidence=confidence,
            batch_size=DEFAULT_BATCH_SIZE,
            bounding_box_cls=BoundingBox,
            progress_callback=progress_callback,
        )
    else:
        raise ValueError(
            "Unsupported CommonForms model. Set COMMONFORMS_MODEL to FFDNet-L/FFDNet-S/FFDetr "
            f"(current: {model_label}) and point COMMONFORMS_MODEL_GCS_URI at matching weights if needed."
        )

    page_sizes = _page_sizes(pdf_path)
    fields = _build_fields(
        widgets_by_page,
        page_sizes=page_sizes,
        model=model_label,
        use_signature_fields=use_signature_fields,
    )
    if output_pdf is not None:
        template = {
            "fields": fields,
            "coordinateSystem": "originTop",
            "sourcePdf": pdf_path.name,
        }
        inject_fields_from_template(pdf_path, template, output_pdf)

    return {
        "fields": fields,
        "coordinateSystem": "originTop",
        "meta": {
            "pipeline": "commonforms",
            "model": model_label,
            "confidence": confidence,
            "imageSize": image_size,
            "device": device,
            "fast": fast,
            "multiline": multiline,
            "keepExistingFields": keep_existing_fields,
            "useSignatureFields": use_signature_fields,
        },
    }


def _resolve_output_root(output: Path | None, output_dir: Path | None) -> Path:
    """
    Pick an output root for JSON/overlay artifacts.
    """
    if output_dir is not None:
        return output_dir
    if output is not None:
        if output.suffix.lower() == ".json":
            logger.info("Output path treated as root; artifacts will be temp-prefixed.")
            return output.parent
        return output
    return Path("backend/fieldDetecting/outputArtifacts")


def main() -> None:
    """
    CLI entrypoint for CommonForms detection.
    """
    parser = argparse.ArgumentParser(
        description="Run CommonForms detection and emit JSON artifacts."
    )
    parser.add_argument("pdf", type=Path, help="Path to input PDF")
    parser.add_argument(
        "--output",
        type=Path,
        help="Directory or file path used to locate the output root (artifacts are temp-prefixed).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Root directory for json/ and overlays/ (overrides --output).",
    )
    parser.add_argument(
        "--output-pdf",
        type=Path,
        help="Optional path to write the fillable PDF generated by CommonForms.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="CommonForms model name or custom weights path (default: FFDNet-L).",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=DEFAULT_CONFIDENCE,
        help="Confidence threshold for detection (default: 0.3).",
    )
    parser.add_argument(
        "--image-size",
        type=int,
        default=DEFAULT_IMAGE_SIZE,
        help="Image size for inference (default: 1600).",
    )
    parser.add_argument(
        "--device",
        default=DEFAULT_DEVICE,
        help="Device for inference, e.g. cpu/cuda/0 (default: cpu).",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        default=DEFAULT_FAST,
        help="Use CPU ONNX weights for faster inference (lower accuracy).",
    )
    parser.add_argument(
        "--multiline",
        action="store_true",
        default=DEFAULT_MULTILINE,
        help="Emit multiline text fields.",
    )
    parser.add_argument(
        "--keep-existing-fields",
        action="store_true",
        default=False,
        help="Keep existing form fields on the PDF.",
    )
    parser.add_argument(
        "--use-signature-fields",
        action="store_true",
        default=False,
        help="Emit signature widgets instead of text fields for signatures.",
    )
    args = parser.parse_args()

    result = detect_commonforms_fields(
        args.pdf,
        output_pdf=args.output_pdf,
        model=args.model,
        confidence=args.confidence,
        image_size=args.image_size,
        device=args.device,
        fast=args.fast,
        multiline=args.multiline,
        keep_existing_fields=args.keep_existing_fields,
        use_signature_fields=args.use_signature_fields,
    )

    output_root = _resolve_output_root(args.output, args.output_dir)
    layout = ensure_output_layout(output_root)
    prefix = temp_prefix_from_pdf(args.pdf)
    output_path = layout.json_dir / f"{prefix}_commonforms_fields.json"
    output_path.write_text(json.dumps(result, indent=2))
    logger.info("Wrote CommonForms fields to %s", output_path)


if __name__ == "__main__":
    main()
