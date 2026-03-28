#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-env/backend.prod.env}"
BACKEND_EXAMPLE="config/backend.prod.env.example"

if [[ ! -f "$ENV_FILE" ]]; then
  if [[ -f "$BACKEND_EXAMPLE" ]]; then
    mkdir -p "env"
    cp "$BACKEND_EXAMPLE" "$ENV_FILE"
    echo "Created $ENV_FILE from $BACKEND_EXAMPLE. Update values and re-run." >&2
    exit 1
  fi
  echo "Missing $ENV_FILE and $BACKEND_EXAMPLE." >&2
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_detector_routing.sh"

PROJECT_ID="${PROJECT_ID:-${FIREBASE_PROJECT_ID:-dullypdf}}"
PRUNE_REGION_CANDIDATES="${PRUNE_REGION_CANDIDATES:-us-east4,us-central1}"
QUEUE_LOCATION="${DETECTOR_TASKS_LOCATION:-${REGION:-us-east4}}"

declare -a REGION_CANDIDATES=()
IFS=',' read -r -a REGION_CANDIDATES <<< "$PRUNE_REGION_CANDIDATES"

run_cmd() {
  echo "+ $*"
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    return 0
  fi
  "$@"
}

service_exists() {
  local service_name="$1"
  local region="$2"
  gcloud run services describe "$service_name" \
    --region "$region" \
    --project "$PROJECT_ID" >/dev/null 2>&1
}

delete_run_service_if_present() {
  local service_name="$1"
  local region="$2"
  local reason="$3"
  if ! service_exists "$service_name" "$region"; then
    return
  fi
  echo "Deleting stale Cloud Run service ${service_name} in ${region} (${reason})."
  run_cmd gcloud run services delete "$service_name" \
    --region "$region" \
    --project "$PROJECT_ID" \
    --quiet
}

queue_exists() {
  local queue_name="$1"
  local location="$2"
  gcloud tasks queues describe "$queue_name" \
    --project "$PROJECT_ID" \
    --location "$location" >/dev/null 2>&1
}

delete_queue_if_present() {
  local queue_name="$1"
  local location="$2"
  local reason="$3"
  if ! queue_exists "$queue_name" "$location"; then
    return
  fi
  echo "Deleting stale Cloud Tasks queue ${queue_name} in ${location} (${reason})."
  run_cmd gcloud tasks queues delete "$queue_name" \
    --project "$PROJECT_ID" \
    --location "$location" \
    --quiet
}

prune_duplicate_regions_for_service() {
  local service_name="$1"
  local expected_region="$2"
  local reason="$3"
  local region=""
  for region in "${REGION_CANDIDATES[@]}"; do
    if [[ -z "$region" || "$region" == "$expected_region" ]]; then
      continue
    fi
    delete_run_service_if_present "$service_name" "$region" "$reason"
  done
}

detector_set_active_routing_vars

DETECTOR_CPU_REGION="$(detector_cpu_region)"
DETECTOR_SERVICE_NAME_LIGHT_CPU="$(detector_service_name_for_target "cpu" "light")"
DETECTOR_SERVICE_NAME_HEAVY_CPU="$(detector_service_name_for_target "cpu" "heavy")"

OPENAI_RENAME_REGION="${OPENAI_RENAME_TASKS_LOCATION:-${REGION:-us-east4}}"
OPENAI_REMAP_REGION="${OPENAI_REMAP_TASKS_LOCATION:-${REGION:-us-east4}}"
OPENAI_RENAME_SERVICE_NAME_LIGHT="${OPENAI_RENAME_SERVICE_NAME_LIGHT:-dullypdf-openai-rename-light}"
OPENAI_RENAME_SERVICE_NAME_HEAVY="${OPENAI_RENAME_SERVICE_NAME_HEAVY:-dullypdf-openai-rename-heavy}"
OPENAI_REMAP_SERVICE_NAME_LIGHT="${OPENAI_REMAP_SERVICE_NAME_LIGHT:-dullypdf-openai-remap-light}"
OPENAI_REMAP_SERVICE_NAME_HEAVY="${OPENAI_REMAP_SERVICE_NAME_HEAVY:-dullypdf-openai-remap-heavy}"

prune_duplicate_regions_for_service \
  "$DETECTOR_SERVICE_NAME_LIGHT_CPU" \
  "$DETECTOR_CPU_REGION" \
  "detector light CPU region should match the active routing plan"
prune_duplicate_regions_for_service \
  "$DETECTOR_SERVICE_NAME_HEAVY_CPU" \
  "$DETECTOR_CPU_REGION" \
  "detector heavy CPU region should match the active routing plan"
prune_duplicate_regions_for_service \
  "$OPENAI_RENAME_SERVICE_NAME_LIGHT" \
  "$OPENAI_RENAME_REGION" \
  "OpenAI rename light worker should only exist in the configured task region"
prune_duplicate_regions_for_service \
  "$OPENAI_RENAME_SERVICE_NAME_HEAVY" \
  "$OPENAI_RENAME_REGION" \
  "OpenAI rename heavy worker should only exist in the configured task region"
prune_duplicate_regions_for_service \
  "$OPENAI_REMAP_SERVICE_NAME_LIGHT" \
  "$OPENAI_REMAP_REGION" \
  "OpenAI remap light worker should only exist in the configured task region"
prune_duplicate_regions_for_service \
  "$OPENAI_REMAP_SERVICE_NAME_HEAVY" \
  "$OPENAI_REMAP_REGION" \
  "OpenAI remap heavy worker should only exist in the configured task region"

for retired_service in \
  "dullypdf-detector" \
  "dullypdf-det-light-probe-cpu" \
  "dullypdf-detector-light-bench-cpu" \
  "dullypdf-detector-heavy-bench-cpu" \
  "dullypdf-detector-light-bench-gpu" \
  "dullypdf-detector-heavy-bench-gpu"
do
  for region in "${REGION_CANDIDATES[@]}"; do
    if [[ -z "$region" ]]; then
      continue
    fi
    delete_run_service_if_present \
      "$retired_service" \
      "$region" \
      "retired experimental detector service not used by the current deploy path"
  done
done

DETECTOR_TASKS_PRUNE_STALE_QUEUES=true bash "${SCRIPT_DIR}/sync-detector-task-queues.sh" "$ENV_FILE"

for region in "${REGION_CANDIDATES[@]}"; do
  if [[ -z "$region" || "$region" == "$QUEUE_LOCATION" ]]; then
    continue
  fi
  for stale_queue in \
    "commonforms-detect" \
    "commonforms-detect-light" \
    "commonforms-detect-heavy" \
    "commonforms-detect-light-cpu"
  do
    delete_queue_if_present \
      "$stale_queue" \
      "$region" \
      "detector queues should only exist in the configured task location"
  done
done
