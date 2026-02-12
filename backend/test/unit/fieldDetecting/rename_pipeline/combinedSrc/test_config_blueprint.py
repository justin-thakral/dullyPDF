import importlib
import logging
import uuid

import pytest


CONFIG_MODULE_PATH = "backend.fieldDetecting.rename_pipeline.combinedSrc.config"
LOGGING_MODULE_PATH = "backend.logging_config"


def _reload_config(
    monkeypatch: pytest.MonkeyPatch,
    *,
    debug_gate: bool,
    sandbox_debug: str = "true",
    log_dir: str | None = None,
):
    monkeypatch.setattr(
        "backend.fieldDetecting.rename_pipeline.debug_flags.debug_enabled",
        lambda: debug_gate,
    )
    monkeypatch.setenv("SANDBOX_DEBUG", sandbox_debug)
    if log_dir is None:
        monkeypatch.delenv("SANDBOX_LOG_DIR", raising=False)
    else:
        monkeypatch.setenv("SANDBOX_LOG_DIR", log_dir)
    # Reload logging_config first (canonical source), then config (re-exports).
    log_mod = importlib.import_module(LOGGING_MODULE_PATH)
    importlib.reload(log_mod)
    cfg = importlib.import_module(CONFIG_MODULE_PATH)
    return importlib.reload(cfg), log_mod


def test_get_logger_initializes_shared_handlers_once(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg, log_mod = _reload_config(monkeypatch, debug_gate=False)

    logger_name = f"sandbox.test.{uuid.uuid4()}"
    logger = cfg.get_logger(logger_name)
    first_handlers = list(logger.handlers)
    again = cfg.get_logger(logger_name)

    assert first_handlers == list(again.handlers)
    assert len(first_handlers) == len(log_mod._SHARED_HANDLERS)
    assert logger.level == logging.INFO


def test_get_logger_adds_file_handler_when_log_dir_set(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg, _log_mod = _reload_config(monkeypatch, debug_gate=False, log_dir=str(tmp_path))

    logger = cfg.get_logger(f"sandbox.test.file.{uuid.uuid4()}")
    file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]

    assert file_handlers
    assert tmp_path.exists()


def test_get_logger_uses_debug_level_when_debug_mode_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg, _log_mod = _reload_config(monkeypatch, debug_gate=True, sandbox_debug="true")

    logger = cfg.get_logger(f"sandbox.test.debug.{uuid.uuid4()}")

    assert logger.level == logging.DEBUG


def test_get_logger_does_not_duplicate_handlers_across_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg, _log_mod = _reload_config(monkeypatch, debug_gate=False)
    logger_name = f"sandbox.test.nodup.{uuid.uuid4()}"

    logger = cfg.get_logger(logger_name)
    count_before = len(logger.handlers)
    cfg.get_logger(logger_name)
    count_after = len(logger.handlers)

    assert count_before == count_after


# ---------------------------------------------------------------------------
# Edge-case tests added below
# ---------------------------------------------------------------------------


def test_log_openai_response_flag_exists_and_is_boolean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LOG_OPENAI_RESPONSE must be a boolean value after module load.
    Other modules rely on it as a truthy/falsy gate.  This verifies the
    flag is present and has the correct type under both gate states."""
    # With the debug gate off, the flag should be False.
    cfg_off, _log_mod = _reload_config(monkeypatch, debug_gate=False)
    assert isinstance(cfg_off.LOG_OPENAI_RESPONSE, bool)
    assert cfg_off.LOG_OPENAI_RESPONSE is False

    # With the debug gate on but the env var set to 'false', still False.
    monkeypatch.setenv("SANDBOX_LOG_OPENAI_RESPONSE", "false")
    cfg_gate_on, _log_mod = _reload_config(monkeypatch, debug_gate=True)
    assert isinstance(cfg_gate_on.LOG_OPENAI_RESPONSE, bool)
    assert cfg_gate_on.LOG_OPENAI_RESPONSE is False

    # With the debug gate on AND the env var set to 'true', it should be True.
    monkeypatch.setenv("SANDBOX_LOG_OPENAI_RESPONSE", "true")
    cfg_true, _log_mod = _reload_config(monkeypatch, debug_gate=True)
    assert isinstance(cfg_true.LOG_OPENAI_RESPONSE, bool)
    assert cfg_true.LOG_OPENAI_RESPONSE is True
