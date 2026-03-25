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

load_env_secret_value() {
  local value_var="$1"
  local secret_var="$2"
  local project_var="$3"
  local default_project="${4:-}"

  local secret_name="${!secret_var:-}"
  if [[ -z "$secret_name" ]]; then
    return 0
  fi

  if ! command -v gcloud >/dev/null 2>&1; then
    echo "Missing gcloud; cannot load ${secret_var}." >&2
    exit 1
  fi

  local secret_project="${!project_var:-$default_project}"
  if [[ -z "$secret_project" ]]; then
    echo "${secret_var} set but ${project_var} or a default project is missing." >&2
    exit 1
  fi

  local secret_value
  secret_value="$(gcloud secrets versions access latest \
    --secret "$secret_name" \
    --project "$secret_project")"
  printf -v "$value_var" '%s' "$secret_value"
  export "$value_var"
}

load_backend_email_secrets() {
  local default_project="${GMAIL_SECRETS_PROJECT:-${FIREBASE_PROJECT_ID:-}}"
  load_env_secret_value GMAIL_CLIENT_SECRET GMAIL_CLIENT_SECRET_SECRET GMAIL_SECRETS_PROJECT "$default_project"
  load_env_secret_value GMAIL_REFRESH_TOKEN GMAIL_REFRESH_TOKEN_SECRET GMAIL_SECRETS_PROJECT "$default_project"
}
