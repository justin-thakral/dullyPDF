#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-env/backend.dev.stack.env}"
DEV_EXAMPLE="config/backend.dev.stack.env.example"
PROD_EXAMPLE="config/backend.prod.env.example"

is_truthy() {
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

if [[ ! -f "$ENV_FILE" ]]; then
  if [[ "$ENV_FILE" == *"prod"* && -f "$PROD_EXAMPLE" ]]; then
    mkdir -p "env"
    cp "$PROD_EXAMPLE" "$ENV_FILE"
    echo "Created $ENV_FILE from $PROD_EXAMPLE. Update values and re-run." >&2
    exit 1
  fi
  if [[ -f "$DEV_EXAMPLE" ]]; then
    mkdir -p "env"
    cp "$DEV_EXAMPLE" "$ENV_FILE"
    echo "Created $ENV_FILE from $DEV_EXAMPLE. Update values and re-run." >&2
    exit 1
  fi
  echo "Missing $ENV_FILE and both env examples." >&2
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_detector_routing.sh"

require_nonempty() {
  local name="$1"
  local actual="${!name:-}"
  if [[ -z "$actual" ]]; then
    echo "Missing required $name in $ENV_FILE (or exported env)." >&2
    exit 1
  fi
}

normalize_detector_deploy_variants() {
  local raw="${1:-active}"
  case "${raw,,}" in
    active)
      printf '%s\n' "active"
      ;;
    cpu|cpu_only)
      printf '%s\n' "cpu"
      ;;
    gpu|gpu_only)
      printf '%s\n' "gpu"
      ;;
    both|all)
      printf '%s\n' "both"
      ;;
    *)
      echo "Unsupported DETECTOR_DEPLOY_VARIANTS value: ${raw}" >&2
      return 1
      ;;
  esac
}

PROJECT_ID="${PROJECT_ID:-${DETECTOR_TASKS_PROJECT:-${FIREBASE_PROJECT_ID:-dullypdf-dev}}}"
REGION="${REGION:-${DETECTOR_TASKS_LOCATION:-us-central1}}"
DETECTOR_SERVICE_REGION="${DETECTOR_SERVICE_REGION:-$REGION}"
ARTIFACT_REPO="${DETECTOR_ARTIFACT_REPO:-dullypdf-backend}"
TAG="${DETECTOR_IMAGE_TAG:-$(date +%Y%m%d-%H%M%S)}"

if [[ -z "${DETECTOR_ROUTING_MODE:-}" && -z "${DETECTOR_DEPLOY_VARIANTS:-}" ]] && is_truthy "${DETECTOR_GPU_ENABLED:-false}"; then
  DETECTOR_ROUTING_MODE="gpu"
  DETECTOR_DEPLOY_VARIANTS="gpu"
fi

DETECTOR_DEPLOY_PHASE="${DETECTOR_DEPLOY_PHASE:-multi}"
DETECTOR_ROUTING_MODE="$(detector_normalize_routing_mode "${DETECTOR_ROUTING_MODE:-}")"
DETECTOR_DEPLOY_VARIANTS="$(normalize_detector_deploy_variants "${DETECTOR_DEPLOY_VARIANTS:-active}")"

GPU_ENABLED="${DETECTOR_GPU_ENABLED:-false}"
if is_truthy "$GPU_ENABLED"; then
  DETECTOR_GPU_ENABLED=true
else
  DETECTOR_GPU_ENABLED=false
fi

STABLE_AUDIENCE_ENABLED="${DETECTOR_USE_STABLE_AUDIENCE:-false}"
if is_truthy "$STABLE_AUDIENCE_ENABLED"; then
  DETECTOR_USE_STABLE_AUDIENCE=true
else
  DETECTOR_USE_STABLE_AUDIENCE=false
fi

SKIP_BUILD_ENABLED="${DETECTOR_SKIP_BUILD:-false}"
if is_truthy "$SKIP_BUILD_ENABLED"; then
  DETECTOR_SKIP_BUILD=true
else
  DETECTOR_SKIP_BUILD=false
fi

ALLOW_UNAUTH_DEPLOY_ENABLED="${DETECTOR_DEPLOY_ALLOW_UNAUTHENTICATED:-false}"
if is_truthy "$ALLOW_UNAUTH_DEPLOY_ENABLED"; then
  DETECTOR_DEPLOY_ALLOW_UNAUTHENTICATED=true
else
  DETECTOR_DEPLOY_ALLOW_UNAUTHENTICATED=false
fi

