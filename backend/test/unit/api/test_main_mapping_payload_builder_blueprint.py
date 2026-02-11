def test_build_schema_mapping_payload_filters_hallucinations_and_alt_keys(app_main) -> None:
    schema_fields = [
        {"name": "first_name"},
        {"name": "consent"},
        {"name": "member_id"},
    ]
    template_tags = [
        {"tag": "A1"},
        {"tag": "A2", "groupKey": "consent_group"},
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
        "checkbox_rules": [
            {"databaseField": "consent", "groupKey": "Consent Group"},
            {"databaseField": "consent", "groupKey": "unknown-group"},
            {"databaseField": "not_allowed", "groupKey": "consent_group"},
        ],
        "checkbox_hints": [
            {"databaseField": "consent", "groupKey": "CONSENT_GROUP", "direct_boolean_possible": "yes", "operation": "enum"},
            {"databaseField": "consent", "groupKey": "missing"},
            {"databaseField": "bad", "groupKey": "consent_group"},
        ],
        "patientIdentifierField": "member_id",
        "notes": "model-notes",
    }

    payload = app_main._build_schema_mapping_payload(schema_fields, template_tags, ai_response)
    assert payload["success"] is True
    assert len(payload["mappings"]) == 2
    assert {entry["databaseField"] for entry in payload["mappings"]} == {"first_name", "consent"}
    assert {entry["originalPdfField"] for entry in payload["mappings"]} == {"A1", "A2"}
    assert payload["templateRules"] == [{"targetField": "A1", "sources": ["first_name"]}]
    assert payload["checkboxRules"] == [{"databaseField": "consent", "groupKey": "consent_group"}]
    assert payload["checkboxHints"] == [
        {
            "databaseField": "consent",
            "groupKey": "consent_group",
            "directBooleanPossible": True,
            "operation": "enum",
        }
    ]
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


def test_build_schema_mapping_payload_unmapped_calculations(app_main) -> None:
    schema_fields = [{"name": "one"}, {"name": "two"}]
    template_tags = [{"tag": "A"}, {"tag": "B"}]
    ai_response = {"mappings": [{"databaseField": "one", "pdfField": "A"}], "identifierKey": "bad"}
    payload = app_main._build_schema_mapping_payload(schema_fields, template_tags, ai_response)
    assert payload["unmappedDatabaseFields"] == ["two"]
    assert payload["unmappedPdfFields"] == ["B"]
    assert payload["identifierKey"] is None


# ---------------------------------------------------------------------------
# Edge-case: _coerce_hint_bool with False, None, and "no"
# ---------------------------------------------------------------------------
# The internal helper converts various representations to bool or None.
# Verify the specific edge values: False (bool), None (pass-through), "no"
# (string falsy).
def test_coerce_hint_bool_edge_values(app_main) -> None:
    # _coerce_hint_bool is defined inside build_schema_mapping_payload, so
    # we exercise it indirectly through the mapping builder with checkbox_hints
    # that carry the directBooleanPossible key using the target values.
    schema_fields = [{"name": "consent"}]
    template_tags = [{"tag": "A1", "groupKey": "consent_group"}]

    # directBooleanPossible=False -> bool False
    ai_response_false = {
        "mappings": [],
        "checkbox_hints": [
            {"databaseField": "consent", "groupKey": "consent_group", "direct_boolean_possible": False},
        ],
    }
    payload_false = app_main._build_schema_mapping_payload(schema_fields, template_tags, ai_response_false)
    assert len(payload_false["checkboxHints"]) == 1
    assert payload_false["checkboxHints"][0]["directBooleanPossible"] is False

    # directBooleanPossible=None -> key should be absent (None is returned)
    ai_response_none = {
        "mappings": [],
        "checkbox_hints": [
            {"databaseField": "consent", "groupKey": "consent_group", "direct_boolean_possible": None},
        ],
    }
    payload_none = app_main._build_schema_mapping_payload(schema_fields, template_tags, ai_response_none)
    assert len(payload_none["checkboxHints"]) == 1
    assert "directBooleanPossible" not in payload_none["checkboxHints"][0]

    # directBooleanPossible="no" -> bool False
    ai_response_no = {
        "mappings": [],
        "checkbox_hints": [
            {"databaseField": "consent", "groupKey": "consent_group", "direct_boolean_possible": "no"},
        ],
    }
    payload_no = app_main._build_schema_mapping_payload(schema_fields, template_tags, ai_response_no)
    assert len(payload_no["checkboxHints"]) == 1
    assert payload_no["checkboxHints"][0]["directBooleanPossible"] is False
