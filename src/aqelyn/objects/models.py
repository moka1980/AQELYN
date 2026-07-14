"""Universal Object Model types (EA-0002 §5-§6)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from aqelyn.conventions import ActorRef, require_tenant_id, require_typed_id

LifecycleState = Literal["active", "archived", "merged", "deleted"]


class NaturalKey(BaseModel):
    namespace: str
    value: str


class SourceRef(BaseModel):
    source_id: str
    evidence_id: str | None = None
    observed_at: datetime
    method: str

    @field_validator("source_id")
    @classmethod
    def _source_id(cls, value: str) -> str:
        return require_typed_id(value, "src", field="source_id")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="evidence_id")


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

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("merged_into")
    @classmethod
    def _merged_into(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "obj", field="merged_into")


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

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "rel", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("from_id", "to_id")
    @classmethod
    def _object_ref(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="relationship endpoint")


class ObjectQuery(BaseModel):
    tenant_id: str | None = None
    object_type: str | None = None
    exclude_object_types: tuple[str, ...] = ()
    labels: dict[str, str] | None = None
    natural_key: NaturalKey | None = None
    include_states: tuple[str, ...] = ("active", "archived")
    limit: int = 100
    cursor: str | None = None

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)