run_single_deploy_phase() {
  local target="$1"
  local service_region="$2"
  local service_light="$3"
  local service_heavy="$4"
  local gpu_enabled="false"
  if [[ "$target" == "gpu" ]]; then
    gpu_enabled="true"
  fi

  echo "Detector deploy phase: target=${target} region=${service_region} light=${service_light:-<skip>} heavy=${service_heavy:-<skip>}"
  REGION="$service_region" \
  DETECTOR_SERVICE_REGION="$DETECTOR_SERVICE_REGION" \
  DETECTOR_GPU_REGION="${DETECTOR_GPU_REGION:-$(detector_gpu_region)}" \
  DETECTOR_DEPLOY_PHASE="single" \
  DETECTOR_GPU_ENABLED="$gpu_enabled" \
  DETECTOR_SERVICE_NAME_LIGHT="$service_light" \
  DETECTOR_SERVICE_NAME_HEAVY="$service_heavy" \
    bash "${SCRIPT_DIR}/deploy-detector-services.sh" "$ENV_FILE"
}

if [[ "$DETECTOR_DEPLOY_PHASE" != "single" ]]; then
  cpu_region="$(detector_cpu_region)"
  gpu_region="$(detector_gpu_region)"
  cpu_light_name="$(detector_service_name_for_target "cpu" "light")"
  cpu_heavy_name="$(detector_service_name_for_target "cpu" "heavy")"
  gpu_light_name="$(detector_service_name_for_target "gpu" "light")"
  gpu_heavy_name="$(detector_service_name_for_target "gpu" "heavy")"

  case "$DETECTOR_DEPLOY_VARIANTS" in
    active)
      case "$DETECTOR_ROUTING_MODE" in
        cpu)
          run_single_deploy_phase "cpu" "$cpu_region" "$cpu_light_name" "$cpu_heavy_name"
          ;;
        split)
          run_single_deploy_phase "cpu" "$cpu_region" "$cpu_light_name" ""
          run_single_deploy_phase "gpu" "$gpu_region" "" "$gpu_heavy_name"
          ;;
        gpu)
          run_single_deploy_phase "gpu" "$gpu_region" "$gpu_light_name" "$gpu_heavy_name"
          ;;
      esac
      ;;
    cpu)
      run_single_deploy_phase "cpu" "$cpu_region" "$cpu_light_name" "$cpu_heavy_name"
      ;;
    gpu)
      run_single_deploy_phase "gpu" "$gpu_region" "$gpu_light_name" "$gpu_heavy_name"
      ;;
    both)
      run_single_deploy_phase "cpu" "$cpu_region" "$cpu_light_name" "$cpu_heavy_name"
      run_single_deploy_phase "gpu" "$gpu_region" "$gpu_light_name" "$gpu_heavy_name"
      ;;
  esac
  exit 0
fi

DEPLOY_REGION="$REGION"
if [[ "$DETECTOR_GPU_ENABLED" == "true" ]]; then
  DEPLOY_REGION="${DETECTOR_GPU_REGION:-$REGION}"
fi

DETECTOR_IMAGE="${DETECTOR_IMAGE:-us-central1-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}/detector-service:${TAG}}"
if [[ "$DETECTOR_GPU_ENABLED" == "true" ]]; then
  DETECTOR_SERVICE_LIGHT="${DETECTOR_SERVICE_NAME_LIGHT-dullypdf-detector-light-gpu}"
  DETECTOR_SERVICE_HEAVY="${DETECTOR_SERVICE_NAME_HEAVY-dullypdf-detector-heavy-gpu}"
  DETECTOR_DOCKERFILE="${DETECTOR_DOCKERFILE:-Dockerfile.detector.gpu}"
else
  DETECTOR_SERVICE_LIGHT="${DETECTOR_SERVICE_NAME_LIGHT-dullypdf-detector-light}"
  DETECTOR_SERVICE_HEAVY="${DETECTOR_SERVICE_NAME_HEAVY-dullypdf-detector-heavy}"
  DETECTOR_DOCKERFILE="${DETECTOR_DOCKERFILE:-Dockerfile.detector}"
fi

CALLER_SA="${DETECTOR_TASKS_SERVICE_ACCOUNT:-}"
RUNTIME_SA="${DETECTOR_RUNTIME_SERVICE_ACCOUNT:-${WORKER_RUNTIME_SERVICE_ACCOUNT:-${CALLER_SA:-}}}"

