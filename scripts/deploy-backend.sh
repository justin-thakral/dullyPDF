#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-dullypdf}"
REGION="${REGION:-}"
BACKEND_REGION="${BACKEND_REGION:-${REGION:-us-east4}}"
SERVICE_NAME="${BACKEND_SERVICE:-dullypdf-backend-east4}"
BACKEND_RUNTIME_SERVICE_ACCOUNT="${BACKEND_RUNTIME_SERVICE_ACCOUNT:-}"
ALLOW_NON_PROD="${DULLYPDF_ALLOW_NON_PROD:-}"
ENV_FILE="${ENV_FILE:-env/backend.prod.env}"
EXAMPLE="config/backend.prod.env.example"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_artifact_registry_guard.sh"

if [[ "$PROJECT_ID" != "dullypdf" && -z "$ALLOW_NON_PROD" ]]; then
  echo "Refusing to deploy backend to non-prod project: $PROJECT_ID. Set DULLYPDF_ALLOW_NON_PROD=1 to override." >&2
  exit 1
fi

if [[ "$PROJECT_ID" == "dullypdf" && "$SERVICE_NAME" == "dullypdf-backend" ]]; then
  echo "Refusing to deploy the retired prod backend service name dullypdf-backend." >&2
  echo "Use BACKEND_SERVICE=dullypdf-backend-east4 instead." >&2
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  if [[ -f "$EXAMPLE" ]]; then
    mkdir -p "env"
    cp "$EXAMPLE" "$ENV_FILE"
    echo "Created $ENV_FILE from $EXAMPLE. Update values and re-run." >&2
    exit 1
  fi
  echo "Missing $ENV_FILE and $EXAMPLE." >&2
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

# Leave unset to preserve the service's current min instance count on redeploy.
BACKEND_MIN_INSTANCES="${BACKEND_MIN_INSTANCES:-}"

source "${SCRIPT_DIR}/_detector_routing.sh"

DETECTOR_SERVICE_REGION="${DETECTOR_SERVICE_REGION:-${DETECTOR_TASKS_LOCATION:-${REGION:-us-east4}}}"
detector_set_active_routing_vars
DETECTOR_ROUTING_MODE="$DETECTOR_ROUTING_MODE_RESOLVED"

if [[ -z "${DETECTOR_SERVICE_URL_LIGHT_ACTIVE:-}" ]]; then
  DETECTOR_SERVICE_URL_LIGHT_ACTIVE="$(
    gcloud run services describe "$DETECTOR_SERVICE_NAME_LIGHT_ACTIVE" \
      --region "$DETECTOR_SERVICE_REGION_LIGHT_ACTIVE" \
      --project "$PROJECT_ID" \
      --format='value(status.url)' 2>/dev/null || true
  )"
fi
if [[ -z "${DETECTOR_SERVICE_URL_HEAVY_ACTIVE:-}" ]]; then
  DETECTOR_SERVICE_URL_HEAVY_ACTIVE="$(
    gcloud run services describe "$DETECTOR_SERVICE_NAME_HEAVY_ACTIVE" \
      --region "$DETECTOR_SERVICE_REGION_HEAVY_ACTIVE" \
      --project "$PROJECT_ID" \
      --format='value(status.url)' 2>/dev/null || true
  )"
fi

DETECTOR_TASKS_AUDIENCE_LIGHT_ACTIVE="$(
  detector_tasks_audience_for_target \
    "$DETECTOR_TARGET_LIGHT_ACTIVE" \
    "light" \
    "$DETECTOR_SERVICE_URL_LIGHT_ACTIVE"
)"
DETECTOR_TASKS_AUDIENCE_HEAVY_ACTIVE="$(
  detector_tasks_audience_for_target \
    "$DETECTOR_TARGET_HEAVY_ACTIVE" \
    "heavy" \
    "$DETECTOR_SERVICE_URL_HEAVY_ACTIVE"
)"

