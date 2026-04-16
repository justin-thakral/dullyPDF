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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_artifact_registry_guard.sh"
source "${SCRIPT_DIR}/_cloud_run_invoker_policy.sh"

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

require_empty() {
  local name="$1"
  local actual="${!name:-}"
  if [[ -n "$actual" ]]; then
    echo "Expected $name to be empty for prod deploys." >&2
    exit 1
  fi
}

PROJECT_ID="${PROJECT_ID:-${OPENAI_RENAME_REMAP_TASKS_PROJECT:-${FIREBASE_PROJECT_ID:-dullypdf-dev}}}"
REGION="${REGION:-${OPENAI_RENAME_REMAP_TASKS_LOCATION:-us-east4}}"
ARTIFACT_REGISTRY_LOCATION="${ARTIFACT_REGISTRY_LOCATION:-us-east4}"
ARTIFACT_REPO="${WORKER_ARTIFACT_REPO:-dullypdf-backend}"
TAG="${WORKER_IMAGE_TAG:-$(date +%Y%m%d-%H%M%S)}"

require_prod_artifact_registry_location "OpenAI worker Artifact Registry location" "$ARTIFACT_REGISTRY_LOCATION"
require_prod_artifact_registry_repo "WORKER_ARTIFACT_REPO" "$ARTIFACT_REPO"

WORKER_IMAGE="${OPENAI_RENAME_REMAP_WORKER_IMAGE:-${ARTIFACT_REGISTRY_LOCATION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}/openai-rename-remap-worker:${TAG}}"
require_prod_artifact_registry_image "OPENAI_RENAME_REMAP_WORKER_IMAGE" "$WORKER_IMAGE" "$ARTIFACT_REPO"

SERVICE_NAME="${OPENAI_RENAME_REMAP_SERVICE_NAME:-dullypdf-openai-rename-remap}"

# Standardize every environment on us-east4 and the canonical service name.
# Without these guards, a mis-set env file can silently create a parallel
# service in another region (as happened on dev during us-central1 drift).
if [[ "$REGION" != "us-east4" ]]; then
  echo "Refusing to deploy OpenAI worker outside us-east4 (got REGION=${REGION})." >&2
  exit 1
fi
if [[ "$SERVICE_NAME" != "dullypdf-openai-rename-remap" ]]; then
  echo "Refusing to deploy OpenAI worker under non-standard service name: ${SERVICE_NAME}." >&2
  exit 1
fi
if [[ -n "${OPENAI_RENAME_REMAP_TASKS_LOCATION:-}" && "$OPENAI_RENAME_REMAP_TASKS_LOCATION" != "us-east4" ]]; then
  echo "Refusing to deploy: env file has OPENAI_RENAME_REMAP_TASKS_LOCATION=${OPENAI_RENAME_REMAP_TASKS_LOCATION}, expected us-east4." >&2
  exit 1
fi

CALLER_SA="${OPENAI_RENAME_REMAP_TASKS_SERVICE_ACCOUNT:-}"
# Dev deploys can reuse the caller identity when no separate runtime account is
# configured. Prod still rejects this fallback below.
RUNTIME_SA="${OPENAI_RENAME_REMAP_RUNTIME_SERVICE_ACCOUNT:-${OPENAI_RENAME_REMAP_TASKS_SERVICE_ACCOUNT:-}}"

require_nonempty PROJECT_ID
require_nonempty REGION
require_nonempty FIREBASE_PROJECT_ID
require_nonempty SANDBOX_SESSION_BUCKET
require_nonempty OPENAI_RENAME_REMAP_TASKS_SERVICE_ACCOUNT
require_nonempty RUNTIME_SA

ALLOW_POLICY_FALLBACK="${OPENAI_RENAME_REMAP_ALLOW_POLICY_PERMISSION_DENIED_FALLBACK:-false}"
if [[ "${ENV:-}" != "prod" && "${ENV:-}" != "production" ]]; then
  ALLOW_POLICY_FALLBACK="true"
fi

if [[ "${ENV:-}" == "prod" || "${ENV:-}" == "production" ]]; then
  require_exact FIREBASE_USE_ADC "true"
  require_empty FIREBASE_CREDENTIALS
  require_empty FIREBASE_CREDENTIALS_SECRET
  require_empty GOOGLE_APPLICATION_CREDENTIALS
  if [[ "$RUNTIME_SA" == "$CALLER_SA" ]]; then
    echo "OPENAI_RENAME_REMAP_RUNTIME_SERVICE_ACCOUNT must differ from OPENAI_RENAME_REMAP_TASKS_SERVICE_ACCOUNT in prod." >&2
    exit 1
  fi
fi

TMP_ENV_FILE="$(mktemp)"
TMP_BUILD_CONFIG="$(mktemp)"
python3 - <<'PY' "$ENV_FILE" "$TMP_ENV_FILE"
import json
import sys

