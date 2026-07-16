"""Trend analysis helpers for Predictive Analytics & Forecasting (EA-0021 P3)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime
from statistics import fmean

from pydantic import BaseModel, ConfigDict, field_validator

from aqelyn.conventions import canonical_json
from aqelyn.conventions.errors import ForecastConfigInvalid, InsufficientHistory
from aqelyn.forecast.models import BasisRef, TrendRecord


class MetricObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_at: datetime
    value: float
    basis: BasisRef

    @field_validator("value", mode="before")
    @classmethod
    def _value(cls, value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ForecastConfigInvalid("history value must be a finite number")
        selected = float(value)
        if not math.isfinite(selected):
            raise ForecastConfigInvalid("history value must be a finite number")
        return selected


def build_trend_record(
    *,
    metric: str,
    window_days: int,
    tenant_id: str | None,
    observations: Sequence[MetricObservation],
    min_history_points: int,
) -> TrendRecord:
    ordered = ordered_observations(observations)
    if len(ordered) < min_history_points:
        raise InsufficientHistory(
            f"{metric} needs at least {min_history_points} history points; got {len(ordered)}"
        )
    values = [row.value for row in ordered]
    slope, r_squared = _linear_fit(values)
    direction = _direction(slope)
    return TrendRecord(
        tenant_id=tenant_id,
        metric=metric,
        window_days=window_days,
        slope=slope,
        r_squared=r_squared,
        direction=direction,
        basis=unique_basis(ordered),
        reason=(
            f"{metric} {direction}: slope {slope:.3f} over {len(values)} points "
            f"in {window_days} days with r_squared {r_squared:.3f}."
        ),
    )


def ordered_observations(observations: Sequence[MetricObservation]) -> list[MetricObservation]:
    return sorted(
        [MetricObservation.model_validate(row.model_dump(mode="json")) for row in observations],
        key=lambda row: (row.observed_at, row.basis.kind, row.basis.ref),
    )


def unique_basis(observations: Sequence[MetricObservation]) -> list[BasisRef]:
    seen: set[bytes] = set()
    selected: list[BasisRef] = []
    for row in ordered_observations(observations):
        key = canonical_json(row.basis.model_dump(mode="json"))
        if key in seen:
            continue
        seen.add(key)
        selected.append(row.basis.model_copy(deep=True))
    selected.sort(key=lambda item: (item.kind, item.ref, item.evidence_id or ""))
    return selected


def _linear_fit(values: Sequence[float]) -> tuple[float, float]:
    xs = [float(index) for index in range(len(values))]
    x_mean = fmean(xs)
    y_mean = fmean(values)
    denom = sum((x - x_mean) ** 2 for x in xs)
    slope = (
        0.0
        if denom == 0.0
        else sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values, strict=True)) / denom
    )
    intercept = y_mean - slope * x_mean
    fitted = [intercept + slope * x for x in xs]
    residual_sum = sum((actual - fit) ** 2 for actual, fit in zip(values, fitted, strict=True))
    total_sum = sum((actual - y_mean) ** 2 for actual in values)
    if total_sum == 0.0:
        return slope, 1.0 if residual_sum == 0.0 else 0.0
    return slope, max(0.0, min(1.0, 1.0 - (residual_sum / total_sum)))


def _direction(slope: float) -> str:
    if abs(slope) < 1e-12:
        return "flat"
    return "up" if slope > 0.0 else "down"
