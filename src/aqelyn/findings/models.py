"""Finding types (Finding-model.spec.md §6)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from aqelyn.conventions import ActorRef, require_tenant_id, require_typed_id

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
