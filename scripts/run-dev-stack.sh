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

normalize_truthy_flag() {
  local raw="${1:-}"
  raw="$(printf '%s' "$raw" | tr '[:upper:]' '[:lower:]')"
  case "$raw" in
    1|true|yes|on) printf 'true' ;;
    *) printf 'false' ;;
  esac
}

build_detector_stable_audience() {
  local service_name="${1:-}"
  if [[ -z "$service_name" ]]; then
    printf '\n'
    return
  fi
  printf 'https://%s.dullypdf.internal\n' "$service_name"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_load_firebase_secret.sh"
source "${SCRIPT_DIR}/_detector_routing.sh"

DEV_STACK_PROD_TOPOLOGY="$(normalize_truthy_flag "${DEV_STACK_PROD_TOPOLOGY:-true}")"

apply_dev_stack_prod_topology() {
  if [[ "$DEV_STACK_PROD_TOPOLOGY" != "true" ]]; then
    return
  fi

  # Keep the localhost stack on dev semantics for local origins, but force the
  # same topology and auth posture as the deployed environment: ADC-backed
  # Firebase, Cloud Tasks/Run detector routing, task-mode rename/remap, and no
  # debug/admin shortcuts. This keeps local smoke paths close to prod without
  # triggering prod-only canonical-origin constraints like https://dullypdf.com.
  export ENV=dev
  export FIREBASE_USE_ADC=true
  export FIREBASE_CHECK_REVOKED=true
  unset FIREBASE_CREDENTIALS
  unset FIREBASE_CREDENTIALS_SECRET
  unset FIREBASE_CREDENTIALS_PROJECT
  unset GOOGLE_APPLICATION_CREDENTIALS

  if [[ -z "${FIREBASE_SERVICE_ACCOUNT_ID:-}" && -n "${BACKEND_RUNTIME_SERVICE_ACCOUNT:-}" ]]; then
    export FIREBASE_SERVICE_ACCOUNT_ID="$BACKEND_RUNTIME_SERVICE_ACCOUNT"
  fi

  export DETECTOR_MODE=tasks
  export DETECTOR_ROUTING_MODE="${DETECTOR_ROUTING_MODE:-gpu}"
  export DETECTOR_SERIALIZE_GPU_TASKS="${DETECTOR_SERIALIZE_GPU_TASKS:-true}"
  export DETECTOR_USE_STABLE_AUDIENCE="${DETECTOR_USE_STABLE_AUDIENCE:-true}"
  export OPENAI_RENAME_REMAP_MODE=tasks
  export SANDBOX_ENABLE_LEGACY_ENDPOINTS=false
  export SANDBOX_ALLOW_ADMIN_OVERRIDE=false
  export ADMIN_TOKEN=
  export SANDBOX_DEBUG=false
  export SANDBOX_DEBUG_FORCE=false
  export SANDBOX_DEBUG_PASSWORD=
  export SANDBOX_LOG_OPENAI_RESPONSE=false
  export SANDBOX_ENABLE_DOCS=false
  export SANDBOX_TRUST_PROXY_HEADERS=true
  export SANDBOX_TRUSTED_PROXY_DEPTH="${SANDBOX_TRUSTED_PROXY_DEPTH:-1}"

  if [[ -z "${SANDBOX_TRUSTED_HOSTS:-}" || "${SANDBOX_TRUSTED_HOSTS:-}" == "*" ]]; then
    export SANDBOX_TRUSTED_HOSTS="localhost,127.0.0.1,[::1],testserver"
  fi

  if [[ -z "${RECAPTCHA_ALLOWED_HOSTNAMES:-}" ]]; then
    export RECAPTCHA_ALLOWED_HOSTNAMES="localhost,127.0.0.1"
  fi
}

apply_dev_stack_prod_topology

if [[ "$(normalize_truthy_flag "${FIREBASE_USE_ADC:-false}")" != "true" ]]; then
  load_firebase_secret
fi
load_backend_email_secrets

DEV_STACK_DETECTOR_GPU="${DEV_STACK_DETECTOR_GPU:-false}"
if detector_is_truthy "$DEV_STACK_DETECTOR_GPU"; then
  DEV_STACK_DETECTOR_GPU=true
else
  DEV_STACK_DETECTOR_GPU=false
fi

DETECTOR_TASKS_PROJECT="${DETECTOR_TASKS_PROJECT:-${FIREBASE_PROJECT_ID:-}}"
DETECTOR_TASKS_LOCATION="${DETECTOR_TASKS_LOCATION:-us-east4}"
DETECTOR_TASKS_QUEUE="${DETECTOR_TASKS_QUEUE:-commonforms-detect-light}"
DETECTOR_TASKS_QUEUE_LIGHT="${DETECTOR_TASKS_QUEUE_LIGHT:-$DETECTOR_TASKS_QUEUE}"
DETECTOR_TASKS_QUEUE_HEAVY="${DETECTOR_TASKS_QUEUE_HEAVY:-commonforms-detect-heavy}"
DETECTOR_TASKS_SERVICE_ACCOUNT="${DETECTOR_TASKS_SERVICE_ACCOUNT:-dullypdf-backend-runtime@dullypdf-dev.iam.gserviceaccount.com}"
DETECTOR_SERVICE_REGION="${DETECTOR_SERVICE_REGION:-${DETECTOR_TASKS_LOCATION}}"
detector_set_active_routing_vars
DETECTOR_ROUTING_MODE="${DETECTOR_ROUTING_MODE_RESOLVED}"

if command -v gcloud >/dev/null 2>&1; then
  if [[ ("${DEV_STACK_PROD_TOPOLOGY}" == "true" || "${DEV_STACK_BUILD:-}" == "1" || -z "${DETECTOR_SERVICE_URL_LIGHT_ACTIVE:-}") && -n "${DETECTOR_TASKS_PROJECT:-}" ]]; then
    DETECTOR_SERVICE_URL_LIGHT_ACTIVE="$(
      gcloud run services describe "$DETECTOR_SERVICE_NAME_LIGHT_ACTIVE" \
        --region "$DETECTOR_SERVICE_REGION_LIGHT_ACTIVE" \
        --project "$DETECTOR_TASKS_PROJECT" \
        --format='value(status.url)' 2>/dev/null || true
    )"
  fi
  if [[ ("${DEV_STACK_PROD_TOPOLOGY}" == "true" || "${DEV_STACK_BUILD:-}" == "1" || -z "${DETECTOR_SERVICE_URL_HEAVY_ACTIVE:-}") && -n "${DETECTOR_TASKS_PROJECT:-}" ]]; then
    DETECTOR_SERVICE_URL_HEAVY_ACTIVE="$(
      gcloud run services describe "$DETECTOR_SERVICE_NAME_HEAVY_ACTIVE" \
        --region "$DETECTOR_SERVICE_REGION_HEAVY_ACTIVE" \
        --project "$DETECTOR_TASKS_PROJECT" \
        --format='value(status.url)' 2>/dev/null || true
    )"
  fi
