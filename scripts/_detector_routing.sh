#!/usr/bin/env bash

detector_is_truthy() {
  local raw="${1:-}"
  case "${raw,,}" in
    1|true|yes|on)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

detector_normalize_routing_mode() {
  local raw="${1:-${DETECTOR_ROUTING_MODE:-}}"
  if [[ -z "$raw" ]]; then
    if detector_is_truthy "${DEV_STACK_DETECTOR_GPU:-false}"; then
      printf '%s\n' "gpu"
    else
      printf '%s\n' "cpu"
    fi
    return 0
  fi

  case "${raw,,}" in
    cpu|cpu_only|all_cpu|cpu-all)
      printf '%s\n' "cpu"
      ;;
    split|hybrid|mixed|cpu_gpu|cpu-light-gpu-heavy|cpu_light_gpu_heavy)
      printf '%s\n' "split"
      ;;
    gpu|gpu_only|gpu_all|all_gpu|all-gpu)
      printf '%s\n' "gpu"
      ;;
    *)
      echo "Unsupported detector routing mode: ${raw}" >&2
      return 1
      ;;
  esac
}

detector_target_for_profile() {
  local routing_mode="$1"
  local profile="$2"
  case "${routing_mode}:${profile}" in
    cpu:light|cpu:heavy)
      printf '%s\n' "cpu"
      ;;
    split:light)
      printf '%s\n' "cpu"
      ;;
    split:heavy)
      printf '%s\n' "gpu"
      ;;
    gpu:light|gpu:heavy)
      printf '%s\n' "gpu"
      ;;
    *)
      echo "Unsupported detector routing target: mode=${routing_mode} profile=${profile}" >&2
      return 1
      ;;
  esac
}

detector_cpu_region() {
  printf '%s\n' "${DETECTOR_SERVICE_REGION:-${REGION:-${DETECTOR_TASKS_LOCATION:-us-central1}}}"
}

detector_gpu_region() {
  local cpu_region
  cpu_region="$(detector_cpu_region)"
  printf '%s\n' "${DETECTOR_GPU_REGION:-${cpu_region}}"
}

detector_region_for_target() {
  local target="$1"
  case "$target" in
    cpu)
      detector_cpu_region
      ;;
    gpu)
      detector_gpu_region
      ;;
    *)
      echo "Unsupported detector target: ${target}" >&2
      return 1
      ;;
  esac
}

detector_service_name_for_target() {
  local target="$1"
  local profile="$2"
  local var_name=""
  local default_value=""
  case "${target}:${profile}" in
    cpu:light)
      var_name="DETECTOR_SERVICE_NAME_LIGHT"
      default_value="dullypdf-detector-light"
      ;;
    cpu:heavy)
      var_name="DETECTOR_SERVICE_NAME_HEAVY"
      default_value="dullypdf-detector-heavy"
      ;;
    gpu:light)
      var_name="DETECTOR_SERVICE_NAME_LIGHT_GPU"
      default_value="dullypdf-detector-light-gpu"
      ;;
    gpu:heavy)
      var_name="DETECTOR_SERVICE_NAME_HEAVY_GPU"
      default_value="dullypdf-detector-heavy-gpu"
      ;;
    *)
      echo "Unsupported detector service name target: ${target}:${profile}" >&2
      return 1
      ;;
  esac

  if [[ -v $var_name ]]; then
    printf '%s\n' "${!var_name}"
  else
    printf '%s\n' "$default_value"
  fi
}

detector_service_url_for_target() {
  local target="$1"
  local profile="$2"
  local profile_var=""
  local generic_var=""
  case "${target}:${profile}" in
    cpu:light)
      profile_var="DETECTOR_SERVICE_URL_LIGHT"
      generic_var="DETECTOR_SERVICE_URL"
      ;;
    cpu:heavy)
      profile_var="DETECTOR_SERVICE_URL_HEAVY"
      generic_var="DETECTOR_SERVICE_URL"
      ;;
    gpu:light)
      profile_var="DETECTOR_SERVICE_URL_LIGHT_GPU"
      generic_var="DETECTOR_SERVICE_URL_GPU"
      ;;
    gpu:heavy)
      profile_var="DETECTOR_SERVICE_URL_HEAVY_GPU"
      generic_var="DETECTOR_SERVICE_URL_GPU"
      ;;
    *)
      echo "Unsupported detector service URL target: ${target}:${profile}" >&2
      return 1
      ;;
  esac

  if [[ -v $profile_var && -n "${!profile_var}" ]]; then
    printf '%s\n' "${!profile_var}"
    return 0
  fi
  if [[ -v $generic_var && -n "${!generic_var}" ]]; then
    printf '%s\n' "${!generic_var}"
    return 0
  fi
  printf '\n'
}

