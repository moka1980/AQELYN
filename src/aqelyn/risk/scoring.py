"""Deterministic Risk Intelligence scoring (EA-0013 R1)."""

from __future__ import annotations

import math

from aqelyn.conventions.errors import RiskConfigInvalid
from aqelyn.risk.models import Risk, RiskBand, RiskConfig


def score_risk(
    risk: Risk,
    *,
    config: RiskConfig | None = None,
    mission_factor: float = 0.0,
    top_mission_id: str | None = None,
) -> Risk:
    cfg = config or RiskConfig()
    mission_factor = _unit(mission_factor, field="mission_factor")
    likelihood = _likelihood(risk, cfg)
    impact = max(risk.impact, mission_factor)
    score = _score(float(round(100.0 * (cfg.w_likelihood * likelihood + cfg.w_impact * impact))))
    band = band_for_score(score, cfg)
    reason = (
        f"Risk score {score:.0f} uses combiner {cfg.combiner}: "
        f"likelihood {likelihood:.3f} at weight {cfg.w_likelihood:.3f}, "
        f"impact {impact:.3f} at weight {cfg.w_impact:.3f}."
    )
    return risk.model_copy(
        update={
            "likelihood": likelihood,
            "impact": impact,
            "score": score,
            "band": band,
            "top_mission_id": top_mission_id if top_mission_id is not None else risk.top_mission_id,
            "reason": reason,
            "factors": {
                "likelihood": likelihood,
                "impact": impact,
                "mission_factor": mission_factor,
                "w_likelihood": cfg.w_likelihood,
                "w_impact": cfg.w_impact,
            },
        },
        deep=True,
    )


def band_for_score(score: float, config: RiskConfig | None = None) -> RiskBand:
    cfg = config or RiskConfig()
    checked = _score(score)
    if checked >= cfg.appetite.over:
        return "over_tolerance"
    if checked >= cfg.appetite.elevated:
        return "elevated"
    return "within_appetite"


def _likelihood(risk: Risk, config: RiskConfig) -> float:
    total = 0.0
    for signal in risk.signals:
        total += config.likelihood_weights.get(signal.kind, 0.0) * signal.weight
    return min(1.0, max(0.0, total))


def _unit(value: float, *, field: str) -> float:
    if not math.isfinite(value) or value < 0.0 or value > 1.0:
        raise RiskConfigInvalid(f"{field} must be in [0,1]")
    return value


def _score(value: float) -> float:
    if not math.isfinite(value):
        raise RiskConfigInvalid("risk score must be finite")
    return min(100.0, max(0.0, value))
