#!/usr/bin/env bash
set -euo pipefail

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

ENV_FILE="${1:-env/backend.dev.stack.env}"
shift || true

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing env file: $ENV_FILE" >&2
  exit 1
fi

if [[ "$#" -gt 0 ]]; then
  PDF_SET=("$@")
else
  PDF_SET=(
    "quickTestFiles/dentalintakeform_d1c394f594.pdf"
    "quickTestFiles/cms1500_06_03d2696ed5.pdf"
    "quickTestFiles/new_patient_forms_1915ccb015.pdf"
  )
fi

for pdf_path in "${PDF_SET[@]}"; do
  if [[ ! -f "$pdf_path" ]]; then
    echo "Missing PDF input: $pdf_path" >&2
    exit 1
  fi
done

set -a
source "$ENV_FILE"
set +a

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/_load_firebase_secret.sh"
load_firebase_secret

PROJECT_ID="${PROJECT_ID:-${DETECTOR_TASKS_PROJECT:-${FIREBASE_PROJECT_ID:-dullypdf-dev}}}"
REGION="${REGION:-${DETECTOR_TASKS_LOCATION:-us-east4}}"
CPU_REGION="${BENCH_CPU_REGION:-${REGION}}"
GPU_REGION="${BENCH_GPU_REGION:-${DETECTOR_GPU_REGION:-us-east4}}"
BENCH_ALLOW_UNAUTHENTICATED="${BENCH_ALLOW_UNAUTHENTICATED:-false}"
BENCH_ALLOW_PROD_PROJECT="${BENCH_ALLOW_PROD_PROJECT:-false}"

if [[ "${PROJECT_ID}" == "dullypdf" || "${ENV:-}" == "prod" ]]; then
  if ! is_truthy "$BENCH_ALLOW_PROD_PROJECT"; then
    echo "Refusing to run detector benchmark against prod without BENCH_ALLOW_PROD_PROJECT=true." >&2
    exit 1
  fi
fi

CPU_SERVICE_LIGHT="${BENCH_CPU_SERVICE_LIGHT:-dullypdf-detector-light-bench-cpu}"
CPU_SERVICE_HEAVY="${BENCH_CPU_SERVICE_HEAVY:-dullypdf-detector-heavy-bench-cpu}"
GPU_SERVICE_LIGHT="${BENCH_GPU_SERVICE_LIGHT:-dullypdf-detector-light-bench-gpu}"
GPU_SERVICE_HEAVY="${BENCH_GPU_SERVICE_HEAVY:-dullypdf-detector-heavy-bench-gpu}"

BENCH_TIMEOUT_SECONDS="${BENCH_TIMEOUT_SECONDS:-1800}"
BENCH_POLL_SECONDS="${BENCH_POLL_SECONDS:-2}"
FORCE_COLD_START_CPU="${FORCE_COLD_START_CPU:-true}"
FORCE_COLD_START_GPU="${FORCE_COLD_START_GPU:-true}"
BENCH_SKIP_BUILD_CPU="${BENCH_SKIP_BUILD_CPU:-false}"
BENCH_SKIP_BUILD_GPU="${BENCH_SKIP_BUILD_GPU:-false}"
RESULTS_DIR="${BENCH_RESULTS_DIR:-tmp/benchmarks}"
mkdir -p "$RESULTS_DIR"
RESULTS_JSONL="${RESULTS_DIR}/detector-cpu-gpu-$(date +%Y%m%d-%H%M%S).jsonl"

service_audience() {
  local service_name="$1"
  printf 'https://%s.dullypdf.internal' "$service_name"
}

deploy_detector_mode() {
  local mode="$1"
  local service_light="$2"
  local service_heavy="$3"
  local gpu_enabled="$4"
  local image_tag="$5"
  local service_region="$6"
  local skip_build="$7"
  local allow_unauthenticated="false"
  if is_truthy "$BENCH_ALLOW_UNAUTHENTICATED"; then
    allow_unauthenticated="true"
  fi
  echo "Deploying ${mode} detector services (${service_light}, ${service_heavy}) in ${service_region}..."
  REGION="$service_region" \
  DETECTOR_SKIP_BUILD="$skip_build" \
  DETECTOR_USE_STABLE_AUDIENCE="true" \
  DETECTOR_DEPLOY_ALLOW_UNAUTHENTICATED="$allow_unauthenticated" \
  DETECTOR_GPU_ENABLED="$gpu_enabled" \
    DETECTOR_GPU_REGION="$service_region" \
    DETECTOR_SERVICE_NAME_LIGHT="$service_light" \
    DETECTOR_SERVICE_NAME_HEAVY="$service_heavy" \
    DETECTOR_IMAGE_TAG="$image_tag" \
    bash scripts/deploy-detector-services.sh "$ENV_FILE"
}