fi

if [[ -z "${DETECTOR_SERVICE_URL_LIGHT_ACTIVE:-}" ]]; then
  echo "Missing detector URL for ${DETECTOR_SERVICE_NAME_LIGHT_ACTIVE}. Deploy it or set the matching URL in $ENV_FILE." >&2
  exit 1
fi

if [[ -z "${DETECTOR_SERVICE_URL_HEAVY_ACTIVE:-}" ]]; then
  echo "Missing detector URL for ${DETECTOR_SERVICE_NAME_HEAVY_ACTIVE}. Deploy it or set the matching URL in $ENV_FILE." >&2
  exit 1
fi

DETECTOR_SERVICE_URL_LIGHT="$DETECTOR_SERVICE_URL_LIGHT_ACTIVE"
DETECTOR_SERVICE_URL_HEAVY="$DETECTOR_SERVICE_URL_HEAVY_ACTIVE"
DETECTOR_SERVICE_URL="$DETECTOR_SERVICE_URL_LIGHT"
DETECTOR_TASKS_AUDIENCE_LIGHT_FALLBACK="$DETECTOR_SERVICE_URL_LIGHT"
DETECTOR_TASKS_AUDIENCE_HEAVY_FALLBACK="$DETECTOR_SERVICE_URL_HEAVY"
if detector_is_truthy "${DETECTOR_USE_STABLE_AUDIENCE:-false}"; then
  DETECTOR_TASKS_AUDIENCE_LIGHT_FALLBACK="$(build_detector_stable_audience "$DETECTOR_SERVICE_NAME_LIGHT_ACTIVE")"
  DETECTOR_TASKS_AUDIENCE_HEAVY_FALLBACK="$(build_detector_stable_audience "$DETECTOR_SERVICE_NAME_HEAVY_ACTIVE")"
