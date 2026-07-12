"""Mission Engine models and config validation (EA-0007 M1)."""

from __future__ import annotations

import math
from typing import Final

from pydantic import BaseModel, Field, field_validator, model_validator

from aqelyn.conventions import require_typed_id
from aqelyn.conventions.errors import MissionConfigInvalid
from aqelyn.findings.models import Severity
from aqelyn.graph import Path

MISSION_OBJECT_TYPE: Final = "mission"
PRIORITY_WEIGHT_EPSILON: Final = 1e-6
DEFAULT_TIER_WEIGHTS: Final[dict[int, float]] = {1: 1.0, 2: 0.7, 3: 0.4, 4: 0.2}
DEFAULT_SEVERITY_WEIGHTS: Final[dict[Severity, float]] = {
    "info": 0.1,
    "low": 0.25,
    "medium": 0.5,
    "high": 0.75,
    "critical": 1.0,
}
DEFAULT_DEPENDENCY_TYPES: Final[tuple[str, ...]] = ("depends_on", "runs_on", "member_of")


def _require_unit_interval(value: float, *, field: str) -> float:
    if not math.isfinite(value) or value < 0.0 or value > 1.0:
        raise MissionConfigInvalid(f"{field} must be in [0,1]")
    return value


def _require_positive_int(value: int, *, field: str) -> int:
    if isinstance(value, bool) or value < 1:
        raise MissionConfigInvalid(f"{field} must be >= 1")
    return value


class MissionView(BaseModel):
    id: str
    display_name: str
    criticality_tier: int
    criticality_weight: float
    reason: str
    used_default_tier: bool = False

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="id")

    @field_validator("criticality_tier")
    @classmethod
    def _criticality_tier(cls, value: int) -> int:
        return _require_positive_int(value, field="criticality_tier")

    @field_validator("criticality_weight")
    @classmethod
    def _criticality_weight(cls, value: float) -> float:
        return _require_unit_interval(value, field="criticality_weight")

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        if not value.strip():
            raise MissionConfigInvalid("reason must not be empty")
        return value


class MissionImpact(BaseModel):
    mission: MissionView
    impact_score: float
    via: Path
    source_object_id: str
    reason: str

    @field_validator("impact_score")
    @classmethod
    def _impact_score(cls, value: float) -> float:
        return _require_unit_interval(value, field="impact_score")

    @field_validator("source_object_id")
    @classmethod
    def _source_object_id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="source_object_id")

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        if not value.strip():
            raise MissionConfigInvalid("reason must not be empty")
        return value


class MissionImpactResult(BaseModel):
    impacts: list[MissionImpact] = Field(default_factory=list)
    truncated: bool = False


class PriorityItem(BaseModel):
    finding_id: str
    priority_score: float
    mission_factor: float
    severity_weight: float
    confidence: float
    top_mission: MissionView | None = None
    reason: str

    @field_validator("finding_id")
    @classmethod
    def _finding_id(cls, value: str) -> str:
        return require_typed_id(value, "fnd", field="finding_id")

    @field_validator("priority_score", "mission_factor", "severity_weight", "confidence")
    @classmethod
    def _unit_interval(cls, value: float) -> float:
        return _require_unit_interval(value, field="priority factor")

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        if not value.strip():
            raise MissionConfigInvalid("reason must not be empty")
        return value


class MissionConfig(BaseModel):
    tier_weights: dict[int, float] = Field(default_factory=lambda: dict(DEFAULT_TIER_WEIGHTS))
    default_tier: int = 3
    severity_weights: dict[Severity, float] = Field(
        default_factory=lambda: dict(DEFAULT_SEVERITY_WEIGHTS)
    )
    w_severity: float = 0.4
    w_mission: float = 0.4
    w_confidence: float = 0.2
    dependency_types: tuple[str, ...] = DEFAULT_DEPENDENCY_TYPES
    max_depth: int = 6
    max_nodes: int = 10_000

    @field_validator("tier_weights")
    @classmethod
    def _tier_weights(cls, value: dict[int, float]) -> dict[int, float]:
        if not value:
            raise MissionConfigInvalid("tier_weights must not be empty")
        out: dict[int, float] = {}
        for tier, weight in value.items():
            out[_require_positive_int(tier, field="tier_weights key")] = _require_unit_interval(
                weight, field=f"tier_weights[{tier!r}]"
            )
        return out

    @field_validator("default_tier")
    @classmethod
    def _default_tier(cls, value: int) -> int:
        return _require_positive_int(value, field="default_tier")

    @field_validator("severity_weights")
    @classmethod
    def _severity_weights(cls, value: dict[Severity, float]) -> dict[Severity, float]:
        for severity, weight in value.items():
            _require_unit_interval(weight, field=f"severity_weights[{severity!r}]")
        return dict(value)

    @field_validator("w_severity", "w_mission", "w_confidence")
    @classmethod
    def _priority_weight(cls, value: float) -> float:
        return _require_unit_interval(value, field="priority weight")

    @model_validator(mode="after")
    def _consistent(self) -> MissionConfig:
        if self.default_tier not in self.tier_weights:
            raise MissionConfigInvalid("default_tier must exist in tier_weights")
        total = self.w_severity + self.w_mission + self.w_confidence
        if abs(total - 1.0) > PRIORITY_WEIGHT_EPSILON:
            raise MissionConfigInvalid("w_severity + w_mission + w_confidence must sum to 1")
        return self
