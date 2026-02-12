"""FastAPI service entrypoint.

The application is structured under ``backend/api`` and ``backend/services``.
``backend/main.py`` is the runtime entrypoint (``python -m backend.main``).
"""

from __future__ import annotations

from backend.api import app, create_app  # noqa: F401


def run():
    """Convenience entrypoint for `python -m backend.main`."""
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=int(8000),
        reload=False,
    )


if __name__ == "__main__":
    run()
