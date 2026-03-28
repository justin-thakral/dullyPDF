#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_ENV_FILE="${REPO_ROOT}/env/backend.prod.env"
CONFIRM_FLAG="${1:-}"
ENV_FILE="${2:-${DEFAULT_ENV_FILE}}"

usage() {
  cat >&2 <<'EOF'
Usage:
  bash scripts/lock-signing-storage-retention.sh --yes-lock-retention [env-file]

This command permanently locks the Cloud Storage retention policy on SIGNING_BUCKET.
Only run it after verifying the bucket retention period and getting explicit ops approval.
EOF
}

if [[ "${CONFIRM_FLAG}" != "--yes-lock-retention" ]]; then
  usage
  exit 1
fi

if ! command -v gcloud >/dev/null 2>&1; then
  echo "Missing gcloud; cannot lock signing bucket retention." >&2
  exit 1
fi

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

SIGNING_BUCKET="${SIGNING_BUCKET:-}"
if [[ -z "${SIGNING_BUCKET}" ]]; then
  echo "SIGNING_BUCKET must be set before locking retention." >&2
  exit 1
fi

PROJECT_ID="${PROJECT_ID:-${FIREBASE_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}}"
if [[ -z "${PROJECT_ID}" ]]; then
  echo "Unable to determine GCP project. Set PROJECT_ID or FIREBASE_PROJECT_ID." >&2
  exit 1
fi

BUCKET_URL="gs://${SIGNING_BUCKET}"
LOCKED_STATE="$(gcloud storage buckets describe "${BUCKET_URL}" --project "${PROJECT_ID}" --format='value(retention_policy.isLocked)' 2>/dev/null || true)"
RETENTION_PERIOD="$(gcloud storage buckets describe "${BUCKET_URL}" --project "${PROJECT_ID}" --format='value(retention_policy.retentionPeriod)' 2>/dev/null || true)"

if [[ -z "${RETENTION_PERIOD}" ]]; then
  echo "Bucket ${BUCKET_URL} does not expose a retention policy yet. Configure retention before locking it." >&2
  exit 1
fi

if [[ "${LOCKED_STATE}" == "True" || "${LOCKED_STATE}" == "true" ]]; then
  echo "Retention policy is already locked for ${BUCKET_URL} (${RETENTION_PERIOD} seconds)."
  exit 0
fi

echo "About to irreversibly lock the retention policy on ${BUCKET_URL} in project ${PROJECT_ID}."
echo "Current retention period: ${RETENTION_PERIOD} seconds"

gcloud storage buckets update "${BUCKET_URL}" --project "${PROJECT_ID}" --lock-retention-period

echo "Locked retention policy:"
gcloud storage buckets describe "${BUCKET_URL}" --project "${PROJECT_ID}" --format='value(retention_policy.isLocked,retention_policy.retentionPeriod)'
