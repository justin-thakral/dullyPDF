#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-env/backend.prod.env}"
BACKEND_EXAMPLE="config/backend.prod.env.example"

if [[ ! -f "$ENV_FILE" ]]; then
  if [[ -f "$BACKEND_EXAMPLE" ]]; then
    mkdir -p "env"
    cp "$BACKEND_EXAMPLE" "$ENV_FILE"
    echo "Created $ENV_FILE from $BACKEND_EXAMPLE. Update values and re-run." >&2
    exit 1
  fi
  echo "Missing $ENV_FILE and $BACKEND_EXAMPLE." >&2
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_artifact_registry_guard.sh"

PROJECT_ID="${PROJECT_ID:-${FIREBASE_PROJECT_ID:-dullypdf}}"
ALLOW_NON_PROD="${DULLYPDF_ALLOW_NON_PROD:-}"
REGION="${SESSION_CLEANUP_REGION:-${BACKEND_REGION:-${IMAGE_SOURCE_REGION:-us-east4}}}"
JOB_NAME="${SESSION_CLEANUP_JOB_NAME:-dullypdf-session-cleanup}"
LEGACY_JOB_REGION="${SESSION_CLEANUP_LEGACY_REGION:-us-central1}"
SESSION_CLEANUP_SERVICE_ACCOUNT="${SESSION_CLEANUP_SERVICE_ACCOUNT:-dullypdf-cleanup@${PROJECT_ID}.iam.gserviceaccount.com}"
SESSION_CLEANUP_SKIP_SCHEDULER="${SESSION_CLEANUP_SKIP_SCHEDULER:-false}"
SESSION_CLEANUP_TIMEOUT_SECONDS="${SESSION_CLEANUP_TIMEOUT_SECONDS:-600}"
SESSION_CLEANUP_MAX_RETRIES="${SESSION_CLEANUP_MAX_RETRIES:-3}"
SESSION_CLEANUP_TASK_COUNT="${SESSION_CLEANUP_TASK_COUNT:-1}"
SESSION_CLEANUP_CPU="${SESSION_CLEANUP_CPU:-1}"
SESSION_CLEANUP_MEMORY="${SESSION_CLEANUP_MEMORY:-512Mi}"
SESSION_CLEANUP_IMAGE="${SESSION_CLEANUP_IMAGE:-${BACKEND_IMAGE:-}}"
IMAGE_SOURCE_SERVICE="${SESSION_CLEANUP_IMAGE_SOURCE_SERVICE:-dullypdf-backend-east4}"
IMAGE_SOURCE_REGION="${SESSION_CLEANUP_IMAGE_SOURCE_REGION:-us-east4}"

require_nonempty() {
  local name="$1"
  local actual="${!name:-}"
  if [[ -z "$actual" ]]; then
    echo "Missing required $name in $ENV_FILE (or exported env)." >&2
    exit 1
  fi
}

require_exact() {
  local name="$1"
  local expected="$2"
  local actual="${!name:-}"
  if [[ "$actual" != "$expected" ]]; then
    echo "Expected $name=$expected (got '${actual}')." >&2
    exit 1
  fi
}

require_integer_ge() {
  local name="$1"
  local min_value="$2"
  local actual="${!name:-}"
  if [[ -z "$actual" ]]; then
    echo "Missing required $name in $ENV_FILE (or exported env)." >&2
    exit 1
  fi
  if ! [[ "$actual" =~ ^[0-9]+$ ]]; then
    echo "Expected $name to be an integer >= ${min_value} (got '${actual}')." >&2
    exit 1
  fi
  if (( actual < min_value )); then
    echo "Expected $name to be >= ${min_value} (got '${actual}')." >&2
    exit 1
  fi
}

if [[ "${ENV:-}" != "prod" ]]; then
  echo "Expected ENV=prod in $ENV_FILE for session-cleanup deploy." >&2
  exit 1
fi

if [[ "$PROJECT_ID" != "dullypdf" && -z "$ALLOW_NON_PROD" ]]; then
  echo "Refusing to deploy session cleanup job to non-prod project: $PROJECT_ID. Set DULLYPDF_ALLOW_NON_PROD=1 to override." >&2
  exit 1
fi

if [[ "$PROJECT_ID" == "dullypdf" && "$REGION" != "us-east4" ]]; then
  echo "Refusing to deploy prod session cleanup job outside us-east4 (got ${REGION})." >&2
  exit 1
fi

require_exact FIREBASE_USE_ADC "true"
require_nonempty FIREBASE_PROJECT_ID
require_nonempty SANDBOX_SESSION_BUCKET
require_nonempty SESSION_CLEANUP_SERVICE_ACCOUNT
require_integer_ge SANDBOX_SESSION_TTL_SECONDS 1
require_integer_ge SESSION_CLEANUP_GRACE_SECONDS 0
require_integer_ge SESSION_CLEANUP_TIMEOUT_SECONDS 1
require_integer_ge SESSION_CLEANUP_MAX_RETRIES 0
require_integer_ge SESSION_CLEANUP_TASK_COUNT 1

if [[ -z "$SESSION_CLEANUP_IMAGE" ]]; then
  SESSION_CLEANUP_IMAGE="$(
    gcloud run services describe "$IMAGE_SOURCE_SERVICE" \
      --region "$IMAGE_SOURCE_REGION" \
      --project "$PROJECT_ID" \
      --format='value(spec.template.spec.containers[0].image)'
  )"
fi
require_nonempty SESSION_CLEANUP_IMAGE
require_prod_artifact_registry_image "SESSION_CLEANUP_IMAGE" "$SESSION_CLEANUP_IMAGE"

gcloud run jobs deploy "$JOB_NAME" \
  --image "$SESSION_CLEANUP_IMAGE" \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --service-account "$SESSION_CLEANUP_SERVICE_ACCOUNT" \
  --tasks "$SESSION_CLEANUP_TASK_COUNT" \
  --max-retries "$SESSION_CLEANUP_MAX_RETRIES" \
  --task-timeout "${SESSION_CLEANUP_TIMEOUT_SECONDS}s" \
  --cpu "$SESSION_CLEANUP_CPU" \
  --memory "$SESSION_CLEANUP_MEMORY" \
  --command "python3" \
  --args "/app/scripts/cleanup_sessions.py,--execute" \
  --set-env-vars "ENV=prod,FIREBASE_PROJECT_ID=${FIREBASE_PROJECT_ID},FIREBASE_USE_ADC=true,SANDBOX_SESSION_BUCKET=${SANDBOX_SESSION_BUCKET},SANDBOX_SESSION_TTL_SECONDS=${SANDBOX_SESSION_TTL_SECONDS},SESSION_CLEANUP_GRACE_SECONDS=${SESSION_CLEANUP_GRACE_SECONDS}"

if [[ "$PROJECT_ID" == "dullypdf" && "$LEGACY_JOB_REGION" != "$REGION" ]]; then
  gcloud run jobs delete "$JOB_NAME" \
    --region "$LEGACY_JOB_REGION" \
    --project "$PROJECT_ID" \
    --quiet >/dev/null 2>&1 || true
fi

case "${SESSION_CLEANUP_SKIP_SCHEDULER,,}" in
  1|true|yes|on)
    ;;
  *)
    bash "${SCRIPT_DIR}/deploy-session-cleanup-scheduler.sh" "$ENV_FILE"
    ;;
esac
