import logging
import os
from pathlib import Path
from typing import Dict

from ..debug_flags import debug_enabled
from ..env_loader import bootstrap_env

bootstrap_env()

# Toggle verbose diagnostics across the sandbox modules.
_DEBUG_GATE = debug_enabled()
DEBUG_MODE = _DEBUG_GATE and os.getenv("SANDBOX_DEBUG", "true").lower() == "true"
LOG_OPENAI_RESPONSE = _DEBUG_GATE and os.getenv("SANDBOX_LOG_OPENAI_RESPONSE", "false").lower() == "true"
LOG_DIR = os.getenv("SANDBOX_LOG_DIR")
LOG_FILE = os.getenv("SANDBOX_LOG_FILE", "sandbox.log")

# Rendering defaults.
DEFAULT_DPI = int(os.getenv("SANDBOX_DPI", "500"))

# Confidence thresholds shared between detection and resolver.
DEFAULT_THRESHOLDS: Dict[str, float] = {
    "high": 0.995,
    "medium": 0.7,
    "min": 0.5,
}

def get_logger(name: str) -> logging.Logger:
    """Return a configured logger that honors the debug gate and SANDBOX_DEBUG."""
    logger = logging.getLogger(name)
    level = logging.DEBUG if DEBUG_MODE else logging.INFO
    if not logger.handlers:
        if LOG_DIR:
            log_dir = Path(LOG_DIR)
        else:
            log_dir = Path(__file__).resolve().parents[2] / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / LOG_FILE
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter(
                fmt="SANDBOX %(levelname)s %(name)s - %(message)s"
            )
        )
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                fmt="SANDBOX %(levelname)s %(name)s - %(message)s"
            )
        )
        logger.addHandler(file_handler)
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger
