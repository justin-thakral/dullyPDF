"""Regression checks for files included in the backend runtime image."""

from __future__ import annotations

from pathlib import Path


DOCKERFILE_PATH = Path("Dockerfile")
DOCKERIGNORE_PATH = Path(".dockerignore")


def test_backend_image_includes_session_cleanup_script() -> None:
    text = DOCKERFILE_PATH.read_text(encoding="utf-8")
    assert "COPY --chown=appuser:appuser scripts/cleanup_sessions.py /app/scripts/cleanup_sessions.py" in text


def test_dockerignore_keeps_only_cleanup_script_from_root_scripts_directory() -> None:
    text = DOCKERIGNORE_PATH.read_text(encoding="utf-8")
    assert "scripts/*" in text
    assert "!scripts/cleanup_sessions.py" in text
