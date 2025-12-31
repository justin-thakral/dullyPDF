from __future__ import annotations

from bisect import bisect_left, bisect_right
from typing import Dict, Iterable, List, Tuple

from .config import get_logger

logger = get_logger(__name__)

try:
    from scipy.spatial import cKDTree  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    cKDTree = None


class LabelIndex:
    """
    Lightweight spatial index over label midpoints.

    Data structures:
    - `_points`: list of (mid_x, mid_y) tuples for each label.
    - `_by_y`: list of (mid_y, idx) pairs sorted by mid_y for fast vertical range scans.
    - Optional `cKDTree`: accelerates nearest-neighbor queries when SciPy is available.

    We use y-binning as the deterministic fallback because most label lookups are gated by
    vertical proximity (same row), and it avoids pulling in extra dependencies.
    """

    def __init__(self, labels: List[Dict]):
        self._labels: List[Dict] = []
        self._points: List[Tuple[float, float]] = []
        for label in labels or []:
            bbox = label.get("bbox") or []
            if len(bbox) != 4:
                continue
            x1, y1, x2, y2 = [float(v) for v in bbox]
            mid_x = (x1 + x2) / 2.0
            mid_y = (y1 + y2) / 2.0
            self._labels.append(label)
            self._points.append((mid_x, mid_y))

        self._by_y = sorted(
            ((pt[1], idx) for idx, pt in enumerate(self._points)),
            key=lambda item: item[0],
        )
        self._ys = [item[0] for item in self._by_y]

        if cKDTree is not None and self._points:
            self._tree = cKDTree(self._points)
            logger.debug("LabelIndex: using cKDTree for %s labels", len(self._points))
        else:
            self._tree = None
            logger.debug("LabelIndex: using y-sorted index for %s labels", len(self._points))

    def __len__(self) -> int:
        return len(self._labels)

    def _indices_by_y(self, mid_y: float, y_range: float) -> List[int]:
        if not self._ys:
            return []
        lo = bisect_left(self._ys, mid_y - y_range)
        hi = bisect_right(self._ys, mid_y + y_range)
        return [self._by_y[i][1] for i in range(lo, hi)]

    def iter_candidates(
        self,
        mid_x: float,
        mid_y: float,
        *,
        k: int = 18,
        y_range: float | None = None,
    ) -> Iterable[Dict]:
        """
        Yield candidate labels near a midpoint.

        Strategy:
        - When cKDTree is available, query the k-nearest labels around (mid_x, mid_y).
        - Otherwise use the y-range slice as a fast deterministic fallback.
        - Always apply y-range filtering when requested to keep row-level proximity.
        """
        indices: List[int] = []
        if self._tree is not None and self._points:
            k = max(1, min(int(k), len(self._points)))
            distances, idxs = self._tree.query((mid_x, mid_y), k=k)
            if k == 1:
                indices = [int(idxs)]
            else:
                indices = [int(i) for i in idxs if i is not None]
            if y_range is not None:
                indices = [
                    i
                    for i in indices
                    if abs(self._points[i][1] - mid_y) <= float(y_range)
                ]
        else:
            if y_range is not None:
                indices = self._indices_by_y(mid_y, float(y_range))
            else:
                indices = list(range(len(self._labels)))

        if y_range is not None and not indices:
            indices = self._indices_by_y(mid_y, float(y_range))

        for idx in indices:
            yield self._labels[idx]
