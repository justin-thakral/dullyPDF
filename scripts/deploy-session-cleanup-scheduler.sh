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
ALLOW_NON_PROD="${DULLYPDF_ALLOW_NON_PROD:-}"
SESSION_CLEANUP_REGION="${SESSION_CLEANUP_REGION:-${BACKEND_REGION:-us-east4}}"
SCHEDULER_LOCATION="${SESSION_CLEANUP_SCHEDULER_LOCATION:-${SESSION_CLEANUP_REGION}}"
JOB_NAME="${SESSION_CLEANUP_JOB_NAME:-dullypdf-session-cleanup}"
SCHEDULER_NAME="${SESSION_CLEANUP_SCHEDULER_NAME:-dullypdf-session-cleanup}"
SCHEDULER_SERVICE_ACCOUNT="${SESSION_CLEANUP_SCHEDULER_SERVICE_ACCOUNT:-${SESSION_CLEANUP_SERVICE_ACCOUNT:-dullypdf-cleanup@${PROJECT_ID}.iam.gserviceaccount.com}}"
SCHEDULER_SCHEDULE="${SESSION_CLEANUP_SCHEDULE:-0 * * * *}"
SCHEDULER_TIME_ZONE="${SESSION_CLEANUP_TIME_ZONE:-UTC}"
LEGACY_SCHEDULER_LOCATION="${SESSION_CLEANUP_LEGACY_SCHEDULER_LOCATION:-us-central1}"
RUN_URI="https://${SESSION_CLEANUP_REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run"

require_nonempty() {
  local name="$1"
  local actual="${!name:-}"
  if [[ -z "$actual" ]]; then
    echo "Missing required $name in $ENV_FILE (or exported env)." >&2
    exit 1
  fi
}

if [[ "${ENV:-}" != "prod" ]]; then
  echo "Expected ENV=prod in $ENV_FILE for session-cleanup scheduler deploy." >&2
  exit 1
fi

if [[ "$PROJECT_ID" != "dullypdf" && -z "$ALLOW_NON_PROD" ]]; then
  echo "Refusing to deploy session cleanup scheduler to non-prod project: $PROJECT_ID. Set DULLYPDF_ALLOW_NON_PROD=1 to override." >&2
  exit 1
fi

if [[ "$PROJECT_ID" == "dullypdf" && "$SESSION_CLEANUP_REGION" != "us-east4" ]]; then
  echo "Refusing to target prod session cleanup scheduler at non-east4 job region ${SESSION_CLEANUP_REGION}." >&2
  exit 1
fi

if [[ "$PROJECT_ID" == "dullypdf" && "$SCHEDULER_LOCATION" != "us-east4" ]]; then
  echo "Refusing to deploy prod session cleanup scheduler outside us-east4 (got ${SCHEDULER_LOCATION})." >&2
  exit 1
fi

require_nonempty FIREBASE_PROJECT_ID
require_nonempty SCHEDULER_SERVICE_ACCOUNT

gcloud run jobs add-iam-policy-binding "$JOB_NAME" \
  --region "$SESSION_CLEANUP_REGION" \
  --project "$PROJECT_ID" \
  --member "serviceAccount:${SCHEDULER_SERVICE_ACCOUNT}" \
  --role "roles/run.jobsExecutor" >/dev/null

if gcloud scheduler jobs describe "$SCHEDULER_NAME" --location "$SCHEDULER_LOCATION" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "$SCHEDULER_NAME" \
    --location "$SCHEDULER_LOCATION" \
    --schedule "$SCHEDULER_SCHEDULE" \
    --time-zone "$SCHEDULER_TIME_ZONE" \
    --uri "$RUN_URI" \
    --http-method POST \
    --oauth-service-account-email "$SCHEDULER_SERVICE_ACCOUNT" \
    --oauth-token-scope "https://www.googleapis.com/auth/cloud-platform"
else
  gcloud scheduler jobs create http "$SCHEDULER_NAME" \
    --location "$SCHEDULER_LOCATION" \
    --schedule "$SCHEDULER_SCHEDULE" \
    --time-zone "$SCHEDULER_TIME_ZONE" \
    --uri "$RUN_URI" \
    --http-method POST \
    --oauth-service-account-email "$SCHEDULER_SERVICE_ACCOUNT" \
    --oauth-token-scope "https://www.googleapis.com/auth/cloud-platform"
fi

if [[ "$PROJECT_ID" == "dullypdf" && "$LEGACY_SCHEDULER_LOCATION" != "$SCHEDULER_LOCATION" ]]; then
  gcloud scheduler jobs delete "$SCHEDULER_NAME" \
    --location "$LEGACY_SCHEDULER_LOCATION" \
    --quiet >/dev/null 2>&1 || true
fi
