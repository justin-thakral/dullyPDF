"""API router modules."""

from .ai import router as ai_router
from .detection import router as detection_router
from .forms import router as forms_router
from .health import router as health_router
from .legacy_detection import router as legacy_detection_router
from .profile import router as profile_router
from .public import router as public_router
from .saved_forms import router as saved_forms_router
from .schemas import router as schemas_router
from .sessions import router as sessions_router

__all__ = [
    "ai_router",
    "detection_router",
    "forms_router",
    "health_router",
    "legacy_detection_router",
    "profile_router",
    "public_router",
    "saved_forms_router",
    "schemas_router",
    "sessions_router",
]
