"""Deterministic Risk Intelligence scoring (EA-0013 R1)."""

from __future__ import annotations

import math
from collections.abc import Sequence

from aqelyn.conventions.errors import RiskConfigInvalid
from aqelyn.mission.models import MissionImpactResult
from aqelyn.risk.models import Risk, RiskBand, RiskConfig, RiskMissionContext


def score_risk(
    risk: Risk,
    *,
    config: RiskConfig | None = None,
    mission_context: RiskMissionContext | None = None,
) -> Risk:
    cfg = config or RiskConfig()
    selected_mission = RiskMissionContext.model_validate(
        (mission_context or risk.mission_context).model_dump(mode="json")
    )
    likelihood = _likelihood(risk, cfg)
    if selected_mission.status == "known":
        if selected_mission.factor is None:
            raise RiskConfigInvalid("known mission context requires a factor")
        impact = max(risk.impact, selected_mission.factor)
    else:
        impact = 1.0
    score = _score(float(round(100.0 * (cfg.w_likelihood * likelihood + cfg.w_impact * impact))))
    band = band_for_score(score, cfg)
    mission_reason = (
        f"mission factor {selected_mission.factor:.3f}"
        if selected_mission.factor is not None
        else (
            "mission context unknown "
            f"({selected_mission.unknown_cause}); impact uses the conservative upper bound"
        )
    )
    reason = (
        f"Risk score {score:.0f} uses combiner {cfg.combiner}: "
        f"likelihood {likelihood:.3f} at weight {cfg.w_likelihood:.3f}, "
        f"impact {impact:.3f} at weight {cfg.w_impact:.3f}, and {mission_reason}."
    )
    factors = {
        "likelihood": likelihood,
        "impact": impact,
        "w_likelihood": cfg.w_likelihood,
        "w_impact": cfg.w_impact,
    }
    if selected_mission.factor is not None:
        factors["mission_factor"] = selected_mission.factor
    return risk.model_copy(
        update={
            "likelihood": likelihood,
            "impact": impact,
            "score": score,
            "band": band,
            "top_mission_id": selected_mission.top_mission_id,
            "mission_context": selected_mission,
            "reason": reason,
            "factors": factors,
        },
        deep=True,
    )


def mission_context_from_results(
    results: Sequence[MissionImpactResult] | None,
) -> RiskMissionContext:
    if results is None:
        return RiskMissionContext(
            status="unknown",
            unknown_cause="provider_unconfigured",
            reason="EA-0007 mission owner is not configured.",
        )
    if not results:
        return RiskMissionContext(
            status="unknown",
            unknown_cause="input_missing",
            reason="EA-0007 mission context has no affected object to assess.",
        )
    if any(result.truncated for result in results):
        return RiskMissionContext(
            status="unknown",
            unknown_cause="assessment_incomplete",
            reason="EA-0007 mission traversal was truncated before impact was complete.",
        )
    if any(not result.impacts for result in results):
        return RiskMissionContext(
            status="unknown",
            unknown_cause="input_missing",
            reason="EA-0007 returned no mission impact for an affected object.",
        )
    selected = min(
        (impact for result in results for impact in result.impacts),
        key=lambda impact: (-impact.impact_score, impact.mission.id),
    )
    return RiskMissionContext(
        status="known",
        factor=selected.impact_score,
        top_mission_id=selected.mission.id,
        reason=selected.reason,
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
