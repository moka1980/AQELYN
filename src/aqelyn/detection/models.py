"""Threat Detection & Analytics models and config validation (EA-0017 D1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aqelyn.conventions import new_id, require_tenant_id, require_typed_id
from aqelyn.conventions.errors import DetectionConfigInvalid, PolicyConfigInvalid
from aqelyn.policy import Condition

DetectionRuleKind = Literal["rule", "behavioral", "correlation"]
AnomalyMeasureKind = Literal["z_score", "percentile", "rate_change"]

VALID_RULE_KINDS: Final[frozenset[str]] = frozenset(("rule", "behavioral", "correlation"))
VALID_MEASURES: Final[frozenset[str]] = frozenset(("z_score", "percentile", "rate_change"))
VALID_SEVERITIES: Final[frozenset[str]] = frozenset(("low", "medium", "high", "critical"))


def _nonempty(value: str, *, field: str) -> str:
    if not value.strip():
        raise DetectionConfigInvalid(f"{field} must not be empty")
    return value


def _nonempty_list(values: list[str], *, field: str) -> list[str]:
    if not values:
        raise DetectionConfigInvalid(f"{field} must not be empty")
    for value in values:
        _nonempty(value, field=field)
    if len(values) != len(set(values)):
        raise DetectionConfigInvalid(f"{field} must not contain duplicates")
    return values


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DetectionConfigInvalid(f"{field} must be >= 1")
    return value


def _unit_interval(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise DetectionConfigInvalid(f"{field} must be in [0,1]")
    selected = float(value)
    if selected < 0.0 or selected > 1.0:
        raise DetectionConfigInvalid(f"{field} must be in [0,1]")
    return selected


def _threshold(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise DetectionConfigInvalid(f"{field} must be >= 0")
    selected = float(value)
    if selected < 0.0:
        raise DetectionConfigInvalid(f"{field} must be >= 0")
    return selected


class SignalRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: str
    source_id: str
    evidence_id: str | None = None
    observed_at: datetime | None = None

    @field_validator("source_type", "source_id")
    @classmethod
    def _nonempty_text(cls, value: str) -> str:
        return _nonempty(value, field="signal ref")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="evidence_id")


class DetectionRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str
    kind: str
    condition: Condition
    subject_type: str
    technique_ids: list[str] = Field(default_factory=list)
    severity: str
    enabled: bool = True
    version: int = 1
    tenant_id: str | None = None

    @field_validator("id", "name", "description", "subject_type")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="detection rule field")

    @field_validator("kind")
    @classmethod
    def _kind(cls, value: str) -> str:
        if value not in VALID_RULE_KINDS:
            raise DetectionConfigInvalid(f"unknown detection rule kind: {value!r}")
        return value

    @field_validator("condition", mode="before")
    @classmethod
    def _condition(cls, value: object) -> Condition:
        if isinstance(value, Condition):
            return value
        try:
            return Condition.model_validate(value)
        except PolicyConfigInvalid as exc:
            raise DetectionConfigInvalid(exc.message) from exc

    @field_validator("technique_ids")
    @classmethod
    def _technique_ids(cls, values: list[str]) -> list[str]:
        return _nonempty_list(values, field="technique_ids") if values else []

    @field_validator("severity")
    @classmethod
    def _severity(cls, value: str) -> str:
        if value not in VALID_SEVERITIES:
            raise DetectionConfigInvalid(f"unknown severity: {value!r}")
        return value

    @field_validator("version", mode="before")
    @classmethod
    def _version(cls, value: object) -> int:
        return _positive_int(value, field="rule version")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)


class BehaviorProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("prf"))
    tenant_id: str | None = None
    subject_ref: str
    metric: str
    window_days: int
    baseline: dict[str, Any] = Field(default_factory=dict)
    computed_at: datetime
    version: int = 1
    insufficient_data: bool = False

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "prf", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("subject_ref", "metric")
    @classmethod
    def _profile_text(cls, value: str) -> str:
        return _nonempty(value, field="profile field")

    @field_validator("window_days", "version", mode="before")
    @classmethod
    def _positive(cls, value: object) -> int:
        return _positive_int(value, field="profile integer")


class AnomalyMeasure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str
    observed: float
    baseline_value: float
    measure: str
    value: float
    threshold: float
    profile_version: int

    @field_validator("metric")
    @classmethod
    def _metric(cls, value: str) -> str:
        return _nonempty(value, field="metric")

    @field_validator("measure")
    @classmethod
    def _measure(cls, value: str) -> str:
        if value not in VALID_MEASURES:
            raise DetectionConfigInvalid(f"unknown anomaly measure: {value!r}")
        return value

    @field_validator("threshold", mode="before")
    @classmethod
    def _threshold(cls, value: object) -> float:
        return _threshold(value, field="threshold")

    @field_validator("profile_version", mode="before")
    @classmethod
    def _profile_version(cls, value: object) -> int:
        return _positive_int(value, field="profile_version")


class ThreatDetection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("det"))
    tenant_id: str | None = None
    rule_id: str
    rule_version: int
    subject_ref: str
    kind: str
    signal_refs: list[SignalRef]
    anomaly: AnomalyMeasure | None = None
    confidence: float
    severity: str
    severity_score: float
    technique_ids: list[str] = Field(default_factory=list)
    evidence_id: str
    profile_version: int | None = None
    reason: str
    detected_at: datetime

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "det", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("rule_id", "subject_ref", "kind", "reason")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="detection field")

    @field_validator("rule_version", mode="before")
    @classmethod
    def _rule_version(cls, value: object) -> int:
        return _positive_int(value, field="rule_version")

    @field_validator("profile_version", mode="before")
    @classmethod
    def _profile_version(cls, value: object) -> int | None:
        if value is None:
            return None
        return _positive_int(value, field="profile_version")

    @field_validator("signal_refs")
    @classmethod
    def _signals(cls, values: list[SignalRef]) -> list[SignalRef]:
        if not values:
            raise DetectionConfigInvalid("signal_refs must not be empty")
        return values

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, value: object) -> float:
        return _unit_interval(value, field="confidence")

    @field_validator("severity")
    @classmethod
    def _severity(cls, value: str) -> str:
        if value not in VALID_SEVERITIES:
            raise DetectionConfigInvalid(f"unknown severity: {value!r}")
        return value

    @field_validator("severity_score", mode="before")
    @classmethod
    def _severity_score(cls, value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise DetectionConfigInvalid("severity_score must be in [0,100]")
        selected = float(value)
        if selected < 0.0 or selected > 100.0:
            raise DetectionConfigInvalid("severity_score must be in [0,100]")
        return selected

    @field_validator("technique_ids")
    @classmethod
    def _techniques(cls, values: list[str]) -> list[str]:
        return _nonempty_list(values, field="technique_ids") if values else []

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")

    @model_validator(mode="after")
    def _pins_profile_for_anomaly(self) -> ThreatDetection:
        if self.anomaly is not None and self.profile_version != self.anomaly.profile_version:
            raise DetectionConfigInvalid("anomaly profile_version must match detection")
        return self


class Projection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("prj"))
    tenant_id: str | None = None
    subject_ref: str
    statement: str
    basis: dict[str, Any]
    horizon_days: int
    confidence: float
    advisory: bool = True

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "prj", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("subject_ref", "statement")
    @classmethod
    def _projection_text(cls, value: str) -> str:
        return _nonempty(value, field="projection field")

    @field_validator("horizon_days", mode="before")
    @classmethod
    def _horizon(cls, value: object) -> int:
        return _positive_int(value, field="horizon_days")

    @field_validator("confidence", mode="before")
    @classmethod
    def _projection_confidence(cls, value: object) -> float:
        return _unit_interval(value, field="confidence")

    @field_validator("advisory")
    @classmethod
    def _advisory(cls, value: bool) -> bool:
        if value is not True:
            raise DetectionConfigInvalid("projection advisory must be true")
        return value


class DetectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thresholds: dict[str, float] = Field(default_factory=dict)
    window_days: int = 30
    batch_size: int = 100
    min_confidence: float = 0.0
    min_samples: int = 5

    @field_validator("thresholds", mode="before")
    @classmethod
    def _thresholds(cls, value: object) -> dict[str, float]:
        if not isinstance(value, dict):
            raise DetectionConfigInvalid("thresholds must be an object")
        out: dict[str, float] = {}
        for key, raw in value.items():
            if not isinstance(key, str) or not key.strip():
                raise DetectionConfigInvalid("threshold keys must be non-empty strings")
            out[key] = _threshold(raw, field=f"thresholds.{key}")
        return out

    @field_validator("window_days", "batch_size", "min_samples", mode="before")
    @classmethod
    def _positive_ints(cls, value: object) -> int:
        return _positive_int(value, field="config integer")

    @field_validator("min_confidence", mode="before")
    @classmethod
    def _min_confidence(cls, value: object) -> float:
        return _unit_interval(value, field="min_confidence")
