#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash scripts/ci/deploy_backend_target.sh --environment <dev|prod> [options]

Options:
  --environment <dev|prod>  Target environment
  --env-file <path>         Backend env file override
  --backend-image <image>   Full backend image reference override
  --dry-run                 Print the derived deploy command without executing it
EOF
}

DEPLOY_ENV=""
ENV_FILE_OVERRIDE=""
BACKEND_IMAGE_OVERRIDE=""
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --environment)
      DEPLOY_ENV="${2:-}"
      shift 2
      ;;
    --env-file)
      ENV_FILE_OVERRIDE="${2:-}"
      shift 2
      ;;
    --backend-image)
      BACKEND_IMAGE_OVERRIDE="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ "$DEPLOY_ENV" != "dev" && "$DEPLOY_ENV" != "prod" ]]; then
  echo "Expected --environment dev|prod." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [[ "$DEPLOY_ENV" == "prod" ]]; then
  ENV_FILE="${ENV_FILE_OVERRIDE:-env/backend.prod.env}"
  CMD=(bash scripts/deploy-backend.sh)
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "+ ENV_FILE=${ENV_FILE} BACKEND_IMAGE=${BACKEND_IMAGE_OVERRIDE:-<auto>} bash scripts/deploy-backend.sh"
    exit 0
  fi
  env \
    ENV_FILE="$ENV_FILE" \
    BACKEND_IMAGE="${BACKEND_IMAGE_OVERRIDE:-}" \
    "${CMD[@]}"
  exit 0
fi

