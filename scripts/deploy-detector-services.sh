#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-env/backend.dev.stack.env}"
DEV_EXAMPLE="config/backend.dev.stack.env.example"
PROD_EXAMPLE="config/backend.prod.env.example"

if [[ ! -f "$ENV_FILE" ]]; then
  if [[ "$ENV_FILE" == *"prod"* && -f "$PROD_EXAMPLE" ]]; then
    mkdir -p "env"
    cp "$PROD_EXAMPLE" "$ENV_FILE"
    echo "Created $ENV_FILE from $PROD_EXAMPLE. Update values and re-run." >&2
    exit 1
  fi
  if [[ -f "$DEV_EXAMPLE" ]]; then
    mkdir -p "env"
    cp "$DEV_EXAMPLE" "$ENV_FILE"
    echo "Created $ENV_FILE from $DEV_EXAMPLE. Update values and re-run." >&2
    exit 1
  fi
  echo "Missing $ENV_FILE and both env examples." >&2
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

require_nonempty() {
  local name="$1"
  local actual="${!name:-}"
  if [[ -z "$actual" ]]; then
    echo "Missing required $name in $ENV_FILE (or exported env)." >&2
    exit 1
  fi
}

PROJECT_ID="${PROJECT_ID:-${DETECTOR_TASKS_PROJECT:-${FIREBASE_PROJECT_ID:-dullypdf-dev}}}"
REGION="${REGION:-${DETECTOR_TASKS_LOCATION:-us-central1}}"
ARTIFACT_REPO="${DETECTOR_ARTIFACT_REPO:-dullypdf-backend}"
TAG="${DETECTOR_IMAGE_TAG:-$(date +%Y%m%d-%H%M%S)}"

DETECTOR_IMAGE="${DETECTOR_IMAGE:-us-central1-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}/detector-service:${TAG}}"
DETECTOR_SERVICE_LIGHT="${DETECTOR_SERVICE_NAME_LIGHT:-dullypdf-detector-light}"
DETECTOR_SERVICE_HEAVY="${DETECTOR_SERVICE_NAME_HEAVY:-dullypdf-detector-heavy}"

CALLER_SA="${DETECTOR_TASKS_SERVICE_ACCOUNT:-}"
RUNTIME_SA="${DETECTOR_RUNTIME_SERVICE_ACCOUNT:-${WORKER_RUNTIME_SERVICE_ACCOUNT:-${CALLER_SA:-}}}"

require_nonempty PROJECT_ID
require_nonempty REGION
require_nonempty FIREBASE_PROJECT_ID
require_nonempty FORMS_BUCKET
require_nonempty DETECTOR_TASKS_SERVICE_ACCOUNT
require_nonempty RUNTIME_SA
require_nonempty COMMONFORMS_MODEL_GCS_URI

TMP_ENV_FILE="$(mktemp)"
python3 - <<'PY' "$ENV_FILE" "$TMP_ENV_FILE"
import json
import sys

env_path = sys.argv[1]
out_path = sys.argv[2]
script_only = {"PORT"}

def parse_env(path):
    values = {}
    with open(path, "r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            if value and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            values[key] = value
    return values

raw_values = parse_env(env_path)
data = {key: value for key, value in raw_values.items() if key not in script_only}
with open(out_path, "w", encoding="utf-8") as handle:
    for key in sorted(data.keys()):
        handle.write(f"{key}: {json.dumps(data[key])}\n")
PY

python3 - <<'PY' "$TMP_ENV_FILE" "$CALLER_SA"
import json
import sys

out_path = sys.argv[1]
caller_sa = sys.argv[2]

with open(out_path, "a", encoding="utf-8") as handle:
    handle.write(f"DETECTOR_ALLOW_UNAUTHENTICATED: {json.dumps('false')}\n")
    handle.write(f"DETECTOR_CALLER_SERVICE_ACCOUNT: {json.dumps(caller_sa)}\n")
PY

cleanup() {
  rm -f "$TMP_ENV_FILE" || true
}
trap cleanup EXIT

build_with_dockerfile() {
  local image="$1"
  local dockerfile="$2"
  local build_config
  build_config="$(mktemp)"
  cat >"$build_config" <<'YAML'
steps:
- name: gcr.io/cloud-builders/docker
  args:
  - build
  - -f
  - $_DOCKERFILE
  - -t
  - $_IMAGE
  - .
images:
- $_IMAGE
YAML
  gcloud builds submit \
    --project "$PROJECT_ID" \
    --config "$build_config" \
    --substitutions "_IMAGE=${image},_DOCKERFILE=${dockerfile}" \
    .
  rm -f "$build_config"
}

echo "Building detector image in project ${PROJECT_ID}..."
build_with_dockerfile "$DETECTOR_IMAGE" "Dockerfile.detector"

deploy_detector() {
  local service_name="$1"
  if [[ -z "$service_name" ]]; then
    return
  fi

  echo "Deploying ${service_name}..."
  gcloud run deploy "$service_name" \
    --image "$DETECTOR_IMAGE" \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --service-account "$RUNTIME_SA" \
    --no-allow-unauthenticated \
    --env-vars-file "$TMP_ENV_FILE"

  local service_url
  service_url="$(
    gcloud run services describe "$service_name" \
      --region "$REGION" \
      --project "$PROJECT_ID" \
      --format='value(status.url)'
  )"
  if [[ -z "$service_url" ]]; then
    echo "Failed to resolve Cloud Run URL for ${service_name}." >&2
    exit 1
  fi

  gcloud run services update "$service_name" \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --update-env-vars "DETECTOR_SERVICE_URL=${service_url},DETECTOR_TASKS_AUDIENCE=${service_url}" >/dev/null

  gcloud run services remove-iam-policy-binding "$service_name" \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --member="allUsers" \
    --role="roles/run.invoker" >/dev/null 2>&1 || true

  gcloud run services add-iam-policy-binding "$service_name" \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --member="serviceAccount:${CALLER_SA}" \
    --role="roles/run.invoker" >/dev/null
}

deploy_detector "$DETECTOR_SERVICE_LIGHT"
deploy_detector "$DETECTOR_SERVICE_HEAVY"

echo
echo "Detector deploy complete. Current invoker bindings:"
for service in "$DETECTOR_SERVICE_LIGHT" "$DETECTOR_SERVICE_HEAVY"; do
  echo "=== ${service}"
  gcloud run services get-iam-policy "$service" \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --format='yaml(bindings)'
done
