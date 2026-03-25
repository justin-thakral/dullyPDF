import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _set_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "test")


@pytest.fixture
def dummy_session_entry() -> dict:
    return {
        "pdf_bytes": b"%PDF-1.4\n%fake\n",
        "fields": [],
        "source_pdf": "test.pdf",
        "result": {},
        "page_count": 1,
        "user_id": "user_1",
    }


@pytest.fixture
def dummy_ten_page_session_entry() -> dict:
    return {
        "pdf_bytes": b"%PDF-1.4\n%fake\n",
        "fields": [],
        "source_pdf": "test.pdf",
        "result": {},
        "page_count": 10,
        "user_id": "user_1",
    }


@pytest.fixture
def dummy_template_field() -> dict:
    return {
        "name": "A1",
        "type": "text",
        "page": 1,
        "rect": {"x": 10, "y": 10, "width": 100, "height": 20},
    }


def _dummy_schema_record(schema_id: str = "schema_1"):
    from backend.firebaseDB.schema_database import SchemaRecord

    return SchemaRecord(
        id=schema_id,
        name="Test schema",
        fields=[{"name": "first_name", "type": "string"}],
        owner_user_id="user_1",
        created_at=None,
        updated_at=None,
        source=None,
        sample_count=None,
    )


def test_zero_credits_does_not_fall_back_to_base() -> None:
    # Proves the original bug: using `data.get(field) or BASE` refills credits when stored=0.
    from backend.firebaseDB import user_database

    data = {user_database.OPENAI_CREDITS_FIELD: 0}
    old_behavior = data.get(user_database.OPENAI_CREDITS_FIELD) or user_database.BASE_OPENAI_CREDITS
    assert old_behavior == user_database.BASE_OPENAI_CREDITS

    fixed_behavior = user_database._resolve_openai_credits_remaining(data)
    assert fixed_behavior == 0


def test_missing_field_falls_back_to_base() -> None:
    from backend.firebaseDB import user_database

    data = {}
    assert user_database._resolve_openai_credits_remaining(data) == user_database.BASE_OPENAI_CREDITS


def test_rename_charges_one_credit_without_schema(
    mocker,
    dummy_session_entry: dict,
    dummy_template_field: dict,
) -> None:
    from backend.main import app

    consume_mock = mocker.patch("backend.api.routes.ai.consume_openai_credits", return_value=(9, True))
    mocker.patch("backend.api.middleware.security.verify_token", return_value={"uid": "user_1", "email": "e", "name": "d"})
    mocker.patch(
        "backend.api.routes.ai.ensure_user",
        return_value=mocker.Mock(app_user_id="user_1", role="base", email="e", display_name="d"),
    )
    mocker.patch("backend.api.routes.ai._get_session_entry", return_value=dummy_session_entry)
    mocker.patch("backend.api.routes.ai.check_rate_limit", return_value=True)
    mocker.patch("backend.api.routes.ai.record_openai_rename_request", return_value=None)
    mocker.patch(
        "backend.api.routes.ai.run_openai_rename_on_pdf",
        return_value=({}, [{"name": "first_name", "originalName": "A1"}]),
    )
    mocker.patch("backend.api.routes.ai._update_session_entry", return_value=None)

    client = TestClient(app)
    resp = client.post(
        "/api/renames/ai",
        json={
            "sessionId": "sess_1",
            "templateFields": [dummy_template_field],
        },
        headers={"Authorization": "Bearer test"},
    )
    assert resp.status_code == 200, resp.text

    consume_mock.assert_called()
    assert consume_mock.call_args.kwargs.get("credits") == 1


