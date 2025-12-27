from typing import Any, Dict, List

from .config import DEFAULT_THRESHOLDS
from .heuristic_resolver import resolve_fields_heuristically


def resolve_pipeline(
    candidates: List[Dict[str, Any]],
    meta: Dict[str, Any],
    labels_by_page: Dict[int, List[Dict[str, Any]]],
    calibrations: Dict[int, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Shared resolver for both native and scanned pipelines.

    Data structures:
    - candidates: list of per-page candidate dicts (lines/boxes/checkboxes).
    - labels_by_page: page-indexed label lists from text/OCR extraction.
    - calibrations: per-page median label height for stable rect sizing.

    Keeping the resolver centralized ensures identical behavior across pipelines while
    routing decisions remain in the pipeline router.
    """
    meta = dict(meta)
    meta.setdefault("thresholds", DEFAULT_THRESHOLDS)
    meta.setdefault("calibrations", calibrations)
    result = resolve_fields_heuristically(candidates, meta, labels_by_page, calibrations)
    result["candidates"] = candidates
    return result
