"""Regression checks for detector queue sync pruning."""

from __future__ import annotations

from pathlib import Path


SCRIPT_PATH = Path("scripts/sync-detector-task-queues.sh")


def _script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def test_sync_detector_task_queues_can_prune_stale_detector_queues() -> None:
    text = _script_text()
    assert 'PRUNE_STALE_QUEUES_ENABLED="${DETECTOR_TASKS_PRUNE_STALE_QUEUES:-false}"' in text
    assert 'delete_queue_if_present()' in text
    assert 'commonforms-detect-heavy' in text
    assert 'not part of the active detector routing plan' in text
    assert "gcloud tasks queues delete" in text