get_service_url() {
  local service_name="$1"
  local service_region="$2"
  gcloud run services describe "$service_name" \
    --region "$service_region" \
    --project "$PROJECT_ID" \
    --format='value(status.url)'
}

enqueue_and_wait() {
  local pdf_path="$1"
  PYTHONPATH="$(pwd)" backend/.venv/bin/python - <<'PY' "$pdf_path" "$BENCH_TIMEOUT_SECONDS" "$BENCH_POLL_SECONDS"
import json
import os
import sys
import time
from pathlib import Path

from backend.firebaseDB.session_database import get_session_metadata
from backend.services.detection_service import enqueue_detection_job
from backend.services.pdf_service import get_pdf_page_count

pdf_path = Path(sys.argv[1])
timeout_seconds = int(sys.argv[2])
poll_seconds = float(sys.argv[3])

pdf_bytes = pdf_path.read_bytes()
page_count = get_pdf_page_count(pdf_bytes)

response = enqueue_detection_job(
    pdf_bytes,
    pdf_path.name,
    None,
    page_count=page_count,
    prewarm_rename=False,
    prewarm_remap=False,
)
session_id = str(response["sessionId"])
deadline = time.time() + timeout_seconds

status = "queued"
metadata = {}
while time.time() < deadline:
    metadata = get_session_metadata(session_id) or {}
    status = str(metadata.get("detection_status") or "").lower()
    if status in {"complete", "failed"}:
        break
    time.sleep(poll_seconds)

result = {
    "session_id": session_id,
    "status": status,
    "page_count": page_count,
    "profile": metadata.get("detection_profile") or "light",
    "queued_at": metadata.get("detection_queued_at"),
    "started_at": metadata.get("detection_started_at"),
    "completed_at": metadata.get("detection_completed_at"),
    "detection_duration_seconds": metadata.get("detection_duration_seconds"),
    "error": metadata.get("detection_error") or "",
}
print(json.dumps(result, ensure_ascii=True))
if status != "complete":
    sys.exit(2)
PY
}

lookup_request_latency_seconds() {
  local service_name="$1"
  local since_iso="$2"

  for _ in $(seq 1 20); do
    local raw_json
    raw_json="$(gcloud logging read \
      "resource.type=\"cloud_run_revision\" AND resource.labels.project_id=\"${PROJECT_ID}\" AND resource.labels.service_name=\"${service_name}\" AND logName=\"projects/${PROJECT_ID}/logs/run.googleapis.com%2Frequests\" AND httpRequest.requestUrl:\"/internal/detect\" AND httpRequest.status=200 AND timestamp>=\"${since_iso}\"" \
      --project "$PROJECT_ID" \
      --limit=20 \
      --format=json)"
    local value
    value="$(python3 - <<'PY' "$raw_json"
import json
import sys

try:
    entries = json.loads(sys.argv[1])
except json.JSONDecodeError:
    entries = []

if not entries:
    print("")
    raise SystemExit(0)

def parse_latency(raw: str) -> float:
    text = str(raw or "").strip()
    if text.endswith("s"):
        text = text[:-1]
    return float(text or 0.0)

entries.sort(key=lambda item: item.get("timestamp", ""))
latency = parse_latency(entries[0].get("httpRequest", {}).get("latency"))
print(latency)
PY
)"
    if [[ -n "${value}" ]]; then
      echo "$value"
      return 0
    fi
    sleep 3
  done

  echo ""
  return 1
}

check_cold_start_event() {
  local service_name="$1"
  local since_iso="$2"
  local until_iso="$3"
  local count
  count="$(
    gcloud logging read \
      "resource.type=\"cloud_run_revision\" AND resource.labels.project_id=\"${PROJECT_ID}\" AND resource.labels.service_name=\"${service_name}\" AND logName=\"projects/${PROJECT_ID}/logs/run.googleapis.com%2Fvarlog%2Fsystem\" AND textPayload:\"Starting new instance\" AND timestamp>=\"${since_iso}\" AND timestamp<=\"${until_iso}\"" \
      --project "$PROJECT_ID" \
      --limit=20 \
      --format='value(timestamp)' | wc -l
  )"
  if [[ "${count}" -gt 0 ]]; then
    echo "true"
  else
    echo "false"
  fi
}