detector_tasks_audience_for_target() {
  local target="$1"
  local profile="$2"
  local fallback_url="${3:-}"
  local profile_var=""
  local generic_var=""
  case "${target}:${profile}" in
    cpu:light)
      profile_var="DETECTOR_TASKS_AUDIENCE_LIGHT"
      generic_var="DETECTOR_TASKS_AUDIENCE"
      ;;
    cpu:heavy)
      profile_var="DETECTOR_TASKS_AUDIENCE_HEAVY"
      generic_var="DETECTOR_TASKS_AUDIENCE"
      ;;
    gpu:light)
      profile_var="DETECTOR_TASKS_AUDIENCE_LIGHT_GPU"
      generic_var="DETECTOR_TASKS_AUDIENCE_GPU"
      ;;
    gpu:heavy)
      profile_var="DETECTOR_TASKS_AUDIENCE_HEAVY_GPU"
      generic_var="DETECTOR_TASKS_AUDIENCE_GPU"
      ;;
    *)
      echo "Unsupported detector audience target: ${target}:${profile}" >&2
      return 1
      ;;
  esac

  if [[ -v $profile_var && -n "${!profile_var}" ]]; then
    printf '%s\n' "${!profile_var}"
    return 0
  fi
  if [[ -v $generic_var && -n "${!generic_var}" ]]; then
    printf '%s\n' "${!generic_var}"
    return 0
  fi
  printf '%s\n' "$fallback_url"
}

detector_set_active_routing_vars() {
  DETECTOR_ROUTING_MODE_RESOLVED="$(detector_normalize_routing_mode "${1:-}")"

  DETECTOR_TARGET_LIGHT_ACTIVE="$(detector_target_for_profile "$DETECTOR_ROUTING_MODE_RESOLVED" "light")"
  DETECTOR_TARGET_HEAVY_ACTIVE="$(detector_target_for_profile "$DETECTOR_ROUTING_MODE_RESOLVED" "heavy")"

  DETECTOR_SERVICE_NAME_LIGHT_ACTIVE="$(detector_service_name_for_target "$DETECTOR_TARGET_LIGHT_ACTIVE" "light")"
  DETECTOR_SERVICE_NAME_HEAVY_ACTIVE="$(detector_service_name_for_target "$DETECTOR_TARGET_HEAVY_ACTIVE" "heavy")"

  DETECTOR_SERVICE_REGION_LIGHT_ACTIVE="$(detector_region_for_target "$DETECTOR_TARGET_LIGHT_ACTIVE")"
  DETECTOR_SERVICE_REGION_HEAVY_ACTIVE="$(detector_region_for_target "$DETECTOR_TARGET_HEAVY_ACTIVE")"

  DETECTOR_SERVICE_URL_LIGHT_ACTIVE="$(detector_service_url_for_target "$DETECTOR_TARGET_LIGHT_ACTIVE" "light")"
  DETECTOR_SERVICE_URL_HEAVY_ACTIVE="$(detector_service_url_for_target "$DETECTOR_TARGET_HEAVY_ACTIVE" "heavy")"

  DETECTOR_TASKS_AUDIENCE_LIGHT_ACTIVE="$(
    detector_tasks_audience_for_target \
      "$DETECTOR_TARGET_LIGHT_ACTIVE" \
      "light" \
      "$DETECTOR_SERVICE_URL_LIGHT_ACTIVE"
  )"
  DETECTOR_TASKS_AUDIENCE_HEAVY_ACTIVE="$(
    detector_tasks_audience_for_target \
      "$DETECTOR_TARGET_HEAVY_ACTIVE" \
      "heavy" \
      "$DETECTOR_SERVICE_URL_HEAVY_ACTIVE"
  )"
}
