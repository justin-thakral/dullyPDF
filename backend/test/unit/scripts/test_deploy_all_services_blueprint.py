"""Regression checks for the aggregate deploy script sequencing."""

from __future__ import annotations

from pathlib import Path


SCRIPT_PATH = Path("scripts/deploy-all-services.sh")


def test_deploy_all_services_includes_firestore_index_deploy() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert 'bash scripts/deploy-firestore-indexes.sh' in text


def test_deploy_all_services_deploys_session_cleanup_job_from_same_backend_image() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert 'source "${SCRIPT_DIR}/_artifact_registry_guard.sh"' in text
    assert 'ARTIFACT_REGISTRY_LOCATION="${ARTIFACT_REGISTRY_LOCATION:-us-east4}"' in text
    assert 'BACKEND_ARTIFACT_REPO="${BACKEND_ARTIFACT_REPO:-dullypdf-backend}"' in text
    assert 'require_prod_artifact_registry_location "Artifact Registry location" "$ARTIFACT_REGISTRY_LOCATION"' in text
    assert 'require_prod_artifact_registry_repo "BACKEND_ARTIFACT_REPO" "$BACKEND_ARTIFACT_REPO"' in text
    assert 'BACKEND_IMAGE="${BACKEND_IMAGE:-${ARTIFACT_REGISTRY_LOCATION}-docker.pkg.dev/${PROJECT_ID}/${BACKEND_ARTIFACT_REPO}/backend:$(date +%Y%m%d-%H%M%S)}"' in text
    assert 'require_prod_artifact_registry_image "BACKEND_IMAGE" "$BACKEND_IMAGE" "$BACKEND_ARTIFACT_REPO"' in text
    assert 'REGION="${REGION:-${DETECTOR_TASKS_LOCATION:-${OPENAI_RENAME_TASKS_LOCATION:-us-east4}}}"' in text
    assert 'BACKEND_REGION="${BACKEND_REGION:-us-east4}"' in text
    assert 'BACKEND_SERVICE="${BACKEND_SERVICE:-dullypdf-backend-east4}"' in text
    assert 'Refusing to deploy all services with retired prod backend service name dullypdf-backend.' in text
    assert 'Use BACKEND_SERVICE=dullypdf-backend-east4 instead.' in text
    assert 'SESSION_CLEANUP_REGION="$BACKEND_REGION" SESSION_CLEANUP_IMAGE_SOURCE_REGION="$BACKEND_REGION" SESSION_CLEANUP_IMAGE_SOURCE_SERVICE="$BACKEND_SERVICE" ENV_FILE="$ENV_FILE" BACKEND_IMAGE="$BACKEND_IMAGE" bash scripts/deploy-session-cleanup-job.sh "$ENV_FILE"' in text


def test_deploy_all_services_deploys_workers_before_backend_and_prunes_stale_resources() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    detector_call = 'ARTIFACT_REGISTRY_LOCATION="$ARTIFACT_REGISTRY_LOCATION" bash scripts/deploy-detector-services.sh "$ENV_FILE"'
    worker_call = 'ARTIFACT_REGISTRY_LOCATION="$ARTIFACT_REGISTRY_LOCATION" bash scripts/deploy-openai-workers.sh "$ENV_FILE"'
    backend_call = 'BACKEND_REGION="$BACKEND_REGION" BACKEND_SERVICE="$BACKEND_SERVICE" ARTIFACT_REGISTRY_LOCATION="$ARTIFACT_REGISTRY_LOCATION" BACKEND_ARTIFACT_REPO="$BACKEND_ARTIFACT_REPO" ENV_FILE="$ENV_FILE" BACKEND_IMAGE="$BACKEND_IMAGE" bash scripts/deploy-backend.sh'
    prune_call = 'REGION="$REGION" ENV_FILE="$ENV_FILE" bash scripts/prune-stale-cloud-resources.sh "$ENV_FILE"'
    assert detector_call in text
    assert worker_call in text
    assert backend_call in text
    assert prune_call in text
    assert text.index(detector_call) < text.index(worker_call) < text.index(backend_call) < text.index(prune_call)