resolve_cloud_run_service_url() {
  local project_id="$1"
  local region="$2"
  local service_name="$3"
  local setting_name="$4"
  local resolved_url=""

  resolved_url="$(
    gcloud run services describe "$service_name" \
      --region "$region" \
      --project "$project_id" \
      --format='value(status.url)' 2>/dev/null || true
  )"
  if [[ -z "$resolved_url" ]]; then
    echo "Failed to resolve ${setting_name} from Cloud Run service ${service_name} in ${region}." >&2
    exit 1
  fi
  printf '%s\n' "$resolved_url"
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

require_nonempty() {
  local name="$1"
  local actual="${!name:-}"
  if [[ -z "$actual" ]]; then
    echo "Missing required $name in $ENV_FILE." >&2
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

require_integer_ge() {
  local name="$1"
  local min_value="$2"
  local actual="${!name:-}"
  if [[ ! "$actual" =~ ^[0-9]+$ ]]; then
    echo "Expected $name to be an integer >= ${min_value} (got '${actual}')." >&2
    exit 1
  fi
  if (( actual < min_value )); then
    echo "Expected $name to be >= ${min_value} (got '${actual}')." >&2
    exit 1
  fi
}

require_optional_integer_ge() {
  local name="$1"
  local min_value="$2"
  local actual="${!name:-}"
  if [[ -z "$actual" ]]; then
    return 0
  fi
  require_integer_ge "$name" "$min_value"
}

service_account_has_project_iam_permission() {
  local service_account="$1"
  local permission="$2"
  local policy_json

  policy_json="$(
    gcloud projects get-iam-policy "$PROJECT_ID" --format=json 2>/dev/null
  )" || return 1

  python3 - "$service_account" "$permission" "$policy_json" <<'PY'
import json
import subprocess
import sys

service_account = sys.argv[1]
permission = sys.argv[2]
policy = json.loads(sys.argv[3])
member = f"serviceAccount:{service_account}"

for binding in policy.get("bindings", []):
    members = binding.get("members") or []
    if member not in members:
        continue
    role = (binding.get("role") or "").strip()
    if not role:
        continue
    if role == "roles/owner":
        print("true")
        raise SystemExit(0)
    cmd = ["gcloud", "iam", "roles", "describe", role, "--format=json"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        continue
    try:
        role_payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        continue
    permissions = set(role_payload.get("includedPermissions") or [])
    if permission in permissions:
        print("true")
        raise SystemExit(0)

raise SystemExit(1)
PY
}

require_firebase_auth_runtime_access() {
  local runtime_sa="${BACKEND_RUNTIME_SERVICE_ACCOUNT:-}"
  if [[ -z "$runtime_sa" ]]; then
    echo "Missing required BACKEND_RUNTIME_SERVICE_ACCOUNT in $ENV_FILE." >&2
    exit 1
  fi
  if ! service_account_has_project_iam_permission "$runtime_sa" "firebaseauth.users.get"; then
    echo "BACKEND_RUNTIME_SERVICE_ACCOUNT must include Firebase Authentication read access" >&2
    echo "(for example roles/firebaseauth.viewer) when FIREBASE_CHECK_REVOKED=true." >&2
    exit 1
  fi
}

require_fill_link_secret_quality() {
  local name="$1"
  local actual="${!name:-}"
  if [[ "$actual" == "change_me_prod_fill_link_token_secret" || "$actual" == "dullypdf-fill-link-dev-secret" ]]; then
    echo "$name must not use the placeholder prod example value." >&2
    exit 1
  fi
  if [[ "${#actual}" -lt 32 ]]; then
    echo "$name must be at least 32 characters in prod." >&2
    exit 1
  fi
}

require_signing_link_secret_quality() {
  local name="$1"
  local actual="${!name:-}"
  if [[ "$actual" == "change_me_prod_signing_link_token_secret" || "$actual" == "dullypdf-signing-dev-secret" ]]; then
    echo "$name must not use the placeholder prod example value." >&2
    exit 1
  fi
  if [[ "${#actual}" -lt 32 ]]; then
    echo "$name must be at least 32 characters in prod." >&2
    exit 1
  fi
}

require_exact ENV "prod"
require_exact SANDBOX_LOG_OPENAI_RESPONSE "false"
require_exact SANDBOX_ENABLE_LEGACY_ENDPOINTS "false"
require_exact SANDBOX_ALLOW_ADMIN_OVERRIDE "false"
require_exact SANDBOX_DEBUG "false"
require_exact SANDBOX_DEBUG_FORCE "false"
require_empty SANDBOX_DEBUG_PASSWORD
require_empty ADMIN_TOKEN
require_empty ADMIN_TOKEN_SECRET
require_exact FIREBASE_CHECK_REVOKED "true"
require_exact FIREBASE_USE_ADC "true"
require_empty FIREBASE_CREDENTIALS
require_empty FIREBASE_CREDENTIALS_SECRET
require_empty GOOGLE_APPLICATION_CREDENTIALS
require_exact DETECTOR_MODE "tasks"
require_exact OPENAI_RENAME_REMAP_MODE "tasks"
require_nonempty FIREBASE_PROJECT_ID
require_nonempty BACKEND_RUNTIME_SERVICE_ACCOUNT
require_nonempty FORMS_BUCKET
require_nonempty TEMPLATES_BUCKET
require_nonempty SIGNING_LINK_TOKEN_SECRET
require_signing_link_secret_quality SIGNING_LINK_TOKEN_SECRET
require_nonempty SIGNING_AUDIT_KMS_KEY
require_nonempty SIGNING_BUCKET
require_nonempty SANDBOX_CORS_ORIGINS
require_nonempty CONTACT_TO_EMAIL
require_nonempty CONTACT_FROM_EMAIL
require_nonempty GMAIL_CLIENT_ID
require_nonempty OPENAI_RENAME_REMAP_TASKS_PROJECT
require_nonempty OPENAI_RENAME_REMAP_TASKS_LOCATION
require_nonempty OPENAI_RENAME_REMAP_TASKS_QUEUE
require_nonempty OPENAI_RENAME_REMAP_TASKS_SERVICE_ACCOUNT
require_integer_ge SIGNING_RETENTION_DAYS 2555
require_integer_ge SIGNING_SESSION_TTL_SECONDS 300
require_integer_ge SIGNING_VIEW_RATE_WINDOW_SECONDS 1
require_integer_ge SIGNING_VIEW_RATE_PER_IP 1
require_integer_ge SIGNING_VIEW_RATE_GLOBAL 0
require_integer_ge SIGNING_ACTION_RATE_WINDOW_SECONDS 1
require_integer_ge SIGNING_ACTION_RATE_PER_IP 1
require_integer_ge SIGNING_ACTION_RATE_GLOBAL 0
require_integer_ge SIGNING_DOCUMENT_RATE_WINDOW_SECONDS 1
require_integer_ge SIGNING_DOCUMENT_RATE_PER_IP 1
require_integer_ge SIGNING_DOCUMENT_RATE_GLOBAL 0
require_optional_integer_ge BACKEND_MIN_INSTANCES 0

if [[ "${SANDBOX_CORS_ORIGINS}" == "*" ]]; then
  echo "SANDBOX_CORS_ORIGINS cannot be '*'" >&2
  exit 1
fi

if echo "${SANDBOX_CORS_ORIGINS}" | grep -E -q "localhost|127\\.0\\.0\\.1"; then
  echo "SANDBOX_CORS_ORIGINS must not include localhost entries in prod." >&2
  exit 1
fi

require_value_or_secret() {
  local name="$1"
  local secret_name="$2"
  local actual="${!name:-}"
  local secret_actual="${!secret_name:-}"
  if [[ -z "$actual" && -z "$secret_actual" ]]; then
    echo "Missing $name (or $secret_name) in $ENV_FILE." >&2
    exit 1
  fi
}

require_value_or_secret GMAIL_CLIENT_SECRET GMAIL_CLIENT_SECRET_SECRET
require_value_or_secret GMAIL_REFRESH_TOKEN GMAIL_REFRESH_TOKEN_SECRET
require_value_or_secret FILL_LINK_TOKEN_SECRET FILL_LINK_TOKEN_SECRET_SECRET
require_value_or_secret STRIPE_SECRET_KEY STRIPE_SECRET_KEY_SECRET
require_value_or_secret STRIPE_WEBHOOK_SECRET STRIPE_WEBHOOK_SECRET_SECRET

OPENAI_RENAME_REMAP_SERVICE_REGION="${OPENAI_RENAME_REMAP_SERVICE_REGION:-${OPENAI_RENAME_REMAP_TASKS_LOCATION:-${REGION:-us-east4}}}"
OPENAI_RENAME_REMAP_SERVICE_NAME="${OPENAI_RENAME_REMAP_SERVICE_NAME:-dullypdf-openai-rename-remap}"

OPENAI_RENAME_REMAP_SERVICE_URL_ACTIVE="$(
  resolve_cloud_run_service_url \
    "$OPENAI_RENAME_REMAP_TASKS_PROJECT" \
    "$OPENAI_RENAME_REMAP_SERVICE_REGION" \
    "$OPENAI_RENAME_REMAP_SERVICE_NAME" \
    "OPENAI_RENAME_REMAP_SERVICE_URL"
)"

