from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, TypeVar

from .config import get_logger

logger = get_logger(__name__)

T = TypeVar("T")
U = TypeVar("U")


def _int_from_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning("Invalid %s=%s; falling back to %s", name, raw, default)
        return default


def resolve_workers(stage: str, *, default: int, use_global: bool = True) -> int:
    """
    Resolve thread counts with a stage override and global fallback.

    Priority:
    1) SANDBOX_{STAGE}_WORKERS
    2) SANDBOX_WORKERS
    3) provided default
    """
    stage_key = f"SANDBOX_{stage.upper()}_WORKERS"
    stage_value = os.getenv(stage_key)
    if stage_value is not None:
        return _int_from_env(stage_key, default)
    if use_global:
        return _int_from_env("SANDBOX_WORKERS", default)
    return default


def run_threaded_map(
    items: List[T],
    worker: Callable[[T], U],
    *,
    max_workers: int,
    label: str,
) -> List[U]:
    """
    Run a worker over a list of items while preserving input order in results.

    This uses a bounded ThreadPool so long-running tasks do not spawn unbounded threads.
    The returned list mirrors the input ordering to keep downstream output deterministic.
    Runtime: O(n) task dispatch plus the worker cost; order preservation is O(n) via index mapping.
    """
    if max_workers <= 1 or len(items) <= 1:
        return [worker(item) for item in items]

    logger.info("Running %s tasks in parallel (workers=%s, items=%s)", label, max_workers, len(items))
    # We preallocate a list indexed by input position to keep deterministic ordering.
    results: List[U] = [None] * len(items)  # type: ignore[list-item]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(worker, item): idx for idx, item in enumerate(items)
        }
        for future in as_completed(future_map):
            idx = future_map[future]
            results[idx] = future.result()
    return results
