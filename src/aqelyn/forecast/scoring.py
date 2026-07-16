"""Outcome scoring and published accuracy for Forecasting (EA-0021 P4)."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from aqelyn.evidence import EvidenceRecord
from aqelyn.forecast.models import AccuracyRecord, Forecast, ForecastPublication, Outcome
from aqelyn.forecast.trend import MetricObservation


class ActualValueSource(Protocol):
    async def actual(
        self,
        *,
        metric: str,
        at: datetime,
        tenant_id: str | None,
    ) -> MetricObservation | None: ...


class EvidenceRecorder(Protocol):
    async def add(self, record: EvidenceRecord) -> EvidenceRecord: ...


def scored_outcome(
    forecast: Forecast,
    *,
    actual: MetricObservation,
    evidence_id: str,
    scored_at: datetime,
) -> Outcome:
    value = _finite(actual.value)
    error = abs(value - forecast.point)
    return Outcome(
        actual=value,
        error=error,
        within_interval=forecast.interval.low <= value <= forecast.interval.high,
        scored_at=scored_at,
        evidence_id=evidence_id,
    )


def unscoreable_outcome(*, reason: str, evidence_id: str, scored_at: datetime) -> Outcome:
    return Outcome(
        within_interval=False,
        scored_at=scored_at,
        evidence_id=evidence_id,
        unscoreable=True,
        reason=reason,
    )


def accuracy_records(
    forecasts: Sequence[Forecast],
    *,
    method: str | None = None,
    metric: str | None = None,
    now: datetime,
) -> list[AccuracyRecord]:
    grouped: dict[tuple[str, str], list[Outcome]] = defaultdict(list)
    for forecast in forecasts:
        if method is not None and forecast.method != method:
            continue
        if metric is not None and forecast.metric != metric:
            continue
        if forecast.outcome is None:
            continue
        grouped[(forecast.method, forecast.metric)].append(forecast.outcome)

    records: list[AccuracyRecord] = []
    for (selected_method, selected_metric), outcomes in grouped.items():
        scored = [
            outcome for outcome in outcomes if not outcome.unscoreable and outcome.error is not None
        ]
        if scored:
            mae = sum(outcome.error or 0.0 for outcome in scored) / len(scored)
            within = sum(1 for outcome in scored if outcome.within_interval) / len(scored)
            updated_at = max(outcome.scored_at for outcome in outcomes)
        else:
            mae = 0.0
            within = 0.0
            updated_at = max((outcome.scored_at for outcome in outcomes), default=now)
        records.append(
            AccuracyRecord(
                method=selected_method,
                metric=selected_metric,
                n=len(scored),
                mae=mae,
                within_interval_pct=within,
                updated_at=updated_at,
            )
        )
    records.sort(key=lambda record: (record.method, record.metric))
    return records


def publish_forecasts(forecasts: Sequence[Forecast], *, now: datetime) -> list[ForecastPublication]:
    records = {
        (record.method, record.metric): record for record in accuracy_records(forecasts, now=now)
    }
    publications: list[ForecastPublication] = []
    for forecast in forecasts:
        accuracy = records.get((forecast.method, forecast.metric))
        if accuracy is None:
            accuracy = AccuracyRecord(
                method=forecast.method,
                metric=forecast.metric,
                n=0,
                mae=0.0,
                within_interval_pct=0.0,
                updated_at=now,
            )
        publications.append(ForecastPublication(forecast=forecast, accuracy=accuracy))
    return publications


def _finite(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError("actual value must be finite")
    selected = float(value)
    if not math.isfinite(selected):
        raise TypeError("actual value must be finite")
    return selected