OPENAI_RENAME_REMAP_TASKS_AUDIENCE_ACTIVE="$OPENAI_RENAME_REMAP_SERVICE_URL_ACTIVE"

require_nonempty DETECTOR_SERVICE_URL_LIGHT_ACTIVE
require_nonempty DETECTOR_SERVICE_URL_HEAVY_ACTIVE
require_firebase_auth_runtime_access

if [[ -n "${FILL_LINK_TOKEN_SECRET:-}" ]]; then
  echo "Use FILL_LINK_TOKEN_SECRET_SECRET for prod; literal FILL_LINK_TOKEN_SECRET is not allowed." >&2
  exit 1
fi

if [[ -n "${STRIPE_SECRET_KEY:-}" || -n "${STRIPE_WEBHOOK_SECRET:-}" ]]; then
  echo "Use STRIPE_SECRET_KEY_SECRET and STRIPE_WEBHOOK_SECRET_SECRET for prod; literal STRIPE_* values are not allowed." >&2
  exit 1
fi

if [[ "${CONTACT_REQUIRE_RECAPTCHA:-true}" != "true" || "${SIGNUP_REQUIRE_RECAPTCHA:-true}" != "true" || "${FILL_LINK_REQUIRE_RECAPTCHA:-true}" != "true" ]]; then
  echo "CONTACT_REQUIRE_RECAPTCHA, SIGNUP_REQUIRE_RECAPTCHA, and FILL_LINK_REQUIRE_RECAPTCHA must be true in prod." >&2
  exit 1
