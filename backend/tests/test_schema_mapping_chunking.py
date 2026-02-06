import unittest


class TestSchemaMappingChunking(unittest.TestCase):
    def test_split_template_tags_respects_max_payload_bytes(self) -> None:
        from backend.ai import schema_mapping as sm

        schema_fields = [{"name": "field_a", "type": "string"}]
        template_tags = []
        for idx in range(60):
            template_tags.append(
                {
                    "tag": f"T{idx}",
                    "type": "text",
                    "page": 1,
                    "rect": None,
                    "groupKey": None,
                    "optionKey": None,
                    "optionLabel": None,
                    "groupLabel": None,
                }
            )

        old_limit = sm.MAX_PAYLOAD_BYTES
        try:
            sm.MAX_PAYLOAD_BYTES = 450
            chunks = sm._split_template_tags(schema_fields, template_tags)
            self.assertGreater(len(chunks), 1)
            for chunk in chunks:
                self.assertLessEqual(sm._payload_size(chunk), sm.MAX_PAYLOAD_BYTES)
        finally:
            sm.MAX_PAYLOAD_BYTES = old_limit

