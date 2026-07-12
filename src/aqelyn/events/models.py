"""Event envelope + Subject (EA-0003 §5)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from aqelyn.conventions import ActorRef


class Subject(BaseModel):
    object_ids: list[str] = Field(default_factory=list)
    evidence_id: str | None = None
    finding_id: str | None = None


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