fi

if [[ "${CONTACT_REQUIRE_RECAPTCHA:-true}" == "true" || "${SIGNUP_REQUIRE_RECAPTCHA:-true}" == "true" || "${FILL_LINK_REQUIRE_RECAPTCHA:-true}" == "true" ]]; then
  require_nonempty RECAPTCHA_SITE_KEY
  require_nonempty RECAPTCHA_ALLOWED_HOSTNAMES
  if [[ -z "${RECAPTCHA_PROJECT_ID:-}" && -z "${FIREBASE_PROJECT_ID:-}" ]]; then
    echo "RECAPTCHA_PROJECT_ID (or FIREBASE_PROJECT_ID) must be set for reCAPTCHA." >&2
    exit 1
  fi
fi

echo "Validating signing storage policy"
python3 scripts/validate-signing-storage.py

BILLING_INTEGRATION_TEST_PATH="backend/test/integration/test_billing_webhook_integration.py"
if [[ ! -f "$BILLING_INTEGRATION_TEST_PATH" ]]; then
  echo "Missing required integration test: $BILLING_INTEGRATION_TEST_PATH" >&2
  exit 1
fi
if ! python3 -m pytest --version >/dev/null 2>&1; then
  echo "pytest is required for deploy preflight checks. Install backend test dependencies first." >&2
  exit 1
