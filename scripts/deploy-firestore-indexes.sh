#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-dullypdf}"
ALLOW_NON_PROD="${DULLYPDF_ALLOW_NON_PROD:-}"
INDEXES_FILE="${INDEXES_FILE:-firestore.indexes.json}"

if [[ "$PROJECT_ID" != "dullypdf" && -z "$ALLOW_NON_PROD" ]]; then
  echo "Refusing to deploy Firestore indexes to non-prod project: $PROJECT_ID. Set DULLYPDF_ALLOW_NON_PROD=1 to override." >&2
  exit 1
fi

if [[ ! -f "$INDEXES_FILE" ]]; then
  echo "Missing required Firestore index config: $INDEXES_FILE" >&2
  exit 1
fi

firebase deploy --only firestore:indexes --project "$PROJECT_ID"
