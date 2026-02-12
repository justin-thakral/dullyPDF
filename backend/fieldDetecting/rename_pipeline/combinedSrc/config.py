"""
Rename pipeline configuration and logging setup.

Logging and the ``get_logger`` factory now live in ``backend.logging_config``.
This module re-exports them for backward compatibility within the
fieldDetecting pipeline and keeps pipeline-specific settings (DPI,
confidence thresholds) here.
"""

import os
from typing import Dict

from ..env_loader import bootstrap_env

bootstrap_env()

# Re-export from the centralized logging module so existing intra-pipeline
# imports (``from ...config import get_logger``) keep working.
from backend.logging_config import DEBUG_MODE, LOG_OPENAI_RESPONSE, get_logger  # noqa: E402, F401

# Rendering defaults.
DEFAULT_DPI = int(os.getenv("SANDBOX_DPI", "500"))

# Confidence thresholds shared between detection and resolver.
DEFAULT_THRESHOLDS: Dict[str, float] = {
    "high": 0.995,
    "medium": 0.7,
    "min": 0.5,
}
