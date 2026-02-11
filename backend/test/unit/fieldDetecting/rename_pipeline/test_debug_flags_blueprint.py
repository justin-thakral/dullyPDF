import importlib
import sys
from types import ModuleType

import pytest


_MODULE_PATH = "backend.fieldDetecting.rename_pipeline.debug_flags"


def _reload_debug_flags(
    monkeypatch: pytest.MonkeyPatch,
    *,
    argv: list[str],
    env: dict[str, str | None] | None = None,
) -> ModuleType:
    env = env or {}
    monkeypatch.setattr(sys, "argv", list(argv))
    for key in ("ENV", "SANDBOX_DEBUG_FORCE", "SANDBOX_DEBUG_PASSWORD", "debugPassword"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)

    module = importlib.import_module(_MODULE_PATH)
    return importlib.reload(module)


def test_debug_flag_detection_and_argv_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _reload_debug_flags(
        monkeypatch,
        argv=["prog", "--debug", "run", "--debug=true"],
        env={"SANDBOX_DEBUG_PASSWORD": "pw"},
    )

    assert module.debug_flag_present() is True
    assert sys.argv == ["prog", "run"]


def test_debug_password_resolution_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _reload_debug_flags(
        monkeypatch,
        argv=["prog"],
        env={
            "SANDBOX_DEBUG_PASSWORD": "new-secret",
            "debugPassword": "legacy-secret",
        },
    )

    assert module.get_debug_password() == "new-secret"
    assert module.debug_password_valid() is True


def test_debug_enabled_requires_password_when_forced(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _reload_debug_flags(
        monkeypatch,
        argv=["prog"],
        env={
            "SANDBOX_DEBUG_FORCE": "true",
            "SANDBOX_DEBUG_PASSWORD": "",
            "debugPassword": "",
        },
    )

    assert module.debug_enabled() is False


def test_debug_enabled_force_with_password(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _reload_debug_flags(
        monkeypatch,
        argv=["prog"],
        env={
            "SANDBOX_DEBUG_FORCE": "1",
            "SANDBOX_DEBUG_PASSWORD": "pw",
        },
    )

    assert module.debug_enabled() is True


def test_debug_disabled_in_prod_even_when_flag_present(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _reload_debug_flags(
        monkeypatch,
        argv=["prog", "--debug"],
        env={
            "ENV": "prod",
            "SANDBOX_DEBUG_FORCE": "1",
            "SANDBOX_DEBUG_PASSWORD": "pw",
        },
    )

    assert module.debug_flag_present() is True
    assert module.debug_enabled() is False
