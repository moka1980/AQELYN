"""Universal Object Model types (EA-0002 §5-§6)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from aqelyn.conventions import ActorRef

LifecycleState = Literal["active", "archived", "merged", "deleted"]


class NaturalKey(BaseModel):
    namespace: str
    value: str


class SourceRef(BaseModel):
    source_id: str
    evidence_id: str | None = None
    observed_at: datetime
    method: str


class AQObject(BaseModel):
    id: str
    object_type: str
    schema_version: int
    tenant_id: str | None = None
    display_name: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)
    natural_keys: list[NaturalKey] = Field(default_factory=list)
    sources: list[SourceRef]
    confidence: float = 1.0
    lifecycle_state: LifecycleState = "active"
    merged_into: str | None = None
    version: int = 1
    first_seen_at: datetime
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime
    created_by: ActorRef
    updated_by: ActorRef


class AQRelationship(BaseModel):
    id: str
    tenant_id: str | None = None
    from_id: str
    to_id: str
    relation_type: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    sources: list[SourceRef] = Field(default_factory=list)
    confidence: float = 1.0
    lifecycle_state: LifecycleState = "active"
    version: int = 1
    created_at: datetime
    updated_at: datetime
    created_by: ActorRef
    updated_by: ActorRef


class ObjectQuery(BaseModel):
    tenant_id: str | None = None
    object_type: str | None = None
    labels: dict[str, str] | None = None
    natural_key: NaturalKey | None = None
    include_states: tuple[str, ...] = ("active", "archived")
    limit: int = 100
    cursor: str | None = None
