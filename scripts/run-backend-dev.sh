#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-env/backend.dev.env}"
EXAMPLE="config/backend.dev.env.example"
OVERRIDE_STRIPE_WEBHOOK_SECRET="${STRIPE_WEBHOOK_SECRET:-}"
OVERRIDE_STRIPE_ENFORCE_WEBHOOK_HEALTH="${STRIPE_ENFORCE_WEBHOOK_HEALTH:-}"
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

if [[ -n "$OVERRIDE_STRIPE_WEBHOOK_SECRET" ]]; then
  export STRIPE_WEBHOOK_SECRET="$OVERRIDE_STRIPE_WEBHOOK_SECRET"
fi
if [[ -n "$OVERRIDE_STRIPE_ENFORCE_WEBHOOK_HEALTH" ]]; then
  export STRIPE_ENFORCE_WEBHOOK_HEALTH="$OVERRIDE_STRIPE_ENFORCE_WEBHOOK_HEALTH"
fi

if [[ -f "mcp/.env.local" ]]; then
  set -a
  source "mcp/.env.local"
  set +a
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_load_firebase_secret.sh"
load_firebase_secret
load_backend_email_secrets

VENV_UVICORN="backend/.venv/bin/uvicorn"
if [[ -x "$VENV_UVICORN" ]]; then
  exec "$VENV_UVICORN" backend.main:app --host 0.0.0.0 --port "${PORT:-8000}" --reload --reload-dir backend
fi
echo "Warning: backend/.venv not found. Using system python may break CommonForms." >&2
exec uvicorn backend.main:app --host 0.0.0.0 --port "${PORT:-8000}" --reload --reload-dir backend
