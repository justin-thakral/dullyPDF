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

PROJECT_ID="${PROJECT_ID:-${OPENAI_RENAME_TASKS_PROJECT:-${OPENAI_REMAP_TASKS_PROJECT:-${FIREBASE_PROJECT_ID:-dullypdf-dev}}}}"
REGION="${REGION:-${OPENAI_RENAME_TASKS_LOCATION:-${OPENAI_REMAP_TASKS_LOCATION:-us-central1}}}"
ARTIFACT_REPO="${WORKER_ARTIFACT_REPO:-dullypdf-backend}"
TAG="${WORKER_IMAGE_TAG:-$(date +%Y%m%d-%H%M%S)}"

RENAME_IMAGE="${OPENAI_RENAME_WORKER_IMAGE:-us-central1-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}/openai-rename-worker:${TAG}}"
REMAP_IMAGE="${OPENAI_REMAP_WORKER_IMAGE:-us-central1-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}/openai-remap-worker:${TAG}}"

RENAME_SERVICE_LIGHT="${OPENAI_RENAME_SERVICE_NAME_LIGHT:-dullypdf-openai-rename-light}"
RENAME_SERVICE_HEAVY="${OPENAI_RENAME_SERVICE_NAME_HEAVY:-dullypdf-openai-rename-heavy}"
REMAP_SERVICE_LIGHT="${OPENAI_REMAP_SERVICE_NAME_LIGHT:-dullypdf-openai-remap-light}"
REMAP_SERVICE_HEAVY="${OPENAI_REMAP_SERVICE_NAME_HEAVY:-dullypdf-openai-remap-heavy}"

RENAME_CALLER_SA="${OPENAI_RENAME_TASKS_SERVICE_ACCOUNT:-}"
REMAP_CALLER_SA="${OPENAI_REMAP_TASKS_SERVICE_ACCOUNT:-}"
RUNTIME_SA="${OPENAI_WORKER_RUNTIME_SERVICE_ACCOUNT:-${WORKER_RUNTIME_SERVICE_ACCOUNT:-${RENAME_CALLER_SA:-${REMAP_CALLER_SA:-}}}}"

require_nonempty PROJECT_ID
require_nonempty REGION
require_nonempty FIREBASE_PROJECT_ID
require_nonempty FORMS_BUCKET
require_nonempty SANDBOX_SESSION_BUCKET
require_nonempty OPENAI_RENAME_TASKS_SERVICE_ACCOUNT
require_nonempty OPENAI_REMAP_TASKS_SERVICE_ACCOUNT
require_nonempty RUNTIME_SA

TMP_ENV_FILE="$(mktemp)"
TMP_RENAME_BUILD_CONFIG="$(mktemp)"
TMP_REMAP_BUILD_CONFIG="$(mktemp)"
python3 - <<'PY' "$ENV_FILE" "$TMP_ENV_FILE"
import json
import sys

env_path = sys.argv[1]
out_path = sys.argv[2]
script_only = {"PORT"}
secret_bindings = {
    "OPENAI_API_KEY_SECRET": "OPENAI_API_KEY",
    "FIREBASE_GITHUB_CLIENT_SECRET_SECRET": "FIREBASE_GITHUB_CLIENT_SECRET",
    "FIREBASE_GOOGLE_CLIENT_SECRET_SECRET": "FIREBASE_GOOGLE_CLIENT_SECRET",
    "GMAIL_CLIENT_SECRET_SECRET": "GMAIL_CLIENT_SECRET",
    "GMAIL_REFRESH_TOKEN_SECRET": "GMAIL_REFRESH_TOKEN",
    "ADMIN_TOKEN_SECRET": "ADMIN_TOKEN",
}

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
omit_keys = set(script_only)
omit_keys.update(secret_bindings.keys())
for binding_key, target_key in secret_bindings.items():
    binding_value = (raw_values.get(binding_key) or "").strip()
    target_value = (raw_values.get(target_key) or "").strip()
    if binding_value or not target_value:
        omit_keys.add(target_key)