fi
DETECTOR_TASKS_AUDIENCE_LIGHT="$(
  detector_tasks_audience_for_target \
    "$DETECTOR_TARGET_LIGHT_ACTIVE" \
    "light" \
    "$DETECTOR_TASKS_AUDIENCE_LIGHT_FALLBACK"
)"
DETECTOR_TASKS_AUDIENCE_HEAVY="$(
  detector_tasks_audience_for_target \
    "$DETECTOR_TARGET_HEAVY_ACTIVE" \
    "heavy" \
    "$DETECTOR_TASKS_AUDIENCE_HEAVY_FALLBACK"
)"
DETECTOR_TASKS_AUDIENCE="$DETECTOR_TASKS_AUDIENCE_LIGHT"
echo "Detector routing mode: ${DETECTOR_ROUTING_MODE} (light=${DETECTOR_TARGET_LIGHT_ACTIVE}:${DETECTOR_SERVICE_NAME_LIGHT_ACTIVE}@${DETECTOR_SERVICE_REGION_LIGHT_ACTIVE}, heavy=${DETECTOR_TARGET_HEAVY_ACTIVE}:${DETECTOR_SERVICE_NAME_HEAVY_ACTIVE}@${DETECTOR_SERVICE_REGION_HEAVY_ACTIVE})"

# Default to local OpenAI execution for dev stack unless task mode is explicitly enabled.
OPENAI_RENAME_REMAP_MODE="${OPENAI_RENAME_REMAP_MODE:-local}"

OPENAI_RENAME_REMAP_TASKS_PROJECT="${OPENAI_RENAME_REMAP_TASKS_PROJECT:-${DETECTOR_TASKS_PROJECT:-${FIREBASE_PROJECT_ID:-}}}"
OPENAI_RENAME_REMAP_TASKS_LOCATION="${OPENAI_RENAME_REMAP_TASKS_LOCATION:-${DETECTOR_TASKS_LOCATION:-us-east4}}"
OPENAI_RENAME_REMAP_TASKS_QUEUE="${OPENAI_RENAME_REMAP_TASKS_QUEUE:-openai-rename-remap}"
OPENAI_RENAME_REMAP_TASKS_SERVICE_ACCOUNT="${OPENAI_RENAME_REMAP_TASKS_SERVICE_ACCOUNT:-${DETECTOR_TASKS_SERVICE_ACCOUNT}}"
OPENAI_RENAME_REMAP_TASKS_AUDIENCE="${OPENAI_RENAME_REMAP_TASKS_AUDIENCE:-}"
OPENAI_RENAME_REMAP_CONFIGURED_SERVICE_URL="${OPENAI_RENAME_REMAP_SERVICE_URL:-}"

