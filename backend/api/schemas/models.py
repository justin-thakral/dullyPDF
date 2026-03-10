"""API request models and payload normalization helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

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
    requestId: Optional[str] = Field(default=None, min_length=1, max_length=120)


class RenameFieldsRequest(BaseModel):
    """OpenAI rename request using cached PDF bytes and optional schema headers."""

    sessionId: str = Field(..., min_length=1)
    schemaId: Optional[str] = None
    templateFields: Optional[List[TemplateOverlayField]] = None
    requestId: Optional[str] = Field(default=None, min_length=1, max_length=120)


class SavedFormSessionRequest(BaseModel):
    """Create a detection session from a saved form + extracted fields."""

    fields: List[Dict[str, Any]] = Field(default_factory=list)
    pageCount: Optional[int] = None


class SavedFormEditorSnapshotUpdateRequest(BaseModel):
    """Persist a ready-to-hydrate editor snapshot for an existing saved form."""

    snapshot: Dict[str, Any] = Field(default_factory=dict)


class TemplateGroupCreateRequest(BaseModel):
    """Create a named group from existing saved templates."""

    name: str = Field(..., min_length=1, max_length=120)
    templateIds: List[str] = Field(default_factory=list)

    model_config = {"extra": "ignore"}

    @field_validator("name", mode="before")
    @classmethod
    def _trim_group_name(cls, value: Any) -> str:
        if value is None:
            raise ValueError("Group name is required")
        resolved = " ".join(str(value).strip().split())
        if not resolved:
            raise ValueError("Group name is required")
        return resolved

    @field_validator("templateIds", mode="before")
    @classmethod
    def _normalize_group_template_ids(cls, value: Any) -> List[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("templateIds must be a list")
        deduped: List[str] = []
        for entry in value:
            template_id = str(entry or "").strip()
            if not template_id or template_id in deduped:
                continue
            deduped.append(template_id)
        return deduped

    @model_validator(mode="after")
    def _validate_group_template_ids(self) -> "TemplateGroupCreateRequest":
        if not self.templateIds:
            raise ValueError("Select at least one saved form")
        return self


class TemplateGroupUpdateRequest(TemplateGroupCreateRequest):
    """Update a named group with a new name and template membership."""


class FillLinkCreateRequest(BaseModel):
    """Publish or refresh a Fill By Link endpoint for a saved template."""

    scopeType: Optional[Literal["template", "group"]] = None
    templateId: Optional[str] = Field(default=None, max_length=160)
    title: Optional[str] = Field(default=None, max_length=200)
    templateName: Optional[str] = Field(default=None, max_length=200)
    groupId: Optional[str] = Field(default=None, max_length=160)
    groupName: Optional[str] = Field(default=None, max_length=200)
    requireAllFields: bool = False
    respondentPdfDownloadEnabled: bool = False
    fields: List[TemplateOverlayField] = Field(default_factory=list)
    checkboxRules: List[Dict[str, Any]] = Field(default_factory=list)
    groupTemplates: List["FillLinkGroupTemplateSource"] = Field(default_factory=list)

    model_config = {"extra": "ignore"}

    @field_validator("scopeType", "templateId", "title", "templateName", "groupId", "groupName", mode="before")
    @classmethod
    def _trim_fill_link_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            trimmed = value.strip()
            return trimmed if trimmed else None
        return value

    @model_validator(mode="after")
    def _validate_fill_link_scope(self) -> "FillLinkCreateRequest":
        scope_type = self.scopeType or ("group" if self.groupId or self.groupTemplates else "template")
        object.__setattr__(self, "scopeType", scope_type)
        if scope_type == "group":
            if not self.groupId:
                raise ValueError("groupId is required for a group Fill By Link")
            if not self.groupTemplates:
                raise ValueError("groupTemplates are required for a group Fill By Link")
            return self
        if not self.templateId:
            raise ValueError("templateId is required for a template Fill By Link")
        return self


class FillLinkGroupTemplateSource(BaseModel):
    """Per-template source data used to build a group Fill By Link schema."""

    templateId: str = Field(..., min_length=1, max_length=160)
    templateName: Optional[str] = Field(default=None, max_length=200)
    fields: List[TemplateOverlayField] = Field(default_factory=list)
    checkboxRules: List[Dict[str, Any]] = Field(default_factory=list)

    model_config = {"extra": "ignore"}

    @field_validator("templateId", "templateName", mode="before")
    @classmethod
    def _trim_group_template_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            trimmed = value.strip()
            return trimmed if trimmed else None
        return value


class FillLinkUpdateRequest(BaseModel):
    """Owner-side Fill By Link update payload."""

    title: Optional[str] = Field(default=None, max_length=200)
    requireAllFields: Optional[bool] = None
    respondentPdfDownloadEnabled: Optional[bool] = None
    fields: Optional[List[TemplateOverlayField]] = None
    checkboxRules: Optional[List[Dict[str, Any]]] = None
    groupName: Optional[str] = Field(default=None, max_length=200)
    groupTemplates: Optional[List[FillLinkGroupTemplateSource]] = None
    status: Optional[Literal["active", "closed"]] = None

    model_config = {"extra": "ignore"}

    @field_validator("title", "groupName", "status", mode="before")
    @classmethod
    def _trim_fill_link_update_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            trimmed = value.strip()
            return trimmed if trimmed else None
        return value


class FillLinkPublicSubmitRequest(BaseModel):
    """Public respondent submission payload."""

    answers: Dict[str, Any] = Field(default_factory=dict)
    attemptId: Optional[str] = Field(default=None, max_length=120)
    recaptchaToken: Optional[str] = Field(default=None, max_length=4096)
    recaptchaAction: Optional[str] = Field(default=None, max_length=120)

    model_config = {"extra": "ignore"}

    @field_validator("attemptId", "recaptchaToken", "recaptchaAction", mode="before")
    @classmethod
    def _trim_fill_link_submit_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            trimmed = value.strip()
            return trimmed if trimmed else None
        return value


FillLinkCreateRequest.model_rebuild()
FillLinkUpdateRequest.model_rebuild()


class DowngradeRetentionUpdateRequest(BaseModel):
    """Update the saved forms preserved during downgrade grace."""

    keptTemplateIds: List[str] = Field(default_factory=list)

    model_config = {"extra": "ignore"}

    @field_validator("keptTemplateIds", mode="before")
    @classmethod
    def _normalize_kept_template_ids(cls, value: Any) -> List[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("keptTemplateIds must be a list")
        deduped: List[str] = []
        for entry in value:
            template_id = str(entry or "").strip()
            if not template_id or template_id in deduped:
                continue
            deduped.append(template_id)
        return deduped


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


BillingCheckoutKind = Literal["pro_monthly", "pro_yearly", "refill_500"]


class BillingCheckoutRequest(BaseModel):
    """Create a Stripe Checkout session for a supported billing action."""

    kind: BillingCheckoutKind = Field(..., min_length=1, max_length=32)
    attempt_id: Optional[str] = Field(default=None, alias="attemptId", max_length=120)

    model_config = {"extra": "ignore"}

    @field_validator("kind", mode="before")
    @classmethod
    def _normalize_kind(cls, value: Any) -> str:
        if value is None:
            raise ValueError("Checkout kind is required")
        resolved = str(value).strip().lower()
        if resolved not in {"pro_monthly", "pro_yearly", "refill_500"}:
            raise ValueError("Unsupported checkout kind")
        return resolved

    @field_validator("attempt_id", mode="before")
    @classmethod
    def _normalize_attempt_id(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        resolved = str(value).strip()
        return resolved or None


class BillingReconcileRequest(BaseModel):
    """Audit and optionally recover recent Stripe checkout fulfillment."""

    lookback_hours: int = Field(default=72, alias="lookbackHours", ge=1, le=720)
    max_events: int = Field(default=100, alias="maxEvents", ge=1, le=500)
    dry_run: bool = Field(default=False, alias="dryRun")
    session_id: Optional[str] = Field(default=None, alias="sessionId", max_length=255)
    attempt_id: Optional[str] = Field(default=None, alias="attemptId", max_length=120)

    model_config = {"extra": "ignore"}

    @field_validator("session_id", "attempt_id", mode="before")
    @classmethod
    def _normalize_optional_identifier(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        resolved = str(value).strip()
        return resolved or None
