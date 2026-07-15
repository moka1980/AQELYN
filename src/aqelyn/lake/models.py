"""Security Data Lake models and config validation (EA-0019 L1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aqelyn.conventions import ActorRef, new_id, require_tenant_id, require_typed_id
from aqelyn.conventions.errors import LakeConfigInvalid, PolicyConfigInvalid
from aqelyn.evidence import BlobRef
from aqelyn.policy import Condition

Classification = Literal["public", "internal", "pii", "secret"]
SchemaType = Literal["string", "int", "float", "bool", "datetime", "json"]
RetentionState = Literal["active", "archived", "expired"]

VALID_CLASSIFICATIONS: Final[frozenset[str]] = frozenset(("public", "internal", "pii", "secret"))
VALID_SCHEMA_TYPES: Final[frozenset[str]] = frozenset(
    ("string", "int", "float", "bool", "datetime", "json")
)


def _nonempty(value: str, *, field: str) -> str:
    if not value.strip():
        raise LakeConfigInvalid(f"{field} must not be empty")
    return value


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise LakeConfigInvalid(f"{field} must be >= 1")
    return value


def _nonnegative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LakeConfigInvalid(f"{field} must be >= 0")
    return value


def _schema(value: object) -> dict[str, SchemaType]:
    if not isinstance(value, dict) or not value:
        raise LakeConfigInvalid("dataset schema must be a non-empty object")
    out: dict[str, SchemaType] = {}
    for raw_key, raw_type in value.items():
        if not isinstance(raw_key, str):
            raise LakeConfigInvalid("dataset schema field names must be strings")
        key = _nonempty(raw_key, field="dataset schema field")
        if not isinstance(raw_type, str) or raw_type not in VALID_SCHEMA_TYPES:
            raise LakeConfigInvalid(f"unknown schema type for field {key!r}")
        out[key] = cast(SchemaType, raw_type)
    return out


def _classifications(value: object) -> dict[str, Classification]:
    if not isinstance(value, dict) or not value:
        raise LakeConfigInvalid("classifications must be a non-empty object")
    out: dict[str, Classification] = {}
    for raw_key, raw_classification in value.items():
        if not isinstance(raw_key, str):
            raise LakeConfigInvalid("classification field names must be strings")
        key = _nonempty(raw_key, field="classification field")
        if (
            not isinstance(raw_classification, str)
            or raw_classification not in VALID_CLASSIFICATIONS
        ):
            raise LakeConfigInvalid(f"unknown classification for field {key!r}")
        out[key] = cast(Classification, raw_classification)
    return out


def _condition(value: object) -> Condition | None:
    if value is None or isinstance(value, Condition):
        return value
    try:
        return Condition.model_validate(value)
    except PolicyConfigInvalid as exc:
        raise LakeConfigInvalid(exc.message) from exc


def _dedupe_nonempty(values: list[str], *, field: str) -> list[str]:
    for value in values:
        _nonempty(value, field=field)
    if len(values) != len(set(values)):
        raise LakeConfigInvalid(f"{field} must not contain duplicates")
    return values


class Dataset(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str
    tenant_id: str | None = None
    schema_: dict[str, SchemaType] = Field(alias="schema", serialization_alias="schema")
    classifications: dict[str, Classification]
    retention_policy_id: str | None = None
    indexed_fields: list[str] = Field(default_factory=list)
    set_by: ActorRef
    set_at: datetime
    version: int = 1

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _nonempty(value, field="dataset name")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("schema_", mode="before")
    @classmethod
    def _schema(cls, value: object) -> dict[str, SchemaType]:
        return _schema(value)

    @field_validator("classifications", mode="before")
    @classmethod
    def _classifications(cls, value: object) -> dict[str, Classification]:
        return _classifications(value)

    @field_validator("retention_policy_id")
    @classmethod
    def _retention_policy_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "rtp", field="retention_policy_id")

    @field_validator("indexed_fields")
    @classmethod
    def _indexed_fields(cls, values: list[str]) -> list[str]:
        return _dedupe_nonempty(values, field="indexed_fields") if values else []

    @field_validator("version", mode="before")
    @classmethod
    def _version(cls, value: object) -> int:
        return _positive_int(value, field="dataset version")

    @model_validator(mode="after")
    def _schema_classification_match(self) -> Dataset:
        schema_fields = set(self.schema_)
        classification_fields = set(self.classifications)
        if schema_fields != classification_fields:
            raise LakeConfigInvalid("classifications must cover exactly the dataset schema fields")
        missing_indexes = [field for field in self.indexed_fields if field not in self.schema_]
        if missing_indexes:
            raise LakeConfigInvalid("indexed_fields must name dataset schema fields")
        return self


class TelemetryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("tlm"))
    tenant_id: str | None = None
    dataset: str
    source_id: str
    occurred_at: datetime
    ingested_at: datetime
    fields: dict[str, Any]
    raw_ref: BlobRef | None = None
    schema_version: int = 1
    retention_state: RetentionState = "active"
    legal_hold: bool = False
    evidence_id: str | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "tlm", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("dataset")
    @classmethod
    def _dataset(cls, value: str) -> str:
        return _nonempty(value, field="dataset")

    @field_validator("source_id")
    @classmethod
    def _source_id(cls, value: str) -> str:
        return require_typed_id(value, "src", field="source_id")

    @field_validator("schema_version", mode="before")
    @classmethod
    def _schema_version(cls, value: object) -> int:
        return _positive_int(value, field="schema_version")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="evidence_id")

    @model_validator(mode="after")
    def _timestamps(self) -> TelemetryRecord:
        if self.ingested_at < self.occurred_at:
            raise LakeConfigInvalid("ingested_at must be >= occurred_at")
        return self


class RetentionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("rtp"))
    dataset: str
    tenant_id: str | None = None
    ttl_days: int | None = None
    archive_after_days: int | None = None
    condition: Condition | None = None
    set_by: ActorRef
    version: int = 1

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "rtp", field="id", allow_empty=True)

    @field_validator("dataset")
    @classmethod
    def _dataset(cls, value: str) -> str:
        return _nonempty(value, field="dataset")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("ttl_days", "archive_after_days", mode="before")
    @classmethod
    def _optional_positive_days(cls, value: object) -> int | None:
        if value is None:
            return None
        return _positive_int(value, field="retention days")

    @field_validator("condition", mode="before")
    @classmethod
    def _condition(cls, value: object) -> Condition | None:
        return _condition(value)

    @field_validator("version", mode="before")
    @classmethod
    def _version(cls, value: object) -> int:
        return _positive_int(value, field="retention policy version")


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: str
    tenant_id: str | None = None
    filter: Condition | None = None
    since: datetime | None = None
    until: datetime | None = None
    fields: list[str] | None = None
    limit: int

    @field_validator("dataset")
    @classmethod
    def _dataset(cls, value: str) -> str:
        return _nonempty(value, field="dataset")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("filter", mode="before")
    @classmethod
    def _filter(cls, value: object) -> Condition | None:
        return _condition(value)

    @field_validator("fields")
    @classmethod
    def _fields(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return _dedupe_nonempty(values, field="fields")

    @field_validator("limit", mode="before")
    @classmethod
    def _limit(cls, value: object) -> int:
        return _positive_int(value, field="query limit")

    @model_validator(mode="after")
    def _time_range(self) -> Query:
        if self.since is not None and self.until is not None and self.until < self.since:
            raise LakeConfigInvalid("until must be >= since")
        return self


class QueryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[dict[str, Any]] = Field(default_factory=list)
    count: int
    truncated: bool
    redacted_fields: list[str] = Field(default_factory=list)

    @field_validator("count", mode="before")
    @classmethod
    def _count(cls, value: object) -> int:
        return _nonnegative_int(value, field="count")

    @field_validator("redacted_fields")
    @classmethod
    def _redacted_fields(cls, values: list[str]) -> list[str]:
        return _dedupe_nonempty(values, field="redacted_fields") if values else []


class ArchiveRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("arc"))
    dataset: str
    tenant_id: str | None = None
    range: dict[str, Any]
    location: BlobRef
    record_count: int
    content_hash: str
    archived_at: datetime
    evidence_id: str

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "arc", field="id", allow_empty=True)

    @field_validator("dataset", "content_hash")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="archive field")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("record_count", mode="before")
    @classmethod
    def _record_count(cls, value: object) -> int:
        return _nonnegative_int(value, field="record_count")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")


class RetentionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: str
    evaluated: int
    archived: int
    expired: int
    skipped_held: int
    skipped_referenced: int
    evidence_id: str
    reason: str

    @field_validator("dataset", "reason")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="retention report field")

    @field_validator(
        "evaluated",
        "archived",
        "expired",
        "skipped_held",
        "skipped_referenced",
        mode="before",
    )
    @classmethod
    def _counts(cls, value: object) -> int:
        return _nonnegative_int(value, field="retention count")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")


class Quarantine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    reason: str
    received_at: datetime
    raw_ref: BlobRef | None = None

    @field_validator("source_id")
    @classmethod
    def _source_id(cls, value: str) -> str:
        return require_typed_id(value, "src", field="source_id")

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return _nonempty(value, field="quarantine reason")


class LakeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_size: int = 1_000
    max_query_rows: int = 10_000
    default_limit: int = 100

    @field_validator("batch_size", "max_query_rows", "default_limit", mode="before")
    @classmethod
    def _positive(cls, value: object) -> int:
        return _positive_int(value, field="lake config integer")

    @model_validator(mode="after")
    def _limits(self) -> LakeConfig:
        if self.default_limit > self.max_query_rows:
            raise LakeConfigInvalid("default_limit must be <= max_query_rows")
        return self
