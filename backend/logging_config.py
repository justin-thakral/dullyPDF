"""Centralized logging configuration for the backend.

Provides a shared ``get_logger`` factory and the ``DEBUG_MODE`` flag so that
every module can import logging without reaching into the fieldDetecting
pipeline internals.
"""

import logging
import os
from pathlib import Path
from typing import List

from backend.fieldDetecting.rename_pipeline.debug_flags import debug_enabled

_DEBUG_GATE = debug_enabled()
DEBUG_MODE = _DEBUG_GATE and os.getenv("SANDBOX_DEBUG", "true").lower() == "true"
LOG_OPENAI_RESPONSE = _DEBUG_GATE and os.getenv("SANDBOX_LOG_OPENAI_RESPONSE", "false").lower() == "true"
LOG_DIR = os.getenv("SANDBOX_LOG_DIR")
LOG_FILE = os.getenv("SANDBOX_LOG_FILE", "sandbox.log")

_LOG_FORMATTER = logging.Formatter(fmt="SANDBOX %(levelname)s %(name)s - %(message)s")
_HANDLERS_READY = False
_SHARED_HANDLERS: List[logging.Handler] = []


def _configure_handlers_once() -> None:
    """Configure shared handlers a single time."""
    global _HANDLERS_READY
    if _HANDLERS_READY:
        return

    handlers: List[logging.Handler] = []
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(_LOG_FORMATTER)
    handlers.append(stream_handler)

    log_dir_raw = (LOG_DIR or "").strip()
    if log_dir_raw:
        log_dir = Path(log_dir_raw)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / LOG_FILE
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(_LOG_FORMATTER)
        handlers.append(file_handler)

    _SHARED_HANDLERS[:] = handlers
    _HANDLERS_READY = True


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger that honors the debug gate and SANDBOX_DEBUG."""
    _configure_handlers_once()
    logger = logging.getLogger(name)
    level = logging.DEBUG if DEBUG_MODE else logging.INFO
    if not getattr(logger, "_sandbox_handlers_attached", False):
        for handler in _SHARED_HANDLERS:
            logger.addHandler(handler)
        setattr(logger, "_sandbox_handlers_attached", True)
    logger.setLevel(level)
    logger.propagate = False
    return logger
