"""
Pytest configuration for the experimental sandbox pipeline.

Why this exists:
- The sandbox code lives under `backend/fieldDetecting`, but `backend/` is not installed as a
  site-package.
- Pytest's rootdir discovery can pick `backend` as the project root, which means the
  repository root is not on `sys.path`.
- Our tests import modules via `backend...`, so we ensure the repository root is
  importable.
"""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
