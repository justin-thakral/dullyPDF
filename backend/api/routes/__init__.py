"""API router exports.

This module intentionally avoids eager imports of all route modules.
Coverage source discovery can import packages multiple times in one process;
lazy exports keep package import side-effect free and load each router on demand.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_ROUTER_MODULES = {
    "billing_router": ".billing",
    "ai_router": ".ai",
    "detection_router": ".detection",
    "fill_links_public_router": ".fill_links_public",
    "fill_links_router": ".fill_links",
    "forms_router": ".forms",
    "groups_router": ".groups",
    "health_router": ".health",
    "legacy_detection_router": ".legacy_detection",
    "profile_router": ".profile",
    "public_router": ".public",
    "saved_forms_router": ".saved_forms",
    "schemas_router": ".schemas",
    "sessions_router": ".sessions",
    "signing_public_router": ".signing_public",
    "signing_router": ".signing",
    "template_api_router": ".template_api",
    "template_api_public_router": ".template_api_public",
}

__all__ = list(_ROUTER_MODULES.keys())


def __getattr__(name: str) -> Any:
    module_path = _ROUTER_MODULES.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_path, __name__)
    router = getattr(module, "router")
    globals()[name] = router
    return router


def __dir__() -> list[str]:
    return sorted(set(globals().keys()) | set(__all__))
