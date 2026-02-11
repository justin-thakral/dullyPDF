"""Unit tests for backend.scripts.verify_session_owner."""

from __future__ import annotations

from fastapi import HTTPException

from backend.scripts import verify_session_owner


def test_expect_forbidden_passes_on_http_403() -> None:
    def _forbidden() -> None:
        raise HTTPException(status_code=403, detail="denied")

    passed, message = verify_session_owner._expect_forbidden("case", _forbidden)

    assert passed is True
    assert message == "case: blocked as expected"


def test_expect_forbidden_fails_on_non_403_status() -> None:
    def _unauthorized() -> None:
        raise HTTPException(status_code=401, detail="unauthorized")

    passed, message = verify_session_owner._expect_forbidden("case", _unauthorized)

    assert passed is False
    assert message == "case: expected 403, got 401"


def test_expect_forbidden_fails_when_no_exception_is_raised() -> None:
    passed, message = verify_session_owner._expect_forbidden("case", lambda: None)

    assert passed is False
    assert message == "case: expected 403, but no exception was raised"


def test_expect_forbidden_reports_unexpected_exception_branch() -> None:
    def _unexpected() -> None:
        raise RuntimeError("boom")

    passed, message = verify_session_owner._expect_forbidden("case", _unexpected)

    assert passed is False
    assert message == "case: unexpected exception RuntimeError"


def test_expect_allowed_passes_when_no_exception_is_raised() -> None:
    passed, message = verify_session_owner._expect_allowed("case", lambda: None)

    assert passed is True
    assert message == "case: allowed as expected"


def test_expect_allowed_reports_unexpected_exception_branch() -> None:
    def _unexpected() -> None:
        raise RuntimeError("boom")

    passed, message = verify_session_owner._expect_allowed("case", _unexpected)

    assert passed is False
    assert message == "case: unexpected exception RuntimeError"


def test_main_returns_zero_when_all_checks_pass(monkeypatch, capsys) -> None:
    called_labels = []

    def _fake_forbidden(label: str, _func):
        called_labels.append(("forbidden", label))
        return True, f"{label}: blocked as expected"

    def _fake_allowed(label: str, _func):
        called_labels.append(("allowed", label))
        return True, f"{label}: allowed as expected"

    monkeypatch.setattr(verify_session_owner, "_expect_forbidden", _fake_forbidden)
    monkeypatch.setattr(verify_session_owner, "_expect_allowed", _fake_allowed)

    exit_code = verify_session_owner.main()
    output_lines = capsys.readouterr().out.strip().splitlines()

    assert exit_code == 0
    assert called_labels == [
        ("forbidden", "missing user_id"),
        ("forbidden", "legacy session with no user_id"),
        ("forbidden", "wrong owner"),
        ("allowed", "matching owner"),
    ]
    assert output_lines == [
        "missing user_id: blocked as expected",
        "legacy session with no user_id: blocked as expected",
        "wrong owner: blocked as expected",
        "matching owner: allowed as expected",
    ]


def test_main_returns_one_when_any_check_fails(monkeypatch, capsys) -> None:
    def _fake_forbidden(label: str, _func):
        return True, f"{label}: blocked as expected"

    def _fake_allowed(label: str, _func):
        return False, f"{label}: unexpected exception RuntimeError"

    monkeypatch.setattr(verify_session_owner, "_expect_forbidden", _fake_forbidden)
    monkeypatch.setattr(verify_session_owner, "_expect_allowed", _fake_allowed)

    exit_code = verify_session_owner.main()
    output_lines = capsys.readouterr().out.strip().splitlines()

    assert exit_code == 1
    assert output_lines == [
        "missing user_id: blocked as expected",
        "legacy session with no user_id: blocked as expected",
        "wrong owner: blocked as expected",
        "matching owner: unexpected exception RuntimeError",
    ]


# ---------------------------------------------------------------------------
# Edge-case tests added for additional branch coverage
# ---------------------------------------------------------------------------


def test_expect_allowed_returns_false_when_http_exception_raised() -> None:
    """When _expect_allowed's callable raises an HTTPException (or any
    exception), it should return (False, ...) because the callable was
    expected to succeed without raising."""

    def _raises_http() -> None:
        raise HTTPException(status_code=403, detail="forbidden")

    passed, message = verify_session_owner._expect_allowed("http-case", _raises_http)

    assert passed is False
    assert "unexpected exception HTTPException" in message


def test_main_partial_failure_runs_all_checks(monkeypatch, capsys) -> None:
    """Even when the first check fails, all subsequent checks must still run.
    The main() function should not short-circuit on the first failure."""
    call_count = {"forbidden": 0, "allowed": 0}

    def _fake_forbidden(label: str, _func):
        call_count["forbidden"] += 1
        # Make the first _expect_forbidden call fail
        if call_count["forbidden"] == 1:
            return False, f"{label}: FAILED"
        return True, f"{label}: blocked as expected"

    def _fake_allowed(label: str, _func):
        call_count["allowed"] += 1
        return True, f"{label}: allowed as expected"

    monkeypatch.setattr(verify_session_owner, "_expect_forbidden", _fake_forbidden)
    monkeypatch.setattr(verify_session_owner, "_expect_allowed", _fake_allowed)

    exit_code = verify_session_owner.main()
    output_lines = capsys.readouterr().out.strip().splitlines()

    # All 4 checks should have been executed despite the first failure
    assert call_count["forbidden"] == 3
    assert call_count["allowed"] == 1
    assert len(output_lines) == 4
    # The overall result should be failure because at least one check failed
    assert exit_code == 1
