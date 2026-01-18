#!/usr/bin/env bash

load_firebase_secret() {
  if [[ -n "${FIREBASE_CREDENTIALS_SECRET:-}" ]]; then
    if ! command -v gcloud >/dev/null 2>&1; then
      echo "Missing gcloud; cannot load FIREBASE_CREDENTIALS_SECRET." >&2
      exit 1
    fi
    local secret_project="${FIREBASE_CREDENTIALS_PROJECT:-${FIREBASE_PROJECT_ID:-}}"
    if [[ -z "$secret_project" ]]; then
      echo "FIREBASE_CREDENTIALS_SECRET set but FIREBASE_CREDENTIALS_PROJECT or FIREBASE_PROJECT_ID is missing." >&2
      exit 1
    fi
    FIREBASE_CREDENTIALS="$(gcloud secrets versions access latest \
      --secret "$FIREBASE_CREDENTIALS_SECRET" \
      --project "$secret_project")"
    export FIREBASE_CREDENTIALS
  fi
}
