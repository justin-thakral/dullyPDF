"""API request models and payload normalization helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


CONTACT_ISSUE_LABELS = {
    "bug_report": "Bug report",
    "cofounder_inquiry": "Co-founder inquiry",
    "question": "Question",
    "feature_request": "Feature request",
    "partnership": "Partnership",
    "other": "Other",
}


def _coerce_rect_float(value: Any, label: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"rect {label} must be a number") from exc


def _rect_from_xywh(x: Any, y: Any, width: Any, height: Any) -> Dict[str, float]:
    x_val = _coerce_rect_float(x, "x")
    y_val = _coerce_rect_float(y, "y")
    width_val = _coerce_rect_float(width, "width")
    height_val = _coerce_rect_float(height, "height")
    if width_val <= 0 or height_val <= 0:
        raise ValueError("rect width/height must be positive")
    return {"x": x_val, "y": y_val, "width": width_val, "height": height_val}


def _rect_from_corners(x1: Any, y1: Any, x2: Any, y2: Any) -> Dict[str, float]:
    x1_val = _coerce_rect_float(x1, "x1")
    y1_val = _coerce_rect_float(y1, "y1")
    x2_val = _coerce_rect_float(x2, "x2")
    y2_val = _coerce_rect_float(y2, "y2")
    width_val = x2_val - x1_val
    height_val = y2_val - y1_val
    if width_val <= 0 or height_val <= 0:
        raise ValueError("rect corner coordinates must produce positive width/height")
    return {"x": x1_val, "y": y1_val, "width": width_val, "height": height_val}


class SchemaField(BaseModel):
    """Schema field metadata (name + type) for AI mapping."""

    name: str = Field(..., min_length=1)
    type: Optional[str] = "string"


class SchemaCreateRequest(BaseModel):
    """Schema creation payload containing only metadata (no rows)."""

    name: Optional[str] = None
    fields: List[SchemaField]
    source: Optional[str] = None
    sampleCount: Optional[int] = None


class TemplateOverlayField(BaseModel):
    """Template overlay field payload with no row data or values."""

    name: str = Field(..., min_length=1)
    type: Optional[str] = "text"
    page: Optional[int] = None
    rect: Optional[Dict[str, float]] = None
    groupKey: Optional[str] = None
    optionKey: Optional[str] = None
    optionLabel: Optional[str] = None
    groupLabel: Optional[str] = None

    model_config = {"extra": "ignore"}

    @field_validator("rect", mode="before")
    @classmethod
    def _normalize_rect(cls, value: Any) -> Optional[Dict[str, float]]:
        if value is None:
            return None
        if isinstance(value, dict):
            if not value:
                return None
            if {"x", "y", "width", "height"}.issubset(value):
                return _rect_from_xywh(value.get("x"), value.get("y"), value.get("width"), value.get("height"))
            if {"x1", "y1", "x2", "y2"}.issubset(value):
                return _rect_from_corners(value.get("x1"), value.get("y1"), value.get("x2"), value.get("y2"))
            raise ValueError("rect dict must include x/y/width/height or x1/y1/x2/y2")
        if isinstance(value, (list, tuple)):
            if len(value) != 4:
                raise ValueError("rect list must have 4 numbers")
            return _rect_from_corners(value[0], value[1], value[2], value[3])
        raise ValueError("rect must be a dict or 4-item list")


class SchemaMappingRequest(BaseModel):
    """OpenAI mapping request using schema metadata + template overlay tags."""

    schemaId: str = Field(..., min_length=1)
    templateId: Optional[str] = None
    templateFields: List[TemplateOverlayField]
    sessionId: Optional[str] = None


class RenameFieldsRequest(BaseModel):
    """OpenAI rename request using cached PDF bytes and optional schema headers."""

    sessionId: str = Field(..., min_length=1)
    schemaId: Optional[str] = None
    templateFields: Optional[List[TemplateOverlayField]] = None


class SavedFormSessionRequest(BaseModel):
    """Create a detection session from a saved form + extracted fields."""

    fields: List[Dict[str, Any]] = Field(default_factory=list)
    pageCount: Optional[int] = None


class ContactRequest(BaseModel):
    """Homepage contact form submission."""

    issueType: str = Field(..., min_length=1)
    summary: str = Field(..., min_length=1, max_length=160)
    message: str = Field(..., min_length=1, max_length=4000)
    contactName: Optional[str] = Field(default=None, max_length=120)
    contactCompany: Optional[str] = Field(default=None, max_length=120)
    contactEmail: Optional[str] = Field(default=None, max_length=254)
    contactPhone: Optional[str] = Field(default=None, max_length=40)
    preferredContact: Optional[str] = Field(default=None, max_length=20)
    includeContactInSubject: bool = False
    recaptchaToken: Optional[str] = Field(default=None, max_length=4096)
    recaptchaAction: Optional[str] = Field(default=None, max_length=120)
    pageUrl: Optional[str] = Field(default=None, max_length=2048)

    model_config = {"extra": "ignore"}

    @field_validator("issueType", mode="before")
    @classmethod
    def _normalize_issue_type(cls, value: Any) -> str:
        if value is None:
            raise ValueError("Issue type is required")
        resolved = str(value).strip().lower()
        if not resolved:
            raise ValueError("Issue type is required")
        if resolved not in CONTACT_ISSUE_LABELS:
            raise ValueError("Unsupported issue type")
        return resolved

    @field_validator(
        "summary",
        "message",
        "contactName",
        "contactCompany",
        "contactEmail",
        "contactPhone",
        "preferredContact",
        "recaptchaAction",
        "pageUrl",
        mode="before",
    )
    @classmethod
    def _trim_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            trimmed = value.strip()
            return trimmed if trimmed else None
        return value

    @model_validator(mode="after")
    def _validate_contact_channels(self) -> "ContactRequest":
        if not self.contactEmail and not self.contactPhone:
            raise ValueError("Provide a contact email or phone number")
        return self


class RecaptchaAssessmentRequest(BaseModel):
    """Lightweight reCAPTCHA verification payload."""

    token: str = Field(..., min_length=1, max_length=4096)
    action: Optional[str] = Field(default=None, max_length=120)

    model_config = {"extra": "ignore"}

    @field_validator("token", "action", mode="before")
    @classmethod
    def _trim_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            trimmed = value.strip()
            return trimmed if trimmed else None
        return value
