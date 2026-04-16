#!/usr/bin/env bash
# Run the local frontend dev server pointed at the deployed dev Cloud Run
# backend. Useful for testing frontend changes against the real dev backend
# without spinning up a local backend container.
#
# Override the backend URL with VITE_API_URL if you want to hit a different
# target (e.g. a preview revision or a local backend).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

DEV_BACKEND_PROJECT="${DEV_BACKEND_PROJECT:-dullypdf-dev}"
DEV_BACKEND_REGION="${DEV_BACKEND_REGION:-us-east4}"
DEV_BACKEND_SERVICE="${DEV_BACKEND_SERVICE:-dullypdf-backend-east4}"
FALLBACK_DEV_BACKEND_URL="https://dullypdf-backend-east4-m5i6mt73oq-uk.a.run.app"

resolve_backend_url() {
  if [[ -n "${VITE_API_URL:-}" ]]; then
    printf '%s\n' "$VITE_API_URL"
    return
  fi
  if command -v gcloud >/dev/null 2>&1; then
    local resolved
    resolved="$(
      gcloud run services describe "$DEV_BACKEND_SERVICE" \
        --region "$DEV_BACKEND_REGION" \
        --project "$DEV_BACKEND_PROJECT" \
        --format='value(status.url)' 2>/dev/null || true
    )"
    if [[ -n "$resolved" ]]; then
      printf '%s\n' "$resolved"
      return
    fi
    echo "Warning: could not resolve deployed dev backend URL via gcloud; falling back to hardcoded default." >&2
  fi
  printf '%s\n' "$FALLBACK_DEV_BACKEND_URL"
}

BACKEND_URL="$(resolve_backend_url)"

echo "Starting frontend dev server on http://localhost:5173"
echo "Proxying /api/* to: $BACKEND_URL"

cd "${REPO_ROOT}/frontend"
VITE_API_URL="$BACKEND_URL" npm run dev
