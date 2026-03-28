#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-env/backend.prod.env}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing detector env file: $ENV_FILE" >&2
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

if [[ "${DETECTOR_MODE:-}" != "tasks" ]]; then
  echo "Skipping detector queue sync because DETECTOR_MODE=${DETECTOR_MODE:-<unset>}." >&2
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_detector_routing.sh"

PROJECT_ID="${PROJECT_ID:-${DETECTOR_TASKS_PROJECT:-${FIREBASE_PROJECT_ID:-dullypdf}}}"
QUEUE_LOCATION="${DETECTOR_TASKS_LOCATION:-${REGION:-us-east4}}"
PRUNE_STALE_QUEUES_ENABLED="${DETECTOR_TASKS_PRUNE_STALE_QUEUES:-false}"

detector_set_active_routing_vars

is_integer() {
  local raw="${1:-}"
  [[ "$raw" =~ ^[0-9]+$ ]]
}

default_max_instances() {
  local target="$1"
  local profile="$2"
  case "${target}:${profile}" in
    cpu:light)
      printf '%s\n' "${DETECTOR_MAX_INSTANCES_LIGHT:-5}"
      ;;
    cpu:heavy)
      printf '%s\n' "${DETECTOR_MAX_INSTANCES_HEAVY:-2}"
      ;;
    gpu:light)
      printf '%s\n' "${DETECTOR_GPU_MAX_INSTANCES_LIGHT:-1}"
      ;;
    gpu:heavy)
      printf '%s\n' "${DETECTOR_GPU_MAX_INSTANCES_HEAVY:-1}"
      ;;
    *)
      echo "Unsupported detector capacity target: ${target}:${profile}" >&2
      exit 1
      ;;
  esac
}

resolve_capacity_for_target_profile() {
  local target="$1"
  local profile="$2"
  local service_name
  local service_region
  local fallback_scale
  local service_json=""
  local max_scale=""
  local concurrency=""
  local capacity=1

  service_name="$(detector_service_name_for_target "$target" "$profile")"
  service_region="$(detector_region_for_target "$target")"
  fallback_scale="$(default_max_instances "$target" "$profile")"

  service_json="$(
    gcloud run services describe "$service_name" \
      --project "$PROJECT_ID" \
      --region "$service_region" \
      --format=json 2>/dev/null || true
  )"

  if [[ -n "$service_json" ]]; then
    max_scale="$(printf '%s' "$service_json" | jq -r '.spec.template.metadata.annotations["autoscaling.knative.dev/maxScale"] // empty')"
    concurrency="$(printf '%s' "$service_json" | jq -r '.spec.template.spec.containerConcurrency // empty')"
  fi

  if ! is_integer "$max_scale"; then
    max_scale="$fallback_scale"
  fi
  if ! is_integer "$concurrency"; then
    concurrency="1"
  fi

  capacity=$(( max_scale * concurrency ))
  if (( capacity < 1 )); then
    capacity=1
  fi
  printf '%s\n' "$capacity"
}

active_target_for_profile() {
  local profile="$1"
  if [[ "$profile" == "heavy" ]]; then
    printf '%s\n' "$DETECTOR_TARGET_HEAVY_ACTIVE"
  else
    printf '%s\n' "$DETECTOR_TARGET_LIGHT_ACTIVE"
  fi
}

active_service_name_for_profile() {
  local profile="$1"
  if [[ "$profile" == "heavy" ]]; then
    printf '%s\n' "$DETECTOR_SERVICE_NAME_HEAVY_ACTIVE"
  else
    printf '%s\n' "$DETECTOR_SERVICE_NAME_LIGHT_ACTIVE"
  fi
}

active_service_region_for_profile() {
  local profile="$1"
  if [[ "$profile" == "heavy" ]]; then
    printf '%s\n' "$DETECTOR_SERVICE_REGION_HEAVY_ACTIVE"
  else
    printf '%s\n' "$DETECTOR_SERVICE_REGION_LIGHT_ACTIVE"
  fi
}

