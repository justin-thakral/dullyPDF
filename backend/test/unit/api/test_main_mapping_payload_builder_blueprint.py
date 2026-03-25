def test_build_schema_mapping_payload_filters_hallucinations_and_alt_keys(app_main) -> None:
    schema_fields = [
        {"name": "first_name"},
        {"name": "consent"},
        {"name": "member_id"},
    ]
    template_tags = [
        {"tag": "A1"},
        {"tag": "A2", "type": "checkbox", "groupKey": "consent_group"},
    ]
    ai_response = {
        "mappings": [
            {"databaseField": "first_name", "pdfField": "A1", "confidence": 0.9, "reasoning": "good"},
            {"source": "consent", "targetField": "A2", "confidence": "0.8"},
            {"databaseField": "hallucinated", "pdfField": "A1"},
            {"databaseField": "first_name", "pdfField": "ZZZ"},
            "bad-entry",
        ],
        "template_rules": [
            {"targetField": "A1", "sources": ["first_name", "bad_src"]},
            {"targetField": "BAD_TAG", "sources": ["first_name"]},
            "bad",
        ],
        "textTransformRules": [
            {"targetField": "A1", "operation": "copy", "sources": ["first_name"]},
            {"targetField": "A2", "operation": "concat", "sources": ["first_name", "consent"], "separator": " | "},
            {"targetField": "A2", "operation": "not_allowed", "sources": ["first_name"]},
            {"targetField": "BAD_TAG", "operation": "copy", "sources": ["first_name"]},
        ],
        "checkbox_rules": [
            {"databaseField": "consent", "groupKey": "Consent Group"},
            {"databaseField": "consent", "groupKey": "unknown-group"},
            {"databaseField": "not_allowed", "groupKey": "consent_group"},
        ],
        "radio_group_suggestions": [
            {
                "suggested_type": "radio_group",
                "group_key": "consent_group",
                "group_label": "Consent",
                "source_field": "consent",
                "selection_reason": "yes_no",
                "suggested_fields": [
                    {"field_name": "A2", "option_key": "yes", "option_label": "Yes"},
                    {"field_name": "A3", "option_key": "no", "option_label": "No"},
                ],
                "confidence": 0.8,
            },
            {
                "suggested_type": "radio_group",
                "group_key": "missing",
                "group_label": "Missing",
                "suggested_fields": [
                    {"field_name": "A2", "option_key": "yes", "option_label": "Yes"},
                    {"field_name": "Z9", "option_key": "no", "option_label": "No"},
                ],
            },
        ],
        "patientIdentifierField": "member_id",
        "notes": "model-notes",
    }

    template_tags.append({"tag": "A3", "type": "checkbox", "groupKey": "consent_group"})
    payload = app_main._build_schema_mapping_payload(schema_fields, template_tags, ai_response)
    assert payload["success"] is True
    assert len(payload["mappings"]) == 2
    assert {entry["databaseField"] for entry in payload["mappings"]} == {"first_name", "consent"}
    assert {entry["originalPdfField"] for entry in payload["mappings"]} == {"A1", "A2"}
    assert payload["templateRules"] == [{"targetField": "A1", "sources": ["first_name"]}]
    assert payload["textTransformRules"] == [
        {"targetField": "A1", "operation": "copy", "sources": ["first_name"], "confidence": 0.6},
        {
            "targetField": "A2",
            "operation": "concat",
            "sources": ["first_name", "consent"],
            "confidence": 0.6,
            "separator": " | ",
        },
    ]
    assert payload["checkboxRules"] == [{"databaseField": "consent", "groupKey": "consent_group"}]
    assert payload["radioGroupSuggestions"] == [
        {
            "id": "consent_group_A2_A3",
            "suggestedType": "radio_group",
            "groupKey": "consent_group",
            "groupLabel": "Consent",
            "sourceField": "consent",
            "selectionReason": "yes_no",
            "suggestedFields": [
                {"fieldName": "A2", "optionKey": "yes", "optionLabel": "Yes"},
                {"fieldName": "A3", "optionKey": "no", "optionLabel": "No"},
            ],
            "confidence": 0.8,
        }
    ]
    assert payload["fillRules"]["version"] == 1
    assert payload["fillRules"]["textTransformRules"] == payload["textTransformRules"]
    assert payload["identifierKey"] == "member_id"
    assert payload["notes"] == "model-notes"


