"""Integration coverage for the detect -> rename -> save/download form flow."""

from __future__ import annotations

from copy import deepcopy
import io
from typing import Any

from fastapi.testclient import TestClient
import pytest

import backend.api.middleware.security as security_middleware
import backend.api.routes.ai as ai_routes
import backend.api.routes.detection as detection_routes
import backend.api.routes.saved_forms as saved_forms_routes
import backend.firebaseDB.fill_link_database as fill_link_database
import backend.firebaseDB.group_database as group_database
import backend.firebaseDB.session_database as session_database
import backend.firebaseDB.signing_database as signing_database
import backend.firebaseDB.template_database as template_database
import backend.firebaseDB.user_database as user_database
from backend.detection.pdf_validation import PdfValidationResult
from backend.detection.status import DETECTION_STATUS_COMPLETE, DETECTION_STATUS_QUEUED
from backend.firebaseDB.firebase_service import RequestUser
from backend.sessions import l2_persistence
from backend.sessions.l1_cache import _API_SESSION_CACHE
from backend.sessions.session_store import store_session_entry
from backend.test.unit.firebase._fakes import FakeFirestoreClient
import backend.main as main


class _InMemoryStorage:
    """Small storage double shared across session and saved-form routes."""

    def __init__(self) -> None:
        self._objects: dict[str, Any] = {}

    def upload_form_pdf(self, local_file_path: str, destination_path: str) -> str:
        with open(local_file_path, "rb") as handle:
            data = handle.read()
        bucket_path = f"gs://forms-bucket/{destination_path}"
        self._objects[bucket_path] = data
        return bucket_path

    def upload_template_pdf(self, local_file_path: str, destination_path: str) -> str:
        with open(local_file_path, "rb") as handle:
            data = handle.read()
        bucket_path = f"gs://templates-bucket/{destination_path}"
        self._objects[bucket_path] = data
        return bucket_path

    def upload_session_pdf_bytes(self, pdf_bytes: bytes, destination_path: str) -> str:
        bucket_path = f"gs://session-bucket/{destination_path}"
        self._objects[bucket_path] = bytes(pdf_bytes)
        return bucket_path

    def upload_session_json(self, payload: Any, destination_path: str) -> str:
        bucket_path = f"gs://session-bucket/{destination_path}"
        self._objects[bucket_path] = deepcopy(payload)
        return bucket_path

    def download_pdf_bytes(self, bucket_path: str) -> bytes:
        data = self._objects.get(bucket_path)
        if not isinstance(data, (bytes, bytearray)):
            raise FileNotFoundError(bucket_path)
        return bytes(data)

    def download_session_json(self, bucket_path: str) -> Any:
        if bucket_path not in self._objects:
            raise FileNotFoundError(bucket_path)
        return deepcopy(self._objects[bucket_path])

    def stream_pdf(self, bucket_path: str) -> io.BytesIO:
        return io.BytesIO(self.download_pdf_bytes(bucket_path))

    def delete_pdf(self, bucket_path: str) -> None:
        if bucket_path not in self._objects:
            raise FileNotFoundError(bucket_path)
        self._objects.pop(bucket_path, None)


@pytest.fixture
def client() -> TestClient:
    return TestClient(main.app)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer integration-token"}


@pytest.fixture
def qa_user() -> RequestUser:
    return RequestUser(
        uid="uid_qa",
        app_user_id="user_qa",
        email="qa@example.com",
        display_name="QA User",
        role="base",
    )


@pytest.fixture(autouse=True)
def _reset_session_cache() -> None:
    _API_SESSION_CACHE.clear()


def _seed_user_credit_profile(
    firestore_client: FakeFirestoreClient,
    qa_user: RequestUser,
    *,
    credits: int,
    base_cycle_key: str,
) -> None:
    firestore_client.collection(user_database.USERS_COLLECTION).document(qa_user.app_user_id).seed(
        {
            "email": qa_user.email,
            "displayName": qa_user.display_name,
            user_database.ROLE_FIELD: user_database.ROLE_BASE,
            user_database.OPENAI_CREDITS_FIELD: credits,
            user_database.OPENAI_CREDITS_BASE_CYCLE_FIELD: base_cycle_key,
            "created_at": "2026-03-28T00:00:00+00:00",
            "updated_at": "2026-03-28T00:00:00+00:00",
        }
    )