DETECTOR_TIMEOUT_SECONDS_LIGHT="${DETECTOR_TIMEOUT_SECONDS_LIGHT:-900}"
DETECTOR_TIMEOUT_SECONDS_HEAVY="${DETECTOR_TIMEOUT_SECONDS_HEAVY:-1200}"
DETECTOR_MAX_INSTANCES_LIGHT="${DETECTOR_MAX_INSTANCES_LIGHT:-5}"
DETECTOR_MAX_INSTANCES_HEAVY="${DETECTOR_MAX_INSTANCES_HEAVY:-2}"
DETECTOR_GPU_MAX_INSTANCES_LIGHT="${DETECTOR_GPU_MAX_INSTANCES_LIGHT:-1}"
DETECTOR_GPU_MAX_INSTANCES_HEAVY="${DETECTOR_GPU_MAX_INSTANCES_HEAVY:-1}"
DETECTOR_CPU_LIGHT="${DETECTOR_CPU_LIGHT:-2}"
DETECTOR_MEMORY_LIGHT="${DETECTOR_MEMORY_LIGHT:-4Gi}"
DETECTOR_CPU_HEAVY="${DETECTOR_CPU_HEAVY:-4}"
DETECTOR_MEMORY_HEAVY="${DETECTOR_MEMORY_HEAVY:-8Gi}"

require_nonempty PROJECT_ID
require_nonempty REGION
require_nonempty DEPLOY_REGION
require_nonempty FIREBASE_PROJECT_ID
require_nonempty FORMS_BUCKET
require_nonempty DETECTOR_TASKS_SERVICE_ACCOUNT
require_nonempty RUNTIME_SA
require_nonempty COMMONFORMS_MODEL_GCS_URI

COMMONFORMS_DEVICE_VALUE="${COMMONFORMS_DEVICE:-cpu}"
if [[ "$DETECTOR_GPU_ENABLED" == "true" ]]; then
  COMMONFORMS_DEVICE_VALUE="cuda"
fi

TMP_ENV_FILE="$(mktemp)"
python3 - <<'PY' "$ENV_FILE" "$TMP_ENV_FILE"
import json
import sys

env_path = sys.argv[1]
out_path = sys.argv[2]
script_only = {"PORT", "COMMONFORMS_DEVICE"}

