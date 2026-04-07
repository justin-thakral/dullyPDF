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

if [[ "${RUN_PLAYWRIGHT_SAFE:-false}" == "true" || "${RUN_WORKSPACE:-false}" == "true" || "${RUN_SHARED_RUNTIME:-false}" == "true" ]]; then
  append_unique "npm run test:playwright:localhost-auth-profile"
fi
if [[ "${RUN_PLAYWRIGHT_SAFE:-false}" == "true" || "${RUN_DETECTION_AI:-false}" == "true" || "${RUN_SHARED_RUNTIME:-false}" == "true" ]]; then
  append_unique "npm run test:playwright:localhost-detection"
fi

if [[ "${RUN_PLAYWRIGHT_SAFE:-false}" == "true" || "${RUN_TEMPLATE_API:-false}" == "true" || "${RUN_SHARED_RUNTIME:-false}" == "true" ]]; then
  append_unique "npm run test:playwright:template-api:real"
fi
if [[ "${RUN_PLAYWRIGHT_SAFE:-false}" == "true" || "${RUN_DETECTION_AI:-false}" == "true" || "${RUN_SHARED_RUNTIME:-false}" == "true" ]]; then
  append_unique "npm run test:playwright:openai-rename"
  append_unique "npm run test:playwright:openai-rename-remap"
fi
if [[ "${RUN_PLAYWRIGHT_SAFE:-false}" == "true" || "${RUN_WORKSPACE:-false}" == "true" || "${RUN_SHARED_RUNTIME:-false}" == "true" ]]; then
  append_unique "npm run test:playwright:saved-form-snapshot:real"
fi
if [[ "${RUN_PLAYWRIGHT_SAFE:-false}" == "true" || "${RUN_FILL_LINKS:-false}" == "true" || "${RUN_SHARED_RUNTIME:-false}" == "true" ]]; then
  append_unique "npm run test:playwright:fill-link-download:real"
fi
if [[ "${RUN_SIGNING:-false}" == "true" ]]; then
  append_unique "npm run test:playwright:signing-envelope"
fi

if [[ "${#commands[@]}" -eq 0 ]]; then
  echo "No real targeted Playwright suites selected."
  exit 0
fi

for command in "${commands[@]}"; do
  echo "+ ${command}"
  eval "${command}"
done