if command -v gcloud >/dev/null 2>&1; then
  if [[ "${OPENAI_RENAME_REMAP_MODE}" == "tasks" && -n "${OPENAI_RENAME_REMAP_TASKS_PROJECT:-}" ]]; then
    RESOLVED_OPENAI_RENAME_REMAP_SERVICE_URL="$(
      gcloud run services describe dullypdf-openai-rename-remap \
        --region "$OPENAI_RENAME_REMAP_TASKS_LOCATION" \
        --project "$OPENAI_RENAME_REMAP_TASKS_PROJECT" \
        --format='value(status.url)' 2>/dev/null || true
    )"
    RESOLVED_OPENAI_RENAME_REMAP_SERVICE_URL="${RESOLVED_OPENAI_RENAME_REMAP_SERVICE_URL%/}"
    OPENAI_RENAME_REMAP_CONFIGURED_SERVICE_URL="${OPENAI_RENAME_REMAP_CONFIGURED_SERVICE_URL%/}"
    OPENAI_RENAME_REMAP_TASKS_AUDIENCE="${OPENAI_RENAME_REMAP_TASKS_AUDIENCE%/}"

    if [[ -n "${RESOLVED_OPENAI_RENAME_REMAP_SERVICE_URL:-}" ]]; then
      # The dev Cloud Run URL can change across redeploys. When the tracked env
      # still points at an older public URL, Cloud Tasks mints a token with the
      # wrong audience and the worker rejects every request with 401. Refresh the
      # local stack to the live Cloud Run URL whenever the configured service URL
      # matches the configured audience or is unset, which keeps the stack
      # aligned with the current worker revision in O(1) time at startup.
      if [[ -z "$OPENAI_RENAME_REMAP_CONFIGURED_SERVICE_URL" || "$OPENAI_RENAME_REMAP_CONFIGURED_SERVICE_URL" == "$OPENAI_RENAME_REMAP_TASKS_AUDIENCE" ]]; then
        if [[ -n "$OPENAI_RENAME_REMAP_CONFIGURED_SERVICE_URL" && "$OPENAI_RENAME_REMAP_CONFIGURED_SERVICE_URL" != "$RESOLVED_OPENAI_RENAME_REMAP_SERVICE_URL" ]]; then
          echo "Refreshing OpenAI worker URL from Cloud Run to avoid stale OIDC audiences."
        fi
        OPENAI_RENAME_REMAP_SERVICE_URL="$RESOLVED_OPENAI_RENAME_REMAP_SERVICE_URL"
        OPENAI_RENAME_REMAP_TASKS_AUDIENCE="$RESOLVED_OPENAI_RENAME_REMAP_SERVICE_URL"
      elif [[ "$OPENAI_RENAME_REMAP_CONFIGURED_SERVICE_URL" != "$RESOLVED_OPENAI_RENAME_REMAP_SERVICE_URL" ]]; then
        echo "Warning: OPENAI_RENAME_REMAP_SERVICE_URL differs from the live Cloud Run URL; using configured value from $ENV_FILE." >&2
        OPENAI_RENAME_REMAP_SERVICE_URL="$OPENAI_RENAME_REMAP_CONFIGURED_SERVICE_URL"
      else
        OPENAI_RENAME_REMAP_SERVICE_URL="$OPENAI_RENAME_REMAP_CONFIGURED_SERVICE_URL"
      fi
    else
      OPENAI_RENAME_REMAP_SERVICE_URL="$OPENAI_RENAME_REMAP_CONFIGURED_SERVICE_URL"
    fi
  fi
fi

if [[ "${OPENAI_RENAME_REMAP_MODE}" == "tasks" ]]; then
  if [[ -z "${OPENAI_RENAME_REMAP_SERVICE_URL:-}" ]]; then
    echo "Missing OPENAI_RENAME_REMAP_SERVICE_URL. Deploy dullypdf-openai-rename-remap or set it in $ENV_FILE." >&2
    exit 1
  fi
fi

