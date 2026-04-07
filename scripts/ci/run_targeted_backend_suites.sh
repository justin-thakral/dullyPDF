#!/usr/bin/env bash
set -euo pipefail

declare -a commands=()

append_unique() {
  local candidate="$1"
  local existing
  for existing in "${commands[@]}"; do
    if [[ "$existing" == "$candidate" ]]; then
      return 0
    fi
  done
  commands+=("$candidate")
}

if [[ "${RUN_TEMPLATE_API:-false}" == "true" || "${RUN_SHARED_RUNTIME:-false}" == "true" ]]; then
  append_unique "npm run test:backend:template-api:integration"
fi
if [[ "${RUN_DETECTION_AI:-false}" == "true" || "${RUN_SHARED_RUNTIME:-false}" == "true" ]]; then
  append_unique "backend/.venv/bin/python -m pytest backend/test/integration/test_detection_rename_saved_form_flow.py -q"
fi
if [[ "${RUN_WORKSPACE:-false}" == "true" || "${RUN_SHARED_RUNTIME:-false}" == "true" ]]; then
  append_unique "backend/.venv/bin/python -m pytest backend/test/integration/test_workspace_bootstrap_integration.py -q"
fi
if [[ "${RUN_FILL_LINKS:-false}" == "true" || "${RUN_SHARED_RUNTIME:-false}" == "true" ]]; then
  append_unique "backend/.venv/bin/python -m pytest backend/test/integration/test_fill_links_integration.py -q"
fi
if [[ "${RUN_SIGNING:-false}" == "true" || "${RUN_SHARED_RUNTIME:-false}" == "true" ]]; then
  append_unique "backend/.venv/bin/python -m pytest backend/test/integration/test_signing_foundation_integration.py -q"
fi
if [[ "${RUN_BILLING:-false}" == "true" || "${RUN_SHARED_RUNTIME:-false}" == "true" ]]; then
  append_unique "backend/.venv/bin/python -m pytest backend/test/integration/test_billing_webhook_integration.py backend/test/integration/test_billing_trial_lifecycle_integration.py backend/test/integration/test_billing_downgrade_lifecycle_integration.py -q"
fi

if [[ "${#commands[@]}" -eq 0 ]]; then
  echo "No targeted backend suites selected."
  exit 0
fi

for command in "${commands[@]}"; do
  echo "+ ${command}"
  eval "${command}"
done
