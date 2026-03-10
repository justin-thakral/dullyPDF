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
RENAME_RUNTIME_SA="${OPENAI_RENAME_RUNTIME_SERVICE_ACCOUNT:-}"
REMAP_RUNTIME_SA="${OPENAI_REMAP_RUNTIME_SERVICE_ACCOUNT:-}"

require_nonempty PROJECT_ID
require_nonempty REGION
require_nonempty FIREBASE_PROJECT_ID
require_nonempty SANDBOX_SESSION_BUCKET
require_nonempty OPENAI_RENAME_TASKS_SERVICE_ACCOUNT
require_nonempty OPENAI_REMAP_TASKS_SERVICE_ACCOUNT
require_nonempty RENAME_RUNTIME_SA
require_nonempty REMAP_RUNTIME_SA

if [[ "${ENV:-}" == "prod" || "${ENV:-}" == "production" ]]; then
  require_exact FIREBASE_USE_ADC "true"
  require_empty FIREBASE_CREDENTIALS
  require_empty FIREBASE_CREDENTIALS_SECRET
  require_empty GOOGLE_APPLICATION_CREDENTIALS
  if [[ "$RENAME_RUNTIME_SA" == "$RENAME_CALLER_SA" || "$REMAP_RUNTIME_SA" == "$REMAP_CALLER_SA" ]]; then
    echo "OPENAI_*_RUNTIME_SERVICE_ACCOUNT must differ from the matching worker caller service account in prod." >&2
    exit 1
  fi
  if [[ "$RENAME_RUNTIME_SA" == "$REMAP_RUNTIME_SA" ]]; then
    echo "OPENAI_RENAME_RUNTIME_SERVICE_ACCOUNT and OPENAI_REMAP_RUNTIME_SERVICE_ACCOUNT must be distinct in prod." >&2
    exit 1
  fi
fi

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
    "OPENAI_RENAME_",
    "OPENAI_REMAP_",
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
  local runtime_service_account="$4"
  local allow_var="$5"
  local caller_var="$6"
  local service_url_var="$7"
  local audience_var="$8"

  reset_invoker_policy() {
    local allowed_member="$1"
    local tmp_policy
    tmp_policy="$(mktemp)"

    gcloud run services get-iam-policy "$service_name" \
      --region "$REGION" \
      --project "$PROJECT_ID" \
      --format=json > "$tmp_policy"

    python3 - <<'PY' "$tmp_policy" "$allowed_member"
import json
import sys

policy_path = sys.argv[1]
allowed_member = sys.argv[2]

with open(policy_path, "r", encoding="utf-8") as handle:
    policy = json.load(handle)

bindings = [binding for binding in policy.get("bindings", []) if binding.get("role") != "roles/run.invoker"]
bindings.append({"role": "roles/run.invoker", "members": [allowed_member]})
policy["bindings"] = bindings

with open(policy_path, "w", encoding="utf-8") as handle:
    json.dump(policy, handle)
PY

    gcloud run services set-iam-policy "$service_name" "$tmp_policy" \
      --region "$REGION" \
      --project "$PROJECT_ID" >/dev/null
    rm -f "$tmp_policy"
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

  # Reset the invoker binding instead of patching members one at a time so
  # stale principals from older deploys do not survive a hardened redeploy.
  reset_invoker_policy "serviceAccount:${caller_service_account}"
}

deploy_worker \
  "$RENAME_SERVICE_LIGHT" \
  "$RENAME_IMAGE" \
  "$RENAME_CALLER_SA" \
  "$RENAME_RUNTIME_SA" \
  "OPENAI_RENAME_ALLOW_UNAUTHENTICATED" \
  "OPENAI_RENAME_CALLER_SERVICE_ACCOUNT" \
  "OPENAI_RENAME_SERVICE_URL" \
  "OPENAI_RENAME_TASKS_AUDIENCE"

deploy_worker \
  "$RENAME_SERVICE_HEAVY" \
  "$RENAME_IMAGE" \
  "$RENAME_CALLER_SA" \
  "$RENAME_RUNTIME_SA" \
  "OPENAI_RENAME_ALLOW_UNAUTHENTICATED" \
  "OPENAI_RENAME_CALLER_SERVICE_ACCOUNT" \
  "OPENAI_RENAME_SERVICE_URL" \
  "OPENAI_RENAME_TASKS_AUDIENCE"

deploy_worker \
  "$REMAP_SERVICE_LIGHT" \
  "$REMAP_IMAGE" \
  "$REMAP_CALLER_SA" \
  "$REMAP_RUNTIME_SA" \
  "OPENAI_REMAP_ALLOW_UNAUTHENTICATED" \
  "OPENAI_REMAP_CALLER_SERVICE_ACCOUNT" \
  "OPENAI_REMAP_SERVICE_URL" \
  "OPENAI_REMAP_TASKS_AUDIENCE"

deploy_worker \
  "$REMAP_SERVICE_HEAVY" \
  "$REMAP_IMAGE" \
  "$REMAP_CALLER_SA" \
  "$REMAP_RUNTIME_SA" \
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