def test_build_schema_mapping_payload_clamps_confidence_and_defaults_notes(app_main) -> None:
    schema_fields = [{"name": "field_a"}, {"name": "field_b"}]
    template_tags = [{"tag": "A1"}, {"tag": "A2"}, {"tag": "A3"}]
    ai_response = {
        "mappings": [
            {"databaseField": "field_a", "pdfField": "A1", "confidence": 2.0},
            {"databaseField": "field_b", "pdfField": "A2", "confidence": -1},
            {"databaseField": "field_a", "pdfField": "A3", "confidence": "bad"},
        ]
    }
    payload = app_main._build_schema_mapping_payload(schema_fields, template_tags, ai_response)
    confidences = [entry["confidence"] for entry in payload["mappings"]]
    assert confidences == [1.0, 0.0, 0.6]
    assert payload["confidence"] == (1.0 + 0.0 + 0.6) / 3.0
    assert payload["notes"] == ""


def test_build_schema_mapping_payload_sanitizes_split_text_transform_rules(app_main) -> None:
    schema_fields = [{"name": "first_name"}, {"name": "last_name"}, {"name": "full_name"}]
    template_tags = [{"tag": "A1"}, {"tag": "A2"}]
    ai_response = {
        "mappings": [],
        "text_transform_rules": [
            {
                "targetField": "A1",
                "operation": "split_name_first_rest",
                "sources": ["full_name"],
                "part": "first",
                "confidence": 0.9,
            },
            {
                "targetField": "A2",
                "operation": "split_delimiter",
                "sources": ["full_name"],
                "delimiter": ",",
                "part": "last",
                "requires_review": "true",
                "confidence": "0.55",
            },
            {
                "targetField": "A2",
                "operation": "split_delimiter",
                "sources": ["full_name"],
                "delimiter": "",
                "part": "first",
            },
        ],
    }

    payload = app_main._build_schema_mapping_payload(schema_fields, template_tags, ai_response)
    assert payload["textTransformRules"] == [
        {
            "targetField": "A1",
            "operation": "split_name_first_rest",
            "sources": ["full_name"],
            "confidence": 0.9,
            "part": "first",
        },
        {
            "targetField": "A2",
            "operation": "split_delimiter",
            "sources": ["full_name"],
            "confidence": 0.55,
            "requiresReview": True,
            "delimiter": ",",
            "part": "last",
        },
    ]


def test_build_schema_mapping_payload_unmapped_calculations(app_main) -> None:
    schema_fields = [{"name": "one"}, {"name": "two"}]
    template_tags = [{"tag": "A"}, {"tag": "B"}]
    ai_response = {"mappings": [{"databaseField": "one", "pdfField": "A"}], "identifierKey": "bad"}
    payload = app_main._build_schema_mapping_payload(schema_fields, template_tags, ai_response)
    assert payload["unmappedDatabaseFields"] == ["two"]
    assert payload["unmappedPdfFields"] == ["B"]
    assert payload["identifierKey"] is None


# ---------------------------------------------------------------------------
# Edge-case: radio-group suggestions are normalized and filtered
# ---------------------------------------------------------------------------
def test_build_schema_mapping_payload_filters_invalid_radio_group_suggestions(app_main) -> None:
    schema_fields = [{"name": "marital_status"}]
    template_tags = [
        {"tag": "single_box", "type": "checkbox", "groupKey": "marital_status", "fieldId": "field-1"},
        {"tag": "married_box", "type": "checkbox", "groupKey": "marital_status", "fieldId": "field-2"},
    ]
    ai_response = {
        "mappings": [],
        "radioGroupSuggestions": [
            {
                "suggestedType": "radio_group",
                "groupKey": "marital_status",
                "groupLabel": "Marital Status",
                "sourceField": "marital_status",
                "selectionReason": "enum",
                "confidence": "0.55",
                "suggestedFields": [
                    {"fieldId": "field-1", "optionKey": "single", "optionLabel": "Single"},
                    {"fieldId": "field-2", "optionKey": "married", "optionLabel": "Married"},
                ],
            },
            {
                "suggestedType": "radio_group",
                "groupKey": "marital_status",
                "groupLabel": "Broken",
                "suggestedFields": [
                    {"fieldId": "field-1", "optionKey": "single", "optionLabel": "Single"},
                ],
            },
        ],
    }

    payload = app_main._build_schema_mapping_payload(schema_fields, template_tags, ai_response)

    assert payload["radioGroupSuggestions"] == [
        {
            "id": "marital_status_field_1_field_2",
            "suggestedType": "radio_group",
            "groupKey": "marital_status",
            "groupLabel": "Marital Status",
            "sourceField": "marital_status",
            "selectionReason": "enum",
            "confidence": 0.55,
            "suggestedFields": [
                {"fieldId": "field-1", "fieldName": "single_box", "optionKey": "single", "optionLabel": "Single"},
                {"fieldId": "field-2", "fieldName": "married_box", "optionKey": "married", "optionLabel": "Married"},
            ],
        }
    ]
