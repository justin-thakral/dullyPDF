"""Regression checks for stale Cloud Run and Cloud Tasks cleanup automation."""

from __future__ import annotations

from pathlib import Path


SCRIPT_PATH = Path("scripts/prune-stale-cloud-resources.sh")


def _script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def test_prune_stale_cloud_resources_prunes_duplicate_worker_regions_and_retired_detector_services() -> None:
    text = _script_text()
    assert 'PRUNE_REGION_CANDIDATES="${PRUNE_REGION_CANDIDATES:-us-east4,us-central1}"' in text
    assert 'prune_duplicate_regions_for_service' in text
    assert 'dullypdf-openai-rename-light' in text
    assert 'dullypdf-openai-remap-heavy' in text
    assert 'dullypdf-detector-light-bench-cpu' in text
    assert 'dullypdf-det-light-probe-cpu' in text
    assert 'gcloud run services delete "$service_name"' in text


def test_prune_stale_cloud_resources_delegates_queue_pruning_to_sync_script_and_cleans_other_regions() -> None:
    text = _script_text()
    assert 'DETECTOR_TASKS_PRUNE_STALE_QUEUES=true bash "${SCRIPT_DIR}/sync-detector-task-queues.sh" "$ENV_FILE"' in text
    assert 'commonforms-detect-light-cpu' in text
    assert 'detector queues should only exist in the configured task location' in text
    assert 'gcloud tasks queues delete "$queue_name"' in text
