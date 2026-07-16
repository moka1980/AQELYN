"""Pure forecasting methods and registry (EA-0021 P1)."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from itertools import pairwise
from statistics import fmean
from typing import Protocol

from aqelyn.conventions.errors import ForecastConfigInvalid, UnknownMethod
from aqelyn.forecast.models import VALID_METHODS, Interval, Method


class MethodResult:
    def __init__(self, *, point: float, interval: Interval) -> None:
        self.point = point
        self.interval = interval

    def as_dict(self) -> dict[str, object]:
        return {
            "point": self.point,
            "interval": self.interval.model_dump(mode="json"),
        }


class PureForecastFn(Protocol):
    def __call__(
        self,
        history: Sequence[float],
        *,
        horizon_days: int,
        level: float,
        params: Mapping[str, object] | None = None,
    ) -> MethodResult: ...


class MethodRegistry:
    def __init__(self) -> None:
        self._methods: dict[str, PureForecastFn] = {}

    def register(self, name: Method, fn: PureForecastFn) -> None:
        _validate_method_name(name)
        if name in self._methods:
            raise ForecastConfigInvalid(f"forecast method already registered: {name}")
        self._methods[name] = fn

    def get(self, name: Method) -> PureForecastFn:
        if name not in self._methods:
            raise UnknownMethod(f"unknown forecast method: {name}")
        return self._methods[name]

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._methods))


def default_method_registry() -> MethodRegistry:
    registry = MethodRegistry()
    registry.register("moving_average", moving_average)
    registry.register("linear_trend", linear_trend)
    registry.register("seasonal_naive", seasonal_naive)
    registry.register("holt_winters", holt_winters)
    registry.register("rate_extrapolation", rate_extrapolation)
    return registry


def moving_average(
    history: Sequence[float],
    *,
    horizon_days: int,
    level: float,
    params: Mapping[str, object] | None = None,
) -> MethodResult:
    values = _validated_history(history)
    _validate_horizon_and_level(horizon_days=horizon_days, level=level)
    window = _positive_param(params, "window", default=len(values))
    selected = values[-min(window, len(values)) :]
    point = fmean(selected)
    return _result(point=point, values=selected, level=level)


def linear_trend(
    history: Sequence[float],
    *,
    horizon_days: int,
    level: float,
    params: Mapping[str, object] | None = None,
) -> MethodResult:
    values = _validated_history(history, min_points=2)
    _validate_horizon_and_level(horizon_days=horizon_days, level=level)
    xs = [float(i) for i in range(len(values))]
    x_mean = fmean(xs)
    y_mean = fmean(values)
    denom = sum((x - x_mean) ** 2 for x in xs)
    slope = (
        0.0
        if denom == 0.0
        else sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values, strict=True)) / denom
    )
    intercept = y_mean - slope * x_mean
    point = intercept + slope * float(len(values) - 1 + horizon_days)
    fitted = [intercept + slope * x for x in xs]
    residuals = [actual - fit for actual, fit in zip(values, fitted, strict=True)]
    return _result(point=point, values=residuals, level=level, center_values=False)


def seasonal_naive(
    history: Sequence[float],
    *,
    horizon_days: int,
    level: float,
    params: Mapping[str, object] | None = None,
) -> MethodResult:
    values = _validated_history(history)
    _validate_horizon_and_level(horizon_days=horizon_days, level=level)
    season_length = _positive_param(params, "season_length", default=7)
    if len(values) <= season_length:
        point = values[-1]
    else:
        index = len(values) - season_length + ((horizon_days - 1) % season_length)
        point = values[index] if index < len(values) else values[-season_length]
    return _result(point=point, values=values[-min(season_length, len(values)) :], level=level)


def holt_winters(
    history: Sequence[float],
    *,
    horizon_days: int,
    level: float,
    params: Mapping[str, object] | None = None,
) -> MethodResult:
    values = _validated_history(history, min_points=2)
    _validate_horizon_and_level(horizon_days=horizon_days, level=level)
    alpha = _unit_param(params, "alpha", default=0.5)
    beta = _unit_param(params, "beta", default=0.3)
    level_value = values[0]
    trend = values[1] - values[0]
    fitted: list[float] = []
    for value in values[1:]:
        previous_level = level_value
        fitted.append(level_value + trend)
        level_value = alpha * value + (1.0 - alpha) * (level_value + trend)
        trend = beta * (level_value - previous_level) + (1.0 - beta) * trend
    point = level_value + trend * horizon_days
    residuals = [actual - fit for actual, fit in zip(values[1:], fitted, strict=True)]
    return _result(point=point, values=residuals, level=level, center_values=False)


def rate_extrapolation(
    history: Sequence[float],
    *,
    horizon_days: int,
    level: float,
    params: Mapping[str, object] | None = None,
) -> MethodResult:
    values = _validated_history(history, min_points=2)
    _validate_horizon_and_level(horizon_days=horizon_days, level=level)
    diffs = [right - left for left, right in pairwise(values)]
    rate = fmean(diffs)
    point = values[-1] + rate * horizon_days
    return _result(point=point, values=diffs, level=level, center_values=False)


def _validated_history(history: Sequence[float], *, min_points: int = 1) -> list[float]:
    if len(history) < min_points:
        raise ForecastConfigInvalid(f"history must contain at least {min_points} point(s)")
    values: list[float] = []
    for value in history:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ForecastConfigInvalid("history values must be finite numbers")
        selected = float(value)
        if not math.isfinite(selected):
            raise ForecastConfigInvalid("history values must be finite numbers")
        values.append(selected)
    return values


def _validate_horizon_and_level(*, horizon_days: int, level: float) -> None:
    if isinstance(horizon_days, bool) or not isinstance(horizon_days, int) or horizon_days < 1:
        raise ForecastConfigInvalid("horizon_days must be >= 1")
    if isinstance(level, bool) or not isinstance(level, int | float):
        raise ForecastConfigInvalid("level must be in (0,1)")
    selected = float(level)
    if not math.isfinite(selected) or selected <= 0.0 or selected >= 1.0:
        raise ForecastConfigInvalid("level must be in (0,1)")


def _validate_method_name(name: str) -> None:
    if name not in VALID_METHODS:
        raise ForecastConfigInvalid(f"unknown forecast method: {name!r}")


def _positive_param(params: Mapping[str, object] | None, name: str, *, default: int) -> int:
    value = default if params is None or name not in params else params[name]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ForecastConfigInvalid(f"{name} must be >= 1")
    return value


def _unit_param(params: Mapping[str, object] | None, name: str, *, default: float) -> float:
    value = default if params is None or name not in params else params[name]
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ForecastConfigInvalid(f"{name} must be in (0,1)")
    selected = float(value)
    if not math.isfinite(selected) or selected <= 0.0 or selected >= 1.0:
        raise ForecastConfigInvalid(f"{name} must be in (0,1)")
    return selected


def _result(
    *,
    point: float,
    values: Sequence[float],
    level: float,
    center_values: bool = True,
) -> MethodResult:
    spread = _spread(values, center_values=center_values)
    margin = spread * (1.0 + float(level))
    low = min(point, point - margin)
    high = max(point, point + margin)
    return MethodResult(point=point, interval=Interval(low=low, high=high, level=level))


def _spread(values: Sequence[float], *, center_values: bool) -> float:
    if not values:
        return 0.0
    if center_values:
        center = fmean(values)
        residuals = [value - center for value in values]
    else:
        residuals = list(values)
    variance = fmean([value * value for value in residuals])
    return math.sqrt(variance)