data = {key: value for key, value in raw_values.items() if key not in omit_keys}
with open(out_path, "w", encoding="utf-8") as handle:
    for key in sorted(data.keys()):
        handle.write(f"{key}: {json.dumps(data[key])}\n")
PY

cleanup() {
  rm -f "$TMP_ENV_FILE" || true
  rm -f "$TMP_RENAME_BUILD_CONFIG" || true
  rm -f "$TMP_REMAP_BUILD_CONFIG" || true
}
trap cleanup EXIT

SECRET_UPDATES=()
if [[ -n "${OPENAI_API_KEY_SECRET:-}" ]]; then
  SECRET_UPDATES+=("OPENAI_API_KEY=${OPENAI_API_KEY_SECRET}:latest")
elif [[ -n "${OPENAI_API_KEY:-}" ]]; then
  # If the service currently uses a Secret Manager binding, remove it first.
  SECRET_UPDATES+=("OPENAI_API_KEY=")
fi
if [[ -n "${FIREBASE_GITHUB_CLIENT_SECRET_SECRET:-}" ]]; then
  SECRET_UPDATES+=("FIREBASE_GITHUB_CLIENT_SECRET=${FIREBASE_GITHUB_CLIENT_SECRET_SECRET}:latest")
fi
if [[ -n "${FIREBASE_GOOGLE_CLIENT_SECRET_SECRET:-}" ]]; then
  SECRET_UPDATES+=("FIREBASE_GOOGLE_CLIENT_SECRET=${FIREBASE_GOOGLE_CLIENT_SECRET_SECRET}:latest")
fi
if [[ -n "${GMAIL_CLIENT_SECRET_SECRET:-}" ]]; then
  SECRET_UPDATES+=("GMAIL_CLIENT_SECRET=${GMAIL_CLIENT_SECRET_SECRET}:latest")
fi
if [[ -n "${GMAIL_REFRESH_TOKEN_SECRET:-}" ]]; then
  SECRET_UPDATES+=("GMAIL_REFRESH_TOKEN=${GMAIL_REFRESH_TOKEN_SECRET}:latest")
fi
if [[ -n "${ADMIN_TOKEN_SECRET:-}" ]]; then
  SECRET_UPDATES+=("ADMIN_TOKEN=${ADMIN_TOKEN_SECRET}:latest")
fi

SECRET_FLAGS=()
REMOVE_SECRETS=()
for update in "${SECRET_UPDATES[@]}"; do
  if [[ "$update" == *"=" && "$update" != *":"* ]]; then
    REMOVE_SECRETS+=("${update%=}")
  else
    SECRET_FLAGS+=("$update")
  fi
done

REMOVE_SECRETS_CSV=""
if [[ "${#REMOVE_SECRETS[@]}" -gt 0 ]]; then
  REMOVE_SECRETS_CSV="$(IFS=,; echo "${REMOVE_SECRETS[*]}")"
fi

SECRET_ARGS=()
if [[ "${#SECRET_FLAGS[@]}" -gt 0 ]]; then
  SECRET_ARGS+=("--update-secrets" "$(IFS=,; echo "${SECRET_FLAGS[*]}")")
fi

echo "Building worker images in project ${PROJECT_ID}..."
cat > "$TMP_RENAME_BUILD_CONFIG" <<EOF
steps:
  - name: gcr.io/cloud-builders/docker
    args: ['build', '-f', 'Dockerfile.ai-rename', '-t', '${RENAME_IMAGE}', '.']
images:
  - '${RENAME_IMAGE}'
EOF

cat > "$TMP_REMAP_BUILD_CONFIG" <<EOF
steps:
  - name: gcr.io/cloud-builders/docker
    args: ['build', '-f', 'Dockerfile.ai-remap', '-t', '${REMAP_IMAGE}', '.']
images:
  - '${REMAP_IMAGE}'
EOF

gcloud builds submit \
  --project "$PROJECT_ID" \
  --config "$TMP_RENAME_BUILD_CONFIG" \
  .