ENV_FILE="${ENV_FILE_OVERRIDE:-env/backend.dev.stack.env}"
if [[ "$ENV_FILE" != /* ]]; then
  ENV_FILE="${REPO_ROOT}/${ENV_FILE}"
fi
if [[ ! -f "$ENV_FILE" ]]; then
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "Dry run: backend env file not present on runner (${ENV_FILE}); command preview will use that path verbatim."
  else
    echo "Missing backend env file: ${ENV_FILE}" >&2
    exit 1
  fi
fi

PROJECT_ID="${PROJECT_ID:-dullypdf-dev}"
BACKEND_REGION="${BACKEND_REGION:-us-east4}"
BACKEND_SERVICE="${BACKEND_SERVICE:-dullypdf-backend-east4}"
BACKEND_RUNTIME_SERVICE_ACCOUNT="${BACKEND_RUNTIME_SERVICE_ACCOUNT:-dullypdf-backend-runtime@dullypdf-dev.iam.gserviceaccount.com}"
ARTIFACT_REGISTRY_LOCATION="${ARTIFACT_REGISTRY_LOCATION:-us-east4}"
BACKEND_ARTIFACT_REPO="${BACKEND_ARTIFACT_REPO:-dullypdf-backend}"
BACKEND_REQUEST_TIMEOUT="${BACKEND_REQUEST_TIMEOUT:-900}"
BACKEND_MEMORY="${BACKEND_MEMORY:-1Gi}"
BACKEND_CPU="${BACKEND_CPU:-2}"
BACKEND_MIN_INSTANCES="${BACKEND_MIN_INSTANCES:-}"

# Standardize dev on us-east4 so dev mirrors prod and we don't recreate a
# parallel service in another region (as happened during us-central1 drift).
if [[ "$BACKEND_REGION" != "us-east4" ]]; then
  echo "Refusing to deploy dev backend outside us-east4 (got BACKEND_REGION=${BACKEND_REGION})." >&2
  exit 1
fi
if [[ "$BACKEND_SERVICE" != "dullypdf-backend-east4" ]]; then
  echo "Refusing to deploy dev backend under non-standard service name: ${BACKEND_SERVICE}." >&2
  exit 1
fi

if [[ -n "$BACKEND_IMAGE_OVERRIDE" ]]; then
  BACKEND_IMAGE="$BACKEND_IMAGE_OVERRIDE"
else
  TAG="$(date +%Y%m%d-%H%M%S)"
  BACKEND_IMAGE="${ARTIFACT_REGISTRY_LOCATION}-docker.pkg.dev/${PROJECT_ID}/${BACKEND_ARTIFACT_REPO}/backend:${TAG}"
fi

if [[ "$DRY_RUN" == "1" ]]; then
  echo "+ gcloud builds submit --tag ${BACKEND_IMAGE} --project ${PROJECT_ID} ."
  echo "+ python3 scripts/ci/render_env_yaml.py ${ENV_FILE} <tmp-env-yaml> --omit PORT --omit DEV_STACK_NO_DOCKER --omit FIREBASE_CREDENTIALS --omit GOOGLE_APPLICATION_CREDENTIALS --omit FIREBASE_CREDENTIALS_SECRET --omit FIREBASE_CREDENTIALS_PROJECT ..."
  echo "+ gcloud run deploy ${BACKEND_SERVICE} --image ${BACKEND_IMAGE} --region ${BACKEND_REGION} --project ${PROJECT_ID} --service-account ${BACKEND_RUNTIME_SERVICE_ACCOUNT} --allow-unauthenticated --env-vars-file <tmp-env-yaml> --timeout ${BACKEND_REQUEST_TIMEOUT}"
  if [[ -n "$BACKEND_MIN_INSTANCES" ]]; then
    echo "+   --min ${BACKEND_MIN_INSTANCES}"
  fi
  exit 0
fi

TMP_ENV_FILE="$(mktemp)"
cleanup() {
  rm -f "$TMP_ENV_FILE" || true
}
trap cleanup EXIT

python3 "${REPO_ROOT}/scripts/ci/render_env_yaml.py" \
  "$ENV_FILE" \
  "$TMP_ENV_FILE" \
  --omit PORT \
  --omit DEV_STACK_NO_DOCKER \
  --omit FIREBASE_CREDENTIALS \
  --omit GOOGLE_APPLICATION_CREDENTIALS \
  --omit FIREBASE_CREDENTIALS_SECRET \
  --omit FIREBASE_CREDENTIALS_PROJECT \
  --set "ENV=dev" \
  --set "FIREBASE_USE_ADC=true" \
  --set "SIGNING_APP_ORIGIN=https://${PROJECT_ID}.web.app" \
  --set "STRIPE_WEBHOOK_ENDPOINT_URL=https://${PROJECT_ID}.web.app/api/billing/webhook" \
  --set "STRIPE_CHECKOUT_SUCCESS_URL=https://${PROJECT_ID}.web.app/?billing=success" \
  --set "STRIPE_CHECKOUT_CANCEL_URL=https://${PROJECT_ID}.web.app/?billing=cancel" \
  --set "SANDBOX_CORS_ORIGINS=https://${PROJECT_ID}.web.app,https://${PROJECT_ID}.firebaseapp.com" \
  --set "SANDBOX_TRUSTED_HOSTS=*" \
  --set "RECAPTCHA_ALLOWED_HOSTNAMES=${PROJECT_ID}.web.app,${PROJECT_ID}.firebaseapp.com,localhost,127.0.0.1" \
  --set "SANDBOX_ALLOW_ADMIN_OVERRIDE=false" \
  --set "ADMIN_TOKEN=" \
  --set "SANDBOX_DEBUG=false" \
  --set "SANDBOX_DEBUG_FORCE=false" \
  --set "SANDBOX_LOG_OPENAI_RESPONSE=false"

echo "Building dev backend image: ${BACKEND_IMAGE}"
gcloud builds submit \
  --tag "$BACKEND_IMAGE" \
  --project "$PROJECT_ID" \
  "$REPO_ROOT"

DEPLOY_ARGS=(
  --image "$BACKEND_IMAGE"
  --region "$BACKEND_REGION"
  --project "$PROJECT_ID"
  --service-account "$BACKEND_RUNTIME_SERVICE_ACCOUNT"
  --allow-unauthenticated
  --env-vars-file "$TMP_ENV_FILE"
  --memory "$BACKEND_MEMORY"
  --cpu "$BACKEND_CPU"
  --timeout "$BACKEND_REQUEST_TIMEOUT"
)

if [[ -n "$BACKEND_MIN_INSTANCES" ]]; then
  DEPLOY_ARGS+=(--min "$BACKEND_MIN_INSTANCES")
fi

echo "Deploying dev backend service: ${BACKEND_SERVICE}"
gcloud run deploy "$BACKEND_SERVICE" "${DEPLOY_ARGS[@]}"

SERVICE_URL="$(
  gcloud run services describe "$BACKEND_SERVICE" \
    --project "$PROJECT_ID" \
    --region "$BACKEND_REGION" \
    --format='value(status.url)'
)"
if [[ -z "$SERVICE_URL" ]]; then
  echo "Failed to resolve the deployed backend URL." >&2
  exit 1
fi

echo "Checking backend health: ${SERVICE_URL}/api/health"
for attempt in $(seq 1 20); do
  if curl --silent --fail "${SERVICE_URL}/api/health" | grep -Fq '"status":"ok"'; then
    echo "Dev backend deploy checks passed."
    exit 0
  fi
  sleep 3
done

echo "Dev backend health check never passed." >&2
exit 1
