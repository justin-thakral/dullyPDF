#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-dullypdf}"
ALLOW_NON_PROD="${DULLYPDF_ALLOW_NON_PROD:-}"
MODE="prod"
ENV_FILE="${ENV_FILE:-env/frontend.${MODE}.env}"
EXAMPLE="config/frontend.${MODE}.env.example"

if [[ "$PROJECT_ID" != "dullypdf" && -z "$ALLOW_NON_PROD" ]]; then
  echo "Refusing to deploy frontend to non-prod project: $PROJECT_ID. Set DULLYPDF_ALLOW_NON_PROD=1 to override." >&2
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  if [[ -f "$EXAMPLE" ]]; then
    mkdir -p "env"
    cp "$EXAMPLE" "$ENV_FILE"
    echo "Created $ENV_FILE from $EXAMPLE. Update values and re-run." >&2
    exit 1
  fi
  echo "Missing $ENV_FILE and $EXAMPLE." >&2
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

require_exact() {
  local name="$1"
  local expected="$2"
  local actual="${!name:-}"
  if [[ "$actual" != "$expected" ]]; then
    echo "Expected $name=$expected (got '${actual}')." >&2
    exit 1
  fi
}

require_nonempty() {
  local name="$1"
  local actual="${!name:-}"
  if [[ -z "$actual" ]]; then
    echo "Missing required $name in $ENV_FILE." >&2
    exit 1
  fi
}

require_empty() {
  local name="$1"
  local actual="${!name:-}"
  if [[ -n "$actual" ]]; then
    echo "Expected $name to be empty for prod builds." >&2
    exit 1
  fi
}

require_nonempty VITE_API_URL
require_nonempty VITE_DETECTION_API_URL
require_nonempty VITE_FIREBASE_PROJECT_ID

if [[ "${VITE_API_URL}" == *"localhost"* || "${VITE_API_URL}" == *"127.0.0.1"* ]]; then
  echo "VITE_API_URL must point to prod backend, not localhost." >&2
  exit 1
fi

if [[ "${VITE_DETECTION_API_URL}" == *"localhost"* || "${VITE_DETECTION_API_URL}" == *"127.0.0.1"* ]]; then
  echo "VITE_DETECTION_API_URL must point to prod backend, not localhost." >&2
  exit 1
fi

if [[ "$VITE_FIREBASE_PROJECT_ID" != "$PROJECT_ID" ]]; then
  echo "VITE_FIREBASE_PROJECT_ID must match $PROJECT_ID for prod deploys." >&2
  exit 1
fi

require_empty VITE_ADMIN_TOKEN

if [[ "${VITE_CONTACT_REQUIRE_RECAPTCHA:-true}" == "true" || "${VITE_SIGNUP_REQUIRE_RECAPTCHA:-true}" == "true" ]]; then
  require_nonempty VITE_RECAPTCHA_SITE_KEY
fi

bash scripts/use-frontend-env.sh "$MODE"

(
  cd frontend
  npm run build
)

firebase deploy --only hosting --project "$PROJECT_ID"