queue_for_profile() {
  local profile="$1"
  if [[ "$profile" == "heavy" ]] \
    && detector_is_truthy "${DETECTOR_SERIALIZE_GPU_TASKS:-false}" \
    && [[ "$DETECTOR_ROUTING_MODE_RESOLVED" == "gpu" ]]; then
    printf '%s\n' "${DETECTOR_TASKS_QUEUE_LIGHT:-${DETECTOR_TASKS_QUEUE:-}}"
    return
  fi

  if [[ "$profile" == "heavy" ]]; then
    printf '%s\n' "${DETECTOR_TASKS_QUEUE_HEAVY:-${DETECTOR_TASKS_QUEUE:-}}"
  else
    printf '%s\n' "${DETECTOR_TASKS_QUEUE_LIGHT:-${DETECTOR_TASKS_QUEUE:-}}"
  fi
}

resolve_profile_capacity() {
  local profile="$1"
  local target
  target="$(active_target_for_profile "$profile")"
  resolve_capacity_for_target_profile "$target" "$profile"
}

resolve_queue_retry_attempts() {
  local attempts="${DETECTOR_TASKS_MAX_ATTEMPTS:-5}"
  if ! is_integer "$attempts" || (( attempts < 1 )); then
    attempts="5"
  fi
  printf '%s\n' "$attempts"
}

create_queue() {
  local queue_name="$1"
  local desired_capacity="$2"
  local reason="$3"
  local retry_attempts
  retry_attempts="$(resolve_queue_retry_attempts)"

  echo "Creating ${queue_name} with maxConcurrentDispatches=${desired_capacity} (${reason})."
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    return
  fi

  gcloud tasks queues create "$queue_name" \
    --project "$PROJECT_ID" \
    --location "$QUEUE_LOCATION" \
    --max-concurrent-dispatches "$desired_capacity" \
    --max-dispatches-per-second "$desired_capacity" \
    --max-attempts "$retry_attempts" >/dev/null
}

sync_queue() {
  local queue_name="$1"
  local desired_capacity="$2"
  local reason="$3"
  local current_capacity=""
  local queue_json=""

  queue_json="$(
    gcloud tasks queues describe "$queue_name" \
      --project "$PROJECT_ID" \
      --location "$QUEUE_LOCATION" \
      --format=json 2>/dev/null || true
  )"

  if [[ -z "$queue_json" ]]; then
    create_queue "$queue_name" "$desired_capacity" "$reason"
    return
  fi

  current_capacity="$(printf '%s' "$queue_json" | jq -r '.rateLimits.maxConcurrentDispatches // empty')"
  if ! is_integer "$current_capacity"; then
    current_capacity="unknown"
  fi

  if [[ "$current_capacity" == "$desired_capacity" ]]; then
    echo "Queue ${queue_name} already at maxConcurrentDispatches=${desired_capacity} (${reason})."
    return
  fi

  echo "Setting ${queue_name} maxConcurrentDispatches=${desired_capacity} (${reason}; current=${current_capacity})."
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    return
  fi

  gcloud tasks queues update "$queue_name" \
    --project "$PROJECT_ID" \
    --location "$QUEUE_LOCATION" \
    --max-concurrent-dispatches "$desired_capacity" >/dev/null
}

delete_queue_if_present() {
  local queue_name="$1"
  local reason="$2"
  local queue_json=""

  queue_json="$(
    gcloud tasks queues describe "$queue_name" \
      --project "$PROJECT_ID" \
      --location "$QUEUE_LOCATION" \
      --format=json 2>/dev/null || true
  )"
  if [[ -z "$queue_json" ]]; then
    return
  fi

  echo "Deleting stale detector queue ${queue_name} (${reason})."
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    return
  fi

  gcloud tasks queues delete "$queue_name" \
    --project "$PROJECT_ID" \
    --location "$QUEUE_LOCATION" \
    --quiet >/dev/null
}

declare -A QUEUE_CAPACITY=()
declare -A QUEUE_REASON=()

