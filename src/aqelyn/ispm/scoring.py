"""Replayable account-control posture scoring (EA-0033 G4)."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from pydantic import ValidationError

from aqelyn.conventions import canonical_json
from aqelyn.conventions.errors import (
    DerivationNotReplayable,
    ISPMConfigInvalid,
    PostureScoreNotReplayable,
    StoreUnavailable,
)
from aqelyn.decision import ClaimRef, Derivation, DerivationStep, build_derivation, replay
from aqelyn.decision.operations import JsonMap, JsonMapping, OperationRegistry
from aqelyn.iag import AccessRisk
from aqelyn.ispm.models import IdentityPostureScore, NormalizedIdentity, PostureFactor
from aqelyn.mission.models import DEFAULT_SEVERITY_WEIGHTS, MissionImpactResult
from aqelyn.risk.models import Risk, RiskConfig, SignalRef
from aqelyn.risk.scoring import score_risk
from aqelyn.trust import TrustAssessment

_POSTURE_SCORE_OP = "ispm_posture_score"
_FACTOR_ORDER = ("iag_risk", "mfa", "lifecycle", "last_activity")


class IdentityMissionOwner(Protocol):
    async def mission_impact(self, object_id: str) -> MissionImpactResult: ...


@dataclass(frozen=True)
class ComposedPosture:
    score: float
    factors: list[PostureFactor]
    iag_risks: list[AccessRisk]
    derivation: Derivation
    confidence: float
    statement: str


def compose_posture(
    identity: NormalizedIdentity,
    account_id: str,
    *,
    iag_risks: Sequence[AccessRisk],
    trust: TrustAssessment,
    mission: MissionImpactResult,
    factor_weights: Mapping[str, float],
    risk_config: RiskConfig,
    computed_at: datetime,
) -> ComposedPosture:
    _validate_factor_weights(factor_weights)
    if mission.truncated:
        raise StoreUnavailable("EA-0007 mission traversal was truncated")
    selected_risks = sorted(
        (AccessRisk.model_validate(risk.model_dump(mode="json")) for risk in iag_risks),
        key=_risk_key,
    )
    mission_factor, top_mission_id = _mission_factor(mission)
    owner_risk = _owner_risk(
        identity,
        account_id,
        iag_risks=selected_risks,
        mission_factor=mission_factor if selected_risks else 0.0,
        top_mission_id=top_mission_id,
        risk_config=risk_config,
        computed_at=computed_at,
    )
    factors = _posture_factors(
        identity,
        iag_risks=selected_risks,
        trust=trust,
        mission=mission,
        owner_risk=owner_risk,
        factor_weights=factor_weights,
    )
    score_result = posture_score_result(
        [],
        {"factors": [factor.model_dump(mode="json") for factor in factors]},
    )
    score = _numeric(score_result.get("score"), field="posture score")
    derivation = _score_derivation(
        identity,
        account_id,
        factors=factors,
        iag_risks=selected_risks,
        trust=trust,
        mission=mission,
        owner_risk=owner_risk,
    )
    return ComposedPosture(
        score=score,
        factors=factors,
        iag_risks=selected_risks,
        derivation=derivation,
        confidence=trust.score,
        statement=_statement(
            account_id,
            score=score,
            factors=factors,
            risk_count=len(selected_risks),
        ),
    )


def validate_replayable_score(score: IdentityPostureScore) -> IdentityPostureScore:
    try:
        stored = IdentityPostureScore.model_validate(score.model_dump(mode="json"))
    except (ISPMConfigInvalid, ValidationError) as exc:
        raise PostureScoreNotReplayable("stored posture score is internally inconsistent") from exc
    try:
        result = replay(stored.derivation, registry=posture_operation_registry())
    except (DerivationNotReplayable, ISPMConfigInvalid) as exc:
        raise PostureScoreNotReplayable("posture score derivation does not replay") from exc
    replayed_score = _numeric(result.get("score"), field="replayed posture score")
    if not math.isclose(replayed_score, stored.score, rel_tol=0.0, abs_tol=1e-6):
        raise PostureScoreNotReplayable("posture score does not match replayed result")
    params = _score_params(stored.derivation)
    expected_factors = [factor.model_dump(mode="json") for factor in stored.factors]
    if canonical_json(params.get("factors")) != canonical_json(expected_factors):
        raise PostureScoreNotReplayable("posture factors do not match the derivation")
    expected_risks = [risk.model_dump(mode="json") for risk in stored.iag_risks]
    if canonical_json(params.get("iag_risks")) != canonical_json(expected_risks):
        raise PostureScoreNotReplayable("EA-0011 risks do not match the derivation")
    trust_payload = params.get("trust")
    if not isinstance(trust_payload, Mapping):
        raise PostureScoreNotReplayable("posture derivation is missing EA-0006 trust")
    confidence = _numeric(trust_payload.get("score"), field="derivation trust score")
    if not math.isclose(confidence, stored.confidence, rel_tol=0.0, abs_tol=1e-6):
        raise PostureScoreNotReplayable("posture confidence does not match EA-0006 trust")
    return stored


def posture_operation_registry() -> OperationRegistry:
    registry = OperationRegistry()
    registry.register(_POSTURE_SCORE_OP, posture_score_result)
    return registry


def posture_score_result(
    inputs: Sequence[JsonMapping],
    params: JsonMapping,
) -> JsonMap:
    _ = inputs
    raw_factors = params.get("factors")
    if not isinstance(raw_factors, Sequence) or isinstance(raw_factors, str | bytes):
        raise ISPMConfigInvalid("posture derivation requires factor records")
    factors = [PostureFactor.model_validate(item) for item in raw_factors]
    total_weight = sum(factor.weight for factor in factors)
    known = [factor for factor in factors if factor.status == "known"]
    known_weight = sum(factor.weight for factor in known)
    if not math.isclose(total_weight, 1.0, rel_tol=0.0, abs_tol=1e-6):
        raise ISPMConfigInvalid("posture derivation factor weights must sum to 1")
    if known_weight <= 0.0:
        raise ISPMConfigInvalid("posture derivation requires a known factor")
    weighted = sum(
        (factor.value if factor.value is not None else 0.0) * factor.weight for factor in known
    )
    known_only_score = weighted / known_weight
    coverage_adjustment = known_weight / total_weight
    return {
        "score": round(known_only_score * coverage_adjustment * 100.0, 6),
        "known_only_score": round(known_only_score * 100.0, 6),
        "coverage_adjustment": round(coverage_adjustment, 6),
        "known_weight": round(known_weight, 6),
    }


def _owner_risk(
    identity: NormalizedIdentity,
    account_id: str,
    *,
    iag_risks: Sequence[AccessRisk],
    mission_factor: float,
    top_mission_id: str | None,
    risk_config: RiskConfig,
    computed_at: datetime,
) -> Risk:
    signals = [
        SignalRef(
            kind="identity",
            ref_id=risk.subject_id,
            weight=DEFAULT_SEVERITY_WEIGHTS[risk.severity],
            evidence_id=identity.evidence_id,
        )
        for risk in iag_risks
    ]
    if not signals:
        signals = [
            SignalRef(
                kind="identity",
                ref_id=account_id,
                weight=0.0,
                evidence_id=identity.evidence_id,
            )
        ]
    impact = max(
        (DEFAULT_SEVERITY_WEIGHTS[risk.severity] for risk in iag_risks),
        default=0.0,
    )
    seed = Risk(
        id=account_id,
        tenant_id=identity.tenant_id,
        correlation_key=f"ispm:{account_id}",
        title=f"Account control risk for {account_id}",
        category="identity_control_posture",
        likelihood=0.0,
        impact=impact,
        score=0.0,
        band="within_appetite",
        signals=signals,
        affected_object_ids=[account_id],
        reason="EA-0011 owner risks composed through EA-0013 scoring.",
        first_seen_at=computed_at,
        last_scored_at=computed_at,
    )
    return score_risk(
        seed,
        config=risk_config,
        mission_factor=mission_factor,
        top_mission_id=top_mission_id,
    )


def _posture_factors(
    identity: NormalizedIdentity,
    *,
    iag_risks: Sequence[AccessRisk],
    trust: TrustAssessment,
    mission: MissionImpactResult,
    owner_risk: Risk,
    factor_weights: Mapping[str, float],
) -> list[PostureFactor]:
    risk_factor = PostureFactor(
        name="iag_risk",
        value=round(1.0 - owner_risk.score / 100.0, 6),
        weight=factor_weights["iag_risk"],
        status="known",
        source_ref={
            "owner": "EA-0011",
            "records": [risk.model_dump(mode="json") for risk in iag_risks],
            "ea0013_risk": owner_risk.model_dump(mode="json"),
            "ea0006_trust": trust.model_dump(mode="json"),
            "ea0007_mission": mission.model_dump(mode="json"),
        },
        reason=(
            f"EA-0011 returned {len(iag_risks)} account or identity control risks; "
            f"EA-0013 scored their composed risk at {owner_risk.score:.0f}."
        ),
    )
    controls = identity.controls.model_dump(mode="json")
    factors = [risk_factor]
    for name in _FACTOR_ORDER[1:]:
        fact = getattr(identity.controls, name)
        if fact.state == "unknown":
            factors.append(
                PostureFactor(
                    name=name,
                    value=None,
                    weight=factor_weights[name],
                    status="unknown",
                    source_ref={"owner": "EA-0033", "control": controls[name]},
                    reason=fact.reason,
                )
            )
            continue
        factors.append(
            PostureFactor(
                name=name,
                value=1.0 if fact.state == "present" else 0.0,
                weight=factor_weights[name],
                status="known",
                source_ref={"owner": "EA-0033", "control": controls[name]},
                reason=fact.reason,
            )
        )
    return factors


def _score_derivation(
    identity: NormalizedIdentity,
    account_id: str,
    *,
    factors: Sequence[PostureFactor],
    iag_risks: Sequence[AccessRisk],
    trust: TrustAssessment,
    mission: MissionImpactResult,
    owner_risk: Risk,
) -> Derivation:
    risk_claim = ClaimRef(
        kind="risk",
        ref_id=identity.object_id,
        evidence_id=identity.evidence_id,
    )
    trust_claim = ClaimRef(
        kind="trust",
        ref_id=trust.subject_ref,
        evidence_id=identity.evidence_id,
    )
    _, top_mission_id = _mission_factor(mission)
    mission_claim = ClaimRef(
        kind="mission",
        ref_id=top_mission_id or account_id,
        evidence_id=identity.evidence_id,
    )
    params: dict[str, Any] = {
        "factors": [factor.model_dump(mode="json") for factor in factors],
        "iag_risks": [risk.model_dump(mode="json") for risk in iag_risks],
        "ea0013_risk": owner_risk.model_dump(mode="json"),
        "trust": trust.model_dump(mode="json"),
        "mission": mission.model_dump(mode="json"),
    }
    output = posture_score_result([], params)
    step = DerivationStep(
        seq=1,
        op=_POSTURE_SCORE_OP,
        input_refs=[risk_claim.ref_id, trust_claim.ref_id, mission_claim.ref_id],
        params=params,
        output=output,
        note=(
            "Compose exact EA-0011 owner risks through EA-0013 with EA-0006 trust, "
            "EA-0007 mission impact, and evidence-backed account control facts."
        ),
    )
    return build_derivation(
        inputs=[risk_claim, trust_claim, mission_claim],
        steps=[step],
        model_version=1,
        engine_version="ispm-posture/v1",
        registry=posture_operation_registry(),
    )


def _score_params(derivation: Derivation) -> Mapping[str, Any]:
    for step in derivation.steps:
        if step.op == _POSTURE_SCORE_OP:
            return step.params
    raise PostureScoreNotReplayable("posture derivation is missing its score operation")


def _mission_factor(result: MissionImpactResult) -> tuple[float, str | None]:
    if not result.impacts:
        return 0.0, None
    selected = max(
        result.impacts,
        key=lambda impact: (impact.impact_score, impact.mission.id),
    )
    return selected.impact_score, selected.mission.id


def _statement(
    account_id: str,
    *,
    score: float,
    factors: Sequence[PostureFactor],
    risk_count: int,
) -> str:
    states = ", ".join(
        f"{factor.name}=" + ("unknown" if factor.value is None else f"{factor.value:.3f}")
        for factor in factors
        if factor.name != "iag_risk"
    )
    return (
        f"Account {account_id} control posture is {score:.1f}/100: {states}; "
        f"EA-0011 reported {risk_count} access-control risks."
    )


def _validate_factor_weights(weights: Mapping[str, float]) -> None:
    if set(weights) != set(_FACTOR_ORDER):
        raise ISPMConfigInvalid(
            "factor_weights must define iag_risk, mfa, lifecycle, and last_activity"
        )
    if not math.isclose(sum(weights.values()), 1.0, rel_tol=0.0, abs_tol=1e-6):
        raise ISPMConfigInvalid("factor_weights must sum to 1 within 1e-6")


def _risk_key(risk: AccessRisk) -> tuple[str, str, bytes]:
    return risk.subject_id, risk.kind, canonical_json(risk.model_dump(mode="json"))


def _numeric(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise PostureScoreNotReplayable(f"{field} must be numeric")
    selected = float(value)
    if not math.isfinite(selected):
        raise PostureScoreNotReplayable(f"{field} must be finite")
    return selected
