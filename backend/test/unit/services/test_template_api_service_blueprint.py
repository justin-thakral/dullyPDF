from __future__ import annotations

import base64
from pathlib import Path

import pytest

from backend.firebaseDB.template_database import TemplateRecord
from backend.services import template_api_service


def _template_record(*, metadata: dict | None = None) -> TemplateRecord:
    return TemplateRecord(
        id="tpl-1",
        pdf_bucket_path="gs://forms/patient-intake.pdf",
        template_bucket_path="gs://templates/patient-intake.json",
        metadata=metadata or {"name": "Patient Intake"},
        created_at="2024-01-01T00:00:00+00:00",
        updated_at="2024-01-01T00:00:00+00:00",
        name="Patient Intake",
    )


def test_build_template_api_snapshot_uses_saved_form_editor_snapshot_and_fill_rules(mocker) -> None:
    template = _template_record(
        metadata={
            "name": "Patient Intake",
            "fillRules": {
                "checkboxRules": [
                    {"databaseField": "consent_signed", "groupKey": "consent_group", "operation": "yes_no"}
                ],
                "textTransformRules": [
                    {"targetField": "full_name", "operation": "concat", "sources": ["first_name", "last_name"]}
                ],
                "radioGroups": [
                    {
                        "groupKey": "marital_status",
                        "options": [
                            {"optionKey": "single", "optionLabel": "Single"},
                            {"optionKey": "married", "optionLabel": "Married"},
                        ],
                    }
                ],
            },
        }
    )
    mocker.patch.object(
        template_api_service,
        "load_saved_form_editor_snapshot",
        return_value={
            "pageCount": 1,
            "pageSizes": {"1": {"width": 612, "height": 792}},
            "fields": [
                {"id": "field-1", "name": "full_name", "type": "text", "page": 1, "rect": {"x": 1, "y": 2, "width": 100, "height": 20}},
                {
                    "id": "field-2",
                    "name": "i_consent_group_yes",
                    "type": "checkbox",
                    "page": 1,
                    "rect": {"x": 10, "y": 20, "width": 12, "height": 12},
                    "groupKey": "consent_group",
                    "optionKey": "yes",
                    "optionLabel": "Yes",
                },
            ],
        },
    )
    mocker.patch.object(template_api_service, "now_iso", return_value="2024-02-01T00:00:00+00:00")

    snapshot = template_api_service.build_template_api_snapshot(template, export_mode="editable")

    assert snapshot["templateId"] == "tpl-1"
    assert snapshot["sourcePdfPath"] == "gs://forms/patient-intake.pdf"
    assert snapshot["defaultExportMode"] == "editable"
    assert snapshot["fields"][0]["rect"] == [1.0, 2.0, 101.0, 22.0]
    assert snapshot["checkboxRules"][0]["groupKey"] == "consent_group"
    assert snapshot["textTransformRules"][0]["targetField"] == "full_name"
    assert snapshot["radioGroups"][0]["groupKey"] == "marital_status"
    assert snapshot["publishedAt"] == "2024-02-01T00:00:00+00:00"


def test_build_template_api_snapshot_requires_editor_snapshot(mocker) -> None:
    mocker.patch.object(template_api_service, "load_saved_form_editor_snapshot", return_value=None)

    with pytest.raises(ValueError, match="editor snapshot"):
        template_api_service.build_template_api_snapshot(_template_record())


def test_template_api_secret_hash_round_trip_and_basic_auth_parse() -> None:
    secret = template_api_service.generate_template_api_secret()
    secret_hash = template_api_service.hash_template_api_secret(secret)
    authorization = "Basic " + base64.b64encode(f"{secret}:".encode("utf-8")).decode("ascii")

    assert secret.startswith(template_api_service.TEMPLATE_API_SECRET_PREFIX)
    assert template_api_service.verify_template_api_secret(secret, secret_hash) is True
    assert template_api_service.verify_template_api_secret("wrong-secret", secret_hash) is False
    assert template_api_service.parse_template_api_basic_secret(authorization) == secret