OPENAI_RENAME_REMAP_SERVICE_URL="${OPENAI_RENAME_REMAP_SERVICE_URL:-}"
OPENAI_RENAME_REMAP_TASKS_AUDIENCE="${OPENAI_RENAME_REMAP_TASKS_AUDIENCE:-${OPENAI_RENAME_REMAP_SERVICE_URL:-}}"

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
FORWARD_TO="${STRIPE_DEV_FORWARD_URL:-http://${BACKEND_HEALTH_HOST}:${BACKEND_PORT}/api/billing/webhook}"
EVENTS="${STRIPE_DEV_FORWARD_EVENTS:-checkout.session.completed,invoice.paid,customer.subscription.updated,customer.subscription.deleted}"
ENABLE_LISTENER_RAW="${STRIPE_DEV_LISTEN_ENABLED:-true}"
ENABLE_LISTENER="$(printf '%s' "$ENABLE_LISTENER_RAW" | tr '[:upper:]' '[:lower:]')"
STACK_WEBHOOK_ENDPOINT_URL="${STRIPE_WEBHOOK_ENDPOINT_URL:-${FORWARD_TO}}"

if [[ "$DEV_STACK_PROD_TOPOLOGY" == "true" ]]; then
  export SIGNING_APP_ORIGIN="${SIGNING_APP_ORIGIN:-http://localhost:${FRONTEND_PORT}}"
fi

LISTENER_PID=""
LISTENER_LOG=""
BACKEND_PID=""

DEV_STACK_NO_DOCKER_RAW="${DEV_STACK_NO_DOCKER:-true}"
DEV_STACK_NO_DOCKER="$(printf '%s' "$DEV_STACK_NO_DOCKER_RAW" | tr '[:upper:]' '[:lower:]')"

HAS_DOCKER=true
if [[ "$DEV_STACK_NO_DOCKER" == "true" || "$DEV_STACK_NO_DOCKER" == "1" || "$DEV_STACK_NO_DOCKER" == "yes" ]]; then
  HAS_DOCKER=false
  echo "Running backend locally via uvicorn (DEV_STACK_NO_DOCKER=true)."
elif ! docker version >/dev/null 2>&1; then
  HAS_DOCKER=false
  echo "Docker not available; will run backend locally via uvicorn."
fi

cleanup() {
  if [[ -n "$LISTENER_PID" ]] && kill -0 "$LISTENER_PID" >/dev/null 2>&1; then
    kill "$LISTENER_PID" >/dev/null 2>&1 || true
    wait "$LISTENER_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "$LISTENER_LOG" && -f "$LISTENER_LOG" ]]; then
    rm -f "$LISTENER_LOG" || true
  fi
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
    wait "$BACKEND_PID" >/dev/null 2>&1 || true
  fi
  if [[ "$HAS_DOCKER" == "true" ]] && docker ps -a --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"; then
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  fi
  if [[ -n "${CREDS_FILE_TEMP:-}" && -f "${CREDS_FILE_TEMP:-}" ]]; then
    rm -f "$CREDS_FILE_TEMP" || true
  fi
}

trap cleanup EXIT INT TERM

if [[ "$HAS_DOCKER" == "true" ]]; then
  if [[ "${DEV_STACK_BUILD:-}" == "1" ]] || ! docker image inspect "$IMAGE_TAG" >/dev/null 2>&1; then
    docker build -t "$IMAGE_TAG" -f Dockerfile .
  fi

  if [[ "${DEV_STACK_BUILD:-}" == "1" ]]; then
    if [[ "${DETECTOR_MODE}" == "tasks" ]]; then
      echo "DEV_STACK_BUILD=1 -> deploying detector Cloud Run services (${DETECTOR_SERVICE_NAME_LIGHT_ACTIVE}, ${DETECTOR_SERVICE_NAME_HEAVY_ACTIVE}) to keep stack config in sync..."
      DETECTOR_ROUTING_MODE="$DETECTOR_ROUTING_MODE" \
      DETECTOR_SERVICE_REGION="$DETECTOR_SERVICE_REGION" \
      DETECTOR_GPU_REGION="${DETECTOR_GPU_REGION:-$(detector_gpu_region)}" \
        bash scripts/deploy-detector-services.sh "$ENV_FILE"
    fi
    if [[ "${OPENAI_RENAME_REMAP_MODE}" == "tasks" ]]; then
      echo "DEV_STACK_BUILD=1 -> deploying OpenAI worker Cloud Run service to keep stack config in sync..."
      bash scripts/deploy-openai-workers.sh "$ENV_FILE"
    fi
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
fi

