import os
from pathlib import Path

_BOOTSTRAPPED = False


def _load_env_file(path: Path) -> None:
    """
    Minimal .env loader.

    This avoids adding a dependency (python-dotenv) while still supporting the
    common KEY=VALUE format for local sandbox runs.
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
            os.environ.setdefault(key, value)
    except FileNotFoundError:
        return


def bootstrap_env() -> None:
    """
    Load local `.env` files once for sandbox runs.

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
