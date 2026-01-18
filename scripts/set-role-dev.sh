#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="env/backend.dev.env"
if [[ $# -gt 0 && -f "$1" ]]; then
  ENV_FILE="$1"
  shift
fi
EXAMPLE="config/backend.dev.env.example"
if [[ ! -f "$ENV_FILE" ]]; then
  if [[ -f "$EXAMPLE" ]]; then
    mkdir -p "env"
    cp "$EXAMPLE" "$ENV_FILE"
    echo "Created $ENV_FILE from $EXAMPLE. Update values as needed."
    exit 1
  fi
  echo "Missing $ENV_FILE and $EXAMPLE."
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_load_firebase_secret.sh"
load_firebase_secret

VENV_PYTHON="backend/.venv/bin/python"
if [[ -x "$VENV_PYTHON" ]]; then
  exec "$VENV_PYTHON" -m backend.firebaseDB.role_cli "$@"
fi
echo "Warning: backend/.venv not found. Using system python may break CommonForms." >&2
exec python -m backend.firebaseDB.role_cli "$@"
