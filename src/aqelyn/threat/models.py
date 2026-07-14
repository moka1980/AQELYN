"""Threat Intelligence Fusion models and config validation (EA-0014 T1)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aqelyn.conventions import ActorRef, require_tenant_id, require_typed_id
from aqelyn.conventions.errors import ThreatConfigInvalid
from aqelyn.graph import Path
from aqelyn.objects import SourceRef

IndicatorType = Literal["domain", "ip", "hash", "url"]
MatchVia = Literal["attribute", "graph"]

VALID_INDICATOR_TYPES: frozenset[str] = frozenset(("domain", "ip", "hash", "url"))
THREAT_INDICATOR_OBJECT_TYPE = "threat_indicator"
THREAT_ACTOR_OBJECT_TYPE = "threat_actor"
THREAT_CAMPAIGN_OBJECT_TYPE = "threat_campaign"
THREAT_OBJECT_TYPES: tuple[str, ...] = (
    THREAT_INDICATOR_OBJECT_TYPE,
    THREAT_ACTOR_OBJECT_TYPE,
    THREAT_CAMPAIGN_OBJECT_TYPE,
)


def _require_nonempty(value: str, *, field: str) -> str:
    if not value.strip():
        raise ThreatConfigInvalid(f"{field} must not be empty")
    return value


def _require_unit_interval(value: float, *, field: str) -> float:
    if not math.isfinite(value) or value < 0.0 or value > 1.0:
        raise ThreatConfigInvalid(f"{field} must be in [0,1]")
    return value


def _require_positive_float(value: float, *, field: str) -> float:
    if not math.isfinite(value) or value <= 0.0:
        raise ThreatConfigInvalid(f"{field} must be > 0")
    return value


class FeedRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    raw: dict[str, Any]
    received_at: datetime
    evidence_id: str | None = None

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


class ThreatIndicator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    tenant_id: str | None = None
    indicator_type: IndicatorType
    value: str
    ttps: list[str] = Field(default_factory=list)
    actor_ids: list[str] = Field(default_factory=list)
    campaign_ids: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    first_seen_at: datetime
    last_seen_at: datetime
    sources: list[SourceRef]
    expires_at: datetime | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("value")
    @classmethod
    def _value(cls, value: str) -> str:
        return _require_nonempty(value, field="indicator value")

    @field_validator("ttps")
    @classmethod
    def _ttps(cls, values: list[str]) -> list[str]:
        return _dedupe_nonempty(values, field="ttps")

    @field_validator("actor_ids", "campaign_ids")
    @classmethod
    def _object_ids(cls, values: list[str]) -> list[str]:
        out = [require_typed_id(value, "obj", field="threat object ref") for value in values]
        if len(out) != len(set(out)):
            raise ThreatConfigInvalid("threat object refs must not contain duplicates")
        return out

    @field_validator("confidence")
    @classmethod
    def _confidence(cls, value: float) -> float:
        return _require_unit_interval(value, field="indicator confidence")

    @field_validator("sources")
    @classmethod
    def _sources(cls, values: list[SourceRef]) -> list[SourceRef]:
        if not values:
            raise ThreatConfigInvalid("indicator sources must not be empty")
        return values


class ThreatMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indicator_id: str
    asset_id: str
    match_type: str
    confidence: float
    evidence_id: str | None = None
    reason: str
    via: Path | None = None

    @field_validator("indicator_id")
    @classmethod
    def _indicator_id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="indicator_id")

    @field_validator("asset_id")
    @classmethod
    def _asset_id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="asset_id")

    @field_validator("match_type", "reason")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        return _require_nonempty(value, field="threat match field")

    @field_validator("confidence")
    @classmethod
    def _confidence(cls, value: float) -> float:
        return _require_unit_interval(value, field="match confidence")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="evidence_id")


class MatchReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matches: list[ThreatMatch] = Field(default_factory=list)
    evaluated: int
    truncated: bool = False

    @field_validator("evaluated")
    @classmethod
    def _evaluated(cls, value: int) -> int:
        if isinstance(value, bool) or value < 0:
            raise ThreatConfigInvalid("evaluated must be >= 0")
        return value


class QuarantinedFeedRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record: FeedRecord
    reason: str
    quarantined_at: datetime

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return _require_nonempty(value, field="quarantine reason")


class ThreatSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    reliability: float
    meta: dict[str, Any] = Field(default_factory=dict)
    set_by: ActorRef
    set_at: datetime
    version: int = 1

    @field_validator("source_id")
    @classmethod
    def _source_id(cls, value: str) -> str:
        if value == "*":
            return value
        return require_typed_id(value, "src", field="source_id")

    @field_validator("reliability")
    @classmethod
    def _reliability(cls, value: float) -> float:
        return _require_unit_interval(value, field="source reliability")

    @field_validator("version")
    @classmethod
    def _version(cls, value: int) -> int:
        if isinstance(value, bool) or value < 1:
            raise ThreatConfigInvalid("source version must be >= 1")
        return value


class FusionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_reliability: dict[str, float] = Field(default_factory=dict)
    recency_half_life_days: float = 30.0
    correlation: dict[str, Any] = Field(default_factory=dict)
    min_match_confidence: float = 0.5
    quarantine_on_malformed: bool = True

    @field_validator("source_reliability")
    @classmethod
    def _source_reliability(cls, values: dict[str, float]) -> dict[str, float]:
        out: dict[str, float] = {}
        for source_id, reliability in values.items():
            out[require_typed_id(source_id, "src", field="source_reliability")] = (
                _require_unit_interval(reliability, field=f"source_reliability[{source_id!r}]")
            )
        return out

    @field_validator("recency_half_life_days")
    @classmethod
    def _recency_half_life_days(cls, value: float) -> float:
        return _require_positive_float(value, field="recency_half_life_days")

    @field_validator("min_match_confidence")
    @classmethod
    def _min_match_confidence(cls, value: float) -> float:
        return _require_unit_interval(value, field="min_match_confidence")

    @model_validator(mode="after")
    def _correlation_mapping(self) -> FusionConfig:
        if not isinstance(self.correlation, dict):
            raise ThreatConfigInvalid("correlation must be a mapping")
        return self


def _dedupe_nonempty(values: list[str], *, field: str) -> list[str]:
    out: list[str] = []
    for value in values:
        out.append(_require_nonempty(value, field=field))
    if len(out) != len(set(out)):
        raise ThreatConfigInvalid(f"{field} must not contain duplicates")
    return out
