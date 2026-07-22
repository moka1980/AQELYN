"""Replayable per-credential governance scoring (C-032 J2)."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ValidationError

from aqelyn.conventions import canonical_json
from aqelyn.conventions.errors import (
    CredentialGovernanceNotReplayable,
    CryptoConfigInvalid,
    DerivationNotReplayable,
    StoreUnavailable,
)
from aqelyn.decision import ClaimRef, Derivation, DerivationStep, build_derivation, replay
from aqelyn.decision.operations import JsonMap, JsonMapping, OperationRegistry
from aqelyn.exposure import ExposureRecord
from aqelyn.governance import ComplianceSnapshot
from aqelyn.inventory import Ownership
from aqelyn.mission.models import MissionImpactResult
from aqelyn.risk.models import Risk, RiskConfig, SignalRef
from aqelyn.risk.scoring import score_risk
from aqelyn.secrets.ingest import crypto_asset_kind
from aqelyn.secrets.models import (
    GOVERNANCE_ACTIVE_EXPOSURE_CAP,
    GOVERNANCE_CRITICAL_EXPOSURE_THRESHOLD,
    GOVERNANCE_FACTOR_NAMES,
    GOVERNANCE_FACTOR_SETS,
    GOVERNANCE_UNKNOWN_PENALTY_POINTS,
    CertificateAsset,
    CredentialGovernanceScore,
    CryptoAsset,
    CryptographicExposure,
    CryptographicKey,
    GovernanceFactor,
    Lifecycle,
    SecretAsset,
    StorageSafetyClassification,
)
from aqelyn.trust import TrustAssessment

_GOVERNANCE_SCORE_OP = "crypto_governance_score"


@dataclass(frozen=True)
class ComposedCredentialGovernance:
    score: float
    factors: list[GovernanceFactor]
    active_critical_exposure_ids: list[str]
    owner_risk: Risk
    derivation: Derivation
    confidence: float
    statement: str


def compose_credential_governance(
    asset: CryptoAsset,
    *,
    ownership: Ownership | None,
    exposure: CryptographicExposure,
    owner_exposure: ExposureRecord | None,
    trust: TrustAssessment,
    mission: MissionImpactResult,
    compliance: ComplianceSnapshot,
    storage_safety: StorageSafetyClassification,
    factor_weights: Mapping[str, float],
    computed_at: datetime,
    risk_config: RiskConfig | None = None,
) -> ComposedCredentialGovernance:
    _validate_factor_weights(factor_weights)
    if mission.truncated:
        raise StoreUnavailable("EA-0007 mission traversal was truncated")
    direct = {
        "lifecycle": _lifecycle_factor(asset, factor_weights["lifecycle"]),
        "storage_safety": _storage_safety_factor(
            storage_safety,
            factor_weights["storage_safety"],
        ),
        "ownership": _ownership_factor(ownership, factor_weights["ownership"]),
        "exposure": _exposure_factor(
            exposure,
            owner_exposure,
            factor_weights["exposure"],
        ),
        "trust": _trust_factor(trust, factor_weights["trust"]),
        "compliance": _compliance_factor(compliance, factor_weights["compliance"]),
    }
    selected_risk_config = risk_config or RiskConfig()
    owner_risk = _owner_risk(
        asset,
        direct=direct,
        mission=mission,
        computed_at=computed_at,
        risk_config=selected_risk_config,
    )
    control_factors = [
        direct["lifecycle"],
        direct["storage_safety"],
        direct["ownership"],
        direct["exposure"],
        direct["compliance"],
    ]
    risk_known = all(factor.status == "known" for factor in control_factors)
    risk_factor = GovernanceFactor(
        name="owner_risk",
        rating=round(1.0 - owner_risk.score / 100.0, 6) if risk_known else None,
        weight=factor_weights["owner_risk"],
        status="known" if risk_known else "unknown",
        source_ref={
            "owner": "EA-0013",
            "record": owner_risk.model_dump(mode="json"),
            "mission": _mission_ref(mission),
        },
        reason=(
            f"EA-0013 composed credential governance risk at {owner_risk.score:.0f}."
            if risk_known
            else "EA-0013 risk is excluded because an underlying control fact is unknown."
        ),
    )
    factors = [risk_factor, *(direct[name] for name in GOVERNANCE_FACTOR_NAMES[1:])]
    active_ids = _active_critical_exposure_ids(owner_exposure)
    result = governance_score_result(
        [],
        {
            "factors": [factor.model_dump(mode="json") for factor in factors],
            "active_critical_exposure_ids": active_ids,
        },
    )
    score = _numeric(result.get("score"), field="governance score")
    derivation = _score_derivation(
        asset,
        factors=factors,
        active_critical_exposure_ids=active_ids,
        owner_risk=owner_risk,
        trust=trust,
        mission=mission,
        compliance=compliance,
        storage_safety=storage_safety,
        ownership=ownership,
        exposure=exposure,
        owner_exposure=owner_exposure,
    )
    return ComposedCredentialGovernance(
        score=score,
        factors=factors,
        active_critical_exposure_ids=active_ids,
        owner_risk=owner_risk,
        derivation=derivation,
        confidence=trust.score,
        statement=_statement(asset.id, score=score, factors=factors, active_ids=active_ids),
    )


def governance_score_result(inputs: Sequence[JsonMapping], params: JsonMapping) -> JsonMap:
    _ = inputs
    raw_factors = params.get("factors")
    if not isinstance(raw_factors, Sequence) or isinstance(raw_factors, str | bytes):
        raise CryptoConfigInvalid("governance derivation requires factor records")
    factors = [GovernanceFactor.model_validate(item) for item in raw_factors]
    names = [factor.name for factor in factors]
    selected = frozenset(names)
    if selected not in GOVERNANCE_FACTOR_SETS or len(names) != len(selected):
        raise CryptoConfigInvalid("governance derivation has an invalid factor set")
    total_weight = sum(factor.weight for factor in factors)
    known = [factor for factor in factors if factor.status == "known"]
    known_weight = sum(factor.weight for factor in known)
    if not math.isclose(total_weight, 1.0, rel_tol=0.0, abs_tol=1e-6):
        raise CryptoConfigInvalid("governance derivation factor weights must sum to 1")
    if known_weight <= 0.0:
        raise CryptoConfigInvalid("governance derivation requires a known factor")
    weighted = sum(
        factor.weight * (factor.rating if factor.rating is not None else 0.0) for factor in known
    )
    known_only_score = weighted / known_weight
    coverage_adjustment = known_weight / total_weight
    unknown_weight = total_weight - known_weight
    uncertainty_penalty = unknown_weight * GOVERNANCE_UNKNOWN_PENALTY_POINTS
    score = max(0.0, known_only_score * coverage_adjustment * 100.0 - uncertainty_penalty)
    active_ids = _exposure_ids(params.get("active_critical_exposure_ids"))
    exposure_cap_applied = bool(active_ids and score > GOVERNANCE_ACTIVE_EXPOSURE_CAP)
    if active_ids:
        score = min(score, GOVERNANCE_ACTIVE_EXPOSURE_CAP)
    return {
        "score": round(score, 6),
        "known_only_score": round(known_only_score * 100.0, 6),
        "coverage_adjustment": round(coverage_adjustment, 6),
        "known_weight": round(known_weight, 6),
        "uncertainty_penalty": round(uncertainty_penalty, 6),
        "exposure_cap_applied": exposure_cap_applied,
    }


def governance_operation_registry() -> OperationRegistry:
    registry = OperationRegistry()
    registry.register(_GOVERNANCE_SCORE_OP, governance_score_result)
    return registry


def validate_replayable_governance_score(
    score: CredentialGovernanceScore,
) -> CredentialGovernanceScore:
    try:
        stored = CredentialGovernanceScore.model_validate(score.model_dump(mode="json"))
    except (CryptoConfigInvalid, ValidationError) as exc:
        raise CredentialGovernanceNotReplayable(
            "stored credential governance score is internally inconsistent"
        ) from exc
    try:
        result = replay(stored.derivation, registry=governance_operation_registry())
    except (DerivationNotReplayable, CryptoConfigInvalid) as exc:
        raise CredentialGovernanceNotReplayable(
            "credential governance derivation does not replay"
        ) from exc
    replayed_score = _numeric(result.get("score"), field="replayed governance score")
    if not math.isclose(replayed_score, stored.score, rel_tol=0.0, abs_tol=1e-6):
        raise CredentialGovernanceNotReplayable(
            "credential governance score does not match replayed result"
        )
    params = _score_params(stored.derivation)
    expected_factors = [factor.model_dump(mode="json") for factor in stored.factors]
    if canonical_json(params.get("factors")) != canonical_json(expected_factors):
        raise CredentialGovernanceNotReplayable(
            "credential governance factors do not match the derivation"
        )
    if _exposure_ids(params.get("active_critical_exposure_ids")) != list(
        stored.active_critical_exposure_ids
    ):
        raise CredentialGovernanceNotReplayable(
            "active critical exposures do not match the derivation"
        )
    subject = params.get("subject")
    if not isinstance(subject, Mapping):
        raise CredentialGovernanceNotReplayable("governance derivation is missing its subject")
    if subject.get("asset_id") != stored.asset_id or subject.get("object_id") != stored.object_id:
        raise CredentialGovernanceNotReplayable(
            "credential governance subject does not match the derivation"
        )
    trust_payload = params.get("trust")
    if not isinstance(trust_payload, Mapping):
        raise CredentialGovernanceNotReplayable("governance derivation is missing EA-0006 trust")
    confidence = _numeric(trust_payload.get("score"), field="derivation trust score")
    if not math.isclose(confidence, stored.confidence, rel_tol=0.0, abs_tol=1e-6):
        raise CredentialGovernanceNotReplayable(
            "credential governance confidence does not match EA-0006 trust"
        )
    return stored


def _lifecycle_factor(asset: CryptoAsset, weight: float) -> GovernanceFactor:
    lifecycles = _asset_lifecycles(asset)
    source = {
        "owner": "EA-0032",
        "asset_id": asset.id,
        "record_hash": _record_hash(asset),
        "lifecycles": {
            name: lifecycle.model_dump(mode="json") for name, lifecycle in lifecycles.items()
        },
    }
    invalid = sorted(
        name for name, lifecycle in lifecycles.items() if lifecycle.status == "invalid"
    )
    unknown = sorted(
        name for name, lifecycle in lifecycles.items() if lifecycle.status == "unknown"
    )
    if invalid:
        return GovernanceFactor(
            name="lifecycle",
            rating=0.0,
            weight=weight,
            status="known",
            source_ref=source,
            reason=f"EA-0032 reports invalid lifecycle controls: {', '.join(invalid)}.",
        )
    if unknown:
        return GovernanceFactor(
            name="lifecycle",
            rating=None,
            weight=weight,
            status="unknown",
            source_ref=source,
            reason=f"EA-0032 lifecycle controls are unknown: {', '.join(unknown)}.",
        )
    return GovernanceFactor(
        name="lifecycle",
        rating=1.0,
        weight=weight,
        status="known",
        source_ref=source,
        reason="EA-0032 reports all applicable lifecycle controls valid.",
    )


def _ownership_factor(ownership: Ownership | None, weight: float) -> GovernanceFactor:
    if ownership is None:
        return GovernanceFactor(
            name="ownership",
            rating=None,
            weight=weight,
            status="unknown",
            source_ref={"owner": "EA-0025", "record_hash": None, "status": "missing"},
            reason="EA-0025 has no ownership record for this credential asset.",
        )
    has_owner = any((ownership.business_owner, ownership.technical_owner, ownership.custodian))
    return GovernanceFactor(
        name="ownership",
        rating=1.0 if has_owner else 0.0,
        weight=weight,
        status="known",
        source_ref={
            "owner": "EA-0025",
            "record_hash": _record_hash(ownership),
            "record": ownership.model_dump(mode="json"),
            "evidence_id": ownership.evidence_id,
        },
        reason=(
            "EA-0025 records at least one attributed owner."
            if has_owner
            else "EA-0025 records that no attributed owner is assigned."
        ),
    )


def _storage_safety_factor(
    classification: StorageSafetyClassification,
    weight: float,
) -> GovernanceFactor:
    source_ref = {
        "owner": "EA-0032",
        "record": classification.model_dump(mode="json"),
        "record_hash": _record_hash(classification),
        "evidence_id": classification.evidence_id,
    }
    if classification.status == "unknown":
        return GovernanceFactor(
            name="storage_safety",
            rating=None,
            weight=weight,
            status="unknown",
            source_ref=source_ref,
            reason=classification.reason,
        )
    return GovernanceFactor(
        name="storage_safety",
        rating=1.0 if classification.status == "approved" else 0.0,
        weight=weight,
        status="known",
        source_ref=source_ref,
        reason=classification.reason,
    )


def _exposure_factor(
    exposure: CryptographicExposure,
    owner_exposure: ExposureRecord | None,
    weight: float,
) -> GovernanceFactor:
    if exposure.status == "reachability_pending":
        return GovernanceFactor(
            name="exposure",
            rating=None,
            weight=weight,
            status="unknown",
            source_ref={
                "owner": "EA-0023",
                "crypto_exposure": exposure.model_dump(mode="json"),
                "record_hash": _record_hash(exposure),
            },
            reason=exposure.reason,
        )
    if owner_exposure is None or owner_exposure.score is None:
        raise CryptoConfigInvalid("confirmed crypto exposure requires its EA-0023 score record")
    if exposure.exposure_record_id != owner_exposure.id:
        raise CryptoConfigInvalid("crypto exposure does not match its EA-0023 owner record")
    evidence_ids = sorted(
        {basis.evidence_id for basis in owner_exposure.basis if basis.evidence_id is not None}
    )
    return GovernanceFactor(
        name="exposure",
        rating=round(1.0 - owner_exposure.score / 100.0, 6),
        weight=weight,
        status="known",
        source_ref={
            "owner": "EA-0023",
            "exposure_id": owner_exposure.id,
            "record_hash": _record_hash(owner_exposure),
            "score": owner_exposure.score,
            "status": owner_exposure.status,
            "reachability": owner_exposure.reachability,
            "evidence_id": evidence_ids[0] if evidence_ids else None,
            "evidence_ids": evidence_ids,
        },
        reason=(
            f"EA-0023 scored credential exposure at {owner_exposure.score:.0f}/100 "
            f"with status {owner_exposure.status}."
        ),
    )


def _trust_factor(trust: TrustAssessment, weight: float) -> GovernanceFactor:
    if trust.no_evidence:
        return GovernanceFactor(
            name="trust",
            rating=None,
            weight=weight,
            status="unknown",
            source_ref={
                "owner": "EA-0006",
                "record_hash": _record_hash(trust),
                "record": trust.model_dump(mode="json"),
            },
            reason=trust.reason,
        )
    return GovernanceFactor(
        name="trust",
        rating=trust.score,
        weight=weight,
        status="known",
        source_ref={
            "owner": "EA-0006",
            "record_hash": _record_hash(trust),
            "record": trust.model_dump(mode="json"),
        },
        reason=trust.reason,
    )


def _compliance_factor(snapshot: ComplianceSnapshot, weight: float) -> GovernanceFactor:
    evaluated = sum(result.evaluated for result in snapshot.control_results)
    source = {
        "owner": "EA-0010",
        "snapshot_id": snapshot.id,
        "record_hash": _record_hash(snapshot),
        "overall_score": snapshot.overall_score,
        "evaluated": evaluated,
        "control_results": [result.model_dump(mode="json") for result in snapshot.control_results],
        "evidence_id": snapshot.evidence_id,
    }
    if evaluated == 0:
        return GovernanceFactor(
            name="compliance",
            rating=None,
            weight=weight,
            status="unknown",
            source_ref=source,
            reason="EA-0010 evaluated no controls for this credential object.",
        )
    return GovernanceFactor(
        name="compliance",
        rating=snapshot.overall_score,
        weight=weight,
        status="known",
        source_ref=source,
        reason=f"EA-0010 evaluated {evaluated} control applications for this credential.",
    )


def _owner_risk(
    asset: CryptoAsset,
    *,
    direct: Mapping[str, GovernanceFactor],
    mission: MissionImpactResult,
    computed_at: datetime,
    risk_config: RiskConfig,
) -> Risk:
    signals: list[SignalRef] = []
    adverse: list[float] = []
    for name in ("lifecycle", "storage_safety", "ownership", "exposure", "compliance"):
        factor = direct[name]
        if factor.status != "known" or factor.rating is None:
            continue
        risk_weight = round(1.0 - factor.rating, 6)
        adverse.append(risk_weight)
        evidence_id = _source_evidence_id(factor.source_ref) or asset.evidence_id
        signals.append(
            SignalRef(
                kind="compliance" if name == "compliance" else "finding",
                ref_id=f"{asset.id}:{name}",
                weight=risk_weight,
                evidence_id=evidence_id,
            )
        )
    if not signals:
        signals = [
            SignalRef(
                kind="finding",
                ref_id=f"{asset.id}:governance-unknown",
                weight=0.0,
                evidence_id=asset.evidence_id,
            )
        ]
    mission_factor, top_mission_id = _mission_factor(mission)
    seed = Risk(
        id=asset.id,
        tenant_id=asset.tenant_id,
        correlation_key=f"crypto-governance:{asset.id}",
        title=f"Credential governance risk for {asset.id}",
        category="credential_governance",
        likelihood=0.0,
        impact=max(adverse, default=0.0),
        score=0.0,
        band="within_appetite",
        signals=signals,
        affected_object_ids=[asset.object_id],
        reason="EA-0032 owner facts composed through EA-0013 scoring.",
        first_seen_at=computed_at,
        last_scored_at=computed_at,
    )
    return score_risk(
        seed,
        config=risk_config,
        mission_factor=mission_factor if any(weight > 0.0 for weight in adverse) else 0.0,
        top_mission_id=top_mission_id,
    )


def _score_derivation(
    asset: CryptoAsset,
    *,
    factors: Sequence[GovernanceFactor],
    active_critical_exposure_ids: Sequence[str],
    owner_risk: Risk,
    trust: TrustAssessment,
    mission: MissionImpactResult,
    compliance: ComplianceSnapshot,
    storage_safety: StorageSafetyClassification,
    ownership: Ownership | None,
    exposure: CryptographicExposure,
    owner_exposure: ExposureRecord | None,
) -> Derivation:
    risk_claim = ClaimRef(kind="risk", ref_id=asset.object_id, evidence_id=asset.evidence_id)
    trust_claim = ClaimRef(
        kind="trust",
        ref_id=trust.subject_ref,
        evidence_id=asset.evidence_id,
    )
    _, top_mission_id = _mission_factor(mission)
    mission_claim = ClaimRef(
        kind="mission",
        ref_id=top_mission_id or asset.id,
        evidence_id=asset.evidence_id,
    )
    params: dict[str, Any] = {
        "subject": {
            "asset_id": asset.id,
            "object_id": asset.object_id,
            "asset_kind": crypto_asset_kind(asset),
            "record_hash": _record_hash(asset),
        },
        "factors": [factor.model_dump(mode="json") for factor in factors],
        "active_critical_exposure_ids": list(active_critical_exposure_ids),
        "ea0013_risk": owner_risk.model_dump(mode="json"),
        "ownership": None if ownership is None else ownership.model_dump(mode="json"),
        "ownership_record_hash": None if ownership is None else _record_hash(ownership),
        "crypto_exposure": exposure.model_dump(mode="json"),
        "exposure_record_hash": (None if owner_exposure is None else _record_hash(owner_exposure)),
        "compliance": {
            "snapshot_id": compliance.id,
            "record_hash": _record_hash(compliance),
            "overall_score": compliance.overall_score,
            "control_results": [
                result.model_dump(mode="json") for result in compliance.control_results
            ],
            "evidence_id": compliance.evidence_id,
        },
        "storage_safety": storage_safety.model_dump(mode="json"),
        "storage_safety_record_hash": _record_hash(storage_safety),
        "trust": trust.model_dump(mode="json"),
        "mission": _mission_ref(mission),
    }
    output = governance_score_result([], params)
    step = DerivationStep(
        seq=1,
        op=_GOVERNANCE_SCORE_OP,
        input_refs=[risk_claim.ref_id, trust_claim.ref_id, mission_claim.ref_id],
        params=params,
        output=output,
        note=(
            "Compose EA-0032 lifecycle and storage safety, EA-0025 ownership, EA-0023 exposure, "
            "EA-0010 compliance, EA-0006 trust, and EA-0007 mission through EA-0013."
        ),
    )
    return build_derivation(
        inputs=[risk_claim, trust_claim, mission_claim],
        steps=[step],
        model_version=1,
        engine_version="crypto-governance/v2",
        registry=governance_operation_registry(),
    )


def _statement(
    asset_id: str,
    *,
    score: float,
    factors: Sequence[GovernanceFactor],
    active_ids: Sequence[str],
) -> str:
    states = ", ".join(
        f"{factor.name}=" + ("unknown" if factor.rating is None else f"{factor.rating:.3f}")
        for factor in factors
    )
    exposure_note = (
        f" Active critical exposure: {', '.join(active_ids)}; it cannot be averaged away."
        if active_ids
        else ""
    )
    return (
        f"Credential {asset_id} governance hygiene is {score:.1f}/100: {states}."
        f"{exposure_note} This score measures governance hygiene, not safety or compromise state."
    )


def _asset_lifecycles(asset: CryptoAsset) -> dict[str, Lifecycle]:
    if isinstance(asset, SecretAsset):
        return {"rotation": asset.rotation}
    if isinstance(asset, CryptographicKey):
        return {"strength": asset.strength, "rotation": asset.rotation}
    if isinstance(asset, CertificateAsset):
        return {
            "expiry": asset.expiry,
            "chain": asset.chain,
            "revocation": asset.revocation,
            "integrity": asset.integrity,
            "authenticity": asset.authenticity,
        }
    raise CryptoConfigInvalid("unsupported crypto asset type")


def _active_critical_exposure_ids(owner_exposure: ExposureRecord | None) -> list[str]:
    if (
        owner_exposure is not None
        and owner_exposure.status == "open"
        and owner_exposure.score is not None
        and owner_exposure.score >= GOVERNANCE_CRITICAL_EXPOSURE_THRESHOLD
    ):
        return [owner_exposure.id]
    return []


def _mission_factor(result: MissionImpactResult) -> tuple[float, str | None]:
    if not result.impacts:
        return 0.0, None
    selected = max(
        result.impacts,
        key=lambda impact: (impact.impact_score, impact.mission.id),
    )
    return selected.impact_score, selected.mission.id


def _mission_ref(result: MissionImpactResult) -> dict[str, object]:
    factor, top_id = _mission_factor(result)
    return {
        "owner": "EA-0007",
        "record_hash": _record_hash(result),
        "top_mission_id": top_id,
        "impact_factor": factor,
        "impact_count": len(result.impacts),
        "truncated": result.truncated,
    }


def _source_evidence_id(source_ref: Mapping[str, Any]) -> str | None:
    value = source_ref.get("evidence_id")
    return value if isinstance(value, str) else None


def _record_hash(record: BaseModel) -> str:
    return hashlib.sha256(canonical_json(record.model_dump(mode="json"))).hexdigest()


def _score_params(derivation: Derivation) -> Mapping[str, Any]:
    for step in derivation.steps:
        if step.op == _GOVERNANCE_SCORE_OP:
            return step.params
    raise CredentialGovernanceNotReplayable(
        "credential governance derivation is missing its score operation"
    )


def _exposure_ids(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise CryptoConfigInvalid("active critical exposure ids must be a list")
    ids: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise CryptoConfigInvalid("active critical exposure ids must be strings")
        ids.append(item)
    if len(ids) != len(set(ids)):
        raise CryptoConfigInvalid("active critical exposure ids must be unique")
    return ids


def _validate_factor_weights(weights: Mapping[str, float]) -> None:
    if set(weights) != set(GOVERNANCE_FACTOR_NAMES):
        raise CryptoConfigInvalid("governance factor weights have an invalid factor set")
    if not math.isclose(sum(weights.values()), 1.0, rel_tol=0.0, abs_tol=1e-6):
        raise CryptoConfigInvalid("governance factor weights must sum to 1 within 1e-6")


def _numeric(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CredentialGovernanceNotReplayable(f"{field} must be numeric")
    selected = float(value)
    if not math.isfinite(selected):
        raise CredentialGovernanceNotReplayable(f"{field} must be finite")
    return selected
