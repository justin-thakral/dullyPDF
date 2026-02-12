"""backend.detection package -- canonical home for detection modules.

Re-exports all public names from submodules for convenience.
"""

from .status import *  # noqa: F401,F403
from .tasks import *  # noqa: F401,F403
from .pdf_validation import *  # noqa: F401,F403

# detector_app exposes a FastAPI `app` instance; import the module directly
# when needed (e.g. ``from backend.detection.detector_app import app``).
