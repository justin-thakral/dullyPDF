from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import get_logger

logger = get_logger(__name__)


@dataclass
class OutputLayout:
    """
    Standardized output layout for sandbox runs.

    Every run writes JSON to `json/` and rendered overlays to `overlays/` under a
    single root directory so artifacts stay grouped together.
    """

    root: Path
    json_dir: Path
    overlays_dir: Path


def ensure_output_layout(root: Path) -> OutputLayout:
    json_dir = root / "json"
    overlays_dir = root / "overlays"
    json_dir.mkdir(parents=True, exist_ok=True)
    overlays_dir.mkdir(parents=True, exist_ok=True)
    logger.debug("Output layout prepared: root=%s", root)
    return OutputLayout(root=root, json_dir=json_dir, overlays_dir=overlays_dir)


def temp_prefix_from_pdf(pdf_path: Path, *, fallback: Optional[str] = None) -> str:
    """
    Build the standardized temp prefix used for sandbox artifacts.

    Format: temp + first 5 + last 5 characters of the PDF stem (lowercased).
    """
    stem = (pdf_path.stem or fallback or "file").lower()
    head = stem[:5]
    tail = stem[-5:] if len(stem) > 5 else stem
    return f"temp{head}{tail}"
