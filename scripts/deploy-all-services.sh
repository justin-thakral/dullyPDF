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
REGION="${REGION:-${DETECTOR_TASKS_LOCATION:-${OPENAI_RENAME_TASKS_LOCATION:-us-east4}}}"
BACKEND_REGION="${BACKEND_REGION:-us-east4}"
BACKEND_SERVICE="${BACKEND_SERVICE:-dullypdf-backend-east4}"
ARTIFACT_REGISTRY_LOCATION="${ARTIFACT_REGISTRY_LOCATION:-us-east4}"
BACKEND_ARTIFACT_REPO="${BACKEND_ARTIFACT_REPO:-dullypdf-backend}"
ALLOW_NON_PROD="${DULLYPDF_ALLOW_NON_PROD:-}"

if [[ "${ENV:-}" != "prod" ]]; then
  echo "Expected ENV=prod in $ENV_FILE for deploy:all-services." >&2
  exit 1
fi

if [[ "$PROJECT_ID" != "dullypdf" && -z "$ALLOW_NON_PROD" ]]; then
  echo "Refusing to deploy all services to non-prod project: $PROJECT_ID. Set DULLYPDF_ALLOW_NON_PROD=1 to override." >&2
  exit 1
fi

if [[ "$PROJECT_ID" == "dullypdf" && "$BACKEND_SERVICE" == "dullypdf-backend" ]]; then
  echo "Refusing to deploy all services with retired prod backend service name dullypdf-backend." >&2
  echo "Use BACKEND_SERVICE=dullypdf-backend-east4 instead." >&2
  exit 1
fi

require_prod_artifact_registry_location "Artifact Registry location" "$ARTIFACT_REGISTRY_LOCATION"
require_prod_artifact_registry_repo "BACKEND_ARTIFACT_REPO" "$BACKEND_ARTIFACT_REPO"

run_cmd() {
  echo "+ $*"
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    return 0
  fi
  "$@"
}

echo "Deploying all services for project=${PROJECT_ID} worker_region=${REGION} backend_region=${BACKEND_REGION} backend_service=${BACKEND_SERVICE}"
if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "DRY_RUN=1 enabled; commands will be printed but not executed."
fi

BACKEND_IMAGE="${BACKEND_IMAGE:-${ARTIFACT_REGISTRY_LOCATION}-docker.pkg.dev/${PROJECT_ID}/${BACKEND_ARTIFACT_REPO}/backend:$(date +%Y%m%d-%H%M%S)}"
require_prod_artifact_registry_image "BACKEND_IMAGE" "$BACKEND_IMAGE" "$BACKEND_ARTIFACT_REPO"

run_cmd env PROJECT_ID="$PROJECT_ID" REGION="$REGION" ARTIFACT_REGISTRY_LOCATION="$ARTIFACT_REGISTRY_LOCATION" bash scripts/deploy-detector-services.sh "$ENV_FILE"
run_cmd env PROJECT_ID="$PROJECT_ID" REGION="$REGION" ARTIFACT_REGISTRY_LOCATION="$ARTIFACT_REGISTRY_LOCATION" bash scripts/deploy-openai-workers.sh "$ENV_FILE"
run_cmd env PROJECT_ID="$PROJECT_ID" REGION="$REGION" BACKEND_REGION="$BACKEND_REGION" BACKEND_SERVICE="$BACKEND_SERVICE" ARTIFACT_REGISTRY_LOCATION="$ARTIFACT_REGISTRY_LOCATION" BACKEND_ARTIFACT_REPO="$BACKEND_ARTIFACT_REPO" ENV_FILE="$ENV_FILE" BACKEND_IMAGE="$BACKEND_IMAGE" bash scripts/deploy-backend.sh
run_cmd env PROJECT_ID="$PROJECT_ID" REGION="$REGION" SESSION_CLEANUP_REGION="$BACKEND_REGION" SESSION_CLEANUP_IMAGE_SOURCE_REGION="$BACKEND_REGION" SESSION_CLEANUP_IMAGE_SOURCE_SERVICE="$BACKEND_SERVICE" ENV_FILE="$ENV_FILE" BACKEND_IMAGE="$BACKEND_IMAGE" bash scripts/deploy-session-cleanup-job.sh "$ENV_FILE"
run_cmd env PROJECT_ID="$PROJECT_ID" DULLYPDF_ALLOW_NON_PROD="${ALLOW_NON_PROD}" bash scripts/deploy-firestore-indexes.sh
if [[ -n "${FRONTEND_ENV_OVERRIDE_FILE:-}" ]]; then
  run_cmd env PROJECT_ID="$PROJECT_ID" ENV_FILE="$FRONTEND_ENV_OVERRIDE_FILE" bash scripts/deploy-frontend.sh
else
  run_cmd env PROJECT_ID="$PROJECT_ID" bash scripts/deploy-frontend.sh
fi
run_cmd env PROJECT_ID="$PROJECT_ID" REGION="$REGION" ENV_FILE="$ENV_FILE" bash scripts/prune-stale-cloud-resources.sh "$ENV_FILE"

echo "All service deploy steps completed."
