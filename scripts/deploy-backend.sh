#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-dullypdf}"
REGION="${REGION:-us-central1}"
SERVICE_NAME="${BACKEND_SERVICE:-dullypdf-backend}"
ALLOW_NON_PROD="${DULLYPDF_ALLOW_NON_PROD:-}"
ENV_FILE="${ENV_FILE:-env/backend.prod.env}"
EXAMPLE="config/backend.prod.env.example"

if [[ "$PROJECT_ID" != "dullypdf" && -z "$ALLOW_NON_PROD" ]]; then
  echo "Refusing to deploy backend to non-prod project: $PROJECT_ID. Set DULLYPDF_ALLOW_NON_PROD=1 to override." >&2
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
require_exact DETECTOR_MODE "tasks"
require_exact OPENAI_RENAME_MODE "tasks"
require_exact OPENAI_REMAP_MODE "tasks"
require_nonempty FIREBASE_PROJECT_ID
require_nonempty FORMS_BUCKET
require_nonempty TEMPLATES_BUCKET
require_nonempty SANDBOX_CORS_ORIGINS
require_nonempty CONTACT_TO_EMAIL
require_nonempty CONTACT_FROM_EMAIL
require_nonempty GMAIL_CLIENT_ID
require_nonempty OPENAI_RENAME_TASKS_PROJECT
require_nonempty OPENAI_RENAME_TASKS_LOCATION
require_nonempty OPENAI_RENAME_TASKS_QUEUE_LIGHT
require_nonempty OPENAI_RENAME_TASKS_QUEUE_HEAVY
require_nonempty OPENAI_RENAME_SERVICE_URL_LIGHT
require_nonempty OPENAI_RENAME_SERVICE_URL_HEAVY
require_nonempty OPENAI_RENAME_TASKS_SERVICE_ACCOUNT
require_nonempty OPENAI_REMAP_TASKS_PROJECT
require_nonempty OPENAI_REMAP_TASKS_LOCATION
require_nonempty OPENAI_REMAP_TASKS_QUEUE_LIGHT
require_nonempty OPENAI_REMAP_TASKS_QUEUE_HEAVY
require_nonempty OPENAI_REMAP_SERVICE_URL_LIGHT
require_nonempty OPENAI_REMAP_SERVICE_URL_HEAVY
require_nonempty OPENAI_REMAP_TASKS_SERVICE_ACCOUNT

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

if [[ "${CONTACT_REQUIRE_RECAPTCHA:-true}" != "true" || "${SIGNUP_REQUIRE_RECAPTCHA:-true}" != "true" ]]; then
  echo "CONTACT_REQUIRE_RECAPTCHA and SIGNUP_REQUIRE_RECAPTCHA must be true in prod." >&2
  exit 1
fi

if [[ "${CONTACT_REQUIRE_RECAPTCHA:-true}" == "true" || "${SIGNUP_REQUIRE_RECAPTCHA:-true}" == "true" ]]; then
  require_nonempty RECAPTCHA_SITE_KEY
  if [[ -z "${RECAPTCHA_PROJECT_ID:-}" && -z "${FIREBASE_PROJECT_ID:-}" ]]; then
    echo "RECAPTCHA_PROJECT_ID (or FIREBASE_PROJECT_ID) must be set for reCAPTCHA." >&2
    exit 1
  fi
fi

TMP_ENV_FILE="$(mktemp)"
python3 - <<'PY' "$ENV_FILE" "$TMP_ENV_FILE"
import json
import sys

env_path = sys.argv[1]
out_path = sys.argv[2]
script_only = {
    "PORT",
}

# If a Secret Manager binding is configured, do not also emit the literal env var
# into --env-vars-file. Cloud Run treats secret-backed env vars as a different
# "type", and deploying a string literal for the same key will fail.
secret_bindings = {
    "OPENAI_API_KEY_SECRET": "OPENAI_API_KEY",
    "GMAIL_CLIENT_SECRET_SECRET": "GMAIL_CLIENT_SECRET",
    "GMAIL_REFRESH_TOKEN_SECRET": "GMAIL_REFRESH_TOKEN",
    "FIREBASE_GITHUB_CLIENT_SECRET_SECRET": "FIREBASE_GITHUB_CLIENT_SECRET",
    "FIREBASE_GOOGLE_CLIENT_SECRET_SECRET": "FIREBASE_GOOGLE_CLIENT_SECRET",
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

TAG="$(date +%Y%m%d-%H%M%S)"
BACKEND_IMAGE="${BACKEND_IMAGE:-us-central1-docker.pkg.dev/${PROJECT_ID}/dullypdf-backend/backend:${TAG}}"

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

if [[ ${#SECRETS_TO_UPDATE[@]} -gt 0 ]]; then
  SECRET_FLAGS+=("--update-secrets" "$(IFS=,; echo "${SECRETS_TO_UPDATE[*]}")")
fi
if [[ ${#SECRETS_TO_REMOVE[@]} -gt 0 ]]; then
  SECRET_FLAGS+=("--remove-secrets" "$(IFS=,; echo "${SECRETS_TO_REMOVE[*]}")")
fi

gcloud run deploy "$SERVICE_NAME" \
  --image "$BACKEND_IMAGE" \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --allow-unauthenticated \
  --env-vars-file "$TMP_ENV_FILE" \
  "${SECRET_FLAGS[@]}"

rm -f "$TMP_ENV_FILE"
