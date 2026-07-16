"""Predictive Analytics & Forecasting models and config validation (EA-0021 P1)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aqelyn.conventions import ActorRef, new_id, require_tenant_id, require_typed_id
from aqelyn.conventions.errors import ForecastConfigInvalid, ForecastNotReplayable
from aqelyn.decision import Derivation

Method = Literal[
    "moving_average",
    "linear_trend",
    "seasonal_naive",
    "holt_winters",
    "rate_extrapolation",
]
BasisKind = Literal["telemetry", "finding", "risk", "metric"]
TrendDirection = Literal["up", "down", "flat"]

VALID_METHODS: Final[frozenset[str]] = frozenset(
    (
        "moving_average",
        "linear_trend",
        "seasonal_naive",
        "holt_winters",
        "rate_extrapolation",
    )
)
VALID_BASIS_KINDS: Final[frozenset[str]] = frozenset(("telemetry", "finding", "risk", "metric"))
VALID_TREND_DIRECTIONS: Final[frozenset[str]] = frozenset(("up", "down", "flat"))
VALID_FORECAST_SUBJECT_PREFIXES: Final[tuple[str, ...]] = ("aggregate:", "system:")


def _nonempty(value: str, *, field: str) -> str:
    if not value.strip():
        raise ForecastConfigInvalid(f"{field} must not be empty")
    return value


def _finite(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ForecastConfigInvalid(f"{field} must be a finite number")
    selected = float(value)
    if not math.isfinite(selected):
        raise ForecastConfigInvalid(f"{field} must be a finite number")
    return selected


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ForecastConfigInvalid(f"{field} must be >= 1")
    return value


def _nonnegative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ForecastConfigInvalid(f"{field} must be >= 0")
    return value


def _unit_closed(value: object, *, field: str) -> float:
    selected = _finite(value, field=field)
    if selected < 0.0 or selected > 1.0:
        raise ForecastConfigInvalid(f"{field} must be in [0,1]")
    return selected


def _unit_open(value: object, *, field: str) -> float:
    selected = _finite(value, field=field)
    if selected <= 0.0 or selected >= 1.0:
        raise ForecastConfigInvalid(f"{field} must be in (0,1)")
    return selected


def _valid_method(value: str) -> str:
    if value not in VALID_METHODS:
        raise ForecastConfigInvalid(f"unknown forecast method: {value!r}")
    return value


class Interval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    low: float
    high: float
    level: float

    @field_validator("low", "high", mode="before")
    @classmethod
    def _bound(cls, value: object) -> float:
        return _finite(value, field="interval bound")

    @field_validator("level", mode="before")
    @classmethod
    def _level(cls, value: object) -> float:
        return _unit_open(value, field="interval level")

    @model_validator(mode="after")
    def _ordered(self) -> Interval:
        if self.low > self.high:
            raise ForecastConfigInvalid("interval.low must be <= interval.high")
        return self


class BasisRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    ref: str
    window: dict[str, Any]
    evidence_id: str | None = None

    @field_validator("kind")
    @classmethod
    def _kind(cls, value: str) -> str:
        if value not in VALID_BASIS_KINDS:
            raise ForecastConfigInvalid(f"unknown basis kind: {value!r}")
        return value

    @field_validator("ref")
    @classmethod
    def _ref(cls, value: str) -> str:
        return _nonempty(value, field="basis ref")

    @field_validator("window")
    @classmethod
    def _window(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ForecastConfigInvalid("basis window must not be empty")
        return dict(value)

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="evidence_id")


class TrendRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("trn"))
    tenant_id: str | None = None
    metric: str
    window_days: int
    slope: float
    r_squared: float
    direction: str
    basis: list[BasisRef]
    reason: str

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "trn", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("metric", "reason")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="trend field")

    @field_validator("window_days", mode="before")
    @classmethod
    def _window_days(cls, value: object) -> int:
        return _positive_int(value, field="window_days")

    @field_validator("slope", mode="before")
    @classmethod
    def _slope(cls, value: object) -> float:
        return _finite(value, field="slope")

    @field_validator("r_squared", mode="before")
    @classmethod
    def _r_squared(cls, value: object) -> float:
        return _unit_closed(value, field="r_squared")

    @field_validator("direction")
    @classmethod
    def _direction(cls, value: str) -> str:
        if value not in VALID_TREND_DIRECTIONS:
            raise ForecastConfigInvalid(f"unknown trend direction: {value!r}")
        return value

    @field_validator("basis")
    @classmethod
    def _basis(cls, values: list[BasisRef]) -> list[BasisRef]:
        if not values:
            raise ForecastConfigInvalid("trend basis must not be empty")
        return values


class Outcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actual: float | None = None
    error: float | None = None
    within_interval: bool = False
    scored_at: datetime
    evidence_id: str
    unscoreable: bool = False
    reason: str | None = None

    @field_validator("actual", "error", mode="before")
    @classmethod
    def _number(cls, value: object) -> float | None:
        if value is None:
            return None
        return _finite(value, field="outcome number")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _nonempty(value, field="outcome reason")

    @model_validator(mode="after")
    def _scored_or_flagged(self) -> Outcome:
        if self.unscoreable:
            if self.reason is None:
                raise ForecastConfigInvalid("unscoreable outcome requires a reason")
            return self
        if self.actual is None or self.error is None:
            raise ForecastConfigInvalid("scoreable outcome requires actual and error")
        return self


class Forecast(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("fct"))
    tenant_id: str | None = None
    metric: str
    subject_ref: str
    method: str
    model_version: int
    horizon_days: int
    issued_at: datetime
    resolves_at: datetime
    point: float
    interval: Interval
    confidence: float
    basis: list[BasisRef]
    derivation: Derivation
    advisory: bool = True
    statement: str
    outcome: Outcome | None = None

    @model_validator(mode="before")
    @classmethod
    def _requires_interval_and_derivation(cls, data: object) -> object:
        if isinstance(data, dict):
            if data.get("interval") is None:
                raise ForecastConfigInvalid("forecast requires an interval")
            if data.get("derivation") is None:
                raise ForecastNotReplayable("forecast requires a replayable derivation")
        return data

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "fct", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("metric", "statement")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="forecast field")

    @field_validator("subject_ref")
    @classmethod
    def _subject_ref(cls, value: str) -> str:
        selected = _nonempty(value, field="subject_ref")
        if not selected.startswith(VALID_FORECAST_SUBJECT_PREFIXES):
            raise ForecastConfigInvalid("forecast subject_ref must be aggregate/system scope")
        return selected

    @field_validator("method")
    @classmethod
    def _method(cls, value: str) -> str:
        return _valid_method(value)

    @field_validator("model_version", "horizon_days", mode="before")
    @classmethod
    def _positive(cls, value: object) -> int:
        return _positive_int(value, field="forecast integer")

    @field_validator("point", mode="before")
    @classmethod
    def _point(cls, value: object) -> float:
        return _finite(value, field="point")

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, value: object) -> float:
        return _unit_closed(value, field="confidence")

    @field_validator("basis")
    @classmethod
    def _basis(cls, values: list[BasisRef]) -> list[BasisRef]:
        if not values:
            raise ForecastConfigInvalid("forecast basis must not be empty")
        return values

    @field_validator("advisory")
    @classmethod
    def _advisory(cls, value: bool) -> bool:
        if value is not True:
            raise ForecastConfigInvalid("forecasts are advisory only")
        return value

    @model_validator(mode="after")
    def _time_order(self) -> Forecast:
        if self.resolves_at <= self.issued_at:
            raise ForecastConfigInvalid("resolves_at must be after issued_at")
        return self


class AccuracyRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: str
    metric: str
    n: int
    mae: float
    within_interval_pct: float
    updated_at: datetime

    @field_validator("method")
    @classmethod
    def _method(cls, value: str) -> str:
        return _valid_method(value)

    @field_validator("metric")
    @classmethod
    def _metric(cls, value: str) -> str:
        return _nonempty(value, field="metric")

    @field_validator("n", mode="before")
    @classmethod
    def _n(cls, value: object) -> int:
        return _nonnegative_int(value, field="n")

    @field_validator("mae", mode="before")
    @classmethod
    def _mae(cls, value: object) -> float:
        selected = _finite(value, field="mae")
        if selected < 0.0:
            raise ForecastConfigInvalid("mae must be >= 0")
        return selected

    @field_validator("within_interval_pct", mode="before")
    @classmethod
    def _within_interval_pct(cls, value: object) -> float:
        return _unit_closed(value, field="within_interval_pct")


class ForecastPublication(BaseModel):
    model_config = ConfigDict(extra="forbid")

    forecast: Forecast
    accuracy: AccuracyRecord


class PredictionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("pdm"))
    tenant_id: str | None = None
    method: str
    params: dict[str, Any]
    version: int
    promoted_by: ActorRef | None = None
    promoted_at: datetime | None = None
    active: bool = False
    evidence_id: str | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "pdm", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("method")
    @classmethod
    def _method(cls, value: str) -> str:
        return _valid_method(value)

    @field_validator("params")
    @classmethod
    def _params(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ForecastConfigInvalid("prediction model params must not be empty")
        return dict(value)

    @field_validator("version", mode="before")
    @classmethod
    def _version(cls, value: object) -> int:
        return _positive_int(value, field="model version")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="evidence_id")

    @model_validator(mode="after")
    def _promotion_integrity(self) -> PredictionModel:
        promoted = (
            self.promoted_by is not None
            or self.promoted_at is not None
            or self.evidence_id is not None
        )
        if self.active and (
            self.promoted_by is None or self.promoted_at is None or self.evidence_id is None
        ):
            raise ForecastConfigInvalid("active prediction models require attributed promotion")
        if promoted and (
            self.promoted_by is None or self.promoted_at is None or self.evidence_id is None
        ):
            raise ForecastConfigInvalid("prediction model promotion metadata must be complete")
        return self


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("scn"))
    tenant_id: str | None = None
    name: str
    assumptions: dict[str, Any]
    base_metric: str
    result: dict[str, Any]
    hypothetical: bool = True
    derivation: Derivation
    created_by: ActorRef

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "scn", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("name", "base_metric")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="scenario field")

    @field_validator("assumptions", "result")
    @classmethod
    def _mapping(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ForecastConfigInvalid("scenario mapping must not be empty")
        return dict(value)

    @field_validator("hypothetical")
    @classmethod
    def _hypothetical(cls, value: bool) -> bool:
        if value is not True:
            raise ForecastConfigInvalid("scenarios are hypothetical only")
        return value


class ForecastConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    methods_allowed: list[str] = Field(default_factory=lambda: sorted(VALID_METHODS))
    max_horizon_days: int = 365
    min_history_points: int = 7
    default_level: float = 0.8
    batch_size: int = 100

    @field_validator("methods_allowed")
    @classmethod
    def _methods_allowed(cls, values: list[str]) -> list[str]:
        if not values:
            raise ForecastConfigInvalid("methods_allowed must not be empty")
        for value in values:
            _valid_method(value)
        if len(values) != len(set(values)):
            raise ForecastConfigInvalid("methods_allowed must not contain duplicates")
        return list(values)

    @field_validator("max_horizon_days", "batch_size", mode="before")
    @classmethod
    def _positive(cls, value: object) -> int:
        return _positive_int(value, field="forecast config integer")

    @field_validator("min_history_points", mode="before")
    @classmethod
    def _min_history_points(cls, value: object) -> int:
        selected = _positive_int(value, field="min_history_points")
        if selected < 2:
            raise ForecastConfigInvalid("min_history_points must be >= 2")
        return selected

    @field_validator("default_level", mode="before")
    @classmethod
    def _default_level(cls, value: object) -> float:
        return _unit_open(value, field="default_level")
