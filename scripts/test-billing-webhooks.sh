#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-env/backend.dev.env}"
BASE_URL="${2:-http://localhost:8000}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing env file: $ENV_FILE" >&2
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

if [[ -f "mcp/.env.local" ]]; then
  set -a
  source "mcp/.env.local"
  set +a
fi

PYTHON_BIN="backend/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

exec "$PYTHON_BIN" -m backend.scripts.billing_webhook_smoke --base-url "$BASE_URL"
