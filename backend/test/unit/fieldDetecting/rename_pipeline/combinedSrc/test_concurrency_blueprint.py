import time

import pytest

from backend.fieldDetecting.rename_pipeline.combinedSrc import concurrency


def test_int_from_env_parses_bounds_and_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANDBOX_TEST_WORKERS", "4")
    assert concurrency._int_from_env("SANDBOX_TEST_WORKERS", 2) == 4

    monkeypatch.setenv("SANDBOX_TEST_WORKERS", "0")
    assert concurrency._int_from_env("SANDBOX_TEST_WORKERS", 2) == 1

    monkeypatch.setenv("SANDBOX_TEST_WORKERS", "bad")
    assert concurrency._int_from_env("SANDBOX_TEST_WORKERS", 2) == 2


def test_resolve_workers_uses_stage_then_global_then_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SANDBOX_RENDER_WORKERS", raising=False)
    monkeypatch.setenv("SANDBOX_WORKERS", "3")
    assert concurrency.resolve_workers("render", default=5) == 3

    monkeypatch.setenv("SANDBOX_RENDER_WORKERS", "7")
    assert concurrency.resolve_workers("render", default=5) == 7

    monkeypatch.delenv("SANDBOX_WORKERS", raising=False)
    monkeypatch.delenv("SANDBOX_RENDER_WORKERS", raising=False)
    assert concurrency.resolve_workers("render", default=5, use_global=False) == 5


def test_run_threaded_map_preserves_input_order() -> None:
    items = [3, 1, 2]

    def worker(item: int) -> int:
        # Invert completion order so this would fail without index-based result placement.
        time.sleep(0.01 * (4 - item))
        return item * 10

    results = concurrency.run_threaded_map(items, worker, max_workers=3, label="test")
    assert results == [30, 10, 20]


def test_run_threaded_map_short_circuits_without_pool(mocker) -> None:
    pool = mocker.patch("backend.fieldDetecting.rename_pipeline.combinedSrc.concurrency.ThreadPoolExecutor")

    assert concurrency.run_threaded_map([1], lambda x: x + 1, max_workers=4, label="single") == [2]
    assert concurrency.run_threaded_map([1, 2], lambda x: x + 1, max_workers=1, label="serial") == [2, 3]
    pool.assert_not_called()


# ---------------------------------------------------------------------------
# Edge-case tests added below
# ---------------------------------------------------------------------------


def test_run_threaded_map_with_empty_list_returns_empty() -> None:
    """An empty items list should return an empty result list immediately,
    regardless of max_workers.  This exercises the short-circuit path where
    len(items) <= 1 combined with items being empty."""

    def _should_not_be_called(item):
        raise AssertionError("Worker must not be invoked for an empty list")

    result = concurrency.run_threaded_map(
        [], _should_not_be_called, max_workers=8, label="empty"
    )
    assert result == []


def test_run_threaded_map_propagates_worker_exception() -> None:
    """When a worker function raises, run_threaded_map should propagate the
    exception (via future.result()) rather than silently returning None or a
    partial result list.  This verifies the error-propagation contract."""

    def _failing_worker(item: int) -> int:
        if item == 2:
            raise ValueError("boom on item 2")
        return item * 10

    with pytest.raises(ValueError, match="boom on item 2"):
        concurrency.run_threaded_map(
            [1, 2, 3], _failing_worker, max_workers=3, label="fail"
        )