def test_build_template_api_schema_collects_scalar_checkbox_and_radio_groups() -> None:
    schema = template_api_service.build_template_api_schema(
        {
            "version": 1,
            "defaultExportMode": "flat",
            "fields": [
                {"name": "full_name", "type": "text", "page": 1, "rect": [1, 2, 3, 4]},
                {
                    "name": "i_consent_yes",
                    "type": "checkbox",
                    "page": 1,
                    "rect": [1, 2, 3, 4],
                    "groupKey": "consent_group",
                    "optionKey": "yes",
                    "optionLabel": "Yes",
                },
                {
                    "name": "i_consent_no",
                    "type": "checkbox",
                    "page": 1,
                    "rect": [1, 2, 3, 4],
                    "groupKey": "consent_group",
                    "optionKey": "no",
                    "optionLabel": "No",
                },
                {
                    "name": "radio_married",
                    "type": "radio",
                    "page": 1,
                    "rect": [1, 2, 3, 4],
                    "groupKey": "marital_status",
                    "optionKey": "married",
                    "optionLabel": "Married",
                },
            ],
            "checkboxRules": [
                {"databaseField": "consent_signed", "groupKey": "consent_group", "operation": "yes_no"}
            ],
            "radioGroups": [
                {
                    "groupKey": "marital_status",
                    "options": [
                        {"optionKey": "single", "optionLabel": "Single"},
                        {"optionKey": "married", "optionLabel": "Married"},
                    ],
                }
            ],
        }
    )

    assert schema["fields"] == [{"key": "full_name", "fieldName": "full_name", "type": "text", "page": 1}]
    assert schema["checkboxFields"] == []
    assert schema["checkboxGroups"] == [
        {
            "key": "consent_signed",
            "groupKey": "consent_group",
            "type": "checkbox_rule",
            "operation": "yes_no",
            "options": [
                {"optionKey": "yes", "optionLabel": "Yes", "fieldName": "i_consent_yes"},
                {"optionKey": "no", "optionLabel": "No", "fieldName": "i_consent_no"},
            ],
            "trueOption": None,
            "falseOption": None,
            "valueMap": None,
        }
    ]
    assert schema["radioGroups"] == [
        {
            "groupKey": "marital_status",
            "type": "radio",
            "options": [
                {"optionKey": "single", "optionLabel": "Single"},
                {"optionKey": "married", "optionLabel": "Married"},
            ],
        }
    ]
    assert schema["exampleData"]["full_name"] == "<full_name>"
    assert schema["exampleData"]["consent_signed"] is True
    assert schema["exampleData"]["marital_status"] == "single"


def test_build_template_api_schema_surfaces_standalone_checkbox_fields() -> None:
    schema = template_api_service.build_template_api_schema(
        {
            "version": 1,
            "defaultExportMode": "flat",
            "fields": [
                {"name": "agree_to_terms", "type": "checkbox", "page": 1, "rect": [1, 2, 3, 4]},
                {"name": "full_name", "type": "text", "page": 1, "rect": [1, 2, 3, 4]},
            ],
            "checkboxRules": [],
            "radioGroups": [],
        }
    )

    assert schema["checkboxFields"] == [
        {"key": "agree_to_terms", "fieldName": "agree_to_terms", "type": "checkbox", "page": 1}
    ]
    assert schema["exampleData"]["agree_to_terms"] is True


