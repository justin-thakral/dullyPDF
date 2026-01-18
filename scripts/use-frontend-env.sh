#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-dev}"
ENV_DIR="env"
ENV_FILE="${ENV_DIR}/frontend.${MODE}.env"
EXAMPLE="config/frontend.${MODE}.env.example"

if [[ ! -f "$ENV_FILE" ]]; then
  if [[ -f "$EXAMPLE" ]]; then
    mkdir -p "$ENV_DIR"
    cp "$EXAMPLE" "$ENV_FILE"
    echo "Created $ENV_FILE from $EXAMPLE. Update values as needed."
    exit 1
  fi
  echo "Missing $ENV_FILE and $EXAMPLE."
  exit 1
fi

cp "$ENV_FILE" "frontend/.env.local"
