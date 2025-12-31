from typing import Any, Dict, List

from ..combinedSrc.config import get_logger
from ..combinedSrc.pipeline_common import resolve_pipeline

logger = get_logger(__name__)


def resolve_scanned_pipeline(
    candidates: List[Dict[str, Any]],
    meta: Dict[str, Any],
    labels_by_page: Dict[int, List[Dict[str, Any]]],
    calibrations: Dict[int, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Resolve fields for scanned PDFs (image-first pipeline).
    """
    return resolve_pipeline(candidates, meta, labels_by_page, calibrations)