def test_resolve_template_api_request_data_validates_radio_checkbox_and_unknown_keys() -> None:
    snapshot = {
        "version": 1,
        "defaultExportMode": "flat",
        "fields": [
            {"name": "full_name", "type": "text", "page": 1, "rect": [1, 2, 3, 4]},
            {"name": "agree_to_terms", "type": "checkbox", "page": 1, "rect": [1, 2, 3, 4]},
            {
                "name": "radio_married",
                "type": "radio",
                "page": 1,
                "rect": [1, 2, 3, 4],
                "groupKey": "marital_status",
                "optionKey": "married",
                "optionLabel": "Married",
            },
            {
                "name": "radio_single",
                "type": "radio",
                "page": 1,
                "rect": [1, 2, 3, 4],
                "groupKey": "marital_status",
                "optionKey": "single",
                "optionLabel": "Single",
            },
            {
                "name": "i_consent_yes",
                "type": "checkbox",
                "page": 1,
                "rect": [1, 2, 3, 4],
                "groupKey": "consent_group",
                "optionKey": "yes",
                "optionLabel": "Yes",
            },
            {
                "name": "i_consent_no",
                "type": "checkbox",
                "page": 1,
                "rect": [1, 2, 3, 4],
                "groupKey": "consent_group",
                "optionKey": "no",
                "optionLabel": "No",
            },
        ],
        "checkboxRules": [
            {
                "databaseField": "consent_signed",
                "groupKey": "consent_group",
                "operation": "yes_no",
                "trueOption": "yes",
                "falseOption": "no",
            }
        ],
        "radioGroups": [
            {
                "groupKey": "marital_status",
                "options": [
                    {"optionKey": "single", "optionLabel": "Single"},
                    {"optionKey": "married", "optionLabel": "Married"},
                ],
            }
        ],
    }

    resolved = template_api_service.resolve_template_api_request_data(
        snapshot,
        {
            "full_name": "Ada Lovelace",
            "agree_to_terms": "yes",
            "consent_signed": "no",
            "marital_status": "Married",
            "ignored_key": "skip me",
        },
        strict=False,
    )

    assert resolved == {
        "full_name": "Ada Lovelace",
        "agree_to_terms": True,
        "consent_signed": False,
        "marital_status": "married",
    }

    with pytest.raises(template_api_service.HTTPException, match="Unknown API Fill keys"):
        template_api_service.resolve_template_api_request_data(
            snapshot,
            {"ignored_key": "skip me"},
            strict=True,
        )

    with pytest.raises(template_api_service.HTTPException, match="invalid option"):
        template_api_service.resolve_template_api_request_data(
            snapshot,
            {"marital_status": "widowed"},
            strict=False,
        )


def test_materialize_template_api_snapshot_delegates_to_fill_link_download_path(mocker, tmp_path: Path) -> None:
    output_path = tmp_path / "filled.pdf"
    cleanup_targets = [output_path]
    materialize_mock = mocker.patch.object(
        template_api_service,
        "materialize_fill_link_response_download",
        return_value=(output_path, cleanup_targets, "patient-intake.pdf"),
    )

    result = template_api_service.materialize_template_api_snapshot(
        {
            "sourcePdfPath": "gs://forms/patient-intake.pdf",
            "fields": [{"name": "full_name", "type": "text", "page": 1, "rect": [1, 2, 3, 4]}],
            "checkboxRules": [],
            "textTransformRules": [],
            "radioGroups": [],
            "defaultExportMode": "editable",
            "templateName": "Patient Intake",
        },
        data={"full_name": "Ada Lovelace"},
        export_mode=None,
        filename="patient-intake-final.pdf",
    )

    assert result == (output_path, cleanup_targets, "patient-intake.pdf")
    materialize_mock.assert_called_once_with(
        {
            "sourcePdfPath": "gs://forms/patient-intake.pdf",
            "fields": [{"name": "full_name", "type": "text", "page": 1, "rect": [1, 2, 3, 4]}],
            "checkboxRules": [],
            "textTransformRules": [],
            "radioGroups": [],
            "downloadMode": "editable",
            "filename": "patient-intake-final.pdf",
        },
        answers={"full_name": "Ada Lovelace"},
        export_mode=None,
    )
