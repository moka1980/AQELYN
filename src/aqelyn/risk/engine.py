"""Risk Intelligence assessment and treatment engine (EA-0013 R3/R4)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Protocol, cast

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.conventions.errors import (
    OptimisticConcurrencyConflict,
    RiskConfigInvalid,
    RiskNotFound,
    StoreUnavailable,
)
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, EvidenceStore
from aqelyn.findings import Automation, Finding, FindingStore, Remediation
from aqelyn.mission.models import MissionImpactResult
from aqelyn.risk.correlate import RiskCorrelator, explain
from aqelyn.risk.models import (
    CorrelationSignal,
    Risk,
    RiskBand,
    RiskConfig,
    RiskSnapshot,
    RiskTreatment,
)
from aqelyn.risk.scoring import score_risk
from aqelyn.risk.store import RiskSnapshotStore, RiskStore, new_risk_snapshot_id, validate_positive
from aqelyn.workflow import Playbook, Run, Step

_ASSESS_QUERY_LIMIT = 10_000
_TOP_RISK_LIMIT = 10
_RISK_MITIGATION_ACTION = "risk.mitigate"
_VALID_TREATMENTS: frozenset[str] = frozenset(("accept", "mitigate", "transfer"))
_SEVERITY_SCORES: tuple[tuple[float, str], ...] = (
    (90.0, "critical"),
    (70.0, "high"),
    (40.0, "medium"),
    (0.0, "low"),
)


class MissionImpactEngine(Protocol):
    async def mission_impact(self, object_id: str) -> MissionImpactResult: ...


class WorkflowProposer(Protocol):
    async def propose(
        self,
        playbook: Playbook,
        *,
        by: ActorRef,
        source_finding: Finding | None = None,
    ) -> Run: ...


class RiskIntelligenceEngine:
    def __init__(
        self,
        finding_store: FindingStore,
        risk_store: RiskStore,
        snapshot_store: RiskSnapshotStore,
        *,
        config: RiskConfig | None = None,
        mission_engine: MissionImpactEngine | None = None,
        evidence_store: EvidenceStore | None = None,
        workflow_engine: WorkflowProposer | None = None,
        source_id: str | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.finding_store = finding_store
        self.risk_store = risk_store
        self.snapshot_store = snapshot_store
        self.config = config or RiskConfig()
        self.mission_engine = mission_engine
        self.evidence_store = evidence_store
        self.workflow_engine = workflow_engine
        self.source_id = source_id or new_id("src")
        self._clock = clock
        self._correlator = RiskCorrelator(finding_store, config=self.config, clock=clock)

    async def correlate(
        self,
        *,
        tenant_id: str | None,
        scope: Mapping[str, object] | None = None,
        signals: Sequence[CorrelationSignal] = (),
    ) -> list[Risk]:
        return await self._correlator.correlate(
            tenant_id=tenant_id,
            scope=scope,
            signals=signals,
        )

    async def score(self, risk: Risk) -> Risk:
        mission_factor, top_mission_id = await self._mission_context(risk)
        return score_risk(
            risk,
            config=self.config,
            mission_factor=mission_factor,
            top_mission_id=top_mission_id,
        )

    async def assess(
        self,
        *,
        tenant_id: str | None,
        scope: Mapping[str, object] | None = None,
        signals: Sequence[CorrelationSignal] = (),
    ) -> RiskSnapshot:
        correlated = await self.correlate(tenant_id=tenant_id, scope=scope, signals=signals)
        existing = await self._existing_by_correlation(tenant_id=tenant_id)
        persisted: list[Risk] = []
        for risk in correlated:
            stored = existing.get(risk.correlation_key)
            if stored is not None:
                risk = risk.model_copy(
                    update={
                        "id": stored.id,
                        "first_seen_at": stored.first_seen_at,
                        "version": stored.version,
                    },
                    deep=True,
                )
            scored = await self.score(risk)
            assessed = scored.model_copy(
                update={"lifecycle": "assessed", "last_scored_at": self._now()},
                deep=True,
            )
            persisted.append(await self.risk_store.upsert(assessed))

        snapshot = _snapshot_from_risks(
            persisted,
            tenant_id=tenant_id,
            run_at=self._now(),
        )
        return await self.snapshot_store.put(snapshot)

    async def trend(self, *, tenant_id: str | None, since: datetime) -> list[dict[str, object]]:
        snapshots = await self.snapshot_store.history(tenant_id=tenant_id, since=since)
        return [_trend_point(snapshot) for snapshot in snapshots]

    async def treat(
        self,
        risk_id: str,
        *,
        decision: str,
        by: ActorRef,
        note: str | None,
        expected_version: int,
        propose_remediation: bool = True,
    ) -> Risk:
        selected = _validate_treatment(decision)
        validate_positive(expected_version, field="expected_version")
        if self.evidence_store is None:
            raise StoreUnavailable("treat requires an EvidenceStore")
        if selected == "mitigate" and propose_remediation and self.workflow_engine is None:
            raise StoreUnavailable("mitigate with propose_remediation=True requires Workflow")

        risk = await self.risk_store.get(risk_id)
        if risk is None:
            raise RiskNotFound(risk_id)
        if risk.version != expected_version:
            raise OptimisticConcurrencyConflict(
                f"expected v{expected_version}, found v{risk.version}"
            )

        treated_at = self._now()
        evidence = await self._record_treatment_evidence(
            risk,
            decision=selected,
            by=by,
            note=note,
            at=treated_at,
            propose_remediation=propose_remediation,
        )
        updated = await self.risk_store.upsert(
            risk.model_copy(
                update={
                    "lifecycle": "treated",
                    "treatment": selected,
                    "treatment_note": note,
                    "treated_by": by,
                },
                deep=True,
            )
        )
        if selected == "mitigate" and propose_remediation:
            assert self.workflow_engine is not None
            finding = await self.finding_store.raise_finding(
                _finding_for_risk_treatment(
                    updated,
                    evidence_id=evidence.id,
                    by=by,
                    note=note,
                    at=treated_at,
                )
            )
            await self.workflow_engine.propose(
                _playbook_for_risk_mitigation(updated, finding=finding),
                by=by,
                source_finding=finding,
            )
        return updated

    def explain(self, risk: Risk) -> dict[str, object]:
        return explain(risk)

    async def _record_treatment_evidence(
        self,
        risk: Risk,
        *,
        decision: RiskTreatment,
        by: ActorRef,
        note: str | None,
        at: datetime,
        propose_remediation: bool,
    ) -> EvidenceRecord:
        assert self.evidence_store is not None
        record = EvidenceRecord(
            id="",
            tenant_id=risk.tenant_id,
            evidence_type="risk.treatment",
            schema_version=1,
            subject=Subject(object_ids=list(risk.affected_object_ids)),
            collected_at=at,
            recorded_at=at,
            collector=by,
            source_id=self.source_id,
            method="risk.treat/v1",
            content={
                "risk_id": risk.id,
                "tenant_id": risk.tenant_id,
                "correlation_key": risk.correlation_key,
                "decision": decision,
                "note": note,
                "expected_version": risk.version,
                "score": risk.score,
                "band": risk.band,
                "lifecycle_before": risk.lifecycle,
                "affected_object_ids": list(risk.affected_object_ids),
                "propose_remediation": propose_remediation,
                "actor": by.model_dump(mode="json"),
            },
            content_hash="",
            confidence=1.0,
            labels={"module": "EA-0013", "kind": "risk_treatment", "decision": decision},
            seq=0,
            prev_hash=None,
            record_hash="",
        )
        return await self.evidence_store.add(record)

    async def _existing_by_correlation(self, *, tenant_id: str | None) -> dict[str, Risk]:
        rows = await self.risk_store.query(tenant_id=tenant_id, limit=_ASSESS_QUERY_LIMIT)
        return {risk.correlation_key: risk for risk in rows}

    async def _mission_context(self, risk: Risk) -> tuple[float, str | None]:
        if self.mission_engine is None:
            return 0.0, None
        best_factor = 0.0
        best_mission_id: str | None = None
        for object_id in sorted(risk.affected_object_ids):
            result = await self.mission_engine.mission_impact(object_id)
            for impact in result.impacts:
                candidate = impact.impact_score
                mission_id = impact.mission.id
                if candidate > best_factor or (
                    candidate == best_factor
                    and (best_mission_id is None or mission_id < best_mission_id)
                ):
                    best_factor = candidate
                    best_mission_id = mission_id
        return best_factor, best_mission_id

    def _now(self) -> datetime:
        return self._clock() if self._clock is not None else utc_now()


def _snapshot_from_risks(
    risks: Sequence[Risk],
    *,
    tenant_id: str | None,
    run_at: datetime,
) -> RiskSnapshot:
    band_counts: dict[RiskBand, int] = {
        "within_appetite": 0,
        "elevated": 0,
        "over_tolerance": 0,
    }
    for risk in risks:
        band_counts[risk.band] += 1
    ordered = sorted(risks, key=lambda risk: (-risk.score, risk.id))
    return RiskSnapshot(
        id=new_risk_snapshot_id(),
        tenant_id=tenant_id,
        run_at=run_at,
        total=len(risks),
        band_counts=band_counts,
        top_risks=[risk.id for risk in ordered[:_TOP_RISK_LIMIT]],
        overall_exposure=_mean([risk.score for risk in risks]),
    )


def _trend_point(snapshot: RiskSnapshot) -> dict[str, object]:
    return {
        "snapshot_id": snapshot.id,
        "run_at": snapshot.run_at.isoformat(),
        "total": snapshot.total,
        "band_counts": dict(snapshot.band_counts),
        "top_risks": list(snapshot.top_risks),
        "overall_exposure": snapshot.overall_exposure,
    }


def _mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _validate_treatment(value: str) -> RiskTreatment:
    if value not in _VALID_TREATMENTS:
        raise RiskConfigInvalid(f"unknown risk treatment decision: {value!r}")
    return cast(RiskTreatment, value)


def _finding_for_risk_treatment(
    risk: Risk,
    *,
    evidence_id: str,
    by: ActorRef,
    note: str | None,
    at: datetime,
) -> Finding:
    return Finding(
        id="",
        tenant_id=risk.tenant_id,
        finding_type="risk.mitigation",
        schema_version=1,
        dedup_key=f"risk.mitigation:{risk.id}",
        title=f"Mitigation requested for risk: {risk.title}",
        severity=_severity_for_score(risk.score),
        severity_score=risk.score,
        status="open",
        what_happened=(
            f"Risk {risk.id} was marked for mitigation by {by.actor_type}:{by.actor_id}."
        ),
        why_it_matters=(
            "The correlated risk is above the owner's chosen treatment path and needs "
            "a controlled remediation workflow."
        ),
        how_determined=(
            "The Risk Intelligence Engine recorded an evidenced treatment decision and "
            "delegated remediation as a proposed Workflow run."
        ),
        risk_of_inaction=(
            "If the proposed mitigation is not reviewed and executed through Workflow, "
            "the risk exposure may remain untreated."
        ),
        evidence_ids=[evidence_id],
        affected_object_ids=list(risk.affected_object_ids),
        expert_details={
            "risk_id": risk.id,
            "correlation_key": risk.correlation_key,
            "score": risk.score,
            "band": risk.band,
            "treatment": risk.treatment,
            "note": note,
            "signals": [signal.model_dump(mode="json") for signal in risk.signals],
            "factor_values": dict(risk.factors),
            "treated_by": by.model_dump(mode="json"),
        },
        remediation=Remediation(
            summary="Review and mitigate the correlated risk through an approved Workflow run.",
            steps=[
                "Review the risk explanation and treatment evidence.",
                "Confirm the proposed mitigation and its blast radius.",
                (
                    "Approve and execute the Workflow remediation run if the mitigation "
                    "remains appropriate."
                ),
            ],
            difficulty="medium",
            estimated_effort=None,
            expected_outcome="The selected risk is remediated through a gated Workflow run.",
            references=["EA-0013 §0", "EA-0008"],
        ),
        automation=Automation(
            eligibility="assisted",
            action_ref=_RISK_MITIGATION_ACTION,
            requires_approval=True,
            risk_note=(
                "Risk Intelligence never performs mitigation directly; it delegates to Workflow."
            ),
        ),
        confidence=1.0,
        source_engine="risk_engine",
        correlation_id=risk.correlation_key,
        first_detected_at=at,
        last_detected_at=at,
    )


def _playbook_for_risk_mitigation(risk: Risk, *, finding: Finding) -> Playbook:
    step_id = f"mitigate-{_slug(risk.id)}"
    return Playbook(
        id=f"risk-mitigate-{_slug(risk.id)}-{_slug(finding.id)}",
        version=1,
        name=f"Mitigate risk {risk.id}",
        description="Proposed remediation for an evidenced Risk Intelligence treatment decision.",
        tenant_id=risk.tenant_id,
        steps=[
            Step(
                id=step_id,
                action_type=_RISK_MITIGATION_ACTION,
                inputs={
                    "risk_id": risk.id,
                    "finding_id": finding.id,
                    "correlation_key": risk.correlation_key,
                    "score": risk.score,
                    "band": risk.band,
                    "affected_object_ids": list(risk.affected_object_ids),
                    "evidence_ids": list(finding.evidence_ids),
                    "remediation": finding.remediation.summary,
                },
                idempotency_key=f"risk:{risk.id}:{finding.id}:mitigate",
                requires_approval=True,
            )
        ],
    )


def _severity_for_score(score: float) -> str:
    for threshold, severity in _SEVERITY_SCORES:
        if score >= threshold:
            return severity
    return "low"


def _slug(value: str) -> str:
    return "".join(char if char.isalnum() else "-" for char in value).strip("-") or "id"
