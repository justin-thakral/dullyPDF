"""Unit tests for backend.env_utils."""

import pytest

from backend.env_utils import env_truthy, env_value, int_env


def test_env_value_returns_empty_string_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_ENV_VALUE", raising=False)
    assert env_value("TEST_ENV_VALUE") == ""


def test_env_value_trims_surrounding_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_ENV_VALUE", "  padded value  ")
    assert env_value("TEST_ENV_VALUE") == "padded value"


@pytest.mark.parametrize("raw_value", ["1", "true", "yes", "TRUE", "YeS"])
def test_env_truthy_accepts_common_truthy_values(
    monkeypatch: pytest.MonkeyPatch,
    raw_value: str,
) -> None:
    monkeypatch.setenv("TEST_ENV_TRUTHY", raw_value)
    assert env_truthy("TEST_ENV_TRUTHY") is True


@pytest.mark.parametrize("raw_value", ["", "0", "false", "no", "FALSE", "No"])
def test_env_truthy_rejects_non_truthy_values(
    monkeypatch: pytest.MonkeyPatch,
    raw_value: str,
) -> None:
    monkeypatch.setenv("TEST_ENV_TRUTHY", raw_value)
    assert env_truthy("TEST_ENV_TRUTHY") is False


def test_int_env_returns_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_INT_ENV", raising=False)
    assert int_env("TEST_INT_ENV", default=42) == 42


def test_int_env_parses_valid_integer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_INT_ENV", " 12 ")
    assert int_env("TEST_INT_ENV", default=42) == 12


def test_int_env_returns_default_for_invalid_integer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_INT_ENV", "12.5")
    assert int_env("TEST_INT_ENV", default=42) == 42


# --- Edge case tests ---


def test_int_env_returns_zero_not_default_for_zero_string(monkeypatch: pytest.MonkeyPatch) -> None:
    """int("0") is valid and should return 0, not fall through to the default."""
    monkeypatch.setenv("TEST_INT_ENV", "0")
    assert int_env("TEST_INT_ENV", default=42) == 0


def test_int_env_parses_negative_integer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Negative integers are valid and should parse correctly."""
    monkeypatch.setenv("TEST_INT_ENV", "-5")
    assert int_env("TEST_INT_ENV", default=42) == -5


def test_env_value_returns_empty_for_whitespace_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pure whitespace should strip to empty string."""
    monkeypatch.setenv("TEST_ENV_VALUE", "   ")
    assert env_value("TEST_ENV_VALUE") == ""


def test_env_truthy_returns_false_when_variable_is_completely_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the env var does not exist at all, env_truthy should return False.
    This exercises the os.getenv->None->(None or "")->""->not in truthy set path."""
    monkeypatch.delenv("TEST_ENV_TRUTHY_UNSET", raising=False)
    assert env_truthy("TEST_ENV_TRUTHY_UNSET") is False
