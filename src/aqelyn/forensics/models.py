"""Digital Forensics models and config validation (EA-0016 F1)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aqelyn.conventions import ActorRef, new_id, require_tenant_id, require_typed_id
from aqelyn.conventions.errors import ForensicsConfigInvalid
from aqelyn.evidence import BlobRef

FORENSIC_ARTIFACT_OBJECT_TYPE = "forensic_artifact"


def _nonempty(value: str, *, field: str) -> str:
    if not value.strip():
        raise ForensicsConfigInvalid(f"{field} must not be empty")
    return value


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ForensicsConfigInvalid(f"{field} must be >= 1")
    return value


def _hash(value: str, *, field: str) -> str:
    selected = value.strip().lower()
    if len(selected) != 64 or any(char not in "0123456789abcdef" for char in selected):
        raise ForensicsConfigInvalid(f"{field} must be a sha256 hex digest")
    return selected


def _unique_typed_ids(values: list[str], prefix: str, *, field: str) -> list[str]:
    out = [require_typed_id(value, prefix, field=field) for value in values]
    if len(out) != len(set(out)):
        raise ForensicsConfigInvalid(f"{field} must not contain duplicates")
    return out


class Acquisition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("acq"))
    tenant_id: str | None = None
    source_ref: str
    collector: ActorRef
    method: str
    acquired_at: datetime
    content_ref: BlobRef | None = None
    content_hash: str
    case_id: str | None = None
    evidence_id: str | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "acq", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("source_ref", "method")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="acquisition field")

    @field_validator("content_hash")
    @classmethod
    def _content_hash(cls, value: str) -> str:
        return _hash(value, field="content_hash")

    @field_validator("case_id")
    @classmethod
    def _case_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "inc", field="case_id")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="evidence_id")


class Artifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("art"))
    tenant_id: str | None = None
    artifact_type: str
    acquisition_id: str
    object_id: str
    evidence_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    linked_asset_ids: list[str] = Field(default_factory=list)
    first_seen_at: datetime
    case_id: str | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "art", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("artifact_type")
    @classmethod
    def _artifact_type(cls, value: str) -> str:
        return _nonempty(value, field="artifact_type")

    @field_validator("acquisition_id")
    @classmethod
    def _acquisition_id(cls, value: str) -> str:
        return require_typed_id(value, "acq", field="acquisition_id")

    @field_validator("object_id")
    @classmethod
    def _object_id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="object_id")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")

    @field_validator("linked_asset_ids")
    @classmethod
    def _linked_asset_ids(cls, values: list[str]) -> list[str]:
        return _unique_typed_ids(values, "obj", field="linked_asset_ids")

    @field_validator("case_id")
    @classmethod
    def _case_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "inc", field="case_id")


class TimelineEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at: datetime
    artifact_id: str
    kind: str
    detail: dict[str, Any] = Field(default_factory=dict)
    evidence_id: str

    @field_validator("artifact_id")
    @classmethod
    def _artifact_id(cls, value: str) -> str:
        return require_typed_id(value, "art", field="artifact_id")

    @field_validator("kind")
    @classmethod
    def _kind(cls, value: str) -> str:
        return _nonempty(value, field="timeline kind")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")


class ForensicTimeline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str | None = None
    events: list[TimelineEvent] = Field(default_factory=list)
    truncated: bool = False

    @field_validator("case_id")
    @classmethod
    def _case_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "inc", field="case_id")


class VerifyReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_id: str
    ok: bool
    broken_at: str | None = None
    detail: str | None = None

    @field_validator("subject_id")
    @classmethod
    def _subject_id(cls, value: str) -> str:
        _nonempty(value, field="subject_id")
        return value


class ForensicsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_size: int = 100
    timeline_window: dict[str, Any] | None = None

    @field_validator("batch_size", mode="before")
    @classmethod
    def _batch_size(cls, value: object) -> int:
        return _positive_int(value, field="batch_size")

    @model_validator(mode="after")
    def _timeline_window(self) -> ForensicsConfig:
        if self.timeline_window is None:
            return self
        for key, value in self.timeline_window.items():
            _nonempty(key, field="timeline_window key")
            if isinstance(value, float) and not math.isfinite(value):
                raise ForensicsConfigInvalid("timeline_window values must be finite")
        return self