def _start_detection_session(
    client: TestClient,
    auth_headers: dict[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    detect_response = client.post(
        "/detect-fields",
        files={"file": ("qa.pdf", b"%PDF-1.4\nintegration\n", "application/pdf")},
        headers=auth_headers,
    )

    assert detect_response.status_code == 200
    detect_payload = detect_response.json()
    status_response = client.get(f"/detect-fields/{detect_payload['sessionId']}", headers=auth_headers)

    assert status_response.status_code == 200
    return detect_payload, status_response.json()


def _seed_saved_form_template(
    firestore_client: FakeFirestoreClient,
    storage: _InMemoryStorage,
    qa_user: RequestUser,
    *,
    template_id: str,
    name: str,
    created_at: str,
) -> None:
    pdf_bucket_path = f"gs://forms-bucket/{template_id}.pdf"
    template_bucket_path = f"gs://templates-bucket/{template_id}.json"
    storage._objects[pdf_bucket_path] = f"%PDF-1.4\n{template_id}\n".encode("utf-8")
    storage._objects[template_bucket_path] = b'{"fields":[]}'
    firestore_client.collection(template_database.TEMPLATES_COLLECTION).document(template_id).seed(
        {
            "user_id": qa_user.app_user_id,
            "pdf_bucket_path": pdf_bucket_path,
            "template_bucket_path": template_bucket_path,
            "metadata": {
                "name": name,
                "fillRules": {"checkboxRules": [], "textTransformRules": []},
            },
            "created_at": created_at,
            "updated_at": created_at,
        }
    )


@pytest.fixture(autouse=True)
def _integration_state(mocker, qa_user: RequestUser):
    firestore_client = FakeFirestoreClient()
    storage = _InMemoryStorage()

    mocker.patch.object(user_database.firebase_firestore, "transactional", side_effect=lambda fn: fn)
    mocker.patch.object(session_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(template_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(user_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(fill_link_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(group_database, "get_firestore_client", return_value=firestore_client)
    mocker.patch.object(signing_database, "get_firestore_client", return_value=firestore_client)

    mocker.patch.object(security_middleware, "verify_token", return_value={"uid": qa_user.uid})
    mocker.patch.object(detection_routes, "verify_token", return_value={"uid": qa_user.uid})
    mocker.patch.object(detection_routes, "ensure_user", return_value=qa_user)
    mocker.patch.object(detection_routes, "check_rate_limit", return_value=True)
    mocker.patch.object(detection_routes, "resolve_detect_max_pages", return_value=10)
    mocker.patch.object(detection_routes, "read_upload_bytes", return_value=b"%PDF-1.4\nintegration-detect\n")
    mocker.patch.object(
        detection_routes,
        "validate_pdf_for_detection",
        return_value=PdfValidationResult(
            pdf_bytes=b"%PDF-1.4\nintegration-detect\n",
            page_count=1,
            was_decrypted=False,
        ),
    )
    mocker.patch.object(detection_routes, "resolve_detection_mode", return_value="tasks")

    mocker.patch.object(ai_routes, "_resolve_user_from_request", return_value=qa_user)
    mocker.patch.object(ai_routes, "resolve_openai_rename_remap_mode", return_value="local")
    mocker.patch.object(ai_routes, "check_rate_limit", return_value=True)
    mocker.patch.object(
        ai_routes,
        "consume_openai_credits",
        return_value=(9, True, {"base": 1, "monthly": 0, "refill": 0}),
    )
    mocker.patch.object(ai_routes, "record_openai_rename_request", return_value=None)

    mocker.patch.object(saved_forms_routes, "require_user", return_value=qa_user)
    mocker.patch.object(saved_forms_routes, "resolve_saved_forms_limit", return_value=10)
    mocker.patch.object(saved_forms_routes, "resolve_fillable_max_pages", return_value=10)
    mocker.patch.object(saved_forms_routes, "get_pdf_page_count", return_value=1)
    mocker.patch.object(
        saved_forms_routes,
        "validate_pdf_for_detection",
        return_value=PdfValidationResult(
            pdf_bytes=b"%PDF-1.4\nsaved-form\n",
            page_count=1,
            was_decrypted=False,
        ),
    )

    mocker.patch.object(l2_persistence, "upload_session_pdf_bytes", side_effect=storage.upload_session_pdf_bytes)
    mocker.patch.object(l2_persistence, "upload_session_json", side_effect=storage.upload_session_json)
    mocker.patch.object(l2_persistence, "download_pdf_bytes", side_effect=storage.download_pdf_bytes)
    mocker.patch.object(l2_persistence, "download_session_json", side_effect=storage.download_session_json)

    mocker.patch.object(detection_routes, "download_session_json", side_effect=storage.download_session_json)
    mocker.patch.object(saved_forms_routes, "upload_form_pdf", side_effect=storage.upload_form_pdf)
    mocker.patch.object(saved_forms_routes, "upload_template_pdf", side_effect=storage.upload_template_pdf)
    mocker.patch.object(saved_forms_routes, "download_pdf_bytes", side_effect=storage.download_pdf_bytes)
    mocker.patch.object(saved_forms_routes, "stream_pdf", side_effect=storage.stream_pdf)
    mocker.patch.object(saved_forms_routes, "delete_pdf", side_effect=storage.delete_pdf)
    mocker.patch.object(saved_forms_routes, "is_gcs_path", side_effect=lambda value: isinstance(value, str) and value.startswith("gs://"))

    def _enqueue_detection_job(
        pdf_bytes: bytes,
        source_pdf: str,
        user: RequestUser | None,
        *,
        page_count: int,
        source_pdf_sha256: str | None = None,
        prewarm_rename: bool,
        prewarm_remap: bool,
    ) -> dict[str, Any]:
        del prewarm_rename, prewarm_remap
        session_id = "sess-detect-rename-save"
        store_session_entry(
            session_id,
            {
                "user_id": user.app_user_id if user else "anonymous",
                "source_pdf": source_pdf,
                "source_pdf_sha256": source_pdf_sha256,
                "pdf_bytes": pdf_bytes,
                "fields": [
                    {
                        "name": "patient_name",
                        "type": "text",
                        "page": 1,
                        "rect": {"x": 10, "y": 20, "width": 100, "height": 24},
                        "confidence": 0.86,
                    }
                ],
                "result": {"pipeline": "commonforms", "provider": "integration-test"},
                "page_count": page_count,
                "detection_status": DETECTION_STATUS_COMPLETE,
            },
            persist_pdf=True,
            persist_fields=True,
            persist_result=True,
        )
        return {
            "sessionId": session_id,
            "status": DETECTION_STATUS_QUEUED,
            "pipeline": "commonforms",
        }

    mocker.patch.object(detection_routes, "enqueue_detection_job", side_effect=_enqueue_detection_job)

    def _run_openai_rename_on_pdf(
        *,
        pdf_bytes: bytes,
        pdf_name: str,
        fields: list[dict[str, Any]],
        database_fields: list[str] | None,
        detector_candidates_by_page: dict[int, list[dict[str, Any]]] | None = None,
    ):
        del pdf_name, database_fields, detector_candidates_by_page
        assert pdf_bytes.startswith(b"%PDF-1.4")
        assert fields[0]["name"] == "patient_name"
        return (
            {
                "renames": [
                    {
                        "originalFieldName": "patient_name",
                        "suggestedRename": "insured_name",
                        "renameConfidence": 0.96,
                        "isItAfieldConfidence": 0.93,
                    }
                ],
                "checkboxRules": [
                    {
                        "databaseField": "accept_terms",
                        "groupKey": "accept_terms",
                    }
                ],
            },
            [
                {
                    "name": "insured_name",
                    "originalName": "patient_name",
                    "type": "text",
                    "page": 1,
                    "rect": [10, 20, 110, 44],
                    "renameConfidence": 0.96,
                    "isItAfieldConfidence": 0.93,
                }
            ],
        )

    mocker.patch.object(ai_routes, "run_openai_rename_on_pdf", side_effect=_run_openai_rename_on_pdf)

    return {
        "firestore_client": firestore_client,
        "storage": storage,
    }


def test_detect_rename_save_and_download_saved_form_round_trip(
    client: TestClient,
    auth_headers: dict[str, str],
    _integration_state,
) -> None:
    detect_payload, status_payload = _start_detection_session(client, auth_headers)
    assert detect_payload["sessionId"] == "sess-detect-rename-save"
    assert detect_payload["status"] == DETECTION_STATUS_QUEUED
    assert status_payload["status"] == DETECTION_STATUS_COMPLETE
    assert status_payload["fieldCount"] == 1
    assert status_payload["fields"][0]["name"] == "patient_name"

    rename_response = client.post(
        "/api/renames/ai",
        json={
            "sessionId": detect_payload["sessionId"],
            "templateFields": status_payload["fields"],
        },
        headers=auth_headers,
    )

    assert rename_response.status_code == 200
    rename_payload = rename_response.json()
    assert rename_payload["fields"][0]["name"] == "insured_name"
    assert rename_payload["checkboxRules"] == [{"databaseField": "accept_terms", "groupKey": "accept_terms"}]

    save_response = client.post(
        "/api/saved-forms",
        files={"pdf": ("renamed-form.pdf", b"%PDF-1.4\nsaved\n", "application/pdf")},
        data={
            "name": "Integration QA Form",
            "sessionId": detect_payload["sessionId"],
        },
        headers=auth_headers,
    )

    assert save_response.status_code == 200
    save_payload = save_response.json()
    assert save_payload["success"] is True
    assert save_payload["name"] == "Integration QA Form"

    list_response = client.get("/api/saved-forms", headers=auth_headers)

    assert list_response.status_code == 200
    listed_forms = list_response.json()["forms"]
    assert len(listed_forms) == 1
    assert listed_forms[0]["id"] == save_payload["id"]
    assert listed_forms[0]["name"] == "Integration QA Form"
    assert isinstance(listed_forms[0]["createdAt"], str) and listed_forms[0]["createdAt"]

    metadata_response = client.get(f"/api/saved-forms/{save_payload['id']}", headers=auth_headers)

    assert metadata_response.status_code == 200
    metadata_payload = metadata_response.json()
    assert metadata_payload["name"] == "Integration QA Form"
    assert metadata_payload["checkboxRules"] == [{"databaseField": "accept_terms", "groupKey": "accept_terms"}]
    assert metadata_payload["fillRules"]["checkboxRules"] == metadata_payload["checkboxRules"]

    saved_form_session_response = client.post(
        f"/api/saved-forms/{save_payload['id']}/session",
        json={"fields": rename_payload["fields"]},
        headers=auth_headers,
    )

    assert saved_form_session_response.status_code == 200
    assert saved_form_session_response.json()["success"] is True
    assert saved_form_session_response.json()["fieldCount"] == 1

    download_response = client.get(f"/api/saved-forms/{save_payload['id']}/download", headers=auth_headers)

    assert download_response.status_code == 200
    assert download_response.headers["content-type"] == "application/pdf"
    assert "Integration_QA_Form.pdf" in download_response.headers["content-disposition"]
    assert download_response.content == b"%PDF-1.4\nsaved\n"

    stored_template = (
        _integration_state["firestore_client"]
        .collection(template_database.TEMPLATES_COLLECTION)
        .document(save_payload["id"])
        .get()
        .to_dict()
    )
    assert stored_template["metadata"]["checkboxRules"] == [{"databaseField": "accept_terms", "groupKey": "accept_terms"}]
    assert stored_template["metadata"]["fillRules"]["checkboxRules"] == stored_template["metadata"]["checkboxRules"]


def test_saved_form_creation_rejects_sixth_form_on_base_plan(
    client: TestClient,
    auth_headers: dict[str, str],
    qa_user: RequestUser,
    _integration_state,
    mocker,
) -> None:
    firestore_client = _integration_state["firestore_client"]
    storage = _integration_state["storage"]
    firestore_client.collection(user_database.USERS_COLLECTION).document(qa_user.app_user_id).seed(
        {
            "email": qa_user.email,
            "displayName": qa_user.display_name,
            user_database.ROLE_FIELD: user_database.ROLE_BASE,
            user_database.OPENAI_CREDITS_FIELD: 10,
            user_database.OPENAI_CREDITS_BASE_CYCLE_FIELD: "2026-03",
            "created_at": "2026-03-01T00:00:00+00:00",
            "updated_at": "2026-03-27T00:00:00+00:00",
        }
    )
    mocker.patch.object(saved_forms_routes, "resolve_saved_forms_limit", return_value=5)

    for index in range(5):
        template_number = index + 1
        _seed_saved_form_template(
            firestore_client,
            storage,
            qa_user,
            template_id=f"form-{template_number}",
            name=f"Saved Form {template_number}",
            created_at=f"2024-01-{template_number:02d}T00:00:00+00:00",
        )

    detect_payload, _ = _start_detection_session(client, auth_headers)
    save_response = client.post(
        "/api/saved-forms",
        files={"pdf": ("limit-test.pdf", b"%PDF-1.4\nsaved\n", "application/pdf")},
        data={
            "name": "Blocked Sixth Form",
            "sessionId": detect_payload["sessionId"],
        },
        headers=auth_headers,
    )

    assert save_response.status_code == 403
    assert "Saved form limit reached" in save_response.text
    stored_templates = list(template_database.list_templates(qa_user.app_user_id))
    assert len(stored_templates) == 5
    assert {template.id for template in stored_templates} == {
        "form-1",
        "form-2",
        "form-3",
        "form-4",
        "form-5",
    }


def test_rename_endpoint_consumes_real_base_credits_until_exhausted(
    client: TestClient,
    auth_headers: dict[str, str],
    qa_user: RequestUser,
    _integration_state,
    mocker,
) -> None:
    firestore_client = _integration_state["firestore_client"]
    _seed_user_credit_profile(
        firestore_client,
        qa_user,
        credits=2,
        base_cycle_key="2026-03",
    )
    mocker.patch.object(ai_routes, "consume_openai_credits", side_effect=user_database.consume_openai_credits)
    mocker.patch.object(user_database, "_current_month_cycle_key", return_value="2026-03")

    detect_payload, status_payload = _start_detection_session(client, auth_headers)
    request_payload = {
        "sessionId": detect_payload["sessionId"],
        "templateFields": status_payload["fields"],
    }

    first_response = client.post("/api/renames/ai", json=request_payload, headers=auth_headers)
    second_response = client.post("/api/renames/ai", json=request_payload, headers=auth_headers)
    blocked_response = client.post("/api/renames/ai", json=request_payload, headers=auth_headers)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert blocked_response.status_code == 402
    assert "OpenAI credits exhausted" in blocked_response.text

    stored_user = (
        firestore_client.collection(user_database.USERS_COLLECTION)
        .document(qa_user.app_user_id)
        .get()
        .to_dict()
    )
    assert stored_user[user_database.OPENAI_CREDITS_FIELD] == 0
    assert stored_user[user_database.OPENAI_CREDITS_BASE_CYCLE_FIELD] == "2026-03"


@pytest.mark.parametrize(
    ("starting_credits", "expected_remaining"),
    [
        (0, 9),
        (12, 11),
    ],
)
def test_rename_endpoint_applies_base_month_rollover_without_overcapping_existing_balance(
    client: TestClient,
    auth_headers: dict[str, str],
    qa_user: RequestUser,
    _integration_state,
    mocker,
    starting_credits: int,
    expected_remaining: int,
) -> None:
    firestore_client = _integration_state["firestore_client"]
    _seed_user_credit_profile(
        firestore_client,
        qa_user,
        credits=starting_credits,
        base_cycle_key="2026-02",
    )
    mocker.patch.object(ai_routes, "consume_openai_credits", side_effect=user_database.consume_openai_credits)
    mocker.patch.object(user_database, "_current_month_cycle_key", return_value="2026-03")

    detect_payload, status_payload = _start_detection_session(client, auth_headers)
    response = client.post(
        "/api/renames/ai",
        json={
            "sessionId": detect_payload["sessionId"],
            "templateFields": status_payload["fields"],
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    stored_user = (
        firestore_client.collection(user_database.USERS_COLLECTION)
        .document(qa_user.app_user_id)
        .get()
        .to_dict()
    )
    assert stored_user[user_database.OPENAI_CREDITS_FIELD] == expected_remaining
    assert stored_user[user_database.OPENAI_CREDITS_BASE_CYCLE_FIELD] == "2026-03"


def test_saved_forms_lock_access_to_templates_beyond_oldest_five_after_real_base_downgrade(
    client: TestClient,
    auth_headers: dict[str, str],
    qa_user: RequestUser,
    _integration_state,
) -> None:
    firestore_client = _integration_state["firestore_client"]
    storage = _integration_state["storage"]
    firestore_client.collection(user_database.USERS_COLLECTION).document(qa_user.app_user_id).seed(
        {
            "email": qa_user.email,
            "displayName": qa_user.display_name,
            user_database.ROLE_FIELD: user_database.ROLE_PRO,
            user_database.OPENAI_CREDITS_MONTHLY_FIELD: 500,
            user_database.OPENAI_CREDITS_REFILL_FIELD: 0,
            user_database.OPENAI_CREDITS_MONTHLY_CYCLE_FIELD: "2026-03",
            "created_at": "2026-03-01T00:00:00+00:00",
            "updated_at": "2026-03-27T00:00:00+00:00",
        }
    )
    for index in range(7):
        template_number = index + 1
        _seed_saved_form_template(
            firestore_client,
            storage,
            qa_user,
            template_id=f"form-{template_number}",
            name=f"Saved Form {template_number}",
            created_at=f"2024-01-{template_number:02d}T00:00:00+00:00",
        )

    user_database.downgrade_to_base_membership(qa_user.app_user_id)

    list_response = client.get("/api/saved-forms", headers=auth_headers)

    assert list_response.status_code == 200
    forms = {entry["id"]: entry for entry in list_response.json()["forms"]}
    assert set(forms) == {f"form-{value}" for value in range(1, 8)}
    assert {form_id for form_id, entry in forms.items() if not entry["locked"]} == {
        "form-1",
        "form-2",
        "form-3",
        "form-4",
        "form-5",
    }
    assert {form_id for form_id, entry in forms.items() if entry["locked"]} == {
        "form-6",
        "form-7",
    }

    retention_state = (
        firestore_client.collection(user_database.USERS_COLLECTION)
        .document(qa_user.app_user_id)
        .get()
        .to_dict()
    )[user_database.DOWNGRADE_RETENTION_FIELD]
    assert retention_state["kept_template_ids"] == [
        "form-1",
        "form-2",
        "form-3",
        "form-4",
        "form-5",
    ]
    assert retention_state["pending_delete_template_ids"] == ["form-6", "form-7"]

    accessible_response = client.get("/api/saved-forms/form-1", headers=auth_headers)
    assert accessible_response.status_code == 200
    assert accessible_response.json()["name"] == "Saved Form 1"

    locked_response = client.get("/api/saved-forms/form-6", headers=auth_headers)
    assert locked_response.status_code == 409
    assert "locked on the base plan" in locked_response.text.lower()

    download_locked_response = client.get("/api/saved-forms/form-7/download", headers=auth_headers)
    assert download_locked_response.status_code == 409

    session_locked_response = client.post(
        "/api/saved-forms/form-7/session",
        json={
            "fields": [
                {
                    "name": "insured_name",
                    "type": "text",
                    "page": 1,
                    "rect": {"x": 10, "y": 20, "width": 100, "height": 24},
                }
            ]
        },
        headers=auth_headers,
    )
    assert session_locked_response.status_code == 409


def test_schema_mapping_rejects_locked_saved_form_template_after_real_base_downgrade(
    client: TestClient,
    auth_headers: dict[str, str],
    qa_user: RequestUser,
    _integration_state,
    mocker,
) -> None:
    firestore_client = _integration_state["firestore_client"]
    storage = _integration_state["storage"]
    firestore_client.collection(user_database.USERS_COLLECTION).document(qa_user.app_user_id).seed(
        {
            "email": qa_user.email,
            "displayName": qa_user.display_name,
            user_database.ROLE_FIELD: user_database.ROLE_PRO,
            user_database.OPENAI_CREDITS_MONTHLY_FIELD: 500,
            user_database.OPENAI_CREDITS_REFILL_FIELD: 0,
            user_database.OPENAI_CREDITS_MONTHLY_CYCLE_FIELD: "2026-03",
            "created_at": "2026-03-01T00:00:00+00:00",
            "updated_at": "2026-03-27T00:00:00+00:00",
        }
    )
    for index in range(7):
        template_number = index + 1
        _seed_saved_form_template(
            firestore_client,
            storage,
            qa_user,
            template_id=f"form-{template_number}",
            name=f"Saved Form {template_number}",
            created_at=f"2024-01-{template_number:02d}T00:00:00+00:00",
        )

    user_database.downgrade_to_base_membership(qa_user.app_user_id)

    mocker.patch.object(
        ai_routes,
        "get_schema",
        return_value=type("SchemaRecord", (), {"id": "schema_1", "fields": [{"name": "insured_name"}]})(),
    )
    build_allowlist_mock = mocker.patch.object(
        ai_routes,
        "build_allowlist_payload",
        return_value={"schemaFields": [{"name": "insured_name"}], "templateTags": [{"tag": "insured_name"}]},
    )
    consume_mock = mocker.patch.object(ai_routes, "consume_openai_credits")
    openai_mock = mocker.patch.object(ai_routes, "call_openai_schema_mapping_chunked")

    response = client.post(
        "/api/schema-mappings/ai",
        json={
            "schemaId": "schema_1",
            "templateId": "form-6",
            "templateFields": [
                {
                    "name": "insured_name",
                    "type": "text",
                    "page": 1,
                    "rect": {"x": 10, "y": 20, "width": 100, "height": 24},
                }
            ],
        },
        headers=auth_headers,
    )

    assert response.status_code == 409
    assert "locked on the base plan" in response.text.lower()
    build_allowlist_mock.assert_not_called()
    consume_mock.assert_not_called()
    openai_mock.assert_not_called()


def test_rename_rejects_legacy_saved_form_session_for_locked_template_after_downgrade(
    client: TestClient,
    auth_headers: dict[str, str],
    qa_user: RequestUser,
    _integration_state,
    mocker,
) -> None:
    firestore_client = _integration_state["firestore_client"]
    storage = _integration_state["storage"]
    firestore_client.collection(user_database.USERS_COLLECTION).document(qa_user.app_user_id).seed(
        {
            "email": qa_user.email,
            "displayName": qa_user.display_name,
            user_database.ROLE_FIELD: user_database.ROLE_PRO,
            user_database.OPENAI_CREDITS_MONTHLY_FIELD: 500,
            user_database.OPENAI_CREDITS_REFILL_FIELD: 0,
            user_database.OPENAI_CREDITS_MONTHLY_CYCLE_FIELD: "2026-03",
            "created_at": "2026-03-01T00:00:00+00:00",
            "updated_at": "2026-03-27T00:00:00+00:00",
        }
    )
    for index in range(7):
        template_number = index + 1
        _seed_saved_form_template(
            firestore_client,
            storage,
            qa_user,
            template_id=f"form-{template_number}",
            name=f"Saved Form {template_number}",
            created_at=f"2024-01-{template_number:02d}T00:00:00+00:00",
        )

    saved_form_session_response = client.post(
        "/api/saved-forms/form-6/session",
        json={
            "fields": [
                {
                    "name": "insured_name",
                    "type": "text",
                    "page": 1,
                    "rect": {"x": 10, "y": 20, "width": 100, "height": 24},
                }
            ]
        },
        headers=auth_headers,
    )

    assert saved_form_session_response.status_code == 200
    saved_session_id = saved_form_session_response.json()["sessionId"]
    session_doc_ref = firestore_client.collection(session_database.SESSION_COLLECTION).document(saved_session_id)
    session_metadata = session_doc_ref.get().to_dict()
    assert session_metadata["source_template_id"] == "form-6"

    legacy_session_metadata = dict(session_metadata)
    legacy_session_metadata.pop("source_template_id", None)
    session_doc_ref.seed(legacy_session_metadata)

    user_database.downgrade_to_base_membership(qa_user.app_user_id)

    consume_mock = mocker.patch.object(ai_routes, "consume_openai_credits")
    openai_mock = mocker.patch.object(ai_routes, "run_openai_rename_on_pdf")

    response = client.post(
        "/api/renames/ai",
        json={
            "sessionId": saved_session_id,
            "templateFields": [
                {
                    "name": "insured_name",
                    "type": "text",
                    "page": 1,
                    "rect": {"x": 10, "y": 20, "width": 100, "height": 24},
                }
            ],
        },
        headers=auth_headers,
    )

    assert response.status_code == 409
    assert "locked on the base plan" in response.text.lower()
    consume_mock.assert_not_called()
    openai_mock.assert_not_called()
    refreshed_session_metadata = session_doc_ref.get().to_dict()
    assert refreshed_session_metadata["source_template_id"] == "form-6"
