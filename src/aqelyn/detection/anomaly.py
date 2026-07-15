"""Explicit anomaly measures for Threat Detection (EA-0017 D3)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from aqelyn.conventions.errors import DetectionConfigInvalid
from aqelyn.detection.models import AnomalyMeasure, BehaviorProfile
from aqelyn.evidence import EvidenceRecord

MeasureName = Literal["z_score", "percentile", "rate_change"]


@dataclass(frozen=True)
class ObservedMetric:
    subject_ref: str
    subject_type: str
    metric: str
    value: float
    observed_at: datetime
    evidence: EvidenceRecord
    measure: MeasureName = "z_score"


def anomaly_measure(
    profile: BehaviorProfile,
    *,
    observed: float,
    measure: MeasureName,
    threshold: float,
) -> AnomalyMeasure:
    _require_ready_profile(profile)
    selected_observed = _finite(observed, field="observed")
    selected_threshold = _finite(threshold, field="threshold")
    if selected_threshold < 0.0:
        raise DetectionConfigInvalid("threshold must be >= 0")

    if measure == "z_score":
        baseline_value = _baseline_float(profile, "mean")
        stddev = _baseline_float(profile, "stddev")
        value = _z_score(selected_observed, baseline_value, stddev)
    elif measure == "percentile":
        baseline_value = _baseline_float(profile, "p95")
        value = _ratio(selected_observed, baseline_value)
    else:
        baseline_value = _baseline_float(profile, "mean")
        value = _rate_change(selected_observed, baseline_value)

    return AnomalyMeasure(
        metric=profile.metric,
        observed=selected_observed,
        baseline_value=baseline_value,
        measure=measure,
        value=value,
        threshold=selected_threshold,
        profile_version=profile.version,
    )


def is_anomalous(measure: AnomalyMeasure) -> bool:
    if measure.measure == "percentile":
        return measure.value >= measure.threshold
    return abs(measure.value) >= measure.threshold


def anomaly_reason(
    *,
    subject_ref: str,
    anomaly: AnomalyMeasure,
    rule_version: int,
) -> str:
    comparison = "ratio" if anomaly.measure == "percentile" else "value"
    return (
        f"{subject_ref} {anomaly.metric} baseline was {anomaly.baseline_value:.3f}; "
        f"observed {anomaly.observed:.3f}. {anomaly.measure} {comparison} "
        f"{anomaly.value:.3f} met threshold {anomaly.threshold:.3f} using profile "
        f"v{anomaly.profile_version} and rule v{rule_version}."
    )


def _require_ready_profile(profile: BehaviorProfile) -> None:
    if profile.insufficient_data or bool(profile.baseline.get("insufficient_data")):
        raise DetectionConfigInvalid("profile has insufficient data")
    if profile.baseline.get("n", 0) < 1:
        raise DetectionConfigInvalid("profile baseline has no samples")


def _baseline_float(profile: BehaviorProfile, key: str) -> float:
    raw = profile.baseline.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise DetectionConfigInvalid(f"profile baseline missing numeric {key}")
    return _finite(float(raw), field=f"baseline.{key}")


def _finite(value: float, *, field: str) -> float:
    selected = float(value)
    if not math.isfinite(selected):
        raise DetectionConfigInvalid(f"{field} must be finite")
    return selected


def _z_score(observed: float, mean: float, stddev: float) -> float:
    if stddev < 0.0:
        raise DetectionConfigInvalid("baseline.stddev must be >= 0")
    if stddev == 0.0:
        return 0.0 if observed == mean else observed - mean
    return (observed - mean) / stddev


def _ratio(observed: float, baseline: float) -> float:
    if baseline == 0.0:
        return 0.0 if observed == 0.0 else observed
    return observed / baseline


def _rate_change(observed: float, baseline: float) -> float:
    if baseline == 0.0:
        return 0.0 if observed == 0.0 else observed
    return (observed - baseline) / abs(baseline)