if detector_is_truthy "${DETECTOR_SERIALIZE_GPU_TASKS:-false}" \
  && [[ "$DETECTOR_ROUTING_MODE_RESOLVED" == "gpu" ]]; then
  shared_queue="$(queue_for_profile "light")"
  if [[ -z "$shared_queue" ]]; then
    echo "DETECTOR_SERIALIZE_GPU_TASKS=true requires DETECTOR_TASKS_QUEUE or DETECTOR_TASKS_QUEUE_LIGHT." >&2
    exit 1
  fi
  QUEUE_CAPACITY["$shared_queue"]="1"
  QUEUE_REASON["$shared_queue"]="single-GPU serialized queue for gpu routing"

  legacy_heavy_queue="${DETECTOR_TASKS_QUEUE_HEAVY:-}"
  if [[ -n "$legacy_heavy_queue" && "$legacy_heavy_queue" != "$shared_queue" ]]; then
    QUEUE_CAPACITY["$legacy_heavy_queue"]="1"
    QUEUE_REASON["$legacy_heavy_queue"]="safety cap for legacy heavy queue during single-GPU mode"
  fi

  if detector_is_truthy "${DETECTOR_GPU_BUSY_FALLBACK_TO_CPU:-false}"; then
    cpu_spill_queue="${DETECTOR_TASKS_QUEUE_LIGHT_CPU:-${DETECTOR_TASKS_QUEUE_CPU:-}}"
    if [[ -z "$cpu_spill_queue" ]]; then
      echo "DETECTOR_GPU_BUSY_FALLBACK_TO_CPU=true requires DETECTOR_TASKS_QUEUE_LIGHT_CPU or DETECTOR_TASKS_QUEUE_CPU." >&2
      exit 1
    fi

    cpu_capacity="$(resolve_capacity_for_target_profile "cpu" "light")"
    QUEUE_CAPACITY["$cpu_spill_queue"]="$cpu_capacity"
    QUEUE_REASON["$cpu_spill_queue"]="cpu spillover queue for gpu-first small PDFs"
  fi
else
  for profile in light heavy; do
    queue_name="$(queue_for_profile "$profile")"
    if [[ -z "$queue_name" ]]; then
      continue
    fi

    profile_capacity="$(resolve_profile_capacity "$profile")"
    current_total="${QUEUE_CAPACITY[$queue_name]:-0}"
    QUEUE_CAPACITY["$queue_name"]=$(( current_total + profile_capacity ))

    current_reason="${QUEUE_REASON[$queue_name]:-}"
    addition="${profile}:capacity=${profile_capacity}"
    if [[ -n "$current_reason" ]]; then
      QUEUE_REASON["$queue_name"]="${current_reason}, ${addition}"
    else
      QUEUE_REASON["$queue_name"]="$addition"
    fi
  done
fi

if [[ ${#QUEUE_CAPACITY[@]} -eq 0 ]]; then
  echo "No detector queues resolved from $ENV_FILE." >&2
  exit 1
fi

while IFS= read -r queue_name; do
  sync_queue "$queue_name" "${QUEUE_CAPACITY[$queue_name]}" "${QUEUE_REASON[$queue_name]}"
done < <(printf '%s\n' "${!QUEUE_CAPACITY[@]}" | sort)

if detector_is_truthy "$PRUNE_STALE_QUEUES_ENABLED"; then
  declare -A KNOWN_DETECTOR_QUEUES=()
  for candidate in \
    "${DETECTOR_TASKS_QUEUE:-}" \
    "${DETECTOR_TASKS_QUEUE_LIGHT:-}" \
    "${DETECTOR_TASKS_QUEUE_HEAVY:-}" \
    "${DETECTOR_TASKS_QUEUE_CPU:-}" \
    "${DETECTOR_TASKS_QUEUE_LIGHT_CPU:-}" \
    "commonforms-detect" \
    "commonforms-detect-light" \
    "commonforms-detect-heavy" \
    "commonforms-detect-light-cpu"
  do
    if [[ -n "$candidate" ]]; then
      KNOWN_DETECTOR_QUEUES["$candidate"]="1"
    fi
  done

  while IFS= read -r queue_name; do
    if [[ -z "$queue_name" ]]; then
      continue
    fi
    if [[ -z "${KNOWN_DETECTOR_QUEUES[$queue_name]:-}" ]]; then
      continue
    fi
    if [[ -n "${QUEUE_CAPACITY[$queue_name]:-}" ]]; then
      continue
    fi
    delete_queue_if_present "$queue_name" "not part of the active detector routing plan"
  done < <(
    gcloud tasks queues list \
      --project "$PROJECT_ID" \
      --location "$QUEUE_LOCATION" \
      --format='value(name)' 2>/dev/null || true
  )
fi