append_result() {
  local mode="$1"
  local pdf_path="$2"
  local service_name="$3"
  local latency_seconds="$4"
  local cold_start_verified="$5"
  local job_json="$6"
  python3 - <<'PY' "$RESULTS_JSONL" "$mode" "$pdf_path" "$service_name" "$latency_seconds" "$cold_start_verified" "$job_json"
import json
import sys

results_path = sys.argv[1]
mode = sys.argv[2]
pdf_path = sys.argv[3]
service_name = sys.argv[4]
latency_seconds = float(sys.argv[5]) if sys.argv[5] else None
cold_start_verified = sys.argv[6].strip().lower() == "true"
job = json.loads(sys.argv[7])

row = {
    "mode": mode,
    "pdf_path": pdf_path,
    "service_name": service_name,
    "session_id": job.get("session_id"),
    "status": job.get("status"),
    "profile": job.get("profile") or "light",
    "page_count": job.get("page_count"),
    "queued_at": job.get("queued_at"),
    "started_at": job.get("started_at"),
    "completed_at": job.get("completed_at"),
    "detection_duration_seconds": job.get("detection_duration_seconds"),
    "request_latency_seconds": latency_seconds,
    "cold_start_verified": cold_start_verified,
    "error": job.get("error") or "",
}
with open(results_path, "a", encoding="utf-8") as handle:
    handle.write(json.dumps(row, ensure_ascii=True) + "\n")
PY
}

run_mode() {
  local mode="$1"
  local service_light="$2"
  local service_heavy="$3"
  local force_cold_start="$4"
  local service_url_light="$5"
  local service_url_heavy="$6"
  local service_region="$7"

  echo "Running ${mode} benchmark in ${service_region}..."
  local cold_start_marker=""
  if [[ "${force_cold_start}" == "true" ]]; then
    # Freshly deployed services have no live instances yet, so the first request
    # exercises a real cold start without creating another GPU revision.
    cold_start_marker="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  fi

  local is_first_run="true"
  for pdf_path in "${PDF_SET[@]}"; do
    export DETECTOR_SERVICE_URL_LIGHT="$service_url_light"
    export DETECTOR_SERVICE_URL_HEAVY="$service_url_heavy"
    export DETECTOR_SERVICE_URL="$service_url_light"
    export DETECTOR_TASKS_AUDIENCE_LIGHT="$(service_audience "$service_light")"
    export DETECTOR_TASKS_AUDIENCE_HEAVY="$(service_audience "$service_heavy")"
    export DETECTOR_TASKS_AUDIENCE="$DETECTOR_TASKS_AUDIENCE_LIGHT"

    local job_json
    job_json="$(enqueue_and_wait "$pdf_path")"
    local status
    status="$(python3 - <<'PY' "$job_json"
import json
import sys
print(str(json.loads(sys.argv[1]).get("status") or ""))
PY
)"
    if [[ "$status" != "complete" ]]; then
      echo "Detection failed for ${mode} ${pdf_path}: ${job_json}" >&2
      exit 1
    fi

    local profile
    profile="$(python3 - <<'PY' "$job_json"
import json
import sys
print(str(json.loads(sys.argv[1]).get("profile") or "light"))
PY
)"
    local queued_at
    queued_at="$(python3 - <<'PY' "$job_json"
import json
import sys
print(str(json.loads(sys.argv[1]).get("queued_at") or ""))
PY
)"
    local completed_at
    completed_at="$(python3 - <<'PY' "$job_json"
import json
import sys
print(str(json.loads(sys.argv[1]).get("completed_at") or ""))
PY
)"
    local detector_service_name
    if [[ "$profile" == "heavy" ]]; then
      detector_service_name="$service_heavy"
    else
      detector_service_name="$service_light"
    fi

    local latency_seconds
    latency_seconds="$(lookup_request_latency_seconds "$detector_service_name" "$queued_at")"
    if [[ -z "$latency_seconds" ]]; then
      echo "Unable to locate request latency for ${mode} ${pdf_path} (${detector_service_name})" >&2
      exit 1
    fi

    local cold_start_verified="false"
    if [[ "${force_cold_start}" == "true" && "${is_first_run}" == "true" ]]; then
      cold_start_verified="$(check_cold_start_event "$detector_service_name" "$cold_start_marker" "$completed_at")"
      if [[ "$cold_start_verified" != "true" ]]; then
        echo "Expected cold start marker for ${mode}, but no Cloud Run start event was found." >&2
        exit 1
      fi
      is_first_run="false"
    fi

    append_result "$mode" "$pdf_path" "$detector_service_name" "$latency_seconds" "$cold_start_verified" "$job_json"
    echo "  ${mode} ${pdf_path} -> ok"
  done
}

