import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI

from .combinedSrc.config import get_logger


logger = get_logger(__name__)

MAX_AI_DB_FIELDS = int(os.getenv("MAX_AI_DB_FIELDS", "500"))
MAX_AI_PDF_FIELDS = int(os.getenv("MAX_AI_PDF_FIELDS", "1500"))
OPENAI_MODEL = os.getenv("OPENAI_FIELD_MAPPING_MODEL", "gpt-5-nano")

ALLOWED_TEMPLATE_OPERATIONS = {
    "copy",
    "coalesce",
    "split",
    "template",
    "join",
    "concat",
    "literal",
}


@dataclass
class MappingResult:
    success: bool
    mappings: List[Dict[str, Any]]
    template_rules: List[Dict[str, Any]]
    identifier_key: Optional[str]
    notes: str
    unmapped_database_fields: List[str]
    unmapped_pdf_fields: List[str]
    confidence: float
    total_mappings: int
    error: Optional[str] = None
    status_code: Optional[int] = None


class FieldMappingService:
    def __init__(self) -> None:
        self._openai: Optional[OpenAI] = None

    def _get_client(self) -> OpenAI:
        if self._openai:
            return self._openai
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            err = RuntimeError("OpenAI API key not configured. Set OPENAI_API_KEY.")
            setattr(err, "status_code", 503)
            raise err
        self._openai = OpenAI(api_key=key)
        return self._openai

    def map_fields(self, database_fields: List[str], pdf_form_fields: List[Dict[str, Any]]) -> MappingResult:
        try:
            if len(database_fields) > MAX_AI_DB_FIELDS:
                raise ValueError(f"Too many database fields for AI mapping ({len(database_fields)}).")
            if len(pdf_form_fields) > MAX_AI_PDF_FIELDS:
                raise ValueError(f"Too many PDF fields for AI mapping ({len(pdf_form_fields)}).")

            exact_matches, duplicate_matches, db_for_ai, pdf_for_ai = self._precompute_matches(
                database_fields, pdf_form_fields
            )

            logger.debug(
                "Pre-AI mapping summary: exact=%s duplicate=%s db_for_ai=%s pdf_for_ai=%s",
                len(exact_matches),
                len(duplicate_matches),
                len(db_for_ai),
                len(pdf_for_ai),
            )

            mapping_request = self._prepare_mapping_request(db_for_ai, pdf_for_ai)
            ai_response = self._call_openai(mapping_request)
            processed = self._process_mapping_response(ai_response, db_for_ai, pdf_for_ai)

            merged_mappings = exact_matches + duplicate_matches + processed["mappings"]
            unmapped_db = [f for f in processed["unmapped"]["database"] if f not in {m["databaseField"] for m in duplicate_matches}]
            unmapped_pdf = [f for f in processed["unmapped"]["pdf"] if f not in {m["pdfField"] for m in duplicate_matches}]

            return MappingResult(
                success=True,
                mappings=merged_mappings,
                template_rules=processed["templateRules"],
                identifier_key=processed["identifierKey"],
                notes=processed.get("aiNotes", ""),
                unmapped_database_fields=unmapped_db,
                unmapped_pdf_fields=unmapped_pdf,
                confidence=processed["overallConfidence"],
                total_mappings=len(merged_mappings),
            )
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            logger.error("Field mapping failed: %s", exc)
            return MappingResult(
                success=False,
                mappings=[],
                template_rules=[],
                identifier_key=None,
                notes="",
                unmapped_database_fields=database_fields,
                unmapped_pdf_fields=[f.get("name", "") for f in pdf_form_fields],
                confidence=0.0,
                total_mappings=0,
                error=str(exc),
                status_code=status_code,
            )

    def _precompute_matches(
        self,
        database_fields: List[str],
        pdf_form_fields: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str], List[Dict[str, Any]]]:
        exact_matches: List[Dict[str, Any]] = []
        pdf_lookup = {str(f.get("name", "")).lower(): f for f in pdf_form_fields}

        matched_db_indices = set()
        matched_pdf_names = set()
        for idx, db_field in enumerate(database_fields):
            key = str(db_field).lower()
            if key in pdf_lookup:
                pdf_field = pdf_lookup[key]
                exact_matches.append({
                    "databaseField": db_field,
                    "pdfField": pdf_field.get("name") or db_field,
                    "confidence": 1.0,
                    "reasoning": "Exact case-insensitive match between database and PDF field names",
                })
                matched_db_indices.add(idx)
                matched_pdf_names.add(pdf_field.get("name"))

        db_for_ai = [f for idx, f in enumerate(database_fields) if idx not in matched_db_indices]
        pdf_for_ai = [f for f in pdf_form_fields if f.get("name") not in matched_pdf_names]

        duplicate_matches: List[Dict[str, Any]] = []
        duplicate_pdf_names = set()
        for db_field in db_for_ai:
            for pdf_field in pdf_for_ai:
                pdf_name = pdf_field.get("name")
                if not pdf_name or pdf_name in duplicate_pdf_names:
                    continue
                if self._is_duplicate_name(db_field, pdf_name):
                    duplicate_matches.append({
                        "databaseField": db_field,
                        "pdfField": pdf_name,
                        "confidence": 0.99,
                        "reasoning": "PDF field duplicates database field name with suffix/truncation",
                    })
                    duplicate_pdf_names.add(pdf_name)

        pdf_for_ai = [f for f in pdf_for_ai if f.get("name") not in duplicate_pdf_names]
        return exact_matches, duplicate_matches, db_for_ai, pdf_for_ai

    def _is_duplicate_name(self, db_field: str, pdf_field: str) -> bool:
        if not db_field or not pdf_field:
            return False
        db_raw = str(db_field)
        pdf_raw = str(pdf_field)
        db_lower = db_raw.lower()
        pdf_lower = pdf_raw.lower()
        if db_lower == pdf_lower:
            return False
        db_trimmed = re.sub(r"_+$", "", db_lower)
        pdf_trimmed = re.sub(r"_+$", "", pdf_lower)
        if pdf_trimmed == db_trimmed:
            return True
        if pdf_trimmed.startswith(f"{db_trimmed}_"):
            return True
        db_compact = re.sub(r"[^a-z0-9]", "", db_lower)
        pdf_compact = re.sub(r"[^a-z0-9]", "", pdf_lower)
        if not db_compact or not pdf_compact:
            return False
        if pdf_compact == db_compact:
            return True
        if pdf_compact.startswith(db_compact) and len(pdf_compact) - len(db_compact) <= max(2, int(len(db_compact) * 0.1)):
            return True
        if db_compact.startswith(pdf_compact) and len(db_compact) - len(pdf_compact) <= max(2, int(len(db_compact) * 0.1)):
            return True
        return False

    def _prepare_mapping_request(self, database_fields: List[str], pdf_form_fields: List[Dict[str, Any]]) -> Dict[str, Any]:
        pdf_descriptions = []
        for field in pdf_form_fields:
            pdf_descriptions.append({
                "name": field.get("name"),
                "type": field.get("type", "text"),
                "context": field.get("context", ""),
                "coordinates": field.get("coordinates"),
                "confidence": field.get("confidence", 0),
            })
        return {
            "databaseFields": database_fields,
            "pdfFields": pdf_descriptions,
            "totalDatabaseFields": len(database_fields),
            "totalPdfFields": len(pdf_descriptions),
        }

    def _call_openai(self, mapping_request: Dict[str, Any]) -> Dict[str, Any]:
        system_prompt = self._create_system_prompt()
        user_prompt = self._create_user_prompt(mapping_request)

        base_req = {
            "model": OPENAI_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        json_req = {**base_req, "response_format": {"type": "json_object"}}

        client = self._get_client()
        try:
            response = client.chat.completions.create(**json_req)
            content = response.choices[0].message.content or "{}"
            return self._parse_json(content)
        except Exception as exc:
            msg = str(getattr(exc, "message", exc))
            param = getattr(exc, "param", None)
            if param == "response_format" or "response_format" in msg:
                response = client.chat.completions.create(**base_req)
                content = response.choices[0].message.content or "{}"
                return self._parse_json(content)
            if param == "temperature" or "temperature" in msg:
                response = client.chat.completions.create(**base_req)
                content = response.choices[0].message.content or "{}"
                return self._parse_json(content)
            raise

    def _parse_json(self, content: str) -> Dict[str, Any]:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", content)
            if match:
                return json.loads(match.group(0))
            return {"mappings": [], "notes": "Non-JSON response received"}

    def _process_mapping_response(
        self,
        ai_response: Dict[str, Any],
        database_fields: List[str],
        pdf_fields: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        valid_mappings: List[Dict[str, Any]] = []
        unmapped_db = list(database_fields)
        unmapped_pdf = [f.get("name") for f in pdf_fields if f.get("name")]

        for mapping in ai_response.get("mappings", []) or []:
            if not self._is_valid_mapping(mapping, database_fields, pdf_fields):
                continue
            record = {
                "databaseField": mapping["databaseField"],
                "pdfField": mapping["pdfField"],
                "confidence": min(max(mapping.get("confidence", 0.5), 0), 1),
                "reasoning": mapping.get("reasoning", "AI suggested mapping"),
                "id": re.sub(r"[^a-zA-Z0-9_]", "_", f"{mapping['databaseField']}_to_{mapping['pdfField']}"),
            }
            valid_mappings.append(record)
            if mapping["databaseField"] in unmapped_db:
                unmapped_db.remove(mapping["databaseField"])
            if mapping["pdfField"] in unmapped_pdf:
                unmapped_pdf.remove(mapping["pdfField"])

        overall_confidence = self._calculate_overall_confidence(valid_mappings, database_fields, pdf_fields)
        template_rules = self._normalize_template_rules(ai_response, database_fields, pdf_fields)
        identifier_key = self._pick_identifier_key(ai_response, database_fields)

        return {
            "mappings": valid_mappings,
            "unmapped": {"database": unmapped_db, "pdf": unmapped_pdf},
            "overallConfidence": overall_confidence,
            "aiNotes": ai_response.get("notes", ""),
            "identifierKey": identifier_key,
            "templateRules": template_rules,
        }

    def _is_valid_mapping(self, mapping: Dict[str, Any], database_fields: List[str], pdf_fields: List[Dict[str, Any]]) -> bool:
        if not mapping.get("databaseField") or not mapping.get("pdfField"):
            return False
        if mapping["databaseField"] not in database_fields:
            return False
        if not any(f.get("name") == mapping["pdfField"] for f in pdf_fields):
            return False
        confidence = mapping.get("confidence")
        return isinstance(confidence, (int, float)) and 0.6 <= confidence <= 1.0

    def _calculate_overall_confidence(
        self,
        mappings: List[Dict[str, Any]],
        database_fields: List[str],
        pdf_fields: List[Dict[str, Any]],
    ) -> float:
        if not mappings:
            return 0.0
        coverage_score = len(mappings) / max(len(database_fields), len(pdf_fields))
        avg_confidence = sum(m["confidence"] for m in mappings) / len(mappings)
        return round((avg_confidence * 0.7 + coverage_score * 0.3), 2)

    def _normalize_template_rules(
        self,
        ai_response: Dict[str, Any],
        database_fields: List[str],
        pdf_fields: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        raw_rules = (
            ai_response.get("templateRules")
            or ai_response.get("template_rules")
            or ai_response.get("derivedMappings")
            or []
        )
        if not isinstance(raw_rules, list):
            return []

        db_lookup = {self._canonical_key(field): field for field in database_fields}
        pdf_lookup = {self._canonical_key(field.get("name", "")): field.get("name") for field in pdf_fields}

        sanitized = []
        for raw in raw_rules:
            try:
                target_raw = self._extract_rule_string(raw.get("targetField") or raw.get("pdfField") or raw.get("target") or raw.get("name"))
                if not target_raw:
                    continue
                canonical_target = pdf_lookup.get(self._canonical_key(target_raw))
                if not canonical_target:
                    continue
                operation = self._extract_rule_string(raw.get("operation") or raw.get("op") or raw.get("type")).lower()
                if operation not in ALLOWED_TEMPLATE_OPERATIONS:
                    continue
                sources = self._extract_sources(raw)
                normalized_sources = []
                for src in sources:
                    key = self._canonical_key(src)
                    if key in db_lookup:
                        normalized_sources.append(db_lookup[key])
                    elif key in pdf_lookup:
                        normalized_sources.append(pdf_lookup[key])
                if not normalized_sources:
                    continue

                options = self._normalize_template_options(operation, raw, normalized_sources)
                if options is None:
                    continue

                sanitized.append({
                    "target": canonical_target,
                    "operation": operation,
                    "sources": list(dict.fromkeys(normalized_sources))[:6],
                    "options": options,
                    "description": self._extract_rule_string(raw.get("description") or raw.get("reasoning") or raw.get("notes")),
                    "confidence": self._extract_confidence_value(raw.get("confidence") or raw.get("score")),
                })
            except Exception as exc:
                logger.debug("Skipping invalid template rule: %s", exc)
        return sanitized

    def _extract_sources(self, rule: Dict[str, Any]) -> List[str]:
        candidates = (
            rule.get("sources")
            or rule.get("sourceFields")
            or rule.get("fields")
            or rule.get("inputs")
            or rule.get("from")
            or ([rule.get("source")] if rule.get("source") else [])
        )
        if not isinstance(candidates, list):
            candidates = []
        result = []
        for entry in candidates:
            if isinstance(entry, str) and entry.strip():
                result.append(entry.strip())
            elif isinstance(entry, dict):
                val = self._extract_rule_string(entry.get("field") or entry.get("name") or entry.get("source") or entry.get("column"))
                if val:
                    result.append(val)
        return list(dict.fromkeys(result))[:6]

    def _normalize_template_options(self, operation: str, raw: Dict[str, Any], sources: List[str]) -> Optional[Dict[str, Any]]:
        options = dict(raw.get("options") or {})

        def merge(key: str) -> None:
            if key not in options and key in raw:
                options[key] = raw[key]

        if operation in {"copy", "coalesce"}:
            return {}
        if operation == "split":
            merge("delimiter")
            merge("index")
            merge("position")
            merge("trim")
            merge("fallback")
            delimiter = self._sanitize_delimiter(options.get("delimiter"))
            index = self._parse_index_option(options.get("index") or options.get("position") or options.get("take"))
            trim = self._parse_boolean_option(options.get("trim"), True)
            fallback = self._extract_rule_string(options.get("fallback") or options.get("default") or options.get("fallbackValue"))
            return {
                "delimiter": delimiter,
                "index": index,
                "trim": trim,
                "fallback": fallback or None,
            }
        if operation in {"join", "concat"}:
            merge("separator")
            merge("trim")
            merge("allowEmpty")
            separator = self._sanitize_separator(options.get("separator"))
            trim = self._parse_boolean_option(options.get("trim"), True)
            allow_empty = self._parse_boolean_option(options.get("allowEmpty"), False)
            return {
                "separator": separator,
                "trim": trim,
                "allowEmpty": allow_empty,
            }
        if operation == "template":
            merge("template")
            merge("trim")
            merge("collapseWhitespace")
            template = self._sanitize_template(options.get("template"))
            if not template:
                return None
            trim = self._parse_boolean_option(options.get("trim"), True)
            collapse = self._parse_boolean_option(options.get("collapseWhitespace"), False)
            return {
                "template": template,
                "trim": trim,
                "collapseWhitespace": collapse,
            }
        if operation == "literal":
            merge("value")
            if "value" not in options:
                return None
            return {"value": self._extract_rule_string(options.get("value"))}
        return {}

    def _sanitize_delimiter(self, value: Any) -> str:
        raw = self._extract_rule_string(value)
        if not raw:
            return " "
        if raw in {"\\s", "\\s+", "\\s*"}:
            return "\\s+"
        return raw[:10]

    def _sanitize_separator(self, value: Any) -> str:
        raw = self._extract_rule_string(value)
        return (raw or " ")[:10]

    def _sanitize_template(self, value: Any) -> str:
        raw = self._extract_rule_string(value)
        if not raw:
            return ""
        if len(raw) > 400:
            raw = raw[:400]
        valid = True
        for match in re.findall(r"\{\{([^}]+)\}\}", raw):
            cleaned = match.strip()
            if not re.match(r"^[a-zA-Z0-9_]+$", cleaned):
                valid = False
        return raw if valid else ""

    def _parse_index_option(self, value: Any) -> int:
        if value is None:
            return 0
        if isinstance(value, str):
            lower = value.strip().lower()
            if lower == "first":
                return 0
            if lower == "last":
                return -1
            try:
                return int(float(value))
            except ValueError:
                return 0
        if isinstance(value, (int, float)):
            return int(value)
        return 0

    def _parse_boolean_option(self, value: Any, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lower = value.strip().lower()
            if lower in {"false", "0", "no", "off"}:
                return False
            if lower in {"true", "1", "yes", "on"}:
                return True
        return default

    def _extract_rule_string(self, value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (int, float, bool)):
            return str(value).strip()
        return ""

    def _extract_confidence_value(self, value: Any) -> Optional[float]:
        try:
            num = float(value)
        except (TypeError, ValueError):
            return None
        if num > 1:
            num = num / 100
        return max(0, min(1, round(num, 3)))

    def _canonical_key(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", str(value or "").lower())

    def _pick_identifier_key(self, ai_response: Dict[str, Any], database_fields: List[str]) -> Optional[str]:
        candidate = str(ai_response.get("identifierKey") or ai_response.get("patientIdentifierField") or "").strip()
        if candidate and candidate in database_fields:
            return candidate
        lowered = {f.lower(): f for f in database_fields}
        for pref in ["mrn", "patient_id", "enterprise_patient_id", "external_mrn", "id"]:
            if pref in lowered:
                return lowered[pref]
        for field in database_fields:
            if "mrn" in field.lower():
                return field
        for field in database_fields:
            if field.lower().endswith("_id") or field.lower() == "id":
                return field
        return database_fields[0] if database_fields else None

    def _create_system_prompt(self) -> str:
        return (
            "You are an expert database field mapping AI that specializes in normalizing field names between "
            "database schemas and PDF form fields.\n\n"
            "Your responsibilities:\n"
            "1. Produce direct database → PDF field mappings where the same data element clearly exists in both lists.\n"
            "2. When the PDF requires a value that can be derived from available database columns (e.g., splitting a full "
            "name, concatenating address parts), emit a precise transformation rule describing how to build that value.\n"
            "3. Prefer accurate, explainable matches; avoid inventing columns or guessing unsupported data.\n\n"
            "**Mapping Priority (CRITICAL - follow this order):**\n"
            "1. **EXACT MATCHES FIRST**: If a database field name matches a PDF field name exactly (case-insensitive), "
            "ALWAYS map it with confidence 1.0.\n"
            "2. **Near-exact matches**: Minor differences like underscores vs spaces → confidence 0.95.\n"
            "   - ALSO treat duplicate-style names (e.g., dob_dob, bmi_bmi_1) as guaranteed matches; map them with "
            "confidence 0.99.\n"
            "3. **Semantic matches**: Different naming but same meaning → confidence 0.85-0.95.\n"
            "4. **Contextual matches**: Use field type, position, labels → confidence 0.7-0.85.\n"
            "5. **Abbreviations**: Expand or match common abbreviations → confidence 0.8-0.9.\n\n"
            "**Permitted transformation operations**\n"
            '- "copy": use the first source field as-is.\n'
            '- "coalesce": return the first non-empty value among several source fields.\n'
            '- "split": extract a token by delimiter/index.\n'
            '- "join"/"concat": combine multiple source fields with a separator.\n'
            '- "template": string template with placeholders like {{patient_first_name}}.\n'
            '- "literal": provide a fixed fallback value.\n\n'
            "Do not introduce new source fields. Every source listed must be present in the supplied database field list.\n\n"
            "**Response JSON structure**\n"
            "{\n"
            '  "mappings": [{"databaseField":"employee_id","pdfField":"employee_id","confidence":1.0,"reasoning":"Exact match"}],\n'
            '  "templateRules": [{"targetField":"First Name","operation":"split","sources":["full_name"],"options":{"delimiter":" ","index":0},"description":"Split full_name"}],\n'
            '  "identifierKey": "mrn",\n'
            '  "notes": "Any additional observations"\n'
            "}\n\n"
            "**Guidelines**\n"
            "- Find and map ALL exact matches first.\n"
            "- Emit direct mappings only when confidence ≥ 0.6.\n"
            "- Template rules are fallbacks only.\n"
            "- targetField must match a real PDF field.\n"
            "- sources must reference existing database columns.\n"
            "- Prefer leaving something unmapped over fabricating a questionable transformation.\n"
            "- Choose the best identifierKey (MRN or similar).\n"
        )

    def _create_user_prompt(self, mapping_request: Dict[str, Any]) -> str:
        database_fields = mapping_request.get("databaseFields", [])
        pdf_fields = mapping_request.get("pdfFields", [])
        pdf_lines = []
        for idx, field in enumerate(pdf_fields):
            context = f' (context: "{field.get("context")}")' if field.get("context") else ""
            field_type = f' [{field.get("type")}]' if field.get("type") else ""
            pdf_lines.append(f'{idx + 1}. "{field.get("name")}"{field_type}{context}')

        return (
            "Please analyze and map these database fields to PDF form fields:\n\n"
            f"**DATABASE FIELDS** ({len(database_fields)} fields):\n"
            + "\n".join(f"{i + 1}. {field}" for i, field in enumerate(database_fields))
            + "\n\n"
            f"**PDF FORM FIELDS** ({len(pdf_fields)} fields):\n"
            + "\n".join(pdf_lines)
            + "\n\n"
            "Deliverables (JSON as specified earlier):\n"
            '- Populate "mappings" with confident direct matches (confidence ≥ 0.6) and reasoning.\n'
            '- Populate "templateRules" with fallback transformations only when a PDF field can be created from existing data.\n'
            "- Choose the best identifierKey from the database fields.\n"
            "- Add any helpful implementation notes.\n"
            "\n"
            "If a PDF field cannot be filled directly or derived safely, leave it unmapped.\n"
        )
