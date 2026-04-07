#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash scripts/ci/deploy_target.sh --environment <dev|prod> --component <frontend|backend|detectors|workers|all> [options]

Options:
  --environment <dev|prod>     Target environment
  --component <name>           Deploy target
  --backend-env-file <path>    Backend env file override
  --frontend-env-file <path>   Frontend override env file
  --backend-image <image>      Optional backend image override (backend/all only)
  --dry-run                    Print derived deploy commands without executing them
EOF
}

DEPLOY_ENV=""
COMPONENT=""
BACKEND_ENV_FILE=""
FRONTEND_ENV_FILE=""
BACKEND_IMAGE=""
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --environment)
      DEPLOY_ENV="${2:-}"
      shift 2
      ;;
    --component)
      COMPONENT="${2:-}"
      shift 2
      ;;
    --backend-env-file)
      BACKEND_ENV_FILE="${2:-}"
      shift 2
      ;;
    --frontend-env-file)
      FRONTEND_ENV_FILE="${2:-}"
      shift 2
      ;;
    --backend-image)
      BACKEND_IMAGE="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

case "$DEPLOY_ENV" in
  dev|prod) ;;
  *)
    echo "Expected --environment dev|prod." >&2
    exit 1
    ;;
esac

case "$COMPONENT" in
  frontend|backend|detectors|workers|all) ;;
  *)
    echo "Expected --component frontend|backend|detectors|workers|all." >&2
    exit 1
    ;;
esac

if [[ -n "$BACKEND_IMAGE" && "$COMPONENT" != "backend" && "$COMPONENT" != "all" ]]; then
  echo "--backend-image is only valid for component=backend|all." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

run_or_echo() {
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "+ $*"
    return 0
  fi
  "$@"
}

default_backend_env_file() {
  if [[ "$DEPLOY_ENV" == "prod" ]]; then
    printf '%s\n' "env/backend.prod.env"
  else
    printf '%s\n' "env/backend.dev.stack.env"
  fi
}

BACKEND_ENV_FILE="${BACKEND_ENV_FILE:-$(default_backend_env_file)}"

deploy_detectors() {
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "+ bash scripts/deploy-detector-services.sh ${BACKEND_ENV_FILE}"
    return 0
  fi
  (
    cd "$REPO_ROOT"
    bash scripts/deploy-detector-services.sh "$BACKEND_ENV_FILE"
  )
}

deploy_workers() {
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "+ bash scripts/deploy-openai-workers.sh ${BACKEND_ENV_FILE}"
    return 0
  fi
  (
    cd "$REPO_ROOT"
    bash scripts/deploy-openai-workers.sh "$BACKEND_ENV_FILE"
  )
}

deploy_firestore_indexes() {
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "+ DULLYPDF_ALLOW_NON_PROD=1 PROJECT_ID=dullypdf-dev bash scripts/deploy-firestore-indexes.sh"
    return 0
  fi
  (
    cd "$REPO_ROOT"
    DULLYPDF_ALLOW_NON_PROD=1 PROJECT_ID=dullypdf-dev bash scripts/deploy-firestore-indexes.sh
  )
}

case "$COMPONENT" in
  frontend)
    (
      cd "$REPO_ROOT"
      args=(--environment "$DEPLOY_ENV")
      if [[ -n "$FRONTEND_ENV_FILE" ]]; then
        args+=(--env-file "$FRONTEND_ENV_FILE")
      fi
      if [[ "$DRY_RUN" == "1" ]]; then
        args+=(--dry-run)
      fi
      bash scripts/ci/deploy_frontend_target.sh "${args[@]}"
    )
    ;;
  backend)
    (
      cd "$REPO_ROOT"
      args=(--environment "$DEPLOY_ENV" --env-file "$BACKEND_ENV_FILE")
      if [[ -n "$BACKEND_IMAGE" ]]; then
        args+=(--backend-image "$BACKEND_IMAGE")
      fi
      if [[ "$DRY_RUN" == "1" ]]; then
        args+=(--dry-run)
      fi
      bash scripts/ci/deploy_backend_target.sh "${args[@]}"
    )
    ;;
  detectors)
    deploy_detectors
    ;;
  workers)
    deploy_workers
    ;;
  all)
    if [[ "$DEPLOY_ENV" == "prod" ]]; then
      if [[ "$DRY_RUN" == "1" ]]; then
        echo "+ BACKEND_IMAGE=${BACKEND_IMAGE:-<auto>} FRONTEND_ENV_OVERRIDE_FILE=${FRONTEND_ENV_FILE:-<default>} DRY_RUN=1 bash scripts/deploy-all-services.sh ${BACKEND_ENV_FILE}"
        exit 0
      fi
      (
        cd "$REPO_ROOT"
        env \
          BACKEND_IMAGE="${BACKEND_IMAGE:-}" \
          FRONTEND_ENV_OVERRIDE_FILE="${FRONTEND_ENV_FILE:-}" \
          bash scripts/deploy-all-services.sh "$BACKEND_ENV_FILE"
      )
      exit 0
    fi

    deploy_detectors
    deploy_workers
    (
      cd "$REPO_ROOT"
      args=(--environment dev --env-file "$BACKEND_ENV_FILE")
      if [[ -n "$BACKEND_IMAGE" ]]; then
        args+=(--backend-image "$BACKEND_IMAGE")
      fi
      if [[ "$DRY_RUN" == "1" ]]; then
        args+=(--dry-run)
      fi
      bash scripts/ci/deploy_backend_target.sh "${args[@]}"
    )
    (
      cd "$REPO_ROOT"
      args=(--environment dev)
      if [[ -n "$FRONTEND_ENV_FILE" ]]; then
        args+=(--env-file "$FRONTEND_ENV_FILE")
      fi
      if [[ "$DRY_RUN" == "1" ]]; then
        args+=(--dry-run)
      fi
      bash scripts/ci/deploy_frontend_target.sh "${args[@]}"
    )
    deploy_firestore_indexes
    ;;
esac
