from backend.firebaseDB.template_database import TemplateRecord
from backend.services.fill_link_download_service import (
    apply_fill_link_answers_to_fields,
    build_fill_link_download_payload,
    build_template_fill_link_download_snapshot,
)


def _template_record() -> TemplateRecord:
    return TemplateRecord(
        id="tpl-1",
        pdf_bucket_path="gs://forms/template.pdf",
        template_bucket_path="gs://templates/template.json",
        metadata={
            "name": "Admissions Form",
            "fillRules": {
                "checkboxRules": [
                    {
                        "databaseField": "consent",
                        "groupKey": "consent_group",
                        "operation": "yes_no",
                        "trueOption": "yes",
                        "falseOption": "no",
                    }
                ],
                "textTransformRules": [
                    {
                        "targetField": "full_name",
                        "operation": "concat",
                        "sources": ["first_name", "last_name"],
                        "separator": " ",
                    }
                ],
            },
        },
        created_at="2024-01-01T00:00:00+00:00",
        updated_at="2024-01-01T00:00:00+00:00",
        name="Admissions Form",
    )


def test_build_template_fill_link_download_snapshot_uses_saved_form_fill_rules() -> None:
    snapshot = build_template_fill_link_download_snapshot(
        template=_template_record(),
        fields=[
            {"name": "first_name", "type": "text", "page": 1, "rect": {"x": 1, "y": 2, "width": 3, "height": 4}},
            {"name": "last_name", "type": "text", "page": 1, "rect": {"x": 5, "y": 6, "width": 7, "height": 8}},
        ],
    )

    assert snapshot["version"] == 1
    assert snapshot["sourcePdfPath"] == "gs://forms/template.pdf"
    assert snapshot["filename"] == "Admissions_Form-response.pdf"
    assert snapshot["downloadMode"] == "flat"
    assert snapshot["checkboxRules"][0]["groupKey"] == "consent_group"
    assert snapshot["textTransformRules"][0]["targetField"] == "full_name"


def test_apply_fill_link_answers_to_fields_sets_text_transform_and_checkbox_values() -> None:
    fields = apply_fill_link_answers_to_fields(
        {
            "fields": [
                {"id": "field-1", "name": "full_name", "type": "text", "page": 1, "rect": [1, 2, 4, 6]},
                {
                    "id": "field-2",
                    "name": "i_consent_group_yes",
                    "type": "checkbox",
                    "page": 1,
                    "rect": [1, 2, 4, 6],
                    "groupKey": "consent_group",
                    "optionKey": "yes",
                    "optionLabel": "Yes",
                },
                {
                    "id": "field-3",
                    "name": "i_consent_group_no",
                    "type": "checkbox",
                    "page": 1,
                    "rect": [1, 2, 4, 6],
                    "groupKey": "consent_group",
                    "optionKey": "no",
                    "optionLabel": "No",
                },
            ],
            "checkboxRules": [
                {
                    "databaseField": "consent",
                    "groupKey": "consent_group",
                    "operation": "yes_no",
                    "trueOption": "yes",
                    "falseOption": "no",
                }
            ],
            "textTransformRules": [
                {
                    "targetField": "full_name",
                    "operation": "concat",
                    "sources": ["first_name", "last_name"],
                    "separator": " ",
                }
            ],
        },
        {
            "first_name": "Ada",
            "last_name": "Lovelace",
            "consent": "yes",
        },
    )

    by_name = {str(field.get("name")): field for field in fields}
    assert by_name["full_name"]["value"] == "Ada Lovelace"
    assert by_name["i_consent_group_yes"]["value"] is True
    assert by_name["i_consent_group_no"]["value"] is False


def test_apply_fill_link_answers_to_fields_sets_direct_checkbox_and_radio_group_values() -> None:
    fields = apply_fill_link_answers_to_fields(
        {
            "fields": [
                {"id": "field-1", "name": "agree_to_terms", "type": "checkbox", "page": 1, "rect": [1, 2, 4, 6]},
                {
                    "id": "field-2",
                    "name": "marital_single",
                    "type": "checkbox",
                    "page": 1,
                    "rect": [1, 2, 4, 6],
                    "groupKey": "marital_status",
                    "optionKey": "single",
                    "optionLabel": "Single",
                },
                {
                    "id": "field-3",
                    "name": "marital_married",
                    "type": "checkbox",
                    "page": 1,
                    "rect": [1, 2, 4, 6],
                    "groupKey": "marital_status",
                    "optionKey": "married",
                    "optionLabel": "Married",
                },
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
        {
            "agree_to_terms": True,
            "marital_status": "married",
        },
    )

    by_name = {str(field.get("name")): field for field in fields}
    assert by_name["agree_to_terms"]["value"] is True
    assert by_name["marital_single"]["value"] is False
    assert by_name["marital_married"]["value"] is True


def test_apply_fill_link_answers_to_fields_sets_implicit_checkbox_group_values_without_rules() -> None:
    fields = apply_fill_link_answers_to_fields(
        {
            "fields": [
                {
                    "id": "field-1",
                    "name": "consent_yes",
                    "type": "checkbox",
                    "page": 1,
                    "rect": [1, 2, 4, 6],
                    "groupKey": "consent_group",
                    "optionKey": "yes",
                    "optionLabel": "Yes",
                },
                {
                    "id": "field-2",
                    "name": "consent_no",
                    "type": "checkbox",
                    "page": 1,
                    "rect": [1, 2, 4, 6],
                    "groupKey": "consent_group",
                    "optionKey": "no",
                    "optionLabel": "No",
                },
            ],
            "checkboxRules": [],
        },
        {
            "consent_group": ["yes"],
        },
    )

    by_name = {str(field.get("name")): field for field in fields}
    assert by_name["consent_yes"]["value"] is True
    assert by_name["consent_no"]["value"] is False


def test_build_fill_link_download_payload_returns_public_download_path() -> None:
    payload = build_fill_link_download_payload(
        type(
            "Record",
            (),
            {
                "respondent_pdf_download_enabled": True,
                "respondent_pdf_snapshot": {"filename": "admissions-response.pdf"},
                "template_name": "Admissions Form",
                "title": "Admissions",
            },
        )(),
        token="token-1",
        response_id="resp-1",
    )

    assert payload == {
        "enabled": True,
        "responseId": "resp-1",
        "downloadPath": "/api/fill-links/public/token-1/responses/resp-1/download",
        "filename": "admissions-response.pdf",
        "mode": "flat",
    }
