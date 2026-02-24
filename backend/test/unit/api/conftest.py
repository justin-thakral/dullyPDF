from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.firebaseDB.firebase_service import RequestUser
import backend.main as main
import backend.api.schemas.models as schema_models
import backend.api.middleware.security as security_middleware
import backend.api.routes.ai as ai_routes
import backend.api.routes.billing as billing_routes
import backend.api.routes.detection as detection_routes
import backend.api.routes.forms as forms_routes
import backend.api.routes.legacy_detection as legacy_detection_routes
import backend.api.routes.profile as profile_routes
import backend.api.routes.public as public_routes
import backend.api.routes.saved_forms as saved_forms_routes
import backend.api.routes.schemas as schemas_routes
import backend.api.routes.sessions as sessions_routes
import backend.services.app_config as app_config_service
import backend.services.auth_service as auth_service
import backend.services.billing_service as billing_service
import backend.services.contact_service as contact_service
import backend.services.email_service as email_service
import backend.services.recaptcha_service as recaptcha_service
import backend.services.detection_service as detection_service
import backend.services.limits_service as limits_service
import backend.services.mapping_service as mapping_service
import backend.services.pdf_service as pdf_service
import backend.firebaseDB.billing_database as billing_database


class _ModuleProxy:
    """Compatibility patch proxy for `backend.main`-targeted unit tests."""

    def __init__(self, modules: list[object]) -> None:
        object.__setattr__(self, "_modules", modules)
        # Seed local attrs so `patch.object` uses setattr restore semantics.
        for name in self._known_names():
            resolved = self._resolve(name)
            if resolved is not None:
                object.__setattr__(self, name, resolved)

    def _known_names(self) -> set[str]:
        names: set[str] = set()
        for module in object.__getattribute__(self, "_modules"):
            for name in dir(module):
                if name.startswith("__"):
                    continue
                names.add(name)
                if not name.startswith("_"):
                    names.add(f"_{name}")
        return names

    def _candidates(self, name: str) -> list[str]:
        candidates = [name]
        if name.startswith("_") and len(name) > 1:
            candidates.append(name[1:])
        elif not name.startswith("_"):
            candidates.append(f"_{name}")
        seen: set[str] = set()
        deduped: list[str] = []
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            deduped.append(candidate)
        return deduped

    def _resolve(self, name: str) -> Any:
        for candidate in self._candidates(name):
            for module in object.__getattribute__(self, "_modules"):
                if hasattr(module, candidate):
                    return getattr(module, candidate)
        return None

    def __getattr__(self, name: str) -> Any:
        resolved = self._resolve(name)
        if resolved is None:
            raise AttributeError(name)
        object.__setattr__(self, name, resolved)
        return resolved

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_modules":
            object.__setattr__(self, name, value)
            return
        object.__setattr__(self, name, value)
        for candidate in self._candidates(name):
            for module in object.__getattribute__(self, "_modules"):
                if hasattr(module, candidate):
                    setattr(module, candidate, value)

    def __delattr__(self, name: str) -> None:
        # Keep compatibility with patch cleanup; local attrs are intentionally stable.
        if name in self.__dict__ and name != "_modules":
            return
        raise AttributeError(name)


@pytest.fixture
def app_main():
    modules = [
        main,
        schema_models,
        security_middleware,
        ai_routes,
        billing_routes,
        detection_routes,
        forms_routes,
        legacy_detection_routes,
        profile_routes,
        public_routes,
        saved_forms_routes,
        schemas_routes,
        sessions_routes,
        app_config_service,
        auth_service,
        billing_service,
        contact_service,
        email_service,
        recaptcha_service,
        detection_service,
        limits_service,
        mapping_service,
        pdf_service,
        billing_database,
    ]
    return _ModuleProxy(modules)


@pytest.fixture
def client(app_main) -> TestClient:
    return TestClient(main.app)


@pytest.fixture
def base_user() -> RequestUser:
    return RequestUser(
        uid="uid_base",
        app_user_id="user_base",
        email="base@example.com",
        display_name="Base User",
        role="base",
    )


@pytest.fixture
def god_user() -> RequestUser:
    return RequestUser(
        uid="uid_god",
        app_user_id="user_god",
        email="god@example.com",
        display_name="God User",
        role="god",
    )


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


@pytest.fixture(autouse=True)
def reset_gmail_token_cache(app_main) -> None:
    app_main._GMAIL_TOKEN_CACHE.clear()
    app_main._GMAIL_TOKEN_CACHE.update({"access_token": None, "expires_at": 0.0})


def make_scope(path: str = "/", headers: dict[str, str] | None = None, client_ip: str | None = "203.0.113.5") -> dict[str, Any]:
    raw_headers = []
    for key, value in (headers or {}).items():
        raw_headers.append((key.lower().encode("latin-1"), value.encode("latin-1")))
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode("latin-1"),
        "headers": raw_headers,
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
    }
    if client_ip is not None:
        scope["client"] = (client_ip, 12345)
    return scope


@pytest.fixture
def scope_builder():
    return make_scope
