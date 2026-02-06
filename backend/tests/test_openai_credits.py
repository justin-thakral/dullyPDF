import unittest
from unittest.mock import Mock, patch


class TestOpenAiCreditsResolution(unittest.TestCase):
    def test_zero_credits_does_not_fall_back_to_base(self) -> None:
        # Proves the original bug: using `data.get(field) or BASE` refills credits when stored=0.
        from backend.firebaseDB import app_database

        data = {app_database.OPENAI_CREDITS_FIELD: 0}
        old_behavior = data.get(app_database.OPENAI_CREDITS_FIELD) or app_database.BASE_OPENAI_CREDITS
        self.assertEqual(old_behavior, app_database.BASE_OPENAI_CREDITS)

        fixed_behavior = app_database._resolve_openai_credits_remaining(data)
        self.assertEqual(fixed_behavior, 0)

    def test_missing_field_falls_back_to_base(self) -> None:
        from backend.firebaseDB import app_database

        data = {}
        self.assertEqual(app_database._resolve_openai_credits_remaining(data), app_database.BASE_OPENAI_CREDITS)


class TestOpenAiCreditsCharging(unittest.TestCase):
    def _dummy_session_entry(self) -> dict:
        return {
            "pdf_bytes": b"%PDF-1.4\n%fake\n",
            "fields": [],
            "source_pdf": "test.pdf",
            "result": {},
            "page_count": 1,
            "user_id": "user_1",
        }

    def _dummy_template_field(self) -> dict:
        return {
            "name": "A1",
            "type": "text",
            "page": 1,
            "rect": {"x": 10, "y": 10, "width": 100, "height": 20},
        }

    def _dummy_schema_record(self, schema_id: str = "schema_1"):
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

    def test_rename_charges_one_credit_without_schema(self) -> None:
        from backend.main import app

        consume_mock = Mock(return_value=(9, True))
        # Keep downstream work cheap; the point here is verifying credits charged.
        with (
            patch("backend.main._verify_token", return_value={"uid": "user_1", "email": "e", "name": "d"}),
            patch("backend.main.ensure_user", return_value=Mock(app_user_id="user_1", role="base", email="e", display_name="d")),
            patch("backend.main._get_session_entry", return_value=self._dummy_session_entry()),
            patch("backend.main.check_rate_limit", return_value=True),
            patch("backend.main.consume_openai_credits", consume_mock),
            patch("backend.main.record_openai_rename_request", return_value=None),
            patch("backend.main.run_openai_rename_on_pdf", return_value=({}, [{"name": "first_name", "originalName": "A1"}])),
            patch("backend.main._update_session_entry", return_value=None),
        ):
            from fastapi.testclient import TestClient

            client = TestClient(app)
            resp = client.post(
                "/api/renames/ai",
                json={
                    "sessionId": "sess_1",
                    "templateFields": [self._dummy_template_field()],
                },
                headers={"Authorization": "Bearer test"},
            )
            self.assertEqual(resp.status_code, 200, resp.text)

        consume_mock.assert_called()
        _, kwargs = consume_mock.call_args
        self.assertEqual(kwargs.get("credits"), 1)

    def test_rename_charges_two_credits_with_schema(self) -> None:
        from backend.main import app

        consume_mock = Mock(return_value=(8, True))
        with (
            patch("backend.main._verify_token", return_value={"uid": "user_1", "email": "e", "name": "d"}),
            patch("backend.main.ensure_user", return_value=Mock(app_user_id="user_1", role="base", email="e", display_name="d")),
            patch("backend.main._get_session_entry", return_value=self._dummy_session_entry()),
            patch("backend.main.check_rate_limit", return_value=True),
            patch("backend.main.get_schema", return_value=self._dummy_schema_record(schema_id="schema_1")),
            patch("backend.main.consume_openai_credits", consume_mock),
            patch("backend.main.record_openai_rename_request", return_value=None),
            patch("backend.main.run_openai_rename_on_pdf", return_value=({}, [{"name": "first_name", "originalName": "A1"}])),
            patch("backend.main._update_session_entry", return_value=None),
        ):
            from fastapi.testclient import TestClient

            client = TestClient(app)
            resp = client.post(
                "/api/renames/ai",
                json={
                    "sessionId": "sess_1",
                    "schemaId": "schema_1",
                    "templateFields": [self._dummy_template_field()],
                },
                headers={"Authorization": "Bearer test"},
            )
            self.assertEqual(resp.status_code, 200, resp.text)

        consume_mock.assert_called()
        _, kwargs = consume_mock.call_args
        self.assertEqual(kwargs.get("credits"), 2)

    def test_schema_mapping_charges_one_credit(self) -> None:
        from backend.main import app

        consume_mock = Mock(return_value=(9, True))
        with (
            patch("backend.main._verify_token", return_value={"uid": "user_1", "email": "e", "name": "d"}),
            patch("backend.main.ensure_user", return_value=Mock(app_user_id="user_1", role="base", email="e", display_name="d")),
            patch("backend.main._get_session_entry", return_value=self._dummy_session_entry()),
            patch("backend.main.check_rate_limit", return_value=True),
            patch("backend.main.get_schema", return_value=self._dummy_schema_record(schema_id="schema_1")),
            patch("backend.main.consume_openai_credits", consume_mock),
            patch("backend.main.record_openai_request", return_value=None),
            patch("backend.main.call_openai_schema_mapping_chunked", return_value={"mappings": [], "checkboxRules": [], "checkboxHints": [], "notes": ""}),
            patch("backend.main._update_session_entry", return_value=None),
        ):
            from fastapi.testclient import TestClient

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
            self.assertEqual(resp.status_code, 200, resp.text)

        consume_mock.assert_called()
        _, kwargs = consume_mock.call_args
        self.assertEqual(kwargs.get("credits"), 1)
