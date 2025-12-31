from __future__ import annotations

import argparse
import json
import os
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

from pypdf import PdfReader

from ..sandbox.combinedSrc.config import get_logger
from ..sandbox.combinedSrc.form_filler import inject_fields_from_template
from ..sandbox.combinedSrc.output_layout import ensure_output_layout, temp_prefix_from_pdf

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
    widget_type: str
    bounding_box: Any
    page_idx: int
    confidence: float


def _import_commonforms():
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


def _category_for_confidence(confidence: float) -> str:
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
    for idx in range(0, len(items), size):
        yield items[idx : idx + size]


def _sort_detected_widgets(widgets: List[DetectedWidget]) -> List[DetectedWidget]:
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
) -> Dict[int, List[DetectedWidget]]:
    results: List[Any] = []
    images = [p.image for p in pages]
    for batch in _batch(images, size=batch_size):
        predictions = detector.model.predict(batch, threshold=confidence)
        if len(pages) == 1 or batch_size == 1:
            predictions = [predictions]
        results.extend(predictions)

    widgets: Dict[int, List[DetectedWidget]] = {}
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

    return widgets


def _detect_ffdnet(
    detector: Any,
    pages: List[Any],
    *,
    confidence: float,
    image_size: int,
    bounding_box_cls: Any,
) -> Dict[int, List[DetectedWidget]]:
    if detector.fast:
        results = [
            detector.model.predict(
                p.image,
                iou=1,
                conf=confidence,
                augment=False,
                imgsz=1216,
                device=detector.device,
            )
            for p in pages
        ]
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

    return widgets


def _page_sizes(pdf_path: Path) -> Dict[int, tuple[float, float]]:
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
    x0 = max(0.0, min(1.0, float(bounding_box.x0))) * page_width
    x1 = max(0.0, min(1.0, float(bounding_box.x1))) * page_width
    y0 = max(0.0, min(1.0, float(bounding_box.y0))) * page_height
    y1 = max(0.0, min(1.0, float(bounding_box.y1))) * page_height
    return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]


def _field_type(widget_type: str, *, use_signature_fields: bool) -> str:
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
) -> Dict[str, Any]:
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    (
        FFDetrDetector,
        FFDNetDetector,
        render_pdf,
        BoundingBox,
        EncryptedPdfError,
    ) = _import_commonforms()

    try:
        pages = render_pdf(str(pdf_path))
    except EncryptedPdfError as exc:
        raise RuntimeError("CommonForms cannot open encrypted PDFs.") from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise RuntimeError("CommonForms failed to render the PDF.") from exc

    if "FFDNET" in model.upper():
        detector = FFDNetDetector(model, device=device, fast=fast)
        widgets_by_page = _detect_ffdnet(
            detector,
            pages,
            confidence=confidence,
            image_size=image_size,
            bounding_box_cls=BoundingBox,
        )
    else:
        detector = FFDetrDetector(model, device=device)
        widgets_by_page = _detect_ffdetr(
            detector,
            pages,
            confidence=confidence,
            batch_size=DEFAULT_BATCH_SIZE,
            bounding_box_cls=BoundingBox,
        )

    page_sizes = _page_sizes(pdf_path)
    fields = _build_fields(
        widgets_by_page,
        page_sizes=page_sizes,
        model=model,
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
            "model": model,
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
    if output_dir is not None:
        return output_dir
    if output is not None:
        if output.suffix.lower() == ".json":
            logger.info("Output path treated as root; artifacts will be temp-prefixed.")
            return output.parent
        return output
    return Path("backend/fieldDetecting/outputArtifacts")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run CommonForms detection and emit sandbox JSON."
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