fi
echo "Running required billing integration gate: $BILLING_INTEGRATION_TEST_PATH"
ENV=test python3 -m pytest -q "$BILLING_INTEGRATION_TEST_PATH"

TMP_ENV_FILE="$(mktemp)"
trap 'rm -f "$TMP_ENV_FILE"' EXIT

python3 - <<'PY' "$ENV_FILE" "$TMP_ENV_FILE"
import json
import sys

env_path = sys.argv[1]
out_path = sys.argv[2]
script_only = {
    "PORT",
    "FIREBASE_CREDENTIALS",
    "FIREBASE_CREDENTIALS_SECRET",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "BACKEND_RUNTIME_SERVICE_ACCOUNT",
    "DETECTOR_ROUTING_MODE",
    "DETECTOR_SERVICE_URL",
    "DETECTOR_SERVICE_URL_LIGHT",
    "DETECTOR_SERVICE_URL_HEAVY",
    "DETECTOR_TASKS_AUDIENCE",
    "DETECTOR_TASKS_AUDIENCE_LIGHT",
    "DETECTOR_TASKS_AUDIENCE_HEAVY",
    "OPENAI_RENAME_REMAP_SERVICE_URL",
    "OPENAI_RENAME_REMAP_TASKS_AUDIENCE",
}

