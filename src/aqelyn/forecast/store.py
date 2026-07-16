"""Forecast persistence protocols and replay gates (EA-0021 P2)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from aqelyn.conventions import ActorRef, canonical_json, require_tenant_id, require_typed_id
from aqelyn.conventions.errors import (
    AQError,
    ForecastConfigInvalid,
    ForecastNotReplayable,
    SchemaValidationError,
)
from aqelyn.decision import Derivation, replay
from aqelyn.decision.operations import (
    JsonMap,
    JsonMapping,
    OperationRegistry,
    default_operation_registry,
)
from aqelyn.forecast.models import (
    VALID_METHODS,
    Forecast,
    Interval,
    Method,
    Outcome,
    PredictionModel,
)

_FORECAST_RESULT_OP = "forecast_result"


class ForecastStore(Protocol):
    async def put(self, forecast: Forecast) -> Forecast: ...

    async def get(self, forecast_id: str, *, tenant_id: str | None = None) -> Forecast | None: ...

    async def record_outcome(
        self,
        forecast_id: str,
        outcome: Outcome,
        *,
        tenant_id: str | None = None,
    ) -> Forecast: ...

    async def due_for_scoring(self, *, tenant_id: str | None, now: datetime) -> list[Forecast]: ...

    async def query(
        self, *, tenant_id: str | None, metric: str | None = None, limit: int = 100
    ) -> list[Forecast]: ...


class PredictionModelStore(Protocol):
    async def put(self, model: PredictionModel) -> PredictionModel: ...

    async def get(
        self, model_id: str, *, tenant_id: str | None = None
    ) -> PredictionModel | None: ...

    async def active(self, method: Method, *, tenant_id: str | None = None) -> PredictionModel: ...

    async def promote(
        self,
        model_id: str,
        *,
        by: ActorRef,
        reason: str,
        evidence_id: str,
        tenant_id: str | None = None,
    ) -> PredictionModel: ...

    async def query(
        self, *, tenant_id: str | None, method: Method | None = None, limit: int = 100
    ) -> list[PredictionModel]: ...


def validate_forecast_id(value: str, *, field: str = "forecast_id") -> str:
    return require_typed_id(value, "fct", field=field)


def validate_model_id(value: str, *, field: str = "model_id") -> str:
    return require_typed_id(value, "pdm", field=field)


def validate_tenant(value: str | None) -> str | None:
    return require_tenant_id(value)


def validate_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ForecastConfigInvalid("limit must be >= 1")
    return value


def validate_method(value: str) -> Method:
    if value not in VALID_METHODS:
        raise ForecastConfigInvalid(f"unknown forecast method: {value!r}")
    return value  # type: ignore[return-value]


def validate_model_version_number(value: int, *, field: str = "model version") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ForecastConfigInvalid(f"{field} must be >= 1")
    return value


def validate_replayable_forecast(forecast: Forecast) -> Forecast:
    if getattr(forecast, "interval", None) is None:
        raise ForecastConfigInvalid("forecast requires an interval")
    if not isinstance(forecast.derivation, Derivation):
        raise ForecastNotReplayable("forecast requires a derivation")
    stored = Forecast.model_validate(forecast.model_dump(mode="json"))
    expected = _expected_result(stored)
    try:
        result = replay(stored.derivation, registry=forecast_operation_registry())
    except AQError as exc:
        raise ForecastNotReplayable(exc.message) from exc
    if canonical_json(result) != canonical_json(expected):
        raise ForecastNotReplayable("forecast derivation result does not match point/interval")
    return stored


def validate_outcome(outcome: Outcome) -> Outcome:
    return Outcome.model_validate(outcome.model_dump(mode="json"))


def validate_prediction_model(model: PredictionModel) -> PredictionModel:
    return PredictionModel.model_validate(model.model_dump(mode="json"))


def validate_inactive_prediction_model(model: PredictionModel) -> PredictionModel:
    stored = validate_prediction_model(model)
    if stored.active:
        raise ForecastConfigInvalid("prediction models must be activated by promote")
    return stored


def validate_promotion_actor(value: ActorRef) -> ActorRef:
    if not isinstance(value, ActorRef):
        raise ForecastConfigInvalid("promotion requires an attributed ActorRef")
    return value


def validate_promotion_reason(value: str) -> str:
    if not value.strip():
        raise ForecastConfigInvalid("promotion reason must not be empty")
    return value


def validate_promotion_evidence_id(value: str) -> str:
    try:
        return require_typed_id(value, "evd", field="promotion evidence_id")
    except SchemaValidationError as exc:
        raise ForecastConfigInvalid("promotion requires evidence_id") from exc


def forecast_operation_registry() -> OperationRegistry:
    registry = default_operation_registry()
    registry.register(_FORECAST_RESULT_OP, forecast_result)
    return registry


def forecast_result(inputs: Sequence[JsonMapping], params: JsonMapping) -> JsonMap:
    _ = inputs
    point = _finite(params.get("point"), field="point")
    interval = Interval.model_validate(params.get("interval"))
    return {"point": point, "interval": interval.model_dump(mode="json")}


def _expected_result(forecast: Forecast) -> dict[str, object]:
    return {
        "point": forecast.point,
        "interval": forecast.interval.model_dump(mode="json"),
    }


def _finite(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ForecastConfigInvalid(f"{field} must be a finite number")
    selected = float(value)
    if not math.isfinite(selected):
        raise ForecastConfigInvalid(f"{field} must be a finite number")
    return selected
