"""Versioned behavior profile construction (EA-0017 D2)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime, timedelta

from aqelyn.conventions import utc_now
from aqelyn.conventions.errors import DetectionConfigInvalid
from aqelyn.detection.models import BehaviorProfile, DetectionConfig
from aqelyn.detection.store import ProfileStore, validate_tenant

Observation = tuple[datetime, float]


async def build_profile(
    *,
    subject_ref: str,
    metric: str,
    tenant_id: str | None,
    observations: Sequence[Observation],
    profile_store: ProfileStore,
    config: DetectionConfig | None = None,
    as_of: datetime | None = None,
) -> BehaviorProfile:
    selected_config = config or DetectionConfig()
    selected_tenant = validate_tenant(tenant_id)
    selected_as_of = as_of or utc_now()
    window_start = selected_as_of - timedelta(days=selected_config.window_days)
    values = _window_values(observations, window_start=window_start, as_of=selected_as_of)
    baseline = _baseline(
        values,
        window_start=window_start,
        window_end=selected_as_of,
        min_samples=selected_config.min_samples,
    )
    latest = await profile_store.latest(
        subject_ref=subject_ref,
        metric=metric,
        tenant_id=selected_tenant,
    )
    profile = BehaviorProfile(
        id="" if latest is None else latest.id,
        tenant_id=selected_tenant,
        subject_ref=subject_ref,
        metric=metric,
        window_days=selected_config.window_days,
        baseline=baseline,
        computed_at=selected_as_of,
        version=1 if latest is None else latest.version + 1,
        insufficient_data=bool(baseline["insufficient_data"]),
    )
    return await profile_store.put(profile)


def _window_values(
    observations: Sequence[Observation],
    *,
    window_start: datetime,
    as_of: datetime,
) -> list[float]:
    values: list[float] = []
    for observed_at, value in observations:
        if observed_at.tzinfo is None:
            raise DetectionConfigInvalid("observation timestamp must be timezone-aware")
        if isinstance(value, bool):
            raise DetectionConfigInvalid("observation value must be numeric")
        selected = float(value)
        if not math.isfinite(selected):
            raise DetectionConfigInvalid("observation value must be finite")
        if window_start <= observed_at <= as_of:
            values.append(selected)
    values.sort()
    return values


def _baseline(
    values: Sequence[float],
    *,
    window_start: datetime,
    window_end: datetime,
    min_samples: int,
) -> dict[str, object]:
    n = len(values)
    out: dict[str, object] = {
        "n": n,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "insufficient_data": n < min_samples,
    }
    if n == 0:
        return out

    mean = sum(values) / n
    variance = sum((value - mean) ** 2 for value in values) / n
    out.update(
        {
            "mean": mean,
            "stddev": math.sqrt(variance),
            "p95": _nearest_rank(values, 0.95),
            "min": values[0],
            "max": values[-1],
        }
    )
    return out


def _nearest_rank(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise DetectionConfigInvalid("cannot compute percentile without values")
    index = max(0, min(len(values) - 1, math.ceil(percentile * len(values)) - 1))
    return values[index]
