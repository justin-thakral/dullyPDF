#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-dullypdf}"
ALLOW_NON_PROD="${DULLYPDF_ALLOW_NON_PROD:-}"
MODE="prod"
ENV_FILE="${ENV_FILE:-env/frontend.${MODE}.env}"
EXAMPLE="config/frontend.${MODE}.env.example"
CRITICAL_WEBP_ASSETS=(
  "/DullyPDFLogoImproved.webp"
  "/demo/mobile-raw-pdf.webp"
  "/demo/mobile-commonforms.webp"
  "/demo/mobile-inspector.webp"
  "/demo/mobile-field-list.webp"
  "/demo/mobile-rename-remap.webp"
  "/demo/mobile-filled.webp"
)

if [[ "$PROJECT_ID" != "dullypdf" && -z "$ALLOW_NON_PROD" ]]; then
  echo "Refusing to deploy frontend to non-prod project: $PROJECT_ID. Set DULLYPDF_ALLOW_NON_PROD=1 to override." >&2
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
    echo "Expected $name to be empty for prod builds." >&2
    exit 1
  fi
}

require_file() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo "Missing required file: $path" >&2
    exit 1
  fi
}

check_remote_content_type() {
  local url="$1"
  local expected_prefix="$2"
  local content_type
  if ! content_type="$(curl -fsSL -o /dev/null -w '%{content_type}' "$url")"; then
    echo "Failed to fetch $url for content-type validation." >&2
    exit 1
  fi
  if [[ "$content_type" != "$expected_prefix"* ]]; then
    echo "Unexpected content type for $url: ${content_type:-<empty>} (expected prefix: $expected_prefix)." >&2
    exit 1
  fi
}

require_nonempty VITE_API_URL
require_nonempty VITE_DETECTION_API_URL
require_nonempty VITE_FIREBASE_PROJECT_ID

if [[ "${VITE_API_URL}" == *"localhost"* || "${VITE_API_URL}" == *"127.0.0.1"* ]]; then
  echo "VITE_API_URL must point to prod backend, not localhost." >&2
  exit 1
fi

if [[ "${VITE_DETECTION_API_URL}" == *"localhost"* || "${VITE_DETECTION_API_URL}" == *"127.0.0.1"* ]]; then
  echo "VITE_DETECTION_API_URL must point to prod backend, not localhost." >&2
  exit 1
fi

if [[ "$VITE_FIREBASE_PROJECT_ID" != "$PROJECT_ID" ]]; then
  echo "VITE_FIREBASE_PROJECT_ID must match $PROJECT_ID for prod deploys." >&2
  exit 1
fi

require_empty VITE_ADMIN_TOKEN

if [[ "${VITE_CONTACT_REQUIRE_RECAPTCHA:-true}" == "true" || "${VITE_SIGNUP_REQUIRE_RECAPTCHA:-true}" == "true" ]]; then
  require_nonempty VITE_RECAPTCHA_SITE_KEY
fi

bash scripts/use-frontend-env.sh "$MODE"
if command -v convert >/dev/null 2>&1; then
  bash scripts/convert-webp-assets.sh
else
  echo "Warning: ImageMagick 'convert' not found; skipping auto-generation and relying on committed WebP assets." >&2
fi

(
  cd frontend
  npm run build
)

for asset_path in "${CRITICAL_WEBP_ASSETS[@]}"; do
  require_file "frontend/dist${asset_path}"
done

firebase deploy --only hosting --project "$PROJECT_ID"

LIVE_BASE_URL="https://${PROJECT_ID}.web.app"
for asset_path in "${CRITICAL_WEBP_ASSETS[@]}"; do
  check_remote_content_type "${LIVE_BASE_URL}${asset_path}" "image/webp"
done

echo "Frontend deploy checks passed: critical WebP assets are present locally and served remotely as image/webp."
