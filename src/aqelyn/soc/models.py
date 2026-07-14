"""Security Operations (SOC) models and config validation (EA-0015 S1)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from aqelyn.conventions import ActorRef, new_id, require_tenant_id, require_typed_id
from aqelyn.conventions.errors import SOCConfigInvalid
from aqelyn.findings.models import Severity
from aqelyn.workflow.models import RunStatus

AlertState = Literal["new", "triaged", "suppressed", "escalated"]
AlertSourceKind = Literal["finding", "threat_match", "risk"]
IncidentStatus = Literal["new", "triaged", "investigating", "contained", "resolved", "closed"]


def _require_nonempty(value: str, *, field: str) -> str:
    if not value.strip():
        raise SOCConfigInvalid(f"{field} must not be empty")
    return value


def _require_positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SOCConfigInvalid(f"{field} must be >= 1")
    return value


def _require_score(value: float, *, field: str) -> float:
    if not math.isfinite(value) or value < 0.0 or value > 100.0:
        raise SOCConfigInvalid(f"{field} must be in [0,100]")
    return value


def _require_unique_typed_ids(values: list[str], prefix: str, *, field: str) -> list[str]:
    out = [require_typed_id(value, prefix, field=field) for value in values]
    if len(out) != len(set(out)):
        raise SOCConfigInvalid(f"{field} must not contain duplicates")
    return out


def _require_optional_evidence_id(value: str | None, *, field: str = "evidence_id") -> str | None:
    if value is None:
        return None
    return require_typed_id(value, "evd", field=field)


class Alert(BaseModel):
    """A triage wrapper over an upstream finding, threat match, or risk."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("alt"))
    tenant_id: str | None = None
    source_kind: AlertSourceKind
    source_ref: str
    evidence_id: str | None = None
    severity: Severity
    state: AlertState = "new"
    correlation_key: str | None = None
    created_at: datetime
    version: int = 1

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "alt", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("source_ref")
    @classmethod
    def _source_ref(cls, value: str) -> str:
        return _require_nonempty(value, field="source_ref")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        return _require_optional_evidence_id(value)

    @field_validator("correlation_key")
    @classmethod
    def _correlation_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_nonempty(value, field="correlation_key")

    @field_validator("version")
    @classmethod
    def _version(cls, value: int) -> int:
        return _require_positive_int(value, field="version")


class TimelineEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at: datetime
    actor: ActorRef
    kind: str
    detail: dict[str, Any] = Field(default_factory=dict)
    evidence_id: str | None = None

    @field_validator("kind")
    @classmethod
    def _kind(cls, value: str) -> str:
        return _require_nonempty(value, field="timeline kind")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        return _require_optional_evidence_id(value)


class ResponseAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    workflow_run_id: str | None = None
    status: RunStatus = "proposed"

    @field_validator("action_type")
    @classmethod
    def _action_type(cls, value: str) -> str:
        return _require_nonempty(value, field="action_type")

    @field_validator("workflow_run_id")
    @classmethod
    def _workflow_run_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "run", field="workflow_run_id")


class Incident(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("inc"))
    tenant_id: str | None = None
    title: str
    status: IncidentStatus = "new"
    priority: float
    alert_ids: list[str] = Field(default_factory=list)
    affected_object_ids: list[str] = Field(default_factory=list)
    top_mission_id: str | None = None
    risk_score: float | None = None
    assignee: ActorRef | None = None
    timeline: list[TimelineEntry] = Field(default_factory=list)
    created_by: ActorRef
    created_at: datetime
    updated_at: datetime
    version: int = 1

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "inc", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        return _require_nonempty(value, field="incident title")

    @field_validator("priority")
    @classmethod
    def _priority(cls, value: float) -> float:
        return _require_score(value, field="priority")

    @field_validator("alert_ids")
    @classmethod
    def _alert_ids(cls, values: list[str]) -> list[str]:
        return _require_unique_typed_ids(values, "alt", field="alert_ids")

    @field_validator("affected_object_ids")
    @classmethod
    def _affected_object_ids(cls, values: list[str]) -> list[str]:
        return _require_unique_typed_ids(values, "obj", field="affected_object_ids")

    @field_validator("top_mission_id")
    @classmethod
    def _top_mission_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "obj", field="top_mission_id")

    @field_validator("risk_score")
    @classmethod
    def _risk_score(cls, value: float | None) -> float | None:
        if value is None:
            return None
        return _require_score(value, field="risk_score")

    @field_validator("version")
    @classmethod
    def _version(cls, value: int) -> int:
        return _require_positive_int(value, field="version")


class Hunt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("hnt"))
    tenant_id: str | None = None
    name: str
    hypothesis: str
    query: dict[str, Any] = Field(default_factory=dict)
    saved_by: ActorRef

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "hnt", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("name", "hypothesis")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        return _require_nonempty(value, field="hunt field")


class SOCConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correlation: dict[str, Any] = Field(default_factory=dict)
    incident_window_seconds: int = 3600
    batch_size: int = 100

    @model_validator(mode="before")
    @classmethod
    def _raw_mapping(cls, data: object) -> object:
        if isinstance(data, Mapping):
            raw_correlation = data.get("correlation")
            if raw_correlation is not None and not isinstance(raw_correlation, Mapping):
                raise SOCConfigInvalid("correlation must be a mapping")
        return data

    @field_validator("incident_window_seconds", "batch_size", mode="before")
    @classmethod
    def _positive_int(cls, value: object, info: ValidationInfo) -> int:
        return _require_positive_int(value, field=info.field_name or "SOCConfig integer field")

    @field_validator("correlation")
    @classmethod
    def _correlation(cls, values: dict[str, Any]) -> dict[str, Any]:
        for key, value in values.items():
            _require_nonempty(key, field="correlation key")
            _validate_correlation_value(key, value)
        return values


def _validate_correlation_value(key: str, value: Any) -> None:
    if key in {"group_by", "fields"}:
        if not isinstance(value, list) or not value:
            raise SOCConfigInvalid(f"correlation.{key} must be a non-empty list")
        for item in value:
            if not isinstance(item, str):
                raise SOCConfigInvalid(f"correlation.{key} entries must be strings")
            _require_nonempty(item, field=f"correlation.{key}")
        if len(value) != len(set(value)):
            raise SOCConfigInvalid(f"correlation.{key} must not contain duplicates")
        return
    if key in {"window_seconds", "max_alerts", "max_groups"}:
        _require_positive_int(value, field=f"correlation.{key}")
        return
    if key.endswith("_seconds") or key.startswith("max_"):
        _require_positive_int(value, field=f"correlation.{key}")
        return
    if isinstance(value, dict):
        for nested_key, nested_value in value.items():
            if not isinstance(nested_key, str):
                raise SOCConfigInvalid(f"correlation.{key} keys must be strings")
            _validate_correlation_value(nested_key, nested_value)
        return
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, str):
                raise SOCConfigInvalid(f"correlation.{key} entries must be strings")
            _require_nonempty(item, field=f"correlation.{key}")
        return
    if value is not None and not isinstance(value, str | int | float | bool):
        raise SOCConfigInvalid(f"correlation.{key} must be JSON-compatible")
