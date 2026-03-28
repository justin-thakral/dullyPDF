"""Regression checks for detector benchmark safety guards."""

from __future__ import annotations

from pathlib import Path


SCRIPT_PATH = Path("scripts/benchmark-detector-cpu-gpu.sh")


def test_benchmark_detector_requires_explicit_prod_opt_in_and_private_default() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert 'REGION="${REGION:-${DETECTOR_TASKS_LOCATION:-us-east4}}"' in text
    assert 'BENCH_ALLOW_UNAUTHENTICATED="${BENCH_ALLOW_UNAUTHENTICATED:-false}"' in text
    assert 'BENCH_ALLOW_PROD_PROJECT="${BENCH_ALLOW_PROD_PROJECT:-false}"' in text
    assert 'Refusing to run detector benchmark against prod without BENCH_ALLOW_PROD_PROJECT=true.' in text
    assert 'DETECTOR_DEPLOY_ALLOW_UNAUTHENTICATED="$allow_unauthenticated"' in text
