#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-env/backend.dev.stack.env}"
EXAMPLE="config/backend.dev.stack.env.example"

if [[ ! -f "$ENV_FILE" ]]; then
  if [[ -f "$EXAMPLE" ]]; then
    mkdir -p "env"
    cp "$EXAMPLE" "$ENV_FILE"
    echo "Created $ENV_FILE from $EXAMPLE. Update values as needed."
    exit 1
  fi
  echo "Missing $ENV_FILE and $EXAMPLE." >&2
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_load_firebase_secret.sh"
load_firebase_secret

DETECTOR_TASKS_PROJECT="${DETECTOR_TASKS_PROJECT:-${FIREBASE_PROJECT_ID:-}}"
DETECTOR_TASKS_LOCATION="${DETECTOR_TASKS_LOCATION:-us-central1}"
DETECTOR_TASKS_QUEUE="${DETECTOR_TASKS_QUEUE:-commonforms-detect-light}"
DETECTOR_TASKS_QUEUE_LIGHT="${DETECTOR_TASKS_QUEUE_LIGHT:-$DETECTOR_TASKS_QUEUE}"
DETECTOR_TASKS_QUEUE_HEAVY="${DETECTOR_TASKS_QUEUE_HEAVY:-commonforms-detect-heavy}"
DETECTOR_TASKS_SERVICE_ACCOUNT="${DETECTOR_TASKS_SERVICE_ACCOUNT:-dullypdf-backend-runtime@dullypdf-dev.iam.gserviceaccount.com}"

if command -v gcloud >/dev/null 2>&1; then
  if [[ -z "${DETECTOR_SERVICE_URL_LIGHT:-}" && -n "${DETECTOR_TASKS_PROJECT:-}" ]]; then
    DETECTOR_SERVICE_URL_LIGHT="$(
      gcloud run services describe dullypdf-detector-light \
        --region "$DETECTOR_TASKS_LOCATION" \
        --project "$DETECTOR_TASKS_PROJECT" \
        --format='value(status.url)' 2>/dev/null || true
    )"
  fi
  if [[ -z "${DETECTOR_SERVICE_URL_HEAVY:-}" && -n "${DETECTOR_TASKS_PROJECT:-}" ]]; then
    DETECTOR_SERVICE_URL_HEAVY="$(
      gcloud run services describe dullypdf-detector-heavy \
        --region "$DETECTOR_TASKS_LOCATION" \
        --project "$DETECTOR_TASKS_PROJECT" \
        --format='value(status.url)' 2>/dev/null || true
    )"
  fi
fi

if [[ -z "${DETECTOR_SERVICE_URL_LIGHT:-}" ]]; then
  echo "Missing DETECTOR_SERVICE_URL_LIGHT. Deploy dullypdf-detector-light or set it in $ENV_FILE." >&2
  exit 1
fi

if [[ -z "${DETECTOR_SERVICE_URL_HEAVY:-}" ]]; then
  echo "Missing DETECTOR_SERVICE_URL_HEAVY. Deploy dullypdf-detector-heavy or set it in $ENV_FILE." >&2
  exit 1
fi

DETECTOR_SERVICE_URL="${DETECTOR_SERVICE_URL:-$DETECTOR_SERVICE_URL_LIGHT}"
DETECTOR_TASKS_AUDIENCE="${DETECTOR_TASKS_AUDIENCE:-$DETECTOR_SERVICE_URL}"
DETECTOR_TASKS_AUDIENCE_LIGHT="${DETECTOR_TASKS_AUDIENCE_LIGHT:-$DETECTOR_SERVICE_URL_LIGHT}"
DETECTOR_TASKS_AUDIENCE_HEAVY="${DETECTOR_TASKS_AUDIENCE_HEAVY:-$DETECTOR_SERVICE_URL_HEAVY}"

BACKEND_PORT="${DEV_STACK_BACKEND_PORT:-8010}"
FRONTEND_PORT="${DEV_STACK_FRONTEND_PORT:-5173}"
IMAGE_TAG="${DEV_STACK_BACKEND_IMAGE:-dullypdf-backend:devstack}"
CONTAINER_NAME="${DEV_STACK_BACKEND_CONTAINER:-dullypdf-backend-devstack}"
BACKEND_BIND="${DEV_STACK_BIND_ADDRESS:-127.0.0.1}"
FRONTEND_ENV_MODE="${DEV_STACK_FRONTEND_ENV:-stack}"
BACKEND_READY_TIMEOUT_SECONDS="${DEV_STACK_BACKEND_READY_TIMEOUT_SECONDS:-45}"
BACKEND_READY_INTERVAL_SECONDS="${DEV_STACK_BACKEND_READY_INTERVAL_SECONDS:-1}"

BACKEND_HEALTH_HOST="${DEV_STACK_HEALTH_HOST:-}"
if [[ -z "${BACKEND_HEALTH_HOST}" ]]; then
  if [[ "${BACKEND_BIND}" == "0.0.0.0" || "${BACKEND_BIND}" == "::" ]]; then
    BACKEND_HEALTH_HOST="127.0.0.1"
  else
    BACKEND_HEALTH_HOST="${BACKEND_BIND}"
  fi
fi
BACKEND_HEALTH_URL="http://${BACKEND_HEALTH_HOST}:${BACKEND_PORT}/api/health"

cleanup() {
  if docker ps -a --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"; then
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  fi
  if [[ -n "${CREDS_FILE_TEMP:-}" && -f "${CREDS_FILE_TEMP:-}" ]]; then
    rm -f "$CREDS_FILE_TEMP" || true
  fi
}

trap cleanup EXIT INT TERM

