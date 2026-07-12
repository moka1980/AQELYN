"""Event envelope + Subject (EA-0003 §5)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from aqelyn.conventions import ActorRef, require_tenant_id, require_typed_id


class Subject(BaseModel):
    object_ids: list[str] = Field(default_factory=list)
    evidence_id: str | None = None
    finding_id: str | None = None

    @field_validator("object_ids")
    @classmethod
    def _object_ids(cls, values: list[str]) -> list[str]:
        return [require_typed_id(value, "obj", field="subject.object_ids") for value in values]

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="subject.evidence_id")

    @field_validator("finding_id")
    @classmethod
    def _finding_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "fnd", field="subject.finding_id")


class Event(BaseModel):
    id: str
    event_type: str
    schema_version: int
    tenant_id: str | None = None
    occurred_at: datetime
    recorded_at: datetime
    producer: ActorRef
    subject: Subject
    payload: dict[str, Any] = Field(default_factory=dict)
    partition_key: str
    correlation_id: str | None = None
    causation_id: str | None = None
    trace_id: str | None = None
    idempotency_key: str | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "evt", field="id")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)