env_path = sys.argv[1]
out_path = sys.argv[2]
script_only = {"PORT"}
secret_bindings = {
    "OPENAI_API_KEY_SECRET": "OPENAI_API_KEY",
}
allowed_exact = {
    "ENV",
    "FIREBASE_PROJECT_ID",
    "FIREBASE_USE_ADC",
    "FIREBASE_CHECK_REVOKED",
    "FIREBASE_CLOCK_SKEW_SECONDS",
    "GCP_PROJECT_ID",
    "OPENAI_API_KEY",
    "OPENAI_REQUEST_TIMEOUT_SECONDS",
    "OPENAI_MAX_RETRIES",
    "OPENAI_WORKER_MAX_RETRIES",
    "OPENAI_SCHEMA_MAPPING_MODEL",
    "OPENAI_SCHEMA_MAX_FIELDS",
    "OPENAI_TEMPLATE_MAX_FIELDS",
    "OPENAI_SCHEMA_MAX_PAYLOAD_BYTES",
    "OPENAI_SCHEMA_MAX_FIELD_NAME_LEN",
    "OPENAI_PRICE_INPUT_PER_1M_USD",
    "OPENAI_PRICE_OUTPUT_PER_1M_USD",
    "OPENAI_PRICE_CACHED_INPUT_PER_1M_USD",
    "OPENAI_PRICE_REASONING_OUTPUT_PER_1M_USD",
    "SANDBOX_DEBUG",
    "SANDBOX_LOG_OPENAI_RESPONSE",
    "SANDBOX_OPENAI_LOG_TTL_SECONDS",
    "BASE_OPENAI_CREDITS",
    "PRO_MONTHLY_OPENAI_CREDITS",
    "SANDBOX_RENAME_MODEL",
}
allowed_prefixes = (
    "OPENAI_RENAME_REMAP_",
    "OPENAI_TASKS_",
    "OPENAI_PREWARM_",
    "SANDBOX_SESSION_",
)

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

data = {
    key: value
    for key, value in raw_values.items()
    if key not in omit_keys
    and (
        key in allowed_exact
        or any(key.startswith(prefix) for prefix in allowed_prefixes)
    )
}
with open(out_path, "w", encoding="utf-8") as handle:
    for key in sorted(data.keys()):
        handle.write(f"{key}: {json.dumps(data[key])}\n")
PY

cleanup() {
  rm -f "$TMP_ENV_FILE" || true
  rm -f "$TMP_BUILD_CONFIG" || true
}
trap cleanup EXIT

SECRET_UPDATES=()
if [[ -n "${OPENAI_API_KEY_SECRET:-}" ]]; then
  SECRET_UPDATES+=("OPENAI_API_KEY=${OPENAI_API_KEY_SECRET}:latest")
elif [[ -n "${OPENAI_API_KEY:-}" ]]; then
  # If the service currently uses a Secret Manager binding, remove it first.
  SECRET_UPDATES+=("OPENAI_API_KEY=")
fi

SECRET_FLAGS=()
REMOVE_SECRETS=(
  "FIREBASE_GITHUB_CLIENT_SECRET"
  "FIREBASE_GOOGLE_CLIENT_SECRET"
  "GMAIL_CLIENT_SECRET"
  "GMAIL_REFRESH_TOKEN"
  "ADMIN_TOKEN"
)
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

echo "Building worker image in project ${PROJECT_ID}..."
cat > "$TMP_BUILD_CONFIG" <<EOF
steps:
  - name: gcr.io/cloud-builders/docker
    args: ['build', '-f', 'Dockerfile.ai-rename-remap', '-t', '${WORKER_IMAGE}', '.']
images:
  - '${WORKER_IMAGE}'
EOF

gcloud builds submit \
  --project "$PROJECT_ID" \
  --config "$TMP_BUILD_CONFIG" \
  .

deploy_worker() {
  local service_name="$1"
  local image="$2"
  local caller_service_account="$3"
  local runtime_service_account="$4"

  reset_invoker_policy() {
    local allowed_member="$1"
    cloud_run_reset_invoker_policy \
      "$service_name" \
      "$REGION" \
      "$PROJECT_ID" \
      "$allowed_member" \
      "$ALLOW_POLICY_FALLBACK" \
      "true"
  }

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
    --service-account "$runtime_service_account" \
    --no-allow-unauthenticated \
    --memory "${OPENAI_RENAME_REMAP_MEMORY:-2Gi}" \
    --cpu "${OPENAI_RENAME_REMAP_CPU:-1}" \
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
    --update-env-vars "OPENAI_RENAME_REMAP_ALLOW_UNAUTHENTICATED=false,OPENAI_RENAME_REMAP_CALLER_SERVICE_ACCOUNT=${caller_service_account},OPENAI_RENAME_REMAP_SERVICE_URL=${service_url},OPENAI_RENAME_REMAP_TASKS_AUDIENCE=${service_url}" >/dev/null

  # Reset the invoker binding instead of patching members one at a time so
  # stale principals from older deploys do not survive a hardened redeploy.
  reset_invoker_policy "serviceAccount:${caller_service_account}"
}

deploy_worker \
  "$SERVICE_NAME" \
  "$WORKER_IMAGE" \
  "$CALLER_SA" \
  "$RUNTIME_SA"

echo
echo "Worker deploy complete. Current invoker bindings:"
echo "=== ${SERVICE_NAME}"
gcloud run services get-iam-policy "$SERVICE_NAME" \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --format='yaml(bindings)'
