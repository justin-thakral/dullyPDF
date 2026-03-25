"""Request security middleware."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from backend.services.app_config import legacy_endpoints_enabled, resolve_stream_cors_headers
from backend.services.auth_service import has_admin_override, verify_token


async def enforce_security_guards(request: Request, call_next):
    """Enforce auth before body parsing and hide legacy endpoints when disabled."""
    origin = request.headers.get("origin")
    cors_headers = resolve_stream_cors_headers(origin)
    if request.method == "OPTIONS":
        return await call_next(request)

    path = request.url.path
    normalized_path = path.rstrip("/") or "/"
    if not legacy_endpoints_enabled() and (
        normalized_path in {"/api/process-pdf", "/api/register-fillable", "/api/detected-fields"}
        or path.startswith("/download/")
    ):
        return JSONResponse(status_code=404, content={"detail": "Not found"}, headers=cors_headers)

    if path == "/detect-fields" or path.startswith("/detect-fields/"):
        authorization = request.headers.get("authorization")
        x_admin_token = request.headers.get("x-admin-token")
        if has_admin_override(authorization, x_admin_token):
            request.state.detect_admin_override = True
            return await call_next(request)
        try:
            request.state.detect_auth_payload = verify_token(authorization)
        except Exception as exc:
            status_code = getattr(exc, "status_code", 401)
            detail = getattr(exc, "detail", "Unauthorized")
            return JSONResponse(
                status_code=status_code,
                content={"detail": detail},
                headers=cors_headers,
            )
        return await call_next(request)

    public_api_paths = {
        "/api/health",
        "/api/contact",
        "/api/recaptcha/assess",
    }
    is_public_fill_link_path = normalized_path.startswith("/api/fill-links/public/")
    is_public_signing_path = normalized_path.startswith("/api/signing/public/")
    is_public_template_api_fill_path = normalized_path.startswith("/api/v1/fill/")
    is_public_billing_webhook = normalized_path == "/api/billing/webhook"
    if (
        path.startswith("/api/")
        and normalized_path not in public_api_paths
        and not is_public_billing_webhook
        and not is_public_fill_link_path
        and not is_public_signing_path
        and not is_public_template_api_fill_path
    ):
        authorization = request.headers.get("authorization")
        try:
            request.state.preverified_auth_payload = verify_token(authorization)
        except Exception as exc:
            status_code = getattr(exc, "status_code", 401)
            detail = getattr(exc, "detail", "Unauthorized")
            return JSONResponse(
                status_code=status_code,
                content={"detail": detail},
                headers=cors_headers,
            )
        return await call_next(request)

    if path.startswith("/download/"):
        authorization = request.headers.get("authorization")
        try:
            request.state.preverified_auth_payload = verify_token(authorization)
        except Exception as exc:
            status_code = getattr(exc, "status_code", 401)
            detail = getattr(exc, "detail", "Unauthorized")
            return JSONResponse(
                status_code=status_code,
                content={"detail": detail},
                headers=cors_headers,
            )
        return await call_next(request)

    return await call_next(request)
