#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash scripts/ci/deploy_frontend_target.sh --environment <dev|prod> [options]

Options:
  --environment <dev|prod>  Target environment
  --env-file <path>         Optional frontend override env file
  --dry-run                 Print the derived deploy command without executing it
EOF
}

DEPLOY_ENV=""
ENV_FILE_OVERRIDE=""
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
  PROJECT_ID="${PROJECT_ID:-dullypdf}"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "+ PROJECT_ID=${PROJECT_ID} ENV_FILE=${ENV_FILE_OVERRIDE:-<default>} bash scripts/deploy-frontend.sh"
    exit 0
  fi
  if [[ -n "$ENV_FILE_OVERRIDE" ]]; then
    env PROJECT_ID="$PROJECT_ID" ENV_FILE="$ENV_FILE_OVERRIDE" bash scripts/deploy-frontend.sh
  else
    env PROJECT_ID="$PROJECT_ID" bash scripts/deploy-frontend.sh
  fi
  exit 0
fi

PROJECT_ID="${PROJECT_ID:-dullypdf-dev}"
MODE="dev"
BASE_URL="https://${PROJECT_ID}.web.app"
TMP_OVERRIDE_FILE="$(mktemp)"
cleanup() {
  rm -f "$TMP_OVERRIDE_FILE" || true
}
trap cleanup EXIT

if [[ -n "$ENV_FILE_OVERRIDE" ]]; then
  if [[ "$ENV_FILE_OVERRIDE" != /* ]]; then
    ENV_FILE_OVERRIDE="${REPO_ROOT}/${ENV_FILE_OVERRIDE}"
  fi
  if [[ ! -f "$ENV_FILE_OVERRIDE" ]]; then
    echo "Missing frontend override file: ${ENV_FILE_OVERRIDE}" >&2
    exit 1
  fi
  cat "$ENV_FILE_OVERRIDE" >> "$TMP_OVERRIDE_FILE"
  printf '\n' >> "$TMP_OVERRIDE_FILE"
fi

append_default_env() {
  local key="$1"
  local value="$2"
  if grep -Eq "^${key}=" "$TMP_OVERRIDE_FILE"; then
    return 0
  fi
  printf '%s=%s\n' "$key" "$value" >> "$TMP_OVERRIDE_FILE"
}

append_default_env "VITE_API_URL" "$BASE_URL"
append_default_env "VITE_DETECTION_API_URL" "$BASE_URL"
append_default_env "VITE_ADMIN_TOKEN" ""

if [[ "$DRY_RUN" == "1" ]]; then
  echo "+ FRONTEND_ENV_OVERRIDE_FILE=${TMP_OVERRIDE_FILE} bash scripts/use-frontend-env.sh ${MODE}"
  echo "+ (cd frontend && npm run build:dev)"
  echo "+ node scripts/generate-static-html.mjs"
  echo "+ node scripts/generate-sitemap.mjs"
  echo "+ firebase deploy --only hosting --project ${PROJECT_ID}"
  exit 0
fi

env FRONTEND_ENV_OVERRIDE_FILE="$TMP_OVERRIDE_FILE" bash "${REPO_ROOT}/scripts/use-frontend-env.sh" "$MODE"

if command -v convert >/dev/null 2>&1; then
  bash "${REPO_ROOT}/scripts/convert-webp-assets.sh"
else
  echo "Warning: ImageMagick 'convert' not found; relying on committed WebP assets." >&2
fi

(
  cd "${REPO_ROOT}/frontend"
  npm run build:dev
)

node "${REPO_ROOT}/scripts/generate-static-html.mjs"
node "${REPO_ROOT}/scripts/generate-sitemap.mjs"

for required_path in \
  "${REPO_ROOT}/frontend/dist/index.html" \
  "${REPO_ROOT}/frontend/dist/healthcare-pdf-automation/index.html" \
  "${REPO_ROOT}/frontend/dist/pdf-to-fillable-form/index.html" \
  "${REPO_ROOT}/frontend/dist/usage-docs/index.html" \
  "${REPO_ROOT}/frontend/dist/sitemap.xml"; do
  if [[ ! -f "$required_path" ]]; then
    echo "Missing required build artifact: ${required_path}" >&2
    exit 1
  fi
done

firebase deploy --only hosting --project "$PROJECT_ID"

if ! body="$(curl --silent --fail "${BASE_URL}/fill-pdf-from-csv")"; then
  echo "Failed to fetch ${BASE_URL}/fill-pdf-from-csv for prerender validation." >&2
  exit 1
fi

if ! grep -Fq 'data-seo-jsonld="true"' <<<"$body"; then
  echo "Expected ${BASE_URL}/fill-pdf-from-csv to contain prerendered SEO markup." >&2
  exit 1
fi

if [[ "$(curl -s -o /dev/null -w '%{http_code}' "${BASE_URL}/fill-pdf-from-csv/")" != "301" ]]; then
  echo "Expected ${BASE_URL}/fill-pdf-from-csv/ to return 301." >&2
  exit 1
fi

if [[ "$(curl -s -o /dev/null -w '%{http_code}' "${BASE_URL}/this-path-should-not-exist")" == "200" ]]; then
  echo "Unexpected 200 from ${BASE_URL}/this-path-should-not-exist." >&2
  exit 1
fi

echo "Dev frontend deploy checks passed."
