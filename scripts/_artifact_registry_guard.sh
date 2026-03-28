#!/usr/bin/env bash

artifact_registry_guard_is_prod_project() {
  [[ "${PROJECT_ID:-}" == "dullypdf" ]]
}

artifact_registry_guard_expected_location() {
  printf '%s\n' "us-east4"
}

artifact_registry_guard_expected_repo() {
  printf '%s\n' "dullypdf-backend"
}

artifact_registry_guard_expected_prefix() {
  local project_id="${1:-${PROJECT_ID:-dullypdf}}"
  local repo="${2:-$(artifact_registry_guard_expected_repo)}"
  printf '%s-docker.pkg.dev/%s/%s/' \
    "$(artifact_registry_guard_expected_location)" \
    "$project_id" \
    "$repo"
}

require_prod_artifact_registry_location() {
  local name="$1"
  local actual="$2"
  local expected="${3:-$(artifact_registry_guard_expected_location)}"

  if artifact_registry_guard_is_prod_project && [[ "$actual" != "$expected" ]]; then
    echo "Refusing to deploy prod ${name} outside ${expected} Artifact Registry location (got ${actual})." >&2
    exit 1
  fi
}

require_prod_artifact_registry_repo() {
  local name="$1"
  local actual="$2"
  local expected="${3:-$(artifact_registry_guard_expected_repo)}"

  if artifact_registry_guard_is_prod_project && [[ "$actual" != "$expected" ]]; then
    echo "Refusing to deploy prod ${name} outside the canonical repo ${expected} (got ${actual})." >&2
    exit 1
  fi
}

require_prod_artifact_registry_image() {
  local name="$1"
  local image="$2"
  local repo="${3:-$(artifact_registry_guard_expected_repo)}"
  local expected_prefix

  if ! artifact_registry_guard_is_prod_project || [[ -z "$image" ]]; then
    return 0
  fi

  expected_prefix="$(artifact_registry_guard_expected_prefix "${PROJECT_ID:-dullypdf}" "$repo")"
  if [[ "$image" != ${expected_prefix}* ]]; then
    echo "Refusing to deploy prod ${name} outside ${expected_prefix} (got ${image})." >&2
    exit 1
  fi
}
