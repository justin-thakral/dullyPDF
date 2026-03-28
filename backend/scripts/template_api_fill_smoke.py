"""Run a live smoke test against a published DullyPDF API Fill endpoint.

The script validates the current schema contract, calls the live fill endpoint
in both default-flat and explicit-editable modes, and inspects the returned
PDFs with pypdf so regressions surface as actionable failures instead of a
generic "200 OK".
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

import requests
from pypdf import PdfReader


DEFAULT_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fill-url",
        required=True,
        help="Live API Fill PDF endpoint, for example http://localhost:8000/api/v1/fill/<endpoint>.pdf",
    )
    parser.add_argument(
        "--schema-url",
        default=None,
        help="Optional schema URL. Defaults to the fill URL with .pdf replaced by /schema.",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("DULLYPDF_API_KEY"),
        help="API Fill key. Defaults to DULLYPDF_API_KEY.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Optional directory for saved schema/PDF artifacts. Defaults to a temporary directory.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"HTTP timeout in seconds. Defaults to {DEFAULT_TIMEOUT_SECONDS}.",
    )
    return parser.parse_args()


def _derive_schema_url(fill_url: str) -> str:
    normalized = fill_url.strip()
    if not normalized:
        raise ValueError("fill_url is required")
    if normalized.endswith(".pdf"):
        return re.sub(r"\.pdf$", "/schema", normalized)
    return normalized.rstrip("/") + "/schema"


def _build_auth_headers(api_key: str) -> Dict[str, str]:
    encoded = base64.b64encode(f"{api_key}:".encode("utf-8")).decode("ascii")
    return {
        "Authorization": f"Basic {encoded}",
        "Content-Type": "application/json",
    }


def _choose_scalar_sample(key: str, field_type: str) -> str:
    normalized_key = str(key or "").strip().lower()
    if field_type == "date" or "date" in normalized_key or normalized_key.endswith("_at"):
        return "2026-03-28"
    if "email" in normalized_key:
        return "api-fill-smoke@example.com"
    if "phone" in normalized_key:
        return "555-0100"
    if "name" in normalized_key:
        return "API Fill Smoke"
    if "company" in normalized_key:
        return "DullyPDF"
    if "city" in normalized_key:
        return "Austin"
    if "state" in normalized_key:
        return "Texas"
    if "zip" in normalized_key or "postal" in normalized_key:
        return "78701"
    if "gpa" in normalized_key:
        return "4.0"
    if "year" in normalized_key:
        return "7"
    return f"sample_{normalized_key or 'value'}"


def _build_sample_data(schema: Dict[str, Any]) -> Dict[str, Any]:
    data: Dict[str, Any] = {}

    for entry in schema.get("fields") or []:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key") or "").strip()
        if not key:
            continue
        data[key] = _choose_scalar_sample(key, str(entry.get("type") or "text").strip().lower())

    for entry in schema.get("checkboxFields") or []:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key") or "").strip()
        if key:
            data[key] = True

    for entry in schema.get("checkboxGroups") or []:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key") or "").strip()
        operation = str(entry.get("operation") or "").strip().lower()
        options = [dict(option) for option in entry.get("options") or [] if isinstance(option, dict)]
        first_option = str((options[0] or {}).get("optionKey") or "").strip() if options else ""
        if not key:
            continue
        if operation == "list":
            data[key] = [first_option] if first_option else []
        elif operation == "enum":
            data[key] = first_option
        else:
            data[key] = True

    for entry in schema.get("radioGroups") or []:
        if not isinstance(entry, dict):
            continue
        group_key = str(entry.get("groupKey") or "").strip()
        options = [dict(option) for option in entry.get("options") or [] if isinstance(option, dict)]
        first_option = str((options[0] or {}).get("optionKey") or "").strip() if options else ""
        if group_key and first_option:
            data[group_key] = first_option

    return data


def _coerce_pdf_field_value(value: Any) -> str | None:
    if hasattr(value, "value"):
        value = getattr(value, "value")
    elif isinstance(value, dict):
        value = value.get("/V")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _select_editable_value_expectations(
    schema: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    max_items: int = 3,
) -> List[tuple[str, str]]:
    expectations: List[tuple[str, str]] = []
    for entry in schema.get("fields") or []:
        if not isinstance(entry, dict):
            continue
        field_type = str(entry.get("type") or "text").strip().lower()
        if field_type not in {"text", "date"}:
            continue
        key = str(entry.get("key") or "").strip()
        field_name = str(entry.get("fieldName") or "").strip()
        if not key or not field_name or key not in payload:
            continue
        expectations.append((field_name, str(payload[key])))
        if len(expectations) >= max_items:
            break
    return expectations


def _write_artifact(path: Path, content: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def _run_smoke(
    *,
    fill_url: str,
    schema_url: str,
    api_key: str,
    output_dir: Path,
    timeout_seconds: float,
) -> List[CheckResult]:
    results: List[CheckResult] = []
    headers = _build_auth_headers(api_key)
    session = requests.Session()

    schema_response = session.get(
        schema_url,
        headers={"Authorization": headers["Authorization"]},
        timeout=timeout_seconds,
    )
    schema_payload = schema_response.json() if schema_response.headers.get("Content-Type", "").startswith("application/json") else {}
    _write_artifact(output_dir / "schema.json", json.dumps(schema_payload, indent=2, sort_keys=True))

    schema_ok = schema_response.status_code == 200 and isinstance(schema_payload.get("schema"), dict)
    results.append(
        CheckResult(
            name="schema_fetch",
            passed=schema_ok,
            detail=f"status={schema_response.status_code}, cache_control={schema_response.headers.get('Cache-Control')}",
        )
    )
    if not schema_ok:
        return results

    results.append(
        CheckResult(
            name="schema_cache_headers",
            passed=schema_response.headers.get("Cache-Control") == "private, no-store",
            detail=f"cache_control={schema_response.headers.get('Cache-Control')}",
        )
    )

    schema = dict(schema_payload["schema"])
    signature_fields = [
        str(entry.get("key") or "").strip()
        for entry in schema.get("fields") or []
        if isinstance(entry, dict) and str(entry.get("type") or "").strip().lower() == "signature"
    ]
    results.append(
        CheckResult(
            name="schema_excludes_signature_widgets",
            passed=not signature_fields,
            detail="signature keys: none" if not signature_fields else f"signature keys: {', '.join(signature_fields)}",
        )
    )

    sample_data = _build_sample_data(schema)

    flat_response = session.post(
        fill_url,
        headers=headers,
        json={"data": sample_data, "strict": True},
        timeout=timeout_seconds,
    )
    _write_artifact(output_dir / "filled-flat.pdf", flat_response.content)
    flat_ok = flat_response.status_code == 200 and flat_response.headers.get("Content-Type") == "application/pdf"
    results.append(
        CheckResult(
            name="flat_fill_response",
            passed=flat_ok and flat_response.headers.get("Cache-Control") == "private, no-store",
            detail=(
                f"status={flat_response.status_code}, content_type={flat_response.headers.get('Content-Type')}, "
                f"cache_control={flat_response.headers.get('Cache-Control')}"
            ),
        )
    )
    if flat_ok:
        flat_reader = PdfReader(io.BytesIO(flat_response.content))
        flat_fields = flat_reader.get_fields() or {}
        results.append(
            CheckResult(
                name="flat_fill_flattens_widgets",
                passed=len(flat_reader.pages) > 0 and len(flat_fields) == 0,
                detail=f"pages={len(flat_reader.pages)}, field_count={len(flat_fields)}",
            )
        )

    editable_response = session.post(
        fill_url,
        headers=headers,
        json={"data": sample_data, "strict": True, "exportMode": "editable"},
        timeout=timeout_seconds,
    )
    _write_artifact(output_dir / "filled-editable.pdf", editable_response.content)
    editable_ok = editable_response.status_code == 200 and editable_response.headers.get("Content-Type") == "application/pdf"
    results.append(
        CheckResult(
            name="editable_fill_response",
            passed=editable_ok and editable_response.headers.get("Cache-Control") == "private, no-store",
            detail=(
                f"status={editable_response.status_code}, content_type={editable_response.headers.get('Content-Type')}, "
                f"cache_control={editable_response.headers.get('Cache-Control')}"
            ),
        )
    )
    if editable_ok:
        editable_reader = PdfReader(io.BytesIO(editable_response.content))
        editable_fields = editable_reader.get_fields() or {}
        expectations = _select_editable_value_expectations(schema, sample_data)
        mismatches: List[str] = []
        for field_name, expected_value in expectations:
            actual_value = _coerce_pdf_field_value(editable_fields.get(field_name))
            if actual_value != expected_value:
                mismatches.append(f"{field_name}={actual_value!r} (expected {expected_value!r})")
        results.append(
            CheckResult(
                name="editable_fill_preserves_field_values",
                passed=len(editable_reader.pages) > 0 and bool(editable_fields) and not mismatches,
                detail=(
                    f"pages={len(editable_reader.pages)}, field_count={len(editable_fields)}, "
                    f"checked={len(expectations)}, mismatches={'; '.join(mismatches) or 'none'}"
                ),
            )
        )

    return results


def main() -> int:
    args = _parse_args()
    if not args.api_key:
        print("Missing API key. Pass --api-key or set DULLYPDF_API_KEY.", file=sys.stderr)
        return 2

    fill_url = str(args.fill_url or "").strip()
    schema_url = str(args.schema_url or _derive_schema_url(fill_url)).strip()
    if not fill_url:
        print("Missing --fill-url.", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir) if args.output_dir else Path(tempfile.mkdtemp(prefix="template-api-fill-smoke-"))
    results = _run_smoke(
        fill_url=fill_url,
        schema_url=schema_url,
        api_key=args.api_key,
        output_dir=output_dir,
        timeout_seconds=float(args.timeout_seconds),
    )

    print(f"Artifacts: {output_dir}")
    failures = [result for result in results if not result.passed]
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.name}: {result.detail}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