def test_rename_charges_two_credits_with_schema(
    mocker,
    dummy_session_entry: dict,
    dummy_template_field: dict,
) -> None:
    from backend.main import app

    consume_mock = mocker.patch("backend.api.routes.ai.consume_openai_credits", return_value=(8, True))
    mocker.patch("backend.api.middleware.security.verify_token", return_value={"uid": "user_1", "email": "e", "name": "d"})
    mocker.patch(
        "backend.api.routes.ai.ensure_user",
        return_value=mocker.Mock(app_user_id="user_1", role="base", email="e", display_name="d"),
    )
    mocker.patch("backend.api.routes.ai._get_session_entry", return_value=dummy_session_entry)
    mocker.patch("backend.api.routes.ai.check_rate_limit", return_value=True)
    mocker.patch("backend.api.routes.ai.get_schema", return_value=_dummy_schema_record(schema_id="schema_1"))
    mocker.patch("backend.api.routes.ai.record_openai_rename_request", return_value=None)
    mocker.patch(
        "backend.api.routes.ai.run_openai_rename_on_pdf",
        return_value=({}, [{"name": "first_name", "originalName": "A1"}]),
    )
    mocker.patch("backend.api.routes.ai._update_session_entry", return_value=None)

    client = TestClient(app)
    resp = client.post(
        "/api/renames/ai",
        json={
            "sessionId": "sess_1",
            "schemaId": "schema_1",
            "templateFields": [dummy_template_field],
        },
        headers={"Authorization": "Bearer test"},
    )
    assert resp.status_code == 200, resp.text

    consume_mock.assert_called()
    assert consume_mock.call_args.kwargs.get("credits") == 2


def test_schema_mapping_charges_one_credit(
    mocker,
    dummy_session_entry: dict,
) -> None:
    from backend.main import app

    consume_mock = mocker.patch("backend.api.routes.ai.consume_openai_credits", return_value=(9, True))
    mocker.patch("backend.api.middleware.security.verify_token", return_value={"uid": "user_1", "email": "e", "name": "d"})
    mocker.patch(
        "backend.api.routes.ai.ensure_user",
        return_value=mocker.Mock(app_user_id="user_1", role="base", email="e", display_name="d"),
    )
    mocker.patch("backend.api.routes.ai._get_session_entry", return_value=dummy_session_entry)
    mocker.patch("backend.api.routes.ai.check_rate_limit", return_value=True)
    mocker.patch("backend.api.routes.ai.get_schema", return_value=_dummy_schema_record(schema_id="schema_1"))
    mocker.patch("backend.api.routes.ai.record_openai_request", return_value=None)
    mocker.patch(
        "backend.api.routes.ai.call_openai_schema_mapping_chunked",
        return_value={"mappings": [], "checkboxRules": [], "radioGroupSuggestions": [], "notes": ""},
    )
    mocker.patch("backend.api.routes.ai._update_session_entry", return_value=None)

    client = TestClient(app)
    resp = client.post(
        "/api/schema-mappings/ai",
        json={
            "schemaId": "schema_1",
            "templateFields": [
                {
                    "name": "A1",
                    "type": "text",
                    "page": 1,
                    "rect": {"x": 10, "y": 10, "width": 100, "height": 20},
                }
            ],
            "sessionId": "sess_1",
        },
        headers={"Authorization": "Bearer test"},
    )
    assert resp.status_code == 200, resp.text

    consume_mock.assert_called()
    assert consume_mock.call_args.kwargs.get("credits") == 1


