#!/usr/bin/env bash
set -euo pipefail

changed_files="${CHANGED_BACKEND_FILES:-}"

run_runtime_units=false
run_governance_units=false

set_output() {
  local key="$1"
  local value="$2"
  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    printf '%s=%s\n' "$key" "$value" >>"$GITHUB_OUTPUT"
  else
    printf '%s=%s\n' "$key" "$value"
  fi
}

is_governance_path() {
  local path="$1"
  case "$path" in
    backend/test/unit/config/*|\
    backend/test/unit/scripts/*|\
    config/backend.prod.env.example|\
    firebase.json|\
    scripts/benchmark-detector-cpu-gpu.sh|\
    scripts/deploy-*.sh|\
    scripts/lock-signing-storage-retention.sh|\
    scripts/prune-stale-cloud-resources.sh|\
    scripts/sync-detector-task-queues.sh|\
    scripts/validate-signing-storage.py)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

is_runtime_path() {
  local path="$1"
  case "$path" in
    backend/README.md|backend/test/docs/*|backend/test/bugs/*|backend/fieldDetecting/docs/*|backend/fieldDetecting/logs/README.md)
      return 1
      ;;
    backend/*|backend/requirements*.txt|package.json)
      is_governance_path "$path" && return 1
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

while IFS= read -r path; do
  [[ -z "$path" ]] && continue

  if is_runtime_path "$path"; then
    run_runtime_units=true
  fi

  if is_governance_path "$path"; then
    run_governance_units=true
  fi
done < <(printf '%s\n' "$changed_files" | tr ' ' '\n' | sed '/^$/d')

set_output "run_runtime_units" "$run_runtime_units"
set_output "run_governance_units" "$run_governance_units"