if [[ "$ENABLE_LISTENER" != "false" && "$ENABLE_LISTENER" != "0" && "$ENABLE_LISTENER" != "no" ]]; then
  if [[ -z "${STRIPE_SECRET_KEY:-}" ]]; then
    echo "Stripe forwarding skipped for dev stack: STRIPE_SECRET_KEY is missing in $ENV_FILE."
  elif ! command -v stripe >/dev/null 2>&1; then
    echo "Stripe forwarding skipped for dev stack: Stripe CLI is not installed."
  else
    LISTENER_LOG="$(mktemp -t dullypdf-stripe-stack-listen-XXXX.log)"
    echo "Starting Stripe CLI forwarding for dev stack to ${FORWARD_TO}"
    echo "Forwarded events: ${EVENTS}"
    STRIPE_API_KEY="${STRIPE_SECRET_KEY}" stripe listen --events "$EVENTS" --forward-to "$FORWARD_TO" \
      > >(tee -a "$LISTENER_LOG") \
      2> >(tee -a "$LISTENER_LOG" >&2) &
    LISTENER_PID="$!"

    secret=""
    deadline=$((SECONDS + 20))
    while (( SECONDS < deadline )); do
      if ! kill -0 "$LISTENER_PID" >/dev/null 2>&1; then
        echo "Stripe listener exited before readiness. See output above for details." >&2
        exit 1
      fi
      secret="$(grep -Eo 'whsec_[A-Za-z0-9]+' "$LISTENER_LOG" | tail -n 1 || true)"
      if [[ -n "$secret" ]]; then
        break
      fi
      sleep 0.2
    done

    if [[ -z "$secret" ]]; then
      echo "Failed to capture Stripe webhook signing secret from listener output." >&2
      exit 1
    fi

    # Stripe CLI forwarding is tunnel-based and does not create a dashboard
    # webhook endpoint, so stack-mode checkout health enforcement must be off.
    export STRIPE_WEBHOOK_SECRET="$secret"
    export STRIPE_ENFORCE_WEBHOOK_HEALTH=false
    export STRIPE_WEBHOOK_ENDPOINT_URL="$STACK_WEBHOOK_ENDPOINT_URL"
    echo "Stripe forwarding active for dev stack. Using ephemeral webhook secret from this listener session."
  fi
fi