if [[ "${DEV_STACK_BUILD:-}" == "1" ]] || ! docker image inspect "$IMAGE_TAG" >/dev/null 2>&1; then
  docker build -t "$IMAGE_TAG" -f Dockerfile .
fi

if [[ -n "${FIREBASE_CREDENTIALS:-}" ]]; then
  CREDS_FILE_TEMP="$(mktemp -t dullypdf-firebase-XXXX.json)"
  printf '%s' "$FIREBASE_CREDENTIALS" > "$CREDS_FILE_TEMP"
  chmod 600 "$CREDS_FILE_TEMP"
  CREDS_FILE="$CREDS_FILE_TEMP"
elif [[ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" && -f "${GOOGLE_APPLICATION_CREDENTIALS:-}" ]]; then
  CREDS_FILE="$GOOGLE_APPLICATION_CREDENTIALS"
else
  echo "Missing Firebase credentials. Set FIREBASE_CREDENTIALS_SECRET or GOOGLE_APPLICATION_CREDENTIALS." >&2
  exit 1
fi

if docker ps -a --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"; then
  docker rm -f "$CONTAINER_NAME" >/dev/null
fi

ENV_ARGS=(
  "-e" "FIREBASE_CREDENTIALS=/var/secrets/firebase-admin.json"
  "-e" "GOOGLE_APPLICATION_CREDENTIALS=/var/secrets/firebase-admin.json"
  "-e" "ENV=prod"
  "-e" "FIREBASE_CHECK_REVOKED=true"
  "-e" "DETECTOR_MODE=tasks"
  "-e" "DETECTOR_TASKS_PROJECT=${DETECTOR_TASKS_PROJECT}"
  "-e" "DETECTOR_TASKS_LOCATION=${DETECTOR_TASKS_LOCATION}"
  "-e" "DETECTOR_TASKS_QUEUE=${DETECTOR_TASKS_QUEUE}"
  "-e" "DETECTOR_SERVICE_URL=${DETECTOR_SERVICE_URL}"
  "-e" "DETECTOR_TASKS_QUEUE_LIGHT=${DETECTOR_TASKS_QUEUE_LIGHT}"
  "-e" "DETECTOR_TASKS_QUEUE_HEAVY=${DETECTOR_TASKS_QUEUE_HEAVY}"
  "-e" "DETECTOR_SERVICE_URL_LIGHT=${DETECTOR_SERVICE_URL_LIGHT}"
  "-e" "DETECTOR_SERVICE_URL_HEAVY=${DETECTOR_SERVICE_URL_HEAVY}"
  "-e" "DETECTOR_TASKS_SERVICE_ACCOUNT=${DETECTOR_TASKS_SERVICE_ACCOUNT}"
  "-e" "DETECTOR_TASKS_AUDIENCE=${DETECTOR_TASKS_AUDIENCE}"
  "-e" "DETECTOR_TASKS_AUDIENCE_LIGHT=${DETECTOR_TASKS_AUDIENCE_LIGHT}"
  "-e" "DETECTOR_TASKS_AUDIENCE_HEAVY=${DETECTOR_TASKS_AUDIENCE_HEAVY}"
  "-e" "SANDBOX_ENABLE_LEGACY_ENDPOINTS=false"
  "-e" "ADMIN_TOKEN="
  "-e" "SANDBOX_DEBUG=false"
  "-e" "SANDBOX_DEBUG_FORCE=false"
  "-e" "SANDBOX_DEBUG_PASSWORD="
)

if [[ -n "${OPENAI_API_KEY:-}" ]]; then
  ENV_ARGS+=("-e" "OPENAI_API_KEY=${OPENAI_API_KEY}")
fi

docker run --rm -d \
  --name "$CONTAINER_NAME" \
  -p "${BACKEND_BIND}:${BACKEND_PORT}:8000" \
  --env-file "$ENV_FILE" \
  "${ENV_ARGS[@]}" \
  -v "${CREDS_FILE}:/var/secrets/firebase-admin.json:ro" \
  "$IMAGE_TAG" >/dev/null

wait_for_backend_health() {
  local deadline current_time
  deadline=$((SECONDS + BACKEND_READY_TIMEOUT_SECONDS))
  echo "Waiting for backend readiness at ${BACKEND_HEALTH_URL}..."

  while true; do
    if command -v curl >/dev/null 2>&1; then
      if curl --silent --show-error --fail --max-time 2 "${BACKEND_HEALTH_URL}" >/dev/null 2>&1; then
        echo "Backend is ready."
        return 0
      fi
    elif command -v wget >/dev/null 2>&1; then
      if wget -q -T 2 -O /dev/null "${BACKEND_HEALTH_URL}" >/dev/null 2>&1; then
        echo "Backend is ready."
        return 0
      fi
    else
      echo "Missing curl/wget; cannot check backend health endpoint." >&2
      return 1
    fi

    current_time=${SECONDS}
    if (( current_time >= deadline )); then
      echo "Backend did not become ready within ${BACKEND_READY_TIMEOUT_SECONDS}s." >&2
      echo "Last backend logs:" >&2
      docker logs --tail 120 "${CONTAINER_NAME}" >&2 || true
      return 1
    fi
    sleep "${BACKEND_READY_INTERVAL_SECONDS}"
  done
}

wait_for_backend_health

echo "Backend (dev stack) running at http://localhost:${BACKEND_PORT}"
echo "Frontend starting at http://localhost:${FRONTEND_PORT}"

bash scripts/use-frontend-env.sh "${FRONTEND_ENV_MODE}"
cd frontend
VITE_API_URL="http://localhost:${BACKEND_PORT}" \
VITE_DETECTION_API_URL="http://localhost:${BACKEND_PORT}" \
VITE_ADMIN_TOKEN="" \
npm run dev -- --port "${FRONTEND_PORT}"
