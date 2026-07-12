"""Trust Engine models and config validation (EA-0006 TR1)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from aqelyn.conventions import ActorRef, require_typed_id
from aqelyn.conventions.errors import SchemaValidationError, TrustConfigInvalid

TrustLevel = Literal["low", "medium", "high"]


def _require_unit_interval(value: float, *, field: str) -> float:
    if not math.isfinite(value) or value < 0.0 or value > 1.0:
        raise TrustConfigInvalid(f"{field} must be in [0,1]")
    return value


def _validate_reliability_key(value: str) -> str:
    if value == "*":
        return value
    if value.startswith("method:") and value != "method:":
        return value
    try:
        return require_typed_id(value, "src", field="key")
    except SchemaValidationError as exc:
        raise TrustConfigInvalid("key must be a src_ id, method:<name>, or *") from exc


class SourceReliability(BaseModel):
    key: str
    weight: float
    rationale: str
    set_by: ActorRef
    set_at: datetime
    version: int = 1

    @field_validator("key")
    @classmethod
    def _key(cls, value: str) -> str:
        return _validate_reliability_key(value)

    @field_validator("weight")
    @classmethod
    def _weight(cls, value: float) -> float:
        return _require_unit_interval(value, field="weight")

    @field_validator("rationale")
    @classmethod
    def _rationale(cls, value: str) -> str:
        if not value.strip():
            raise TrustConfigInvalid("rationale must not be empty")
        return value

    @field_validator("version")
    @classmethod
    def _version(cls, value: int) -> int:
        if value < 1:
            raise TrustConfigInvalid("version must be >= 1")
        return value


class EvidenceContribution(BaseModel):
    evidence_id: str
    weight: float
    source_reliability: float
    type_weight: float
    recency_factor: float
    collector_confidence: float
    age_days: float

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")


class TrustAssessment(BaseModel):
    subject_ref: str
    score: float
    level: TrustLevel
    method: str
    contributions: list[EvidenceContribution] = Field(default_factory=list)
    reason: str
    no_evidence: bool
    computed_at: datetime


class Decision(BaseModel):
    decision: str
    score: float
    threshold: float
    rationale: str


class TrustThresholds(BaseModel):
    low: float = 0.34
    high: float = 0.67

    @field_validator("low", "high")
    @classmethod
    def _threshold(cls, value: float) -> float:
        return _require_unit_interval(value, field="threshold")

    @model_validator(mode="after")
    def _ordered(self) -> TrustThresholds:
        if self.low > self.high:
            raise TrustConfigInvalid("thresholds.low must be <= thresholds.high")
        return self


class TrustConfig(BaseModel):
    type_weights: dict[str, float] = Field(default_factory=dict)
    thresholds: TrustThresholds = Field(default_factory=TrustThresholds)
    half_life_days: float = 90.0
    recency_floor: float = 0.1
    default_reliability: float = 0.5

    @field_validator("type_weights")
    @classmethod
    def _type_weights(cls, value: dict[str, float]) -> dict[str, float]:
        for key, weight in value.items():
            _require_unit_interval(weight, field=f"type_weights[{key!r}]")
        return dict(value)

    @field_validator("half_life_days")
    @classmethod
    def _half_life_days(cls, value: float) -> float:
        if not math.isfinite(value) or value <= 0.0:
            raise TrustConfigInvalid("half_life_days must be > 0")
        return value

    @field_validator("recency_floor")
    @classmethod
    def _recency_floor(cls, value: float) -> float:
        return _require_unit_interval(value, field="recency_floor")

    @field_validator("default_reliability")
    @classmethod
    def _default_reliability(cls, value: float) -> float:
        return _require_unit_interval(value, field="default_reliability")
