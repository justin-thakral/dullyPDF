"""FastAPI app factory and router wiring."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.middleware.security import enforce_security_guards
from backend.api.routes import (
    ai_router,
    detection_router,
    forms_router,
    health_router,
    legacy_detection_router,
    profile_router,
    public_router,
    saved_forms_router,
    schemas_router,
    sessions_router,
)
from backend.services.app_config import docs_enabled, require_prod_env, resolve_cors_origins


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    require_prod_env()
    docs_on = docs_enabled()
    app = FastAPI(
        title="Sandbox PDF Field Detector",
        docs_url="/docs" if docs_on else None,
        redoc_url="/redoc" if docs_on else None,
        openapi_url="/openapi.json" if docs_on else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolve_cors_origins(),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.middleware("http")(enforce_security_guards)

    app.include_router(health_router)
    app.include_router(public_router)
    app.include_router(profile_router)
    app.include_router(legacy_detection_router)
    app.include_router(detection_router)
    app.include_router(schemas_router)
    app.include_router(ai_router)
    app.include_router(forms_router)
    app.include_router(saved_forms_router)
    app.include_router(sessions_router)
    return app


app = create_app()