def test_rename_with_schema_charges_four_credits_for_ten_pages(
    mocker,
    dummy_ten_page_session_entry: dict,
    dummy_template_field: dict,
) -> None:
    from backend.main import app

    consume_mock = mocker.patch("backend.api.routes.ai.consume_openai_credits", return_value=(6, True))
    mocker.patch("backend.api.middleware.security.verify_token", return_value={"uid": "user_1", "email": "e", "name": "d"})
    mocker.patch(
        "backend.api.routes.ai.ensure_user",
        return_value=mocker.Mock(app_user_id="user_1", role="base", email="e", display_name="d"),
    )
    mocker.patch("backend.api.routes.ai._get_session_entry", return_value=dummy_ten_page_session_entry)
    mocker.patch("backend.api.routes.ai.check_rate_limit", return_value=True)
    mocker.patch("backend.api.routes.ai.get_schema", return_value=_dummy_schema_record(schema_id="schema_1"))
    mocker.patch("backend.api.routes.ai.record_openai_rename_request", return_value=None)
    mocker.patch(
        "backend.api.routes.ai.run_openai_rename_on_pdf",
        return_value=({}, [{"name": "first_name", "originalName": "A1"}]),
    )
    mocker.patch("backend.api.routes.ai._update_session_entry", return_value=None)

    client = TestClient(app)
    resp = client.post(
        "/api/renames/ai",
        json={
            "sessionId": "sess_1",
            "schemaId": "schema_1",
            "templateFields": [dummy_template_field],
        },
        headers={"Authorization": "Bearer test"},
    )
    assert resp.status_code == 200, resp.text

    consume_mock.assert_called()
    assert consume_mock.call_args.kwargs.get("credits") == 4


def test_schema_mapping_charges_two_credits_for_ten_pages(
    mocker,
    dummy_ten_page_session_entry: dict,
) -> None:
    from backend.main import app

    consume_mock = mocker.patch("backend.api.routes.ai.consume_openai_credits", return_value=(8, True))
    mocker.patch("backend.api.middleware.security.verify_token", return_value={"uid": "user_1", "email": "e", "name": "d"})
    mocker.patch(
        "backend.api.routes.ai.ensure_user",
        return_value=mocker.Mock(app_user_id="user_1", role="base", email="e", display_name="d"),
    )
    mocker.patch("backend.api.routes.ai._get_session_entry", return_value=dummy_ten_page_session_entry)
    mocker.patch("backend.api.routes.ai.check_rate_limit", return_value=True)
    mocker.patch("backend.api.routes.ai.get_schema", return_value=_dummy_schema_record(schema_id="schema_1"))
    mocker.patch("backend.api.routes.ai.record_openai_request", return_value=None)
    mocker.patch(
        "backend.api.routes.ai.call_openai_schema_mapping_chunked",
        return_value={"mappings": [], "checkboxRules": [], "radioGroupSuggestions": [], "notes": ""},
    )
    mocker.patch("backend.api.routes.ai._update_session_entry", return_value=None)

    client = TestClient(app)
    resp = client.post(
        "/api/schema-mappings/ai",
        json={
            "schemaId": "schema_1",
            "templateFields": [
                {
                    "name": "A1",
                    "type": "text",
                    "page": 1,
                    "rect": {"x": 10, "y": 10, "width": 100, "height": 20},
                }
            ],
            "sessionId": "sess_1",
        },
        headers={"Authorization": "Bearer test"},
    )
    assert resp.status_code == 200, resp.text

    consume_mock.assert_called()
    assert consume_mock.call_args.kwargs.get("credits") == 2


# ---------------------------------------------------------------------------
# Edge-case tests for _resolve_openai_credits_remaining
# ---------------------------------------------------------------------------


def test_resolve_openai_credits_remaining_non_numeric_value_falls_back_to_base() -> None:
    """When the stored value for openai_credits_remaining is a non-numeric
    string (e.g. 'not-a-number'), int() raises ValueError and the function
    should fall back to BASE_OPENAI_CREDITS."""
    from backend.firebaseDB import user_database

    data = {user_database.OPENAI_CREDITS_FIELD: "not-a-number"}
    result = user_database._resolve_openai_credits_remaining(data)
    assert result == user_database.BASE_OPENAI_CREDITS


def test_resolve_openai_credits_remaining_negative_value_preserved() -> None:
    """When the stored value is a valid negative integer (e.g. -5), int()
    succeeds and the function should return the negative value as-is rather
    than falling back to the default. This tests that negative credits are
    not masked by the fallback logic."""
    from backend.firebaseDB import user_database

    data = {user_database.OPENAI_CREDITS_FIELD: -5}
    result = user_database._resolve_openai_credits_remaining(data)
    assert result == -5