# If a Secret Manager binding is configured, do not also emit the literal env var
# into --env-vars-file. Cloud Run treats secret-backed env vars as a different
# "type", and deploying a string literal for the same key will fail.
secret_bindings = {
    "OPENAI_API_KEY_SECRET": "OPENAI_API_KEY",
    "GMAIL_CLIENT_SECRET_SECRET": "GMAIL_CLIENT_SECRET",
    "GMAIL_REFRESH_TOKEN_SECRET": "GMAIL_REFRESH_TOKEN",
    "FILL_LINK_TOKEN_SECRET_SECRET": "FILL_LINK_TOKEN_SECRET",
    "STRIPE_SECRET_KEY_SECRET": "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET_SECRET": "STRIPE_WEBHOOK_SECRET",
    "FIREBASE_GITHUB_CLIENT_SECRET_SECRET": "FIREBASE_GITHUB_CLIENT_SECRET",
    "FIREBASE_GOOGLE_CLIENT_SECRET_SECRET": "FIREBASE_GOOGLE_CLIENT_SECRET",
    "SIGNING_PDF_CERT_PEM_SECRET": "SIGNING_PDF_CERT_PEM",
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
    if not binding_value:
        continue
    target_value = (raw_values.get(target_key) or "").strip()
    if target_value:
        print(
            f"Warning: {binding_key} is set; ignoring literal {target_key} from {env_path}.",
            file=sys.stderr,
        )
    omit_keys.add(target_key)

data = {key: value for key, value in raw_values.items() if key not in omit_keys}
with open(out_path, "w", encoding="utf-8") as handle:
    for key in sorted(data.keys()):
        handle.write(f"{key}: {json.dumps(data[key])}\n")
PY

python3 - "$TMP_ENV_FILE" \
  "$DETECTOR_ROUTING_MODE" \
  "$DETECTOR_SERVICE_URL_LIGHT_ACTIVE" \
  "$DETECTOR_SERVICE_URL_HEAVY_ACTIVE" \
  "$DETECTOR_TASKS_AUDIENCE_LIGHT_ACTIVE" \
  "$DETECTOR_TASKS_AUDIENCE_HEAVY_ACTIVE" \
  "$OPENAI_RENAME_REMAP_SERVICE_URL_ACTIVE" \
  "$OPENAI_RENAME_REMAP_TASKS_AUDIENCE_ACTIVE" <<'PY'
import json
import sys

out_path = sys.argv[1]
routing_mode = sys.argv[2]
light_url = sys.argv[3]
heavy_url = sys.argv[4]
light_audience = sys.argv[5]
heavy_audience = sys.argv[6]
rename_remap_url = sys.argv[7]
rename_remap_audience = sys.argv[8]

with open(out_path, "a", encoding="utf-8") as handle:
    handle.write(f"DETECTOR_ROUTING_MODE: {json.dumps(routing_mode)}\n")
    handle.write(f"DETECTOR_SERVICE_URL: {json.dumps(light_url)}\n")
    handle.write(f"DETECTOR_SERVICE_URL_LIGHT: {json.dumps(light_url)}\n")
    handle.write(f"DETECTOR_SERVICE_URL_HEAVY: {json.dumps(heavy_url)}\n")
    handle.write(f"DETECTOR_TASKS_AUDIENCE: {json.dumps(light_audience)}\n")
    handle.write(f"DETECTOR_TASKS_AUDIENCE_LIGHT: {json.dumps(light_audience)}\n")
    handle.write(f"DETECTOR_TASKS_AUDIENCE_HEAVY: {json.dumps(heavy_audience)}\n")
    handle.write(f"OPENAI_RENAME_REMAP_SERVICE_URL: {json.dumps(rename_remap_url)}\n")
    handle.write(f"OPENAI_RENAME_REMAP_TASKS_AUDIENCE: {json.dumps(rename_remap_audience)}\n")
PY

TAG="$(date +%Y%m%d-%H%M%S)"
ARTIFACT_REGISTRY_LOCATION="${ARTIFACT_REGISTRY_LOCATION:-us-east4}"
BACKEND_ARTIFACT_REPO="${BACKEND_ARTIFACT_REPO:-dullypdf-backend}"
BACKEND_IMAGE="${BACKEND_IMAGE:-${ARTIFACT_REGISTRY_LOCATION}-docker.pkg.dev/${PROJECT_ID}/${BACKEND_ARTIFACT_REPO}/backend:${TAG}}"

require_prod_artifact_registry_location "backend Artifact Registry location" "$ARTIFACT_REGISTRY_LOCATION"
require_prod_artifact_registry_repo "BACKEND_ARTIFACT_REPO" "$BACKEND_ARTIFACT_REPO"
require_prod_artifact_registry_image "BACKEND_IMAGE" "$BACKEND_IMAGE" "$BACKEND_ARTIFACT_REPO"

gcloud builds submit \
  --tag "$BACKEND_IMAGE" \
  --project "$PROJECT_ID" \
  .

SECRET_FLAGS=()
SECRETS_TO_UPDATE=()
SECRETS_TO_REMOVE=()

append_csv() {
  local -n arr="$1"
  local value="$2"
  if [[ -z "$value" ]]; then
    return
  fi
  arr+=("$value")
}

if [[ -n "${OPENAI_API_KEY_SECRET:-}" ]]; then
  append_csv SECRETS_TO_UPDATE "OPENAI_API_KEY=${OPENAI_API_KEY_SECRET}:latest"
elif [[ -n "${OPENAI_API_KEY:-}" ]]; then
  # Switching from secret -> literal requires removing the secret binding first.
  append_csv SECRETS_TO_REMOVE "OPENAI_API_KEY"
fi

if [[ -n "${GMAIL_CLIENT_SECRET_SECRET:-}" ]]; then
  append_csv SECRETS_TO_UPDATE "GMAIL_CLIENT_SECRET=${GMAIL_CLIENT_SECRET_SECRET}:latest"
else
  append_csv SECRETS_TO_REMOVE "GMAIL_CLIENT_SECRET"
fi

if [[ -n "${GMAIL_REFRESH_TOKEN_SECRET:-}" ]]; then
  append_csv SECRETS_TO_UPDATE "GMAIL_REFRESH_TOKEN=${GMAIL_REFRESH_TOKEN_SECRET}:latest"
else
  append_csv SECRETS_TO_REMOVE "GMAIL_REFRESH_TOKEN"
fi

if [[ -n "${FILL_LINK_TOKEN_SECRET_SECRET:-}" ]]; then
  append_csv SECRETS_TO_UPDATE "FILL_LINK_TOKEN_SECRET=${FILL_LINK_TOKEN_SECRET_SECRET}:latest"
else
  append_csv SECRETS_TO_REMOVE "FILL_LINK_TOKEN_SECRET"
fi

if [[ -n "${STRIPE_SECRET_KEY_SECRET:-}" ]]; then
  append_csv SECRETS_TO_UPDATE "STRIPE_SECRET_KEY=${STRIPE_SECRET_KEY_SECRET}:latest"
else
  append_csv SECRETS_TO_REMOVE "STRIPE_SECRET_KEY"
fi

if [[ -n "${STRIPE_WEBHOOK_SECRET_SECRET:-}" ]]; then
  append_csv SECRETS_TO_UPDATE "STRIPE_WEBHOOK_SECRET=${STRIPE_WEBHOOK_SECRET_SECRET}:latest"
else
  append_csv SECRETS_TO_REMOVE "STRIPE_WEBHOOK_SECRET"
fi

if [[ -n "${FIREBASE_GITHUB_CLIENT_SECRET_SECRET:-}" ]]; then
  append_csv SECRETS_TO_UPDATE "FIREBASE_GITHUB_CLIENT_SECRET=${FIREBASE_GITHUB_CLIENT_SECRET_SECRET}:latest"
else
  append_csv SECRETS_TO_REMOVE "FIREBASE_GITHUB_CLIENT_SECRET"
fi

if [[ -n "${FIREBASE_GOOGLE_CLIENT_SECRET_SECRET:-}" ]]; then
  append_csv SECRETS_TO_UPDATE "FIREBASE_GOOGLE_CLIENT_SECRET=${FIREBASE_GOOGLE_CLIENT_SECRET_SECRET}:latest"
else
  append_csv SECRETS_TO_REMOVE "FIREBASE_GOOGLE_CLIENT_SECRET"
fi

if [[ -n "${SIGNING_PDF_CERT_PEM_SECRET:-}" ]]; then
  append_csv SECRETS_TO_UPDATE "SIGNING_PDF_CERT_PEM=${SIGNING_PDF_CERT_PEM_SECRET}:latest"
else
  append_csv SECRETS_TO_REMOVE "SIGNING_PDF_CERT_PEM"
fi

if [[ ${#SECRETS_TO_UPDATE[@]} -gt 0 ]]; then
  SECRET_FLAGS+=("--update-secrets" "$(IFS=,; echo "${SECRETS_TO_UPDATE[*]}")")
fi
if [[ ${#SECRETS_TO_REMOVE[@]} -gt 0 ]]; then
  SECRET_FLAGS+=("--remove-secrets" "$(IFS=,; echo "${SECRETS_TO_REMOVE[*]}")")
fi

BACKEND_REQUEST_TIMEOUT="${BACKEND_REQUEST_TIMEOUT:-900}"
BACKEND_MEMORY="${BACKEND_MEMORY:-1Gi}"
BACKEND_CPU="${BACKEND_CPU:-2}"

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

gcloud run deploy "$SERVICE_NAME" \
  "${DEPLOY_ARGS[@]}" \
  "${SECRET_FLAGS[@]}"

bash "${SCRIPT_DIR}/sync-detector-task-queues.sh" "$ENV_FILE"
