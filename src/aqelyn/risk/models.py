"""Risk Intelligence models and config validation (EA-0013 R1)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aqelyn.conventions import ActorRef, require_tenant_id, require_typed_id
from aqelyn.conventions.errors import RiskConfigInvalid

SignalKind = Literal["finding", "compliance", "identity", "config", "threat_intel"]
RiskBand = Literal["within_appetite", "elevated", "over_tolerance"]
RiskLifecycle = Literal["identified", "assessed", "treated", "closed"]
RiskTreatment = Literal["none", "accept", "mitigate", "transfer"]

VALID_SIGNAL_KINDS: frozenset[str] = frozenset(
    ("finding", "compliance", "identity", "config", "threat_intel")
)
VALID_BANDS: frozenset[str] = frozenset(("within_appetite", "elevated", "over_tolerance"))
VALID_COMBINERS: frozenset[str] = frozenset(("mission_weighted/v1",))
RISK_WEIGHT_EPSILON = 1e-6


def _require_nonempty(value: str, *, field: str) -> str:
    if not value.strip():
        raise RiskConfigInvalid(f"{field} must not be empty")
    return value


def _require_unit_interval(value: float, *, field: str) -> float:
    if not math.isfinite(value) or value < 0.0 or value > 1.0:
        raise RiskConfigInvalid(f"{field} must be in [0,1]")
    return value


def _require_score(value: float, *, field: str) -> float:
    if not math.isfinite(value) or value < 0.0 or value > 100.0:
        raise RiskConfigInvalid(f"{field} must be in [0,100]")
    return value


def _require_nonnegative_int(value: int, *, field: str) -> int:
    if isinstance(value, bool) or value < 0:
        raise RiskConfigInvalid(f"{field} must be >= 0")
    return value


def _require_positive_int(value: int, *, field: str) -> int:
    if isinstance(value, bool) or value < 1:
        raise RiskConfigInvalid(f"{field} must be >= 1")
    return value


class SignalRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: SignalKind
    ref_id: str
    weight: float
    evidence_id: str | None = None

    @field_validator("ref_id")
    @classmethod
    def _ref_id(cls, value: str) -> str:
        return _require_nonempty(value, field="ref_id")

    @field_validator("weight")
    @classmethod
    def _weight(cls, value: float) -> float:
        return _require_unit_interval(value, field="signal weight")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="evidence_id")


class AppetiteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    elevated: float = 40.0
    over: float = 70.0

    @field_validator("elevated", "over")
    @classmethod
    def _threshold(cls, value: float) -> float:
        return _require_score(value, field="appetite threshold")

    @model_validator(mode="after")
    def _ordered(self) -> AppetiteConfig:
        if self.elevated >= self.over:
            raise RiskConfigInvalid("appetite.elevated must be lower than appetite.over")
        return self


class RiskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    likelihood_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "finding": 1.0,
            "compliance": 0.7,
            "identity": 0.8,
            "config": 0.7,
            "threat_intel": 0.6,
        }
    )
    appetite: AppetiteConfig = Field(default_factory=AppetiteConfig)
    correlation: dict[str, Any] = Field(default_factory=dict)
    combiner: str = "mission_weighted/v1"
    w_likelihood: float = 0.5
    w_impact: float = 0.5

    @field_validator("likelihood_weights")
    @classmethod
    def _likelihood_weights(cls, values: dict[str, float]) -> dict[str, float]:
        if not values:
            raise RiskConfigInvalid("likelihood_weights must not be empty")
        out: dict[str, float] = {}
        for kind, weight in values.items():
            if kind not in VALID_SIGNAL_KINDS:
                raise RiskConfigInvalid(f"unknown signal kind in likelihood_weights: {kind!r}")
            out[kind] = _require_unit_interval(weight, field=f"likelihood_weights[{kind!r}]")
        return out

    @field_validator("combiner")
    @classmethod
    def _combiner(cls, value: str) -> str:
        selected = _require_nonempty(value, field="combiner")
        if selected not in VALID_COMBINERS:
            raise RiskConfigInvalid(f"unknown risk combiner: {selected!r}")
        return selected

    @field_validator("w_likelihood", "w_impact")
    @classmethod
    def _weight(cls, value: float) -> float:
        return _require_unit_interval(value, field="risk score weight")

    @model_validator(mode="after")
    def _consistent(self) -> RiskConfig:
        total = self.w_likelihood + self.w_impact
        if abs(total - 1.0) > RISK_WEIGHT_EPSILON:
            raise RiskConfigInvalid("w_likelihood + w_impact must sum to 1")
        return self


class Risk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    tenant_id: str | None = None
    correlation_key: str
    title: str
    category: str
    likelihood: float
    impact: float
    score: float
    band: RiskBand
    signals: list[SignalRef]
    affected_object_ids: list[str] = Field(default_factory=list)
    top_mission_id: str | None = None
    lifecycle: RiskLifecycle = "identified"
    treatment: RiskTreatment = "none"
    treatment_note: str | None = None
    treated_by: ActorRef | None = None
    reason: str
    factors: dict[str, float] = Field(default_factory=dict)
    first_seen_at: datetime
    last_scored_at: datetime
    version: int = 1

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return _require_nonempty(value, field="risk id")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("correlation_key", "title", "category", "reason")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        return _require_nonempty(value, field="risk field")

    @field_validator("likelihood", "impact")
    @classmethod
    def _unit_interval(cls, value: float) -> float:
        return _require_unit_interval(value, field="risk factor")

    @field_validator("score")
    @classmethod
    def _score(cls, value: float) -> float:
        return _require_score(value, field="risk score")

    @field_validator("signals")
    @classmethod
    def _signals(cls, values: list[SignalRef]) -> list[SignalRef]:
        if not values:
            raise RiskConfigInvalid("risk requires at least one signal")
        return values

    @field_validator("affected_object_ids")
    @classmethod
    def _affected_object_ids(cls, values: list[str]) -> list[str]:
        out = [require_typed_id(value, "obj", field="affected_object_ids") for value in values]
        if len(out) != len(set(out)):
            raise RiskConfigInvalid("affected_object_ids must not contain duplicates")
        return out

    @field_validator("top_mission_id")
    @classmethod
    def _top_mission_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "obj", field="top_mission_id")

    @field_validator("treatment_note")
    @classmethod
    def _treatment_note(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise RiskConfigInvalid("treatment_note must not be empty when present")
        return value

    @field_validator("factors")
    @classmethod
    def _factors(cls, values: dict[str, float]) -> dict[str, float]:
        out: dict[str, float] = {}
        for key, value in values.items():
            out[_require_nonempty(key, field="factors key")] = _require_score(
                value, field=f"factors[{key!r}]"
            )
        return out

    @field_validator("version")
    @classmethod
    def _version(cls, value: int) -> int:
        return _require_positive_int(value, field="version")


class RiskSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    tenant_id: str | None = None
    run_at: datetime
    total: int
    band_counts: dict[RiskBand, int] = Field(default_factory=dict)
    top_risks: list[str] = Field(default_factory=list)
    overall_exposure: float

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return _require_nonempty(value, field="risk snapshot id")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("total")
    @classmethod
    def _total(cls, value: int) -> int:
        return _require_nonnegative_int(value, field="total")

    @field_validator("band_counts")
    @classmethod
    def _band_counts(cls, values: dict[str, int]) -> dict[RiskBand, int]:
        out: dict[RiskBand, int] = {}
        for band, count in values.items():
            if band not in VALID_BANDS:
                raise RiskConfigInvalid(f"unknown band in band_counts: {band!r}")
            out[cast(RiskBand, band)] = _require_nonnegative_int(
                count, field=f"band_counts[{band!r}]"
            )
        return out

    @field_validator("top_risks")
    @classmethod
    def _top_risks(cls, values: list[str]) -> list[str]:
        out = [_require_nonempty(value, field="top_risks") for value in values]
        if len(out) != len(set(out)):
            raise RiskConfigInvalid("top_risks must not contain duplicates")
        return out

    @field_validator("overall_exposure")
    @classmethod
    def _overall_exposure(cls, value: float) -> float:
        return _require_score(value, field="overall_exposure")
