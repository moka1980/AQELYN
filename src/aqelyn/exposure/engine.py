"""Known-data exposure derivation and owner-engine delegations (EA-0023 E2-E3)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, field_validator

from aqelyn.conventions import ActorRef, new_id, require_tenant_id, require_typed_id, utc_now
from aqelyn.conventions.errors import (
    DerivationNotReplayable,
    ExposureConfigInvalid,
    ExposureNotReplayable,
)
from aqelyn.decision import ClaimRef, DerivationStep, build_derivation, replay
from aqelyn.evidence.models import EvidenceRecord
from aqelyn.exposure.models import (
    VALID_REACHABILITY,
    AssetRef,
    AttackSurfaceAsset,
    ExposureBasis,
    ExposureConfig,
    ExposureRecord,
    Reachability,
    ReachablePath,
)
from aqelyn.exposure.store import ExposureStore, validate_tenant
from aqelyn.findings.models import Automation, Finding, Remediation
from aqelyn.findings.store import FindingStore
from aqelyn.forecast.models import TrendRecord
from aqelyn.graph.models import EdgeView, Path
from aqelyn.iag.models import AccessPath, AccessRiskReport
from aqelyn.mission.models import MissionImpactResult
from aqelyn.objects import ObjectQuery
from aqelyn.risk.models import Risk, RiskConfig, SignalRef
from aqelyn.risk.scoring import score_risk
from aqelyn.trust.models import TrustAssessment


class KnownSurfaceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_ref: AssetRef
    classification: str = "known_asset"
    exposure_type: str = "known_surface"
    reachability: Reachability | None = None
    basis: list[ExposureBasis]
    observed_at: datetime | None = None
    rationale: str | None = None

    @field_validator("classification", "exposure_type")
    @classmethod
    def _text(cls, value: str) -> str:
        if not value.strip():
            raise ExposureConfigInvalid("known surface text fields must not be empty")
        return value

    @field_validator("reachability")
    @classmethod
    def _reachability(cls, value: Reachability | None) -> Reachability | None:
        if value is not None and value not in VALID_REACHABILITY:
            raise ExposureConfigInvalid(f"unknown reachability: {value!r}")
        return value

    @field_validator("basis")
    @classmethod
    def _basis(cls, values: list[ExposureBasis]) -> list[ExposureBasis]:
        if not values:
            raise ExposureConfigInvalid("known surface record requires at least one basis")
        return values


class KnownSurfaceSource(Protocol):
    async def list_known_surface(
        self, *, tenant_id: str | None
    ) -> Sequence[KnownSurfaceRecord]: ...


class ExposurePathGraph(Protocol):
    async def paths(
        self,
        from_id: str,
        to_id: str,
        *,
        direction: str = "both",
        relation_types: Sequence[str] | None = None,
        max_depth: int = 6,
        max_paths: int = 10,
        max_work: int = 50_000,
    ) -> list[Path]: ...


class IdentityExposureProvider(Protocol):
    async def access_paths(
        self, identity_id: str, *, tenant_id: str | None = None
    ) -> list[AccessPath]: ...

    async def analyze_risk(
        self, *, tenant_id: str | None, scope: ObjectQuery | None = None
    ) -> AccessRiskReport: ...


class ExposureTrendProvider(Protocol):
    async def analyze_trend(
        self, *, metric: str, window_days: int, tenant_id: str | None
    ) -> TrendRecord: ...


class ExposureEvidenceLookup(Protocol):
    async def get(self, evidence_id: str, *, actor: ActorRef) -> EvidenceRecord: ...


class ExposureTrustProvider(Protocol):
    async def assess(
        self,
        subject_ref: str,
        evidence: Sequence[EvidenceRecord],
        *,
        now: datetime | None = None,
    ) -> TrustAssessment: ...


class ExposureMissionProvider(Protocol):
    async def mission_impact(self, object_id: str) -> MissionImpactResult: ...


class StaticKnownSurfaceSource:
    def __init__(self, records: Sequence[KnownSurfaceRecord], *, unavailable: bool = False) -> None:
        self.records = [record.model_copy(deep=True) for record in records]
        self.unavailable = unavailable
        self.reads: list[str | None] = []

    async def list_known_surface(self, *, tenant_id: str | None) -> Sequence[KnownSurfaceRecord]:
        self.reads.append(tenant_id)
        if self.unavailable:
            raise ExposureConfigInvalid("known surface source unavailable")
        return [record.model_copy(deep=True) for record in self.records]


class KnownDataExposureEngine:
    def __init__(
        self,
        store: ExposureStore,
        source: KnownSurfaceSource,
        *,
        config: ExposureConfig | None = None,
        graph: ExposurePathGraph | None = None,
        identity_provider: IdentityExposureProvider | None = None,
        trend_provider: ExposureTrendProvider | None = None,
        evidence_lookup: ExposureEvidenceLookup | None = None,
        trust_provider: ExposureTrustProvider | None = None,
        mission_provider: ExposureMissionProvider | None = None,
        finding_store: FindingStore | None = None,
        risk_config: RiskConfig | None = None,
        path_roots: Sequence[str] = (),
    ) -> None:
        self.store = store
        self.source = source
        self.config = config or ExposureConfig()
        self.graph = graph
        self.identity_provider = identity_provider
        self.trend_provider = trend_provider
        self.evidence_lookup = evidence_lookup
        self.trust_provider = trust_provider
        self.mission_provider = mission_provider
        self.finding_store = finding_store
        self.risk_config = risk_config or RiskConfig()
        self.path_roots = [require_typed_id(root, "obj", field="path_roots") for root in path_roots]

    async def derive_surface(self, *, tenant_id: str | None) -> list[AttackSurfaceAsset]:
        selected_tenant = validate_tenant(tenant_id)
        rows = await self.source.list_known_surface(tenant_id=selected_tenant)
        assets = [
            AttackSurfaceAsset(
                tenant_id=selected_tenant,
                asset_ref=row.asset_ref,
                classification=row.classification,
                exposure_level=_level_for(row.reachability, default=self.config.default_level),
                discovered_at=row.observed_at or _basis_as_of(row.basis),
                validated_at=row.observed_at,
                basis=row.basis,
            )
            for row in rows
        ]
        assets.sort(key=lambda asset: (asset.asset_ref.kind, asset.asset_ref.ref_id, asset.id))
        return assets

    async def analyze_exposure(
        self, *, asset_ref: AssetRef, tenant_id: str | None
    ) -> ExposureRecord:
        selected_tenant = require_tenant_id(tenant_id)
        try:
            rows = await self.source.list_known_surface(tenant_id=selected_tenant)
        except Exception as exc:
            record = _unknown_record(
                asset_ref=asset_ref,
                tenant_id=selected_tenant,
                basis=_basis_from_asset(asset_ref),
                rationale=f"Known exposure source unavailable; recorded unknown: {exc}",
            )
            return await self.store.put(record)

        match = _find_row(rows, asset_ref)
        if match is None or match.reachability is None:
            record = _unknown_record(
                asset_ref=asset_ref,
                tenant_id=selected_tenant,
                basis=_basis_from_asset(asset_ref),
                rationale="Reachability could not be derived from known data.",
            )
        else:
            record = ExposureRecord(
                tenant_id=selected_tenant,
                asset_ref=asset_ref,
                exposure_type=match.exposure_type,
                reachability=match.reachability,
                basis=match.basis,
                score=None,
                confidence=None,
                derivation=None,
                rationale=match.rationale or "Reachability is derived from handed-in known data.",
                flagged=match.reachability == "unknown",
                discovered_at=match.observed_at or _basis_as_of(match.basis),
                validated_at=match.observed_at,
                status="open",
            )
        return await self.store.put(record)

    async def reachable_paths(
        self, *, target_ref: str, tenant_id: str | None
    ) -> list[ReachablePath]:
        _ = validate_tenant(tenant_id)
        target_id = require_typed_id(target_ref, "obj", field="target_ref")
        if self.graph is None:
            raise ExposureConfigInvalid("knowledge graph provider is unavailable")
        results: list[ReachablePath] = []
        for root_id in self.path_roots:
            delegated = await self.graph.paths(
                root_id,
                target_id,
                direction="out",
                max_paths=self.config.max_paths - len(results),
                max_work=self.config.max_work,
            )
            for path in delegated:
                results.append(
                    ReachablePath(
                        target_ref=target_id,
                        path=list(path.node_ids),
                        via="graph",
                        max_work=self.config.max_work,
                    )
                )
                if len(results) >= self.config.max_paths:
                    return results
        return results

    async def identity_exposure(
        self, *, asset_ref: AssetRef, tenant_id: str | None
    ) -> ExposureRecord:
        selected_tenant = validate_tenant(tenant_id)
        if self.identity_provider is None:
            raise ExposureConfigInvalid("identity exposure provider is unavailable")
        access_paths = await self.identity_provider.access_paths(
            asset_ref.ref_id, tenant_id=selected_tenant
        )
        risk_report = await self.identity_provider.analyze_risk(
            tenant_id=selected_tenant, scope=None
        )
        record = ExposureRecord(
            tenant_id=selected_tenant,
            asset_ref=asset_ref,
            exposure_type="identity_access",
            reachability="unknown",
            basis=_basis_from_iag(asset_ref, access_paths, risk_report),
            score=None,
            confidence=None,
            derivation=None,
            rationale="Identity exposure cites EA-0011 IAG; no entitlement verdict is re-derived.",
            flagged=True,
            discovered_at=utc_now(),
            validated_at=None,
            status="open",
        )
        return await self.store.put(record)

    async def trend(self, *, category: str, window_days: int, tenant_id: str | None) -> TrendRecord:
        selected_tenant = validate_tenant(tenant_id)
        if self.trend_provider is None:
            raise ExposureConfigInvalid("forecast trend provider is unavailable")
        return await self.trend_provider.analyze_trend(
            metric=category,
            window_days=window_days,
            tenant_id=selected_tenant,
        )

    async def score_exposure(self, exposure: ExposureRecord) -> ExposureRecord:
        selected = exposure.model_copy(deep=True)
        if self.evidence_lookup is None:
            raise ExposureConfigInvalid("evidence lookup is unavailable")
        if self.trust_provider is None:
            raise ExposureConfigInvalid("trust provider is unavailable")
        if self.mission_provider is None:
            raise ExposureConfigInvalid("mission provider is unavailable")
        asset_id = require_typed_id(selected.asset_ref.ref_id, "obj", field="asset_ref.ref_id")
        evidence = await self._evidence_for(selected)
        trust = await self.trust_provider.assess(
            f"exposure:{selected.id}",
            evidence,
            now=selected.validated_at or selected.discovered_at,
        )
        mission = await self.mission_provider.mission_impact(asset_id)
        mission_factor, top_mission_id = _mission_factors(mission)
        risk = _risk_for_exposure(
            selected,
            trust=trust,
            mission_factor=mission_factor,
            top_mission_id=top_mission_id,
            risk_config=self.risk_config,
        )
        derivation = _score_derivation(
            selected,
            trust=trust,
            mission_factor=mission_factor,
            top_mission_id=top_mission_id,
            risk=risk,
        )
        scored = selected.model_copy(
            update={
                "score": risk.score,
                "confidence": trust.score,
                "derivation": derivation,
                "rationale": _score_reason(selected, trust=trust, risk=risk),
                "validated_at": selected.validated_at or utc_now(),
            },
            deep=True,
        )
        return validate_replayable_exposure(scored)

    async def raise_exposure_finding(self, exposure: ExposureRecord) -> Finding:
        selected = validate_replayable_exposure(exposure)
        if self.finding_store is None:
            raise ExposureConfigInvalid("finding store is unavailable")
        evidence_ids = _evidence_ids(selected)
        if not evidence_ids:
            raise ExposureConfigInvalid("material exposure finding requires evidence")
        finding = _finding_for_exposure(selected, evidence_ids=evidence_ids)
        return await self.finding_store.raise_finding(finding)

    async def _evidence_for(self, exposure: ExposureRecord) -> list[EvidenceRecord]:
        assert self.evidence_lookup is not None
        actor = ActorRef(actor_type="system", actor_id="exposure_engine")
        records: list[EvidenceRecord] = []
        for evidence_id in _evidence_ids(exposure):
            records.append(await self.evidence_lookup.get(evidence_id, actor=actor))
        if not records:
            raise ExposureConfigInvalid("scoring requires evidence-backed exposure basis")
        records.sort(key=lambda record: record.id)
        return records


def validate_replayable_exposure(exposure: ExposureRecord) -> ExposureRecord:
    if exposure.score is None:
        return exposure.model_copy(deep=True)
    if exposure.derivation is None:
        raise ExposureNotReplayable("scored exposure requires a replayable derivation")
    try:
        replay(exposure.derivation)
    except DerivationNotReplayable as exc:
        raise ExposureNotReplayable("exposure score derivation does not replay") from exc
    return exposure.model_copy(deep=True)


def _evidence_ids(exposure: ExposureRecord) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for basis in exposure.basis:
        if basis.evidence_id is None or basis.evidence_id in seen:
            continue
        seen.add(basis.evidence_id)
        out.append(basis.evidence_id)
    if exposure.asset_ref.evidence_id is not None and exposure.asset_ref.evidence_id not in seen:
        out.append(exposure.asset_ref.evidence_id)
    return out


def _mission_factors(result: MissionImpactResult) -> tuple[float, str | None]:
    if not result.impacts:
        return 0.0, None
    selected = max(
        result.impacts,
        key=lambda impact: (impact.impact_score, impact.mission.id),
    )
    return selected.impact_score, selected.mission.id


def _risk_for_exposure(
    exposure: ExposureRecord,
    *,
    trust: TrustAssessment,
    mission_factor: float,
    top_mission_id: str | None,
    risk_config: RiskConfig,
) -> Risk:
    evidence_id = _first_evidence_id(exposure)
    asset_id = require_typed_id(exposure.asset_ref.ref_id, "obj", field="asset_ref.ref_id")
    observed = exposure.validated_at or exposure.discovered_at
    seed = Risk(
        id=f"risk:{exposure.id}",
        tenant_id=exposure.tenant_id,
        correlation_key=f"exposure:{exposure.asset_ref.ref_id}:{exposure.exposure_type}",
        title=f"Exposure risk for {exposure.asset_ref.ref_id}",
        category="attack_surface_exposure",
        likelihood=0.0,
        impact=_reachability_factor(exposure.reachability),
        score=0.0,
        band="within_appetite",
        signals=[
            SignalRef(
                kind="finding",
                ref_id=f"exposure:{exposure.id}",
                weight=trust.score,
                evidence_id=evidence_id,
            )
        ],
        affected_object_ids=[asset_id],
        top_mission_id=top_mission_id,
        reason="Exposure risk is composed from reachability, Trust, and Mission impact.",
        first_seen_at=exposure.discovered_at,
        last_scored_at=observed,
    )
    return score_risk(
        seed,
        config=risk_config,
        mission_factor=mission_factor,
        top_mission_id=top_mission_id,
    )


def _score_derivation(
    exposure: ExposureRecord,
    *,
    trust: TrustAssessment,
    mission_factor: float,
    top_mission_id: str | None,
    risk: Risk,
) -> Any:
    evidence_id = _first_evidence_id(exposure)
    trust_claim = ClaimRef(kind="trust", ref_id=trust.subject_ref, evidence_id=evidence_id)
    mission_claim = ClaimRef(
        kind="mission",
        ref_id=top_mission_id or exposure.asset_ref.ref_id,
        evidence_id=evidence_id,
    )
    risk_claim = ClaimRef(kind="risk", ref_id=risk.id, evidence_id=evidence_id)
    selected_output: dict[str, Any] = {
        "claims": [
            trust_claim.model_dump(mode="json"),
            mission_claim.model_dump(mode="json"),
            risk_claim.model_dump(mode="json"),
        ],
        "count": 3,
    }
    risk_unit = risk.score / 100.0
    weighed_items = [{**claim, "weight": risk_unit} for claim in selected_output["claims"]]
    weighed_output: dict[str, Any] = {"items": weighed_items}
    scored_items = [{**item, "score": risk_unit} for item in weighed_items]
    scored_output: dict[str, Any] = {"items": scored_items, "factor": 1.0}
    steps = [
        DerivationStep(
            seq=1,
            op="select_claims",
            input_refs=[trust_claim.ref_id, mission_claim.ref_id, risk_claim.ref_id],
            params={"kinds": ["trust", "mission", "risk"]},
            output=selected_output,
            note="Select the Trust, Mission, and Risk owner records used for exposure scoring.",
        ),
        DerivationStep(
            seq=2,
            op="weigh",
            input_refs=["step:1"],
            params={"default": risk_unit},
            output=weighed_output,
            note=(
                "Use EA-0013 risk score as the replayed exposure score factor; "
                f"EA-0006 trust={trust.score:.3f}, EA-0007 mission={mission_factor:.3f}."
            ),
        ),
        DerivationStep(
            seq=3,
            op="mission_weight",
            input_refs=["step:2"],
            params={"factor": 1.0, "source_field": "weight", "target_field": "score"},
            output=scored_output,
            note="Emit a replayable [0,1] score factor without recomputing owner engines.",
        ),
    ]
    return build_derivation(
        inputs=[trust_claim, mission_claim, risk_claim],
        steps=steps,
        model_version=1,
        engine_version="exposure-score/v1",
    )


def _score_reason(
    exposure: ExposureRecord,
    *,
    trust: TrustAssessment,
    risk: Risk,
) -> str:
    return (
        f"{exposure.rationale} Exposure score {risk.score:.0f} is composed from "
        f"Trust confidence {trust.score:.3f}, Mission impact {risk.factors['mission_factor']:.3f}, "
        f"and EA-0013 risk band {risk.band}."
    )


def _finding_for_exposure(exposure: ExposureRecord, *, evidence_ids: list[str]) -> Finding:
    score = exposure.score if exposure.score is not None else 0.0
    affected = _affected_object_ids(exposure)
    return Finding(
        id=new_id("fnd"),
        tenant_id=exposure.tenant_id,
        finding_type="attack_surface_exposure",
        schema_version=1,
        dedup_key=f"exposure:{exposure.asset_ref.ref_id}:{exposure.exposure_type}",
        title=(
            f"{_title_reachability(exposure.reachability)} exposure on {exposure.asset_ref.ref_id}"
        ),
        severity=_severity_for_score(score),
        severity_score=round(score / 100.0, 6),
        status="open",
        what_happened=(
            f"AQELYN derived {exposure.reachability} reachability for "
            f"{exposure.asset_ref.ref_id} from known-data attack-surface records."
        ),
        why_it_matters=(
            "Reachable or uncertain externally relevant surface can increase attack paths "
            "and should be reviewed with its cited basis."
        ),
        how_determined=(
            "The Threat Exposure engine used handed-in known data, owner-engine scoring, "
            "and a replayable derivation; it performed no scan or response action."
        ),
        risk_of_inaction=(
            "Untreated exposure can leave reachable services, identities, or domains "
            "available to an attacker."
        ),
        evidence_ids=evidence_ids,
        affected_object_ids=affected,
        expert_details={
            "exposure_id": exposure.id,
            "reachability": exposure.reachability,
            "score": score,
            "derivation": exposure.derivation.model_dump(mode="json")
            if exposure.derivation is not None
            else None,
        },
        remediation=Remediation(
            summary="Review the exposure and route any remediation through the Workflow Engine.",
            steps=[
                "Validate the cited exposure basis.",
                "Decide whether the exposed surface should remain reachable.",
                "Create a gated remediation workflow if a change is required.",
            ],
            difficulty="medium",
            estimated_effort=None,
            expected_outcome=(
                "Exposure is accepted, reduced, or remediated through governed workflow."
            ),
        ),
        automation=Automation(
            eligibility="none",
            action_ref=None,
            requires_approval=True,
            risk_note=(
                "Threat Exposure raises findings only; actions must be proposed through EA-0008."
            ),
        ),
        confidence=exposure.confidence if exposure.confidence is not None else 0.0,
        source_engine="exposure_engine",
        first_detected_at=exposure.discovered_at,
        last_detected_at=exposure.validated_at or exposure.discovered_at,
    )


def _first_evidence_id(exposure: ExposureRecord) -> str | None:
    evidence_ids = _evidence_ids(exposure)
    return evidence_ids[0] if evidence_ids else None


def _affected_object_ids(exposure: ExposureRecord) -> list[str]:
    ref_id = exposure.asset_ref.ref_id
    if not ref_id.startswith("obj_"):
        return []
    return [require_typed_id(ref_id, "obj", field="affected_object_ids")]


def _reachability_factor(reachability: str) -> float:
    if reachability == "external":
        return 1.0
    if reachability == "internal":
        return 0.45
    return 0.15


def _severity_for_score(score: float) -> str:
    if score >= 90.0:
        return "critical"
    if score >= 70.0:
        return "high"
    if score >= 40.0:
        return "medium"
    if score > 0.0:
        return "low"
    return "info"


def _title_reachability(reachability: str) -> str:
    if reachability == "unknown":
        return "Unknown"
    return reachability.capitalize()


def _find_row(rows: Sequence[KnownSurfaceRecord], asset_ref: AssetRef) -> KnownSurfaceRecord | None:
    for row in rows:
        if row.asset_ref.kind == asset_ref.kind and row.asset_ref.ref_id == asset_ref.ref_id:
            return row
    return None


def _basis_from_asset(asset_ref: AssetRef) -> list[ExposureBasis]:
    return [
        ExposureBasis(
            kind="inventory",
            ref=asset_ref.ref_id,
            as_of=utc_now(),
            evidence_id=asset_ref.evidence_id,
        )
    ]


def _basis_from_iag(
    asset_ref: AssetRef,
    paths: Sequence[AccessPath],
    report: AccessRiskReport,
) -> list[ExposureBasis]:
    now = utc_now()
    basis: list[ExposureBasis] = []
    for index, path in enumerate(paths):
        basis.append(
            ExposureBasis(
                kind="access",
                ref=f"iag:access_path:{path.identity_id}:{index}",
                as_of=now,
                evidence_id=_first_edge_evidence(path.via.edges),
            )
        )
    for risk in report.risks:
        if risk.subject_id != asset_ref.ref_id:
            continue
        evidence_id = None
        if risk.evidence_path is not None:
            evidence_id = _first_edge_evidence(risk.evidence_path.edges)
        basis.append(
            ExposureBasis(
                kind="access",
                ref=f"iag:risk:{risk.kind}:{risk.subject_id}",
                as_of=now,
                evidence_id=evidence_id,
            )
        )
    return basis or _basis_from_asset(asset_ref)


def _first_edge_evidence(edges: Sequence[EdgeView]) -> str | None:
    for edge in edges:
        for source in edge.sources:
            if source.evidence_id is not None:
                return source.evidence_id
    return None


def _basis_as_of(values: Sequence[ExposureBasis]) -> datetime:
    return min(value.as_of for value in values)


def _level_for(reachability: Reachability | None, *, default: str) -> str:
    if reachability == "external":
        return "high"
    if reachability == "internal":
        return "low"
    return default


def _unknown_record(
    *,
    asset_ref: AssetRef,
    tenant_id: str | None,
    basis: list[ExposureBasis],
    rationale: str,
) -> ExposureRecord:
    return ExposureRecord(
        id=new_id("exp"),
        tenant_id=tenant_id,
        asset_ref=asset_ref,
        exposure_type="known_surface",
        reachability="unknown",
        basis=basis,
        score=None,
        confidence=None,
        derivation=None,
        rationale=rationale,
        flagged=True,
        discovered_at=utc_now(),
        validated_at=None,
        status="open",
    )
