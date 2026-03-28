"""Minimal .env loader for rename pipeline scripts."""

import os
from pathlib import Path

_BOOTSTRAPPED = False
_ADC_PROTECTED_KEYS = {
    "FIREBASE_CREDENTIALS",
    "FIREBASE_CREDENTIALS_SECRET",
    "FIREBASE_CREDENTIALS_PROJECT",
    "GOOGLE_APPLICATION_CREDENTIALS",
}


def _adc_mode_enabled() -> bool:
    raw = (os.getenv("FIREBASE_USE_ADC") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _is_prod_runtime() -> bool:
    raw = (os.getenv("ENV") or "").strip().lower()
    return raw in {"prod", "production"}


def _should_skip_loaded_key(key: str) -> bool:
    """
    Prevent local .env credential hydration from polluting prod/ADC flows.

    The rename/debug bootstrap runs during broad backend imports via
    ``backend.logging_config``. When a caller has already selected prod or ADC
    mode, importing a convenience ``backend/.env`` file must not inject legacy
    Firebase credential variables because prod validation depends on those
    remaining unset.
    """
    normalized = str(key or "").strip()
    if normalized not in _ADC_PROTECTED_KEYS:
        return False
    return _is_prod_runtime() or _adc_mode_enabled()


def _load_env_file(path: Path) -> None:
    """
    Minimal .env loader.

    This avoids adding a dependency (python-dotenv) while still supporting the
    common KEY=VALUE format for local rename pipeline runs.
    """
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not key:
                continue
            if _should_skip_loaded_key(key):
                continue
            os.environ.setdefault(key, value)
    except FileNotFoundError:
        return


def bootstrap_env() -> None:
    """
    Load local `.env` files once for rename pipeline runs.

    We keep this minimal and explicit because many scripts are launched directly
    and do not inherit shell-sourced environment variables.
    """
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    here = Path(__file__).resolve()
    repo_root = here.parents[3]
    candidate_paths = [
        repo_root / "backend" / ".env",
        repo_root / ".env",
        repo_root.parent / ".env.cloudsql",
        repo_root.parent / ".env",
        here.parent / ".env",
    ]
    for path in candidate_paths:
        _load_env_file(path)
    _BOOTSTRAPPED = True
