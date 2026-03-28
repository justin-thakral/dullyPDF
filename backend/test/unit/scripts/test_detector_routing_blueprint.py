"""Regression checks for detector routing helper semantics."""

from __future__ import annotations

from pathlib import Path


SCRIPT_PATH = Path("scripts/_detector_routing.sh")


def _script_text() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def test_detector_routing_can_collapse_heavy_gpu_onto_light_gpu_for_single_gpu_mode() -> None:
    text = _script_text()
    assert "detector_share_single_gpu_service()" in text
    assert 'if detector_share_single_gpu_service "$DETECTOR_ROUTING_MODE_RESOLVED"; then' in text
    assert 'DETECTOR_SERVICE_NAME_HEAVY_ACTIVE="$DETECTOR_SERVICE_NAME_LIGHT_ACTIVE"' in text
    assert 'DETECTOR_SERVICE_URL_HEAVY_ACTIVE="$DETECTOR_SERVICE_URL_LIGHT_ACTIVE"' in text
    assert 'DETECTOR_TASKS_AUDIENCE_HEAVY_ACTIVE="$DETECTOR_TASKS_AUDIENCE_LIGHT_ACTIVE"' in text
