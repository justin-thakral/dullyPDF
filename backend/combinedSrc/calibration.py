from typing import Dict, List

from .config import get_logger

logger = get_logger(__name__)


def _median(values: List[float]) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    mid = len(sorted_vals) // 2
    if len(sorted_vals) % 2 == 1:
        return sorted_vals[mid]
    return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0


def compute_label_height_calibration(labels_by_page: Dict[int, List[Dict]]) -> Dict[int, Dict]:
    """
    Compute median label height per page to calibrate field heights.

    Heuristic:
    - Use label heights in a reasonable range to avoid giant titles.
    - Clamp resulting target height in rect_builder.
    """
    calibration: Dict[int, Dict] = {}
    for page_idx, labels in labels_by_page.items():
        heights: List[float] = []
        for label in labels:
            bbox = label.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            h = float(bbox[3]) - float(bbox[1])
            if 6 <= h <= 36:  # ignore very small noise and big headers
                heights.append(h)
        median_h = _median(heights)
        calibration[page_idx] = {
            "medianLabelHeight": median_h if median_h > 0 else 12.0,
        }
        logger.debug(
            "Page %s calibration -> median label height: %.2f pts (samples=%s)",
            page_idx,
            calibration[page_idx]["medianLabelHeight"],
            len(heights),
        )
    return calibration