if [[ "$HAS_DOCKER" == "true" ]]; then
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
    "-e" "OPENAI_RENAME_REMAP_MODE=${OPENAI_RENAME_REMAP_MODE}"
    "-e" "OPENAI_RENAME_REMAP_TASKS_PROJECT=${OPENAI_RENAME_REMAP_TASKS_PROJECT}"
    "-e" "OPENAI_RENAME_REMAP_TASKS_LOCATION=${OPENAI_RENAME_REMAP_TASKS_LOCATION}"
    "-e" "OPENAI_RENAME_REMAP_TASKS_QUEUE=${OPENAI_RENAME_REMAP_TASKS_QUEUE}"
    "-e" "OPENAI_RENAME_REMAP_SERVICE_URL=${OPENAI_RENAME_REMAP_SERVICE_URL:-}"
    "-e" "OPENAI_RENAME_REMAP_TASKS_SERVICE_ACCOUNT=${OPENAI_RENAME_REMAP_TASKS_SERVICE_ACCOUNT}"
    "-e" "OPENAI_RENAME_REMAP_TASKS_AUDIENCE=${OPENAI_RENAME_REMAP_TASKS_AUDIENCE:-}"
    "-e" "OPENAI_PREWARM_ENABLED=${OPENAI_PREWARM_ENABLED:-true}"
    "-e" "OPENAI_PREWARM_REMAINING_PAGES=${OPENAI_PREWARM_REMAINING_PAGES:-3}"
    "-e" "OPENAI_PREWARM_TIMEOUT_SECONDS=${OPENAI_PREWARM_TIMEOUT_SECONDS:-2}"
    "-e" "SANDBOX_ENABLE_LEGACY_ENDPOINTS=false"
    "-e" "STRIPE_WEBHOOK_ENDPOINT_URL=${STRIPE_WEBHOOK_ENDPOINT_URL:-${STACK_WEBHOOK_ENDPOINT_URL}}"
    "-e" "ADMIN_TOKEN="
    "-e" "SANDBOX_DEBUG=false"
    "-e" "SANDBOX_DEBUG_FORCE=false"
    "-e" "SANDBOX_DEBUG_PASSWORD="
  )

  if [[ -n "${OPENAI_API_KEY:-}" ]]; then
    ENV_ARGS+=("-e" "OPENAI_API_KEY=${OPENAI_API_KEY}")
  fi
  if [[ -n "${STRIPE_WEBHOOK_SECRET:-}" ]]; then
    ENV_ARGS+=("-e" "STRIPE_WEBHOOK_SECRET=${STRIPE_WEBHOOK_SECRET}")
  fi
  if [[ -n "${STRIPE_ENFORCE_WEBHOOK_HEALTH:-}" ]]; then
    ENV_ARGS+=("-e" "STRIPE_ENFORCE_WEBHOOK_HEALTH=${STRIPE_ENFORCE_WEBHOOK_HEALTH}")
  fi

  docker run --rm -d \
    --name "$CONTAINER_NAME" \
    -p "${BACKEND_BIND}:${BACKEND_PORT}:8000" \
    --env-file "$ENV_FILE" \
    "${ENV_ARGS[@]}" \
    -v "${CREDS_FILE}:/var/secrets/firebase-admin.json:ro" \
    "$IMAGE_TAG" >/dev/null
else
  # No Docker: run backend locally via uvicorn
  export PORT="${BACKEND_PORT}"
  VENV_UVICORN="backend/.venv/bin/uvicorn"
  if [[ -x "$VENV_UVICORN" ]]; then
    "$VENV_UVICORN" backend.main:app --host "${BACKEND_BIND}" --port "${BACKEND_PORT}" --reload --reload-dir backend &
  else
    echo "Warning: backend/.venv not found. Using system python." >&2
    uvicorn backend.main:app --host "${BACKEND_BIND}" --port "${BACKEND_PORT}" --reload --reload-dir backend &
  fi
  BACKEND_PID="$!"
fi

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
      if [[ "$HAS_DOCKER" == "true" ]]; then
        echo "Last backend logs:" >&2
        docker logs --tail 120 "${CONTAINER_NAME}" >&2 || true
      fi
      return 1
    fi
    sleep "${BACKEND_READY_INTERVAL_SECONDS}"
  done
}

wait_for_backend_health

echo "Backend (dev stack) running at http://${BACKEND_BIND}:${BACKEND_PORT}"
echo "Frontend starting at http://localhost:${FRONTEND_PORT}"

bash scripts/use-frontend-env.sh "${FRONTEND_ENV_MODE}"
cd frontend
VITE_API_URL="http://localhost:${BACKEND_PORT}" \
VITE_DETECTION_API_URL="http://localhost:${BACKEND_PORT}" \
VITE_ADMIN_TOKEN="" \
npm run dev -- --port "${FRONTEND_PORT}"
