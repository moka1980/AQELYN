"""Vulnerability Intelligence reference engine (EA-0024 V2-V3)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from aqelyn.conventions import ActorRef, new_id, require_typed_id, utc_now
from aqelyn.conventions.errors import (
    CoverageUnavailable,
    CrossTenantReference,
    DerivationNotReplayable,
    VulnConfigInvalid,
    VulnNotFound,
    VulnNotReplayable,
)
from aqelyn.decision import ClaimRef, Derivation, DerivationStep, build_derivation, replay
from aqelyn.findings import Automation, Finding, FindingStore, Remediation
from aqelyn.forecast import TrendRecord
from aqelyn.mission import MissionImpactResult
from aqelyn.vuln.models import (
    CoverageReport,
    Disposition,
    DispositionKind,
    RemediationPlan,
    VulnConfig,
    VulnerabilityAssessment,
    VulnerabilityRecord,
    VulnPriority,
)
from aqelyn.vuln.store import VulnerabilityStore

_FACTOR_ORDER = ("cvss", "epss", "threat", "exposure", "mission", "baseline", "trust")
_SCORE_TOLERANCE = 0.000001


@dataclass(frozen=True)
class PriorityFactor:
    value: float
    source: str
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _unit_factor(self.value, field="priority factor"))
        if not self.source.strip():
            raise VulnConfigInvalid("priority factor source must not be empty")
        if not self.reason.strip():
            raise VulnConfigInvalid("priority factor reason must not be empty")


class ThreatExploitProvider(Protocol):
    async def exploitation_factor(self, vulnerability: VulnerabilityRecord) -> PriorityFactor: ...


class ExposureReachabilityProvider(Protocol):
    async def reachability_factor(self, vulnerability: VulnerabilityRecord) -> PriorityFactor: ...


class BaselineBlockingProvider(Protocol):
    async def blocking_factor(self, vulnerability: VulnerabilityRecord) -> PriorityFactor: ...


class ScannerTrustProvider(Protocol):
    async def scanner_trust(self, vulnerability: VulnerabilityRecord) -> PriorityFactor: ...


class VulnerabilityMissionProvider(Protocol):
    async def mission_impact(self, object_id: str) -> MissionImpactResult: ...


class VulnerabilityCoverageProvider(Protocol):
    async def coverage(self, *, tenant_id: str | None) -> CoverageReport: ...


class VulnerabilityTrendProvider(Protocol):
    async def analyze_trend(
        self, *, metric: str, window_days: int, tenant_id: str | None
    ) -> TrendRecord: ...


class VulnerabilityIntelligenceEngine:
    def __init__(
        self,
        store: VulnerabilityStore,
        *,
        config: VulnConfig | None = None,
        threat_provider: ThreatExploitProvider | None = None,
        exposure_provider: ExposureReachabilityProvider | None = None,
        mission_provider: VulnerabilityMissionProvider | None = None,
        baseline_provider: BaselineBlockingProvider | None = None,
        trust_provider: ScannerTrustProvider | None = None,
        coverage_provider: VulnerabilityCoverageProvider | None = None,
        trend_provider: VulnerabilityTrendProvider | None = None,
        finding_store: FindingStore | None = None,
    ) -> None:
        self.store = store
        self.config = config or VulnConfig()
        self.threat_provider = threat_provider
        self.exposure_provider = exposure_provider
        self.mission_provider = mission_provider
        self.baseline_provider = baseline_provider
        self.trust_provider = trust_provider or _StoredScannerTrustProvider()
        self.coverage_provider = coverage_provider
        self.trend_provider = trend_provider
        self.finding_store = finding_store

    async def ingest(
        self,
        *,
        records: Sequence[VulnerabilityRecord],
        tenant_id: str | None,
    ) -> list[VulnerabilityRecord]:
        stored: list[VulnerabilityRecord] = []
        for record in records:
            candidate = _with_tenant(record, tenant_id=tenant_id)
            existing = await self._matching_record(candidate, tenant_id=tenant_id)
            if existing is not None:
                candidate = candidate.model_copy(
                    update={
                        "id": existing.id,
                        "disposition": _reasserted_disposition(existing),
                        "status": "reasserted"
                        if existing.disposition is not None
                        else candidate.status,
                    },
                    deep=True,
                )
            stored.append(await self.store.put(candidate))
        return stored

    async def disposition(
        self,
        vulnerability_id: str,
        *,
        kind: DispositionKind,
        by: ActorRef,
        reason: str,
        tenant_id: str | None,
    ) -> VulnerabilityRecord:
        current = await self.store.get(vulnerability_id, tenant_id=tenant_id)
        if current is None:
            raise VulnNotFound(vulnerability_id)
        updated = current.model_copy(
            update={
                "disposition": Disposition(
                    actor=by,
                    kind=kind,
                    reason=reason,
                    at=utc_now(),
                    reasserted_by_scanner=False,
                )
            },
            deep=True,
        )
        return await self.store.put(updated)

    async def prioritize(
        self,
        vulnerability_id: str,
        *,
        tenant_id: str | None,
    ) -> VulnPriority:
        current = await self.store.get(vulnerability_id, tenant_id=tenant_id)
        if current is None:
            raise VulnNotFound(vulnerability_id)
        factors = await self._factors_for(current)
        score, factor_payload = _compose_score(current, factors=factors, config=self.config)
        priority = _priority_for_score(score)
        derivation = _priority_derivation(
            current,
            score=score,
            priority=priority,
            factors=factor_payload,
        )
        return validate_replayable_priority(
            VulnPriority(
                tenant_id=current.tenant_id,
                vulnerability_id=current.id,
                score=score,
                priority=priority,
                factors=factor_payload,
                confidence=float(factor_payload["trust"]["value"]),
                derivation=derivation,
                rationale=_priority_reason(current, score=score, priority=priority),
            )
        )

    async def assess(self, *, tenant_id: str | None) -> VulnerabilityAssessment:
        coverage = await self._coverage(tenant_id=tenant_id)
        records = await self.store.query(
            tenant_id=tenant_id,
            limit=max(self.config.max_priorities * 2, 100),
        )
        priorities: list[VulnPriority] = []
        unavailable: list[dict[str, str]] = []
        for record in _prioritizable(records):
            if len(priorities) >= self.config.max_priorities:
                break
            try:
                priorities.append(await self.prioritize(record.id, tenant_id=tenant_id))
            except Exception as exc:
                unavailable.append(
                    {
                        "vulnerability_id": record.id,
                        "reason": str(exc) or exc.__class__.__name__,
                    }
                )
        priorities.sort(key=lambda item: (-item.score, item.vulnerability_id))
        return VulnerabilityAssessment(
            tenant_id=tenant_id,
            priorities=priorities,
            coverage=coverage,
            suppressed_count=_suppressed_count(records),
            degraded=bool(unavailable),
            unavailable=unavailable,
            generated_at=utc_now(),
        )

    async def recommend(self, priority: VulnPriority, *, tenant_id: str | None) -> RemediationPlan:
        selected = validate_replayable_priority(priority)
        if selected.tenant_id != tenant_id:
            raise CrossTenantReference("priority tenant_id does not match remediation request")
        return RemediationPlan(
            tenant_id=tenant_id,
            vulnerability_id=selected.vulnerability_id,
            priority=selected.priority,
            proposed_campaign={
                "source": "vuln_engine",
                "kind": "ea0018_response_campaign_proposal",
                "vulnerability_id": selected.vulnerability_id,
                "priority_id": selected.id,
                "phases": [
                    {"name": "contain", "action": "validate_exposure"},
                    {"name": "remediate", "action": "patch_or_mitigate"},
                    {"name": "recover", "action": "verify_restored_state"},
                ],
                "requires_workflow": True,
            },
            owner=None,
            target_date=None,
            rationale=(
                "Advisory remediation proposal only; execution must be planned and gated "
                "through EA-0018/EA-0008."
            ),
        )

    async def raise_vulnerability(self, priority: VulnPriority, *, by: ActorRef) -> Finding:
        selected = validate_replayable_priority(priority)
        if self.finding_store is None:
            raise VulnConfigInvalid("finding store is unavailable")
        vulnerability = await self.store.get(
            selected.vulnerability_id,
            tenant_id=selected.tenant_id,
        )
        if vulnerability is None:
            raise VulnNotFound(selected.vulnerability_id)
        finding = _finding_for_priority(selected, vulnerability, by=by)
        return await self.finding_store.raise_finding(finding)

    async def trend(
        self,
        *,
        metric: str = "vulnerabilities.open",
        window_days: int = 30,
        tenant_id: str | None,
    ) -> TrendRecord:
        if self.trend_provider is None:
            raise VulnConfigInvalid("forecast trend provider is unavailable")
        return await self.trend_provider.analyze_trend(
            metric=metric,
            window_days=window_days,
            tenant_id=tenant_id,
        )

    async def _matching_record(
        self,
        candidate: VulnerabilityRecord,
        *,
        tenant_id: str | None,
    ) -> VulnerabilityRecord | None:
        for record in await self.store.query(tenant_id=tenant_id, cve_id=candidate.cve_id):
            if (
                record.scanner == candidate.scanner
                and record.asset_ref.kind == candidate.asset_ref.kind
                and record.asset_ref.ref_id == candidate.asset_ref.ref_id
            ):
                return record
        return None

    async def _factors_for(self, vulnerability: VulnerabilityRecord) -> dict[str, PriorityFactor]:
        threat = (
            await self.threat_provider.exploitation_factor(vulnerability)
            if self.threat_provider is not None
            else PriorityFactor(0.0, "threat:unavailable", "No EA-0014 threat signal supplied.")
        )
        exposure = (
            await self.exposure_provider.reachability_factor(vulnerability)
            if self.exposure_provider is not None
            else PriorityFactor(0.0, "exposure:unavailable", "No EA-0023 exposure signal supplied.")
        )
        baseline = (
            await self.baseline_provider.blocking_factor(vulnerability)
            if self.baseline_provider is not None
            else PriorityFactor(0.0, "baseline:unavailable", "No EA-0012 blocking signal supplied.")
        )
        trust = await self.trust_provider.scanner_trust(vulnerability)
        mission = await self._mission_factor(vulnerability)
        return {
            "cvss": PriorityFactor(
                _normalize_cvss(vulnerability.cvss.value),
                vulnerability.cvss.source,
                (
                    "CVSS is carried verbatim from the published source and normalized only "
                    "for composition."
                ),
            ),
            "epss": _epss_factor(vulnerability),
            "threat": threat,
            "exposure": exposure,
            "mission": mission,
            "baseline": PriorityFactor(
                1.0 - baseline.value,
                baseline.source,
                (
                    f"EA-0012 blocking factor {baseline.value:.3f} reduces priority; "
                    f"{baseline.reason}"
                ),
            ),
            "trust": trust,
        }

    async def _mission_factor(self, vulnerability: VulnerabilityRecord) -> PriorityFactor:
        if self.mission_provider is None:
            return PriorityFactor(0.0, "mission:unavailable", "No EA-0007 mission signal supplied.")
        result = await self.mission_provider.mission_impact(vulnerability.asset_ref.ref_id)
        if not result.impacts:
            return PriorityFactor(
                0.0,
                f"mission:none:{vulnerability.asset_ref.ref_id}",
                "EA-0007 returned no mission impact for the affected asset.",
            )
        selected = max(result.impacts, key=lambda impact: (impact.impact_score, impact.mission.id))
        return PriorityFactor(selected.impact_score, selected.mission.id, selected.reason)

    async def _coverage(self, *, tenant_id: str | None) -> CoverageReport:
        if self.coverage_provider is None:
            raise CoverageUnavailable("coverage provider is unavailable")
        try:
            return await self.coverage_provider.coverage(tenant_id=tenant_id)
        except CoverageUnavailable:
            raise
        except Exception as exc:
            raise CoverageUnavailable("coverage provider is unavailable") from exc


class _StoredScannerTrustProvider:
    async def scanner_trust(self, vulnerability: VulnerabilityRecord) -> PriorityFactor:
        return PriorityFactor(
            vulnerability.confidence,
            f"trust:scanner:{vulnerability.scanner}",
            "Scanner trust is carried from the EA-0006 confidence on the vulnerability record.",
        )


def validate_replayable_priority(priority: VulnPriority) -> VulnPriority:
    try:
        stored = VulnPriority.model_validate(priority.model_dump(mode="json"))
        result = replay(stored.derivation)
    except DerivationNotReplayable as exc:
        raise VulnNotReplayable("vulnerability priority derivation does not replay") from exc
    replayed_score = _score_from_replay(result)
    if abs(replayed_score - stored.score) > _SCORE_TOLERANCE:
        raise VulnNotReplayable("vulnerability priority score does not replay")
    factor_sources = _factor_sources_from_derivation(stored)
    if factor_sources != stored.factors:
        raise VulnNotReplayable("vulnerability priority factors do not match derivation")
    return stored


def _with_tenant(record: VulnerabilityRecord, *, tenant_id: str | None) -> VulnerabilityRecord:
    if tenant_id is None:
        return record
    if record.tenant_id is not None and record.tenant_id != tenant_id:
        raise CrossTenantReference("ingested vulnerability tenant_id does not match request")
    return record.model_copy(update={"tenant_id": tenant_id}, deep=True)


def _reasserted_disposition(record: VulnerabilityRecord) -> Disposition | None:
    if record.disposition is None:
        return None
    return record.disposition.model_copy(update={"reasserted_by_scanner": True}, deep=True)


def _prioritizable(records: Sequence[VulnerabilityRecord]) -> list[VulnerabilityRecord]:
    return [
        record
        for record in sorted(records, key=lambda item: (item.discovered_at, item.id))
        if record.status != "closed" and record.disposition is None
    ]


def _suppressed_count(records: Sequence[VulnerabilityRecord]) -> int:
    return sum(1 for record in records if record.disposition is not None)


def _finding_for_priority(
    priority: VulnPriority,
    vulnerability: VulnerabilityRecord,
    *,
    by: ActorRef,
) -> Finding:
    evidence_ids = _evidence_ids(vulnerability)
    if not evidence_ids:
        raise VulnConfigInvalid("material vulnerability finding requires evidence")
    affected = _affected_object_ids(vulnerability)
    return Finding(
        id=new_id("fnd"),
        tenant_id=vulnerability.tenant_id,
        finding_type="vulnerability.priority",
        schema_version=1,
        dedup_key=f"vulnerability.priority:{vulnerability.id}",
        title=f"{priority.priority.title()} vulnerability priority: {vulnerability.cve_id}",
        severity=_finding_severity(priority.score),
        severity_score=round(priority.score / 100.0, 6),
        status="open",
        what_happened=(
            f"Scanner {vulnerability.scanner} reported {vulnerability.cve_id} on "
            f"{vulnerability.asset_ref.ref_id}; AQELYN prioritized it as "
            f"{priority.priority} ({priority.score:.1f}/100)."
        ),
        why_it_matters=(
            "The priority composes carried CVSS/EPSS, exploit intelligence, exposure, mission "
            "impact, baseline blocking, and scanner trust."
        ),
        how_determined=(
            "The Vulnerability Intelligence Engine used the replayable priority derivation and "
            "the cited scanner basis; it did not scan, patch, or execute a response."
        ),
        risk_of_inaction=(
            "Leaving a material vulnerability unresolved can preserve a reachable, "
            "mission-relevant weakness for attackers."
        ),
        evidence_ids=evidence_ids,
        affected_object_ids=affected,
        expert_details={
            "vulnerability_id": vulnerability.id,
            "priority_id": priority.id,
            "scanner": vulnerability.scanner,
            "cve_id": vulnerability.cve_id,
            "score": priority.score,
            "priority": priority.priority,
            "factors": priority.factors,
            "derivation": priority.derivation.model_dump(mode="json"),
            "raised_by": by.model_dump(mode="json"),
        },
        remediation=Remediation(
            summary="Plan vulnerability remediation through response orchestration.",
            steps=[
                "Review the cited scanner evidence and priority factor breakdown.",
                "Validate whether the affected asset remains exposed or mission-relevant.",
                "Create a gated EA-0018 response campaign if remediation is still appropriate.",
            ],
            difficulty="medium",
            estimated_effort=None,
            expected_outcome=(
                "The vulnerability is accepted, mitigated, or remediated through governed workflow."
            ),
            references=[vulnerability.cve_id, "EA-0018", "EA-0008"],
        ),
        automation=Automation(
            eligibility="none",
            action_ref=None,
            requires_approval=True,
            risk_note=(
                "Vulnerability Intelligence raises findings only; remediation is advisory and "
                "must go through EA-0018/EA-0008."
            ),
        ),
        confidence=priority.confidence,
        source_engine="vuln_engine",
        correlation_id=priority.id,
        first_detected_at=vulnerability.discovered_at,
        last_detected_at=utc_now(),
    )


def _evidence_ids(vulnerability: VulnerabilityRecord) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for basis in vulnerability.basis:
        if basis.evidence_id is None or basis.evidence_id in seen:
            continue
        seen.add(basis.evidence_id)
        out.append(basis.evidence_id)
    if (
        vulnerability.asset_ref.evidence_id is not None
        and vulnerability.asset_ref.evidence_id not in seen
    ):
        out.append(vulnerability.asset_ref.evidence_id)
    return out


def _affected_object_ids(vulnerability: VulnerabilityRecord) -> list[str]:
    ref_id = vulnerability.asset_ref.ref_id
    if not ref_id.startswith("obj_"):
        return []
    return [require_typed_id(ref_id, "obj", field="affected_object_ids")]


def _finding_severity(score: float) -> str:
    if score >= 90.0:
        return "critical"
    if score >= 70.0:
        return "high"
    if score >= 40.0:
        return "medium"
    if score > 0.0:
        return "low"
    return "info"


def _epss_factor(vulnerability: VulnerabilityRecord) -> PriorityFactor:
    if vulnerability.epss is None:
        return PriorityFactor(0.0, "epss:missing", "No EPSS carried score was supplied.")
    return PriorityFactor(
        _unit_factor(vulnerability.epss.value, field="epss.value"),
        vulnerability.epss.source,
        "EPSS is carried verbatim from the published source and used as a probability.",
    )


def _compose_score(
    vulnerability: VulnerabilityRecord,
    *,
    factors: dict[str, PriorityFactor],
    config: VulnConfig,
) -> tuple[float, dict[str, Any]]:
    total_weight = sum(config.score_weights.get(name, 0.0) for name in _FACTOR_ORDER)
    if total_weight <= 0.0:
        raise VulnConfigInvalid("score_weights must contain at least one positive V3 factor")
    score_unit = 0.0
    payload: dict[str, Any] = {}
    for name in _FACTOR_ORDER:
        factor = factors[name]
        weight = config.score_weights.get(name, 0.0)
        normalized_weight = weight / total_weight
        contribution = factor.value * normalized_weight
        score_unit += contribution
        payload[name] = {
            "value": round(factor.value, 6),
            "source": factor.source,
            "weight": round(normalized_weight, 6),
            "raw_weight": round(weight, 6),
            "contribution": round(contribution, 6),
            "reason": factor.reason,
        }
    payload["cvss"]["carried_value"] = vulnerability.cvss.value
    payload["cvss"]["carried_vector"] = vulnerability.cvss.vector
    if vulnerability.epss is not None:
        payload["epss"]["carried_value"] = vulnerability.epss.value
    return (round(_clamp_unit(score_unit) * 100.0, 6), payload)


def _priority_derivation(
    vulnerability: VulnerabilityRecord,
    *,
    score: float,
    priority: str,
    factors: dict[str, Any],
) -> Derivation:
    evidence_id = _first_evidence_id(vulnerability)
    trust_claim = ClaimRef(
        kind="trust",
        ref_id=f"scanner:{vulnerability.scanner}",
        evidence_id=evidence_id,
    )
    mission_source = str(factors["mission"]["source"])
    mission_claim = ClaimRef(kind="mission", ref_id=mission_source, evidence_id=evidence_id)
    risk_claim = ClaimRef(
        kind="risk",
        ref_id=f"vulnerability-priority:{vulnerability.id}",
        evidence_id=evidence_id,
    )
    selected_output: dict[str, Any] = {
        "claims": [
            trust_claim.model_dump(mode="json"),
            mission_claim.model_dump(mode="json"),
            risk_claim.model_dump(mode="json"),
        ],
        "count": 3,
    }
    score_unit = round(score / 100.0, 6)
    weighed_items = [{**claim, "weight": score_unit} for claim in selected_output["claims"]]
    weighed_output: dict[str, Any] = {"items": weighed_items}
    scored_items = [{**item, "score": score_unit} for item in weighed_items]
    scored_output: dict[str, Any] = {"items": scored_items, "factor": 1.0}
    steps = [
        DerivationStep(
            seq=1,
            op="select_claims",
            input_refs=[trust_claim.ref_id, mission_claim.ref_id, risk_claim.ref_id],
            params={"kinds": ["trust", "mission", "risk"]},
            output=selected_output,
            note="Select the owner records used for vulnerability prioritization.",
        ),
        DerivationStep(
            seq=2,
            op="weigh",
            input_refs=["step:1"],
            params={"default": score_unit, "factor_sources": factors, "priority": priority},
            output=weighed_output,
            note=(
                "Compose carried CVSS/EPSS with EA-0014 threat, EA-0023 exposure, "
                "EA-0007 mission, EA-0012 baseline, and EA-0006 trust factors."
            ),
        ),
        DerivationStep(
            seq=3,
            op="mission_weight",
            input_refs=["step:2"],
            params={"factor": 1.0, "source_field": "weight", "target_field": "score"},
            output=scored_output,
            note="Emit the replayable [0,1] priority score without recomputing owner engines.",
        ),
    ]
    return build_derivation(
        inputs=[trust_claim, mission_claim, risk_claim],
        steps=steps,
        model_version=1,
        engine_version="vulnerability-priority/v1",
    )


def _factor_sources_from_derivation(priority: VulnPriority) -> dict[str, Any]:
    for step in priority.derivation.steps:
        if step.seq == 2:
            selected = step.params.get("factor_sources")
            if not isinstance(selected, dict):
                raise VulnNotReplayable("vulnerability derivation is missing factor sources")
            return selected
    raise VulnNotReplayable("vulnerability derivation is missing factor source step")


def _score_from_replay(result: dict[str, Any]) -> float:
    items = result.get("items")
    if not isinstance(items, list) or not items:
        raise VulnNotReplayable("vulnerability priority derivation emitted no score items")
    scores: list[float] = []
    for item in items:
        if not isinstance(item, dict):
            raise VulnNotReplayable("vulnerability priority derivation emitted invalid score item")
        selected = item.get("score")
        if not isinstance(selected, int | float) or isinstance(selected, bool):
            raise VulnNotReplayable("vulnerability priority derivation emitted invalid score")
        scores.append(float(selected))
    return round(max(scores) * 100.0, 6)


def _priority_for_score(score: float) -> str:
    if score >= 90.0:
        return "immediate"
    if score >= 70.0:
        return "high"
    if score >= 40.0:
        return "medium"
    if score >= 10.0:
        return "low"
    return "deferred"


def _priority_reason(
    vulnerability: VulnerabilityRecord,
    *,
    score: float,
    priority: str,
) -> str:
    return (
        f"{priority.title()} priority {score:.1f} for {vulnerability.cve_id} is composed from "
        "carried severity, threat exploitation, exposure, mission impact, baseline blocking, "
        "and scanner trust."
    )


def _first_evidence_id(vulnerability: VulnerabilityRecord) -> str | None:
    for basis in vulnerability.basis:
        if basis.evidence_id is not None:
            return basis.evidence_id
    return vulnerability.asset_ref.evidence_id


def _normalize_cvss(value: float) -> float:
    return _clamp_unit(value / 10.0)


def _unit_factor(value: float, *, field: str) -> float:
    if isinstance(value, bool) or not math.isfinite(value) or value < 0.0 or value > 1.0:
        raise VulnConfigInvalid(f"{field} must be in [0,1]")
    return float(value)


def _clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, value))