summarize_results() {
  python3 - <<'PY' "$RESULTS_JSONL"
import json
import math
import statistics
import sys
from collections import defaultdict

path = sys.argv[1]
rows = []
with open(path, "r", encoding="utf-8") as handle:
    for line in handle:
        text = line.strip()
        if text:
            rows.append(json.loads(text))

if not rows:
    raise SystemExit("No benchmark rows were collected.")

CPU_VCPU_RATE = 0.000024
CPU_MEM_RATE = 0.0000025
GPU_VCPU_RATE = 0.000018
GPU_MEM_RATE = 0.000002
GPU_L4_RATE = 0.0001867

def percentile(values, p):
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    idx = int(round((len(ordered) - 1) * (p / 100.0)))
    idx = max(0, min(len(ordered) - 1, idx))
    return ordered[idx]

def run_rate(mode, profile):
    if mode == "gpu":
        return (4 * GPU_VCPU_RATE) + (16 * GPU_MEM_RATE) + GPU_L4_RATE
    if profile == "heavy":
        return (4 * CPU_VCPU_RATE) + (8 * CPU_MEM_RATE)
    return (2 * CPU_VCPU_RATE) + (4 * CPU_MEM_RATE)

for row in rows:
    latency = float(row["request_latency_seconds"])
    row["estimated_cost_usd"] = latency * run_rate(str(row["mode"]), str(row.get("profile") or "light"))

grouped = defaultdict(list)
for row in rows:
    grouped[str(row["mode"])].append(row)

print("Benchmark results:")
print(f"rows={len(rows)} source={path}")
for mode in ("cpu", "gpu"):
    items = grouped.get(mode, [])
    if not items:
        continue
    det = [float(item["detection_duration_seconds"]) for item in items]
    lat = [float(item["request_latency_seconds"]) for item in items]
    cost = [float(item["estimated_cost_usd"]) for item in items]
    cold_hits = sum(1 for item in items if item.get("cold_start_verified"))
    print(
        f"{mode}: runs={len(items)} cold_verified={cold_hits} "
        f"detect_p50={percentile(det, 50):.3f}s detect_p95={percentile(det, 95):.3f}s "
        f"latency_p50={percentile(lat, 50):.3f}s latency_p95={percentile(lat, 95):.3f}s "
        f"billable_seconds={sum(lat):.3f}s estimated_cost={sum(cost):.6f} USD"
    )

cpu_items = grouped.get("cpu", [])
gpu_items = grouped.get("gpu", [])
if cpu_items and gpu_items:
    cpu_det = [float(item["detection_duration_seconds"]) for item in cpu_items]
    gpu_det = [float(item["detection_duration_seconds"]) for item in gpu_items]
    cpu_lat = [float(item["request_latency_seconds"]) for item in cpu_items]
    gpu_lat = [float(item["request_latency_seconds"]) for item in gpu_items]
    cpu_cost = sum(float(item["estimated_cost_usd"]) for item in cpu_items)
    gpu_cost = sum(float(item["estimated_cost_usd"]) for item in gpu_items)
    print("Comparison:")
    print(
        f"detect_p50_speedup={percentile(cpu_det, 50)/percentile(gpu_det, 50):.3f}x "
        f"latency_p50_speedup={percentile(cpu_lat, 50)/percentile(gpu_lat, 50):.3f}x "
        f"cost_ratio={gpu_cost/cpu_cost:.3f}x"
    )
PY
}

CPU_TAG="${BENCH_CPU_TAG:-bench-cpu-$(date +%Y%m%d-%H%M%S)}"
GPU_TAG="${BENCH_GPU_TAG:-bench-gpu-$(date +%Y%m%d-%H%M%S)}"

deploy_detector_mode "cpu" "$CPU_SERVICE_LIGHT" "$CPU_SERVICE_HEAVY" "false" "$CPU_TAG" "$CPU_REGION" "$BENCH_SKIP_BUILD_CPU"
deploy_detector_mode "gpu" "$GPU_SERVICE_LIGHT" "$GPU_SERVICE_HEAVY" "true" "$GPU_TAG" "$GPU_REGION" "$BENCH_SKIP_BUILD_GPU"

CPU_URL_LIGHT="$(get_service_url "$CPU_SERVICE_LIGHT" "$CPU_REGION")"
CPU_URL_HEAVY="$(get_service_url "$CPU_SERVICE_HEAVY" "$CPU_REGION")"
GPU_URL_LIGHT="$(get_service_url "$GPU_SERVICE_LIGHT" "$GPU_REGION")"
GPU_URL_HEAVY="$(get_service_url "$GPU_SERVICE_HEAVY" "$GPU_REGION")"

run_mode "cpu" "$CPU_SERVICE_LIGHT" "$CPU_SERVICE_HEAVY" "$FORCE_COLD_START_CPU" "$CPU_URL_LIGHT" "$CPU_URL_HEAVY" "$CPU_REGION"
run_mode "gpu" "$GPU_SERVICE_LIGHT" "$GPU_SERVICE_HEAVY" "$FORCE_COLD_START_GPU" "$GPU_URL_LIGHT" "$GPU_URL_HEAVY" "$GPU_REGION"

summarize_results
echo "Saved detailed rows: ${RESULTS_JSONL}"
