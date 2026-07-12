"""Evidence types (EA-0004 §5-§8)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from aqelyn.conventions import ActorRef, require_tenant_id, require_typed_id
from aqelyn.events import Subject


class BlobRef(BaseModel):
    hash: str
    size_bytes: int
    media_type: str
    uri: str


class EvidenceRecord(BaseModel):
    id: str
    tenant_id: str | None = None
    evidence_type: str
    schema_version: int
    subject: Subject
    collected_at: datetime
    recorded_at: datetime
    collector: ActorRef
    source_id: str
    method: str
    content: dict[str, Any] | None = None
    content_ref: BlobRef | None = None
    content_hash: str
    confidence: float = 1.0
    labels: dict[str, str] = Field(default_factory=dict)
    seq: int
    prev_hash: str | None
    record_hash: str
    signature: dict[str, Any] | None = None
    anchor: dict[str, Any] | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("source_id")
    @classmethod
    def _source_id(cls, value: str) -> str:
        return require_typed_id(value, "src", field="source_id")

    @model_validator(mode="after")
    def _content_xor_ref(self) -> EvidenceRecord:
        if (self.content is None) == (self.content_ref is None):
            from aqelyn.conventions.errors import SchemaValidationError

            raise SchemaValidationError("exactly one of content / content_ref required")
        return self


class VerifyResult(BaseModel):
    ok: bool
    broken_at_seq: int | None = None
    detail: str | None = None


class EvidencePackage(BaseModel):
    id: str
    tenant_id: str | None = None
    evidence_ids: list[str]
    manifest_hash: str
    package_hash: str
    created_by: ActorRef
    created_at: datetime
    reason: str

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "pkg", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("evidence_ids")
    @classmethod
    def _evidence_ids(cls, values: list[str]) -> list[str]:
        return [require_typed_id(value, "evd", field="evidence_ids") for value in values]
