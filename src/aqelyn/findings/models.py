"""Finding types (Finding-model.spec.md §6)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from aqelyn.conventions import ActorRef, require_tenant_id, require_typed_id
from aqelyn.conventions.errors import SchemaValidationError

Severity = Literal["info", "low", "medium", "high", "critical"]
Status = Literal[
    "open", "acknowledged", "in_progress", "resolved", "risk_accepted", "false_positive"
]


class Remediation(BaseModel):
    summary: str
    steps: list[str] = Field(default_factory=list)
    difficulty: str
    estimated_effort: str | None = None
    expected_outcome: str
    references: list[str] = Field(default_factory=list)


class Automation(BaseModel):
    eligibility: str  # none | assisted | automatic
    action_ref: str | None = None
    requires_approval: bool = True
    risk_note: str | None = None


class AuditEntry(BaseModel):
    at: datetime
    actor: ActorRef
    action: str
    from_status: str | None = None
    to_status: str | None = None
    note: str | None = None


class Finding(BaseModel):
    id: str
    tenant_id: str | None = None
    finding_type: str
    schema_version: int
    dedup_key: str
    title: str
    severity: Severity
    severity_score: float
    status: Status = "open"
    what_happened: str
    why_it_matters: str
    how_determined: str
    risk_of_inaction: str
    evidence_ids: list[str]
    affected_object_ids: list[str] = Field(default_factory=list)
    expert_details: dict[str, Any] | None = None
    remediation: Remediation
    automation: Automation
    confidence: float = 1.0
    source_engine: str
    correlation_id: str | None = None
    first_detected_at: datetime
    last_detected_at: datetime
    resolved_at: datetime | None = None
    audit: list[AuditEntry] = Field(default_factory=list)
    version: int = 1

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "fnd", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("evidence_ids")
    @classmethod
    def _evidence_ids(cls, values: list[str]) -> list[str]:
        return [require_typed_id(value, "evd", field="evidence_ids") for value in values]

    @field_validator("affected_object_ids")
    @classmethod
    def _affected_object_ids(cls, values: list[str]) -> list[str]:
        return [require_typed_id(value, "obj", field="affected_object_ids") for value in values]


_CURSOR_SEPARATOR = "|"


def encode_finding_cursor(*, severity_score: float, finding_id: str) -> str:
    """Encode the complete sort key, not just the id.

    Findings are ordered by ``severity_score DESC, id``, so a cursor keyed on ``id``
    alone is incoherent: a row with a larger id sorts *before* the cursor row when its
    severity is higher, which skips and duplicates across pages. The cursor therefore
    carries both components.

    ``repr`` of a float round-trips exactly under ``float()``, so the resume point is
    the same value the store ordered by -- not a rounded approximation of it.
    """
    return f"{severity_score!r}{_CURSOR_SEPARATOR}{finding_id}"


def decode_finding_cursor(value: str) -> tuple[float, str]:
    head, separator, finding_id = value.partition(_CURSOR_SEPARATOR)
    if not separator:
        raise SchemaValidationError("finding cursor must encode severity_score and id")
    try:
        severity_score = float(head)
    except ValueError as exc:
        raise SchemaValidationError("finding cursor severity_score is not a number") from exc
    if not math.isfinite(severity_score):
        raise SchemaValidationError("finding cursor severity_score must be finite")
    return severity_score, require_typed_id(finding_id, "fnd", field="cursor")


class FindingQuery(BaseModel):
    tenant_id: str | None = None
    status: tuple[str, ...] | None = None
    severity: tuple[str, ...] | None = None
    finding_type: str | None = None
    affected_object_id: str | None = None
    limit: int = 100
    cursor: str | None = None

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("cursor")
    @classmethod
    def _cursor(cls, value: str | None) -> str | None:
        if value is None:
            return None
        decode_finding_cursor(value)
        return value

    @field_validator("affected_object_id")
    @classmethod
    def _affected_object_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "obj", field="affected_object_id")


TRANSITIONS: dict[str, set[str]] = {
    "open": {"acknowledged", "in_progress", "risk_accepted", "false_positive"},
    "acknowledged": {"in_progress", "risk_accepted", "false_positive"},
    "in_progress": {"resolved", "risk_accepted", "false_positive"},
    "resolved": {"open"},
    "risk_accepted": {"open"},
    "false_positive": {"open"},
}

REQUIRED_TEXT = (
    "title",
    "what_happened",
    "why_it_matters",
    "how_determined",
    "risk_of_inaction",
)