gcloud builds submit \
  --project "$PROJECT_ID" \
  --config "$TMP_REMAP_BUILD_CONFIG" \
  .

deploy_worker() {
  local service_name="$1"
  local image="$2"
  local caller_service_account="$3"
  local allow_var="$4"
  local caller_var="$5"
  local service_url_var="$6"
  local audience_var="$7"

  # Cloud Run rejects secret->literal type changes in a single deploy call.
  # Remove stale secret bindings first so literals from --env-vars-file can apply.
  if [[ -n "$REMOVE_SECRETS_CSV" ]]; then
    gcloud run services update "$service_name" \
      --region "$REGION" \
      --project "$PROJECT_ID" \
      --remove-secrets "$REMOVE_SECRETS_CSV" >/dev/null 2>&1 || true
  fi

  echo "Deploying ${service_name}..."
  gcloud run deploy "$service_name" \
    --image "$image" \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --service-account "$RUNTIME_SA" \
    --no-allow-unauthenticated \
    --env-vars-file "$TMP_ENV_FILE" \
    "${SECRET_ARGS[@]}"

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
    --update-env-vars "${allow_var}=false,${caller_var}=${caller_service_account},${service_url_var}=${service_url},${audience_var}=${service_url}" >/dev/null

  # Defense in depth: ensure public invoker access is removed even if previously granted.
  gcloud run services remove-iam-policy-binding "$service_name" \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --member="allUsers" \
    --role="roles/run.invoker" >/dev/null 2>&1 || true

  gcloud run services add-iam-policy-binding "$service_name" \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --member="serviceAccount:${caller_service_account}" \
    --role="roles/run.invoker" >/dev/null
}

deploy_worker \
  "$RENAME_SERVICE_LIGHT" \
  "$RENAME_IMAGE" \
  "$RENAME_CALLER_SA" \
  "OPENAI_RENAME_ALLOW_UNAUTHENTICATED" \
  "OPENAI_RENAME_CALLER_SERVICE_ACCOUNT" \
  "OPENAI_RENAME_SERVICE_URL" \
  "OPENAI_RENAME_TASKS_AUDIENCE"

deploy_worker \
  "$RENAME_SERVICE_HEAVY" \
  "$RENAME_IMAGE" \
  "$RENAME_CALLER_SA" \
  "OPENAI_RENAME_ALLOW_UNAUTHENTICATED" \
  "OPENAI_RENAME_CALLER_SERVICE_ACCOUNT" \
  "OPENAI_RENAME_SERVICE_URL" \
  "OPENAI_RENAME_TASKS_AUDIENCE"

deploy_worker \
  "$REMAP_SERVICE_LIGHT" \
  "$REMAP_IMAGE" \
  "$REMAP_CALLER_SA" \
  "OPENAI_REMAP_ALLOW_UNAUTHENTICATED" \
  "OPENAI_REMAP_CALLER_SERVICE_ACCOUNT" \
  "OPENAI_REMAP_SERVICE_URL" \
  "OPENAI_REMAP_TASKS_AUDIENCE"

deploy_worker \
  "$REMAP_SERVICE_HEAVY" \
  "$REMAP_IMAGE" \
  "$REMAP_CALLER_SA" \
  "OPENAI_REMAP_ALLOW_UNAUTHENTICATED" \
  "OPENAI_REMAP_CALLER_SERVICE_ACCOUNT" \
  "OPENAI_REMAP_SERVICE_URL" \
  "OPENAI_REMAP_TASKS_AUDIENCE"

echo
echo "Worker deploy complete. Current invoker bindings:"
for service in \
  "$RENAME_SERVICE_LIGHT" \
  "$RENAME_SERVICE_HEAVY" \
  "$REMAP_SERVICE_LIGHT" \
  "$REMAP_SERVICE_HEAVY"
do
  echo "=== ${service}"
  gcloud run services get-iam-policy "$service" \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --format='yaml(bindings)'
done