def parse_env(path):
    values = {}
    with open(path, "r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            if value and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            values[key] = value
    return values

raw_values = parse_env(env_path)
data = {key: value for key, value in raw_values.items() if key not in script_only}
with open(out_path, "w", encoding="utf-8") as handle:
    for key in sorted(data.keys()):
        handle.write(f"{key}: {json.dumps(data[key])}\n")
PY

python3 - "$TMP_ENV_FILE" "$CALLER_SA" "$DETECTOR_DEPLOY_ALLOW_UNAUTHENTICATED" "$COMMONFORMS_DEVICE_VALUE" <<'PY'
import json
import sys

out_path = sys.argv[1]
caller_sa = sys.argv[2]

with open(out_path, "a", encoding="utf-8") as handle:
    handle.write(f"DETECTOR_ALLOW_UNAUTHENTICATED: {json.dumps(sys.argv[3])}\n")
    handle.write(f"DETECTOR_CALLER_SERVICE_ACCOUNT: {json.dumps(caller_sa)}\n")
    handle.write(f"COMMONFORMS_DEVICE: {json.dumps(sys.argv[4])}\n")
PY

cleanup() {
  rm -f "$TMP_ENV_FILE" || true
}
trap cleanup EXIT

build_stable_audience() {
  local service_name="$1"
  printf 'https://%s.dullypdf.internal' "$service_name"
}

build_with_dockerfile() {
  local image="$1"
  local dockerfile="$2"
  local build_config
  build_config="$(mktemp)"
  cat >"$build_config" <<'YAML'
steps:
- name: gcr.io/cloud-builders/docker
  args:
  - build
  - -f
  - $_DOCKERFILE
  - -t
  - $_IMAGE
  - .
images:
- $_IMAGE
YAML
  gcloud builds submit \
    --project "$PROJECT_ID" \
    --config "$build_config" \
    --substitutions "_IMAGE=${image},_DOCKERFILE=${dockerfile}" \
    .
  rm -f "$build_config"
}

if [[ "$DETECTOR_SKIP_BUILD" == "true" ]]; then
  echo "Skipping detector image build; reusing ${DETECTOR_IMAGE}."
else
  echo "Building detector image in project ${PROJECT_ID}..."
  build_with_dockerfile "$DETECTOR_IMAGE" "$DETECTOR_DOCKERFILE"
fi
echo "Deploying detector services in region ${DEPLOY_REGION}..."

deploy_detector() {
  local service_name="$1"
  local profile="$2"
  if [[ -z "$service_name" ]]; then
    return
  fi

  local deploy_args=()
  local timeout_seconds="$DETECTOR_TIMEOUT_SECONDS_LIGHT"
  local max_instances="$DETECTOR_MAX_INSTANCES_LIGHT"
  local cpu_limit="$DETECTOR_CPU_LIGHT"
  local memory_limit="$DETECTOR_MEMORY_LIGHT"
  local stable_audience=""
  local service_env_file
  if [[ "$profile" == "heavy" ]]; then
    timeout_seconds="$DETECTOR_TIMEOUT_SECONDS_HEAVY"
    max_instances="$DETECTOR_MAX_INSTANCES_HEAVY"
    cpu_limit="$DETECTOR_CPU_HEAVY"
    memory_limit="$DETECTOR_MEMORY_HEAVY"
  fi
  if [[ "$DETECTOR_USE_STABLE_AUDIENCE" == "true" ]]; then
    stable_audience="$(build_stable_audience "$service_name")"
  fi
  service_env_file="$(mktemp)"
  cp "$TMP_ENV_FILE" "$service_env_file"
  python3 - <<'PY' "$service_env_file" "$stable_audience"
import json
import sys

out_path = sys.argv[1]
stable_audience = sys.argv[2]
with open(out_path, "a", encoding="utf-8") as handle:
    if stable_audience:
        handle.write(f"DETECTOR_TASKS_AUDIENCE: {json.dumps(stable_audience)}\n")
PY

  deploy_args+=(
    --concurrency "1"
    --timeout "${timeout_seconds}"
  )
  if [[ "$DETECTOR_GPU_ENABLED" == "true" ]]; then
    if [[ "$profile" == "heavy" ]]; then
      max_instances="$DETECTOR_GPU_MAX_INSTANCES_HEAVY"
    else
      max_instances="$DETECTOR_GPU_MAX_INSTANCES_LIGHT"
    fi
    deploy_args+=(
      --max-instances "${max_instances}"
      --gpu "1"
      --gpu-type "nvidia-l4"
      --no-gpu-zonal-redundancy
      --cpu "4"
      --memory "16Gi"
      --min-instances "0"
    )
  else
    deploy_args+=(
      --max-instances "${max_instances}"
      --cpu "${cpu_limit}"
      --memory "${memory_limit}"
    )
  fi

  echo "Deploying ${service_name}..."
  gcloud run deploy "$service_name" \
    --image "$DETECTOR_IMAGE" \
    --region "$DEPLOY_REGION" \
    --project "$PROJECT_ID" \
    --quiet \
    --service-account "$RUNTIME_SA" \
    --env-vars-file "$service_env_file" \
    "$(
      if [[ "$DETECTOR_DEPLOY_ALLOW_UNAUTHENTICATED" == "true" ]]; then
        printf '%s' '--allow-unauthenticated'
      else
        printf '%s' '--no-allow-unauthenticated'
      fi
    )" \
    "${deploy_args[@]}"
  rm -f "$service_env_file"

  local service_url
  service_url="$(
    gcloud run services describe "$service_name" \
      --region "$DEPLOY_REGION" \
      --project "$PROJECT_ID" \
      --format='value(status.url)'
  )"
  if [[ -z "$service_url" ]]; then
    echo "Failed to resolve Cloud Run URL for ${service_name}." >&2
    exit 1
  fi

  if [[ "$DETECTOR_DEPLOY_ALLOW_UNAUTHENTICATED" == "true" ]]; then
    gcloud run services add-iam-policy-binding "$service_name" \
      --region "$DEPLOY_REGION" \
      --project "$PROJECT_ID" \
      --member="allUsers" \
      --role="roles/run.invoker" >/dev/null
  else
    gcloud run services remove-iam-policy-binding "$service_name" \
      --region "$DEPLOY_REGION" \
      --project "$PROJECT_ID" \
      --member="allUsers" \
      --role="roles/run.invoker" >/dev/null 2>&1 || true

    gcloud run services add-iam-policy-binding "$service_name" \
      --region "$DEPLOY_REGION" \
      --project "$PROJECT_ID" \
      --member="serviceAccount:${CALLER_SA}" \
      --role="roles/run.invoker" >/dev/null
  fi
}

deploy_detector "$DETECTOR_SERVICE_LIGHT" "light"
deploy_detector "$DETECTOR_SERVICE_HEAVY" "heavy"

echo
echo "Detector deploy complete. Current invoker bindings:"
for service in "$DETECTOR_SERVICE_LIGHT" "$DETECTOR_SERVICE_HEAVY"; do
  if [[ -z "$service" ]]; then
    continue
  fi
  echo "=== ${service}"
  gcloud run services get-iam-policy "$service" \
    --region "$DEPLOY_REGION" \
    --project "$PROJECT_ID" \
    --format='yaml(bindings)'
done
