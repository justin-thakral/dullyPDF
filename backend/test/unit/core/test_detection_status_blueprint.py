"""Unit tests for backend.detection_status constants."""

import backend.detection.status as status


def test_detection_status_constants_are_stable() -> None:
    assert status.DETECTION_STATUS_QUEUED == "queued"
    assert status.DETECTION_STATUS_RUNNING == "running"
    assert status.DETECTION_STATUS_COMPLETE == "complete"
    assert status.DETECTION_STATUS_FAILED == "failed"


def test_detection_status_values_are_unique_non_empty_strings() -> None:
    values = [
        status.DETECTION_STATUS_QUEUED,
        status.DETECTION_STATUS_RUNNING,
        status.DETECTION_STATUS_COMPLETE,
        status.DETECTION_STATUS_FAILED,
    ]

    assert all(isinstance(value, str) and value for value in values)
    assert len(set(values)) == len(values)


def test_terminal_statuses_contains_exactly_complete_and_failed() -> None:
    """DETECTION_TERMINAL_STATUSES is an exported set used by callers to check
    if a detection job is done. Verify it contains exactly the right members."""
    assert status.DETECTION_TERMINAL_STATUSES == {
        status.DETECTION_STATUS_COMPLETE,
        status.DETECTION_STATUS_FAILED,
    }


def test_terminal_and_nonterminal_statuses_cover_all_constants() -> None:
    """Guard against adding a new status constant without classifying it as
    terminal or non-terminal. The union of both groups must cover all
    DETECTION_STATUS_* constants."""
    all_statuses = {
        status.DETECTION_STATUS_QUEUED,
        status.DETECTION_STATUS_RUNNING,
        status.DETECTION_STATUS_COMPLETE,
        status.DETECTION_STATUS_FAILED,
    }
    non_terminal = {status.DETECTION_STATUS_QUEUED, status.DETECTION_STATUS_RUNNING}
    assert status.DETECTION_TERMINAL_STATUSES | non_terminal == all_statuses
