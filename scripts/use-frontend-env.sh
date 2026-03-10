#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

MODE="${1:-dev}"
PUBLIC_FILE="${REPO_ROOT}/config/public/frontend.${MODE}.env"
LOCAL_OVERRIDE_FILE="${REPO_ROOT}/env/frontend.${MODE}.local.env"
LEGACY_OVERRIDE_FILE="${REPO_ROOT}/env/frontend.${MODE}.env"
OUTPUT_FILE="${REPO_ROOT}/frontend/.env.local"
EXPLICIT_OVERRIDE_FILE="${FRONTEND_ENV_OVERRIDE_FILE:-}"

if [[ ! -f "$PUBLIC_FILE" ]]; then
  echo "Missing committed frontend env file: $PUBLIC_FILE" >&2
  exit 1
fi

cp "$PUBLIC_FILE" "$OUTPUT_FILE"

if [[ -f "$LEGACY_OVERRIDE_FILE" ]]; then
  {
    printf "\n# Legacy local override (%s)\n" "$LEGACY_OVERRIDE_FILE"
    cat "$LEGACY_OVERRIDE_FILE"
  } >> "$OUTPUT_FILE"
  echo "Applied legacy override file: $LEGACY_OVERRIDE_FILE" >&2
fi

if [[ -f "$LOCAL_OVERRIDE_FILE" ]]; then
  {
    printf "\n# Local override (%s)\n" "$LOCAL_OVERRIDE_FILE"
    cat "$LOCAL_OVERRIDE_FILE"
  } >> "$OUTPUT_FILE"
fi

if [[ -n "$EXPLICIT_OVERRIDE_FILE" ]]; then
  if [[ "$EXPLICIT_OVERRIDE_FILE" != /* ]]; then
    EXPLICIT_OVERRIDE_FILE="${REPO_ROOT}/${EXPLICIT_OVERRIDE_FILE}"
  fi
  if [[ ! -f "$EXPLICIT_OVERRIDE_FILE" ]]; then
    echo "Missing FRONTEND_ENV_OVERRIDE_FILE: $EXPLICIT_OVERRIDE_FILE" >&2
    exit 1
  fi
  {
    printf "\n# Explicit override (%s)\n" "$EXPLICIT_OVERRIDE_FILE"
    cat "$EXPLICIT_OVERRIDE_FILE"
  } >> "$OUTPUT_FILE"
fi
