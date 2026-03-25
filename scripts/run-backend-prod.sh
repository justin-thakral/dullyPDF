#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-env/backend.prod.env}"
EXAMPLE="config/backend.prod.env.example"
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
source "${SCRIPT_DIR}/_detector_routing.sh"
source "${SCRIPT_DIR}/_load_firebase_secret.sh"

DETECTOR_SERVICE_REGION="${DETECTOR_SERVICE_REGION:-${REGION:-${DETECTOR_TASKS_LOCATION:-us-central1}}}"
detector_set_active_routing_vars
DETECTOR_ROUTING_MODE="$DETECTOR_ROUTING_MODE_RESOLVED"
PROJECT_ID="${PROJECT_ID:-${DETECTOR_TASKS_PROJECT:-${FIREBASE_PROJECT_ID:-}}}"

if command -v gcloud >/dev/null 2>&1 && [[ -n "${PROJECT_ID:-}" ]]; then
  if [[ -z "${DETECTOR_SERVICE_URL_LIGHT_ACTIVE:-}" ]]; then
    DETECTOR_SERVICE_URL_LIGHT_ACTIVE="$(
      gcloud run services describe "$DETECTOR_SERVICE_NAME_LIGHT_ACTIVE" \
        --region "$DETECTOR_SERVICE_REGION_LIGHT_ACTIVE" \
        --project "$PROJECT_ID" \
        --format='value(status.url)' 2>/dev/null || true
    )"
  fi
  if [[ -z "${DETECTOR_SERVICE_URL_HEAVY_ACTIVE:-}" ]]; then
    DETECTOR_SERVICE_URL_HEAVY_ACTIVE="$(
      gcloud run services describe "$DETECTOR_SERVICE_NAME_HEAVY_ACTIVE" \
        --region "$DETECTOR_SERVICE_REGION_HEAVY_ACTIVE" \
        --project "$PROJECT_ID" \
        --format='value(status.url)' 2>/dev/null || true
    )"
  fi
fi

export DETECTOR_SERVICE_URL="${DETECTOR_SERVICE_URL_LIGHT_ACTIVE:-$DETECTOR_SERVICE_URL}"
export DETECTOR_SERVICE_URL_LIGHT="${DETECTOR_SERVICE_URL_LIGHT_ACTIVE:-$DETECTOR_SERVICE_URL_LIGHT}"
export DETECTOR_SERVICE_URL_HEAVY="${DETECTOR_SERVICE_URL_HEAVY_ACTIVE:-$DETECTOR_SERVICE_URL_HEAVY}"
export DETECTOR_TASKS_AUDIENCE="$(
  detector_tasks_audience_for_target \
    "$DETECTOR_TARGET_LIGHT_ACTIVE" \
    "light" \
    "${DETECTOR_SERVICE_URL_LIGHT_ACTIVE:-$DETECTOR_SERVICE_URL_LIGHT}"
)"
export DETECTOR_TASKS_AUDIENCE_LIGHT="$DETECTOR_TASKS_AUDIENCE"
export DETECTOR_TASKS_AUDIENCE_HEAVY="$(
  detector_tasks_audience_for_target \
    "$DETECTOR_TARGET_HEAVY_ACTIVE" \
    "heavy" \
    "${DETECTOR_SERVICE_URL_HEAVY_ACTIVE:-$DETECTOR_SERVICE_URL_HEAVY}"
)"

load_firebase_secret
load_backend_email_secrets

VENV_UVICORN="backend/.venv/bin/uvicorn"
if [[ -x "$VENV_UVICORN" ]]; then
  exec "$VENV_UVICORN" backend.main:app --host 0.0.0.0 --port "${PORT:-8000}"
fi
echo "Warning: backend/.venv not found. Using system python may break CommonForms." >&2
exec uvicorn backend.main:app --host 0.0.0.0 --port "${PORT:-8000}"
