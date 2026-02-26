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

PROJECT_ID="${PROJECT_ID:-${FIREBASE_PROJECT_ID:-dullypdf}}"
REGION="${REGION:-${DETECTOR_TASKS_LOCATION:-${OPENAI_RENAME_TASKS_LOCATION:-us-central1}}}"
ALLOW_NON_PROD="${DULLYPDF_ALLOW_NON_PROD:-}"

if [[ "${ENV:-}" != "prod" ]]; then
  echo "Expected ENV=prod in $ENV_FILE for deploy:all-services." >&2
  exit 1
fi

if [[ "$PROJECT_ID" != "dullypdf" && -z "$ALLOW_NON_PROD" ]]; then
  echo "Refusing to deploy all services to non-prod project: $PROJECT_ID. Set DULLYPDF_ALLOW_NON_PROD=1 to override." >&2
  exit 1
fi

run_cmd() {
  echo "+ $*"
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    return 0
  fi
  "$@"
}

echo "Deploying all services for project=${PROJECT_ID} region=${REGION}"
if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "DRY_RUN=1 enabled; commands will be printed but not executed."
fi

run_cmd env PROJECT_ID="$PROJECT_ID" REGION="$REGION" ENV_FILE="$ENV_FILE" bash scripts/deploy-backend.sh
run_cmd env PROJECT_ID="$PROJECT_ID" REGION="$REGION" bash scripts/deploy-detector-services.sh "$ENV_FILE"
run_cmd env PROJECT_ID="$PROJECT_ID" REGION="$REGION" bash scripts/deploy-openai-workers.sh "$ENV_FILE"
if [[ -n "${FRONTEND_ENV_OVERRIDE_FILE:-}" ]]; then
  run_cmd env PROJECT_ID="$PROJECT_ID" ENV_FILE="$FRONTEND_ENV_OVERRIDE_FILE" bash scripts/deploy-frontend.sh
else
  run_cmd env PROJECT_ID="$PROJECT_ID" bash scripts/deploy-frontend.sh
fi

echo "All service deploy steps completed."
