"""Threat Intelligence Fusion engine (EA-0014 T1)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.conventions.errors import MalformedFeedRecord, ObjectNotFound, StoreUnavailable
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, EvidenceStore
from aqelyn.findings import Automation, Finding, FindingStore, Remediation
from aqelyn.graph import InMemoryKnowledgeGraph, KnowledgeGraph
from aqelyn.mission import MissionImpactResult
from aqelyn.objects import ObjectQuery, ObjectStore
from aqelyn.risk import CorrelationSignal
from aqelyn.threat.confidence import score_confidence
from aqelyn.threat.correlate import correlate
from aqelyn.threat.correlate import explain as explain_match
from aqelyn.threat.models import (
    FeedRecord,
    FusionConfig,
    MatchReport,
    QuarantinedFeedRecord,
    ThreatIndicator,
    ThreatMatch,
)
from aqelyn.threat.normalize import (
    ensure_threat_object_types,
    indicator_to_object,
    normalize_record,
    object_to_indicator,
    quarantine_time,
)
from aqelyn.threat.registry import InMemoryThreatSourceRegistry, ThreatSourceRegistry
from aqelyn.workflow import Playbook, Run, Step

_ACTOR = ActorRef(actor_type="system", actor_id="threat_fusion_engine")
THREAT_RESPONSE_ACTION = "threat.respond"


class MissionImpactProvider(Protocol):
    async def mission_impact(self, object_id: str) -> MissionImpactResult: ...


class WorkflowProposer(Protocol):
    async def propose(
        self,
        playbook: Playbook,
        *,
        by: ActorRef,
        source_finding: Finding | None = None,
    ) -> Run: ...


class ThreatFusionEngine:
    def __init__(
        self,
        object_store: ObjectStore,
        *,
        config: FusionConfig | None = None,
        actor: ActorRef | None = None,
        source_registry: ThreatSourceRegistry | None = None,
        graph: KnowledgeGraph | None = None,
        evidence_store: EvidenceStore | None = None,
        finding_store: FindingStore | None = None,
        workflow_engine: WorkflowProposer | None = None,
        mission_engine: MissionImpactProvider | None = None,
        source_id: str | None = None,
    ) -> None:
        self.object_store = object_store
        self.config = config or FusionConfig()
        self.actor = actor or _ACTOR
        self.source_registry = source_registry or InMemoryThreatSourceRegistry()
        self.graph = graph or InMemoryKnowledgeGraph(object_store)
        self.evidence_store = evidence_store
        self.finding_store = finding_store
        self.workflow_engine = workflow_engine
        self.mission_engine = mission_engine
        self.source_id = source_id or new_id("src")
        self._risk_signals: tuple[CorrelationSignal, ...] = ()
        self._quarantine: list[QuarantinedFeedRecord] = []
        ensure_threat_object_types(object_store)

    @property
    def quarantine(self) -> tuple[QuarantinedFeedRecord, ...]:
        return tuple(self._quarantine)

    @property
    def risk_signals(self) -> tuple[CorrelationSignal, ...]:
        return self._risk_signals

    async def ingest(
        self,
        records: Sequence[FeedRecord],
        *,
        tenant_id: str | None,
    ) -> list[ThreatIndicator]:
        indicators: list[ThreatIndicator] = []
        for record in records:
            try:
                indicator = normalize_record(record, tenant_id=tenant_id, config=self.config)
            except MalformedFeedRecord as exc:
                if not self.config.quarantine_on_malformed:
                    raise
                self._quarantine.append(
                    QuarantinedFeedRecord(
                        record=record,
                        reason=exc.message,
                        quarantined_at=quarantine_time(),
                    )
                )
                continue
            saved = await self.object_store.upsert(indicator_to_object(indicator, by=self.actor))
            indicators.append(object_to_indicator(saved))
        return indicators

    def explain(self, item: ThreatIndicator | ThreatMatch) -> dict[str, object]:
        if isinstance(item, ThreatMatch):
            return explain_match(item)
        indicator = item
        return {
            "indicator_id": indicator.id,
            "indicator_type": indicator.indicator_type,
            "value": indicator.value,
            "confidence": indicator.confidence,
            "sources": [source.model_dump(mode="json") for source in indicator.sources],
            "reason": (
                "Indicator was normalized from handed-in feed data and cataloged by natural key."
            ),
        }

    async def score_confidence(
        self, indicator: ThreatIndicator, *, now: datetime | None = None
    ) -> float:
        return await score_confidence(
            indicator,
            registry=self.source_registry,
            config=self.config,
            now=now,
        )

    async def correlate(
        self,
        *,
        tenant_id: str | None,
        scope: ObjectQuery | None = None,
        now: datetime | None = None,
    ) -> MatchReport:
        return await correlate(
            object_store=self.object_store,
            graph=self.graph,
            tenant_id=tenant_id,
            scope=scope,
            config=self.config.correlation,
            min_match_confidence=self.config.min_match_confidence,
            now=now,
        )

    async def matches_to_findings(
        self,
        report: MatchReport,
        *,
        by: ActorRef,
        prioritize: bool = True,
    ) -> list[str]:
        if self.evidence_store is None:
            raise StoreUnavailable("matches_to_findings requires an EvidenceStore")
        if self.finding_store is None:
            raise StoreUnavailable("matches_to_findings requires a FindingStore")

        generated: list[tuple[Finding, ThreatMatch, EvidenceRecord, CorrelationSignal]] = []
        for match in report.matches:
            finding, evidence, signal = await self._finding_for_match(match, by=by)
            generated.append((finding, match, evidence, signal))

        if prioritize:
            generated.sort(key=lambda item: (-item[0].severity_score, item[0].id))

        self._risk_signals = tuple(signal for _, _, _, signal in generated)
        for finding, match, evidence, _signal in generated:
            await self._propose_response(finding, match=match, evidence=evidence, by=by)
        return [finding.id for finding, _, _, _ in generated]

    async def _finding_for_match(
        self, match: ThreatMatch, *, by: ActorRef
    ) -> tuple[Finding, EvidenceRecord, CorrelationSignal]:
        assert self.evidence_store is not None
        assert self.finding_store is not None
        indicator = await self._indicator(match.indicator_id)
        asset = await self.object_store.get(match.asset_id, resolve_merged=False)
        if asset is None:
            raise ObjectNotFound(match.asset_id)
        evidence = await self._record_match_evidence(match, indicator=indicator, by=by)
        severity_score = await self._severity_score(match)
        correlation_key = _correlation_key(indicator, match)
        finding = await self.finding_store.raise_finding(
            _finding(
                match,
                indicator=indicator,
                asset_display_name=asset.display_name,
                evidence_id=evidence.id,
                severity_score=severity_score,
                correlation_key=correlation_key,
                at=evidence.recorded_at,
            )
        )
        return (
            finding,
            evidence,
            _risk_signal(finding, match=match, evidence=evidence, correlation_key=correlation_key),
        )

    async def _indicator(self, indicator_id: str) -> ThreatIndicator:
        obj = await self.object_store.get(indicator_id, resolve_merged=False)
        if obj is None:
            raise ObjectNotFound(indicator_id)
        return object_to_indicator(obj)

    async def _record_match_evidence(
        self,
        match: ThreatMatch,
        *,
        indicator: ThreatIndicator,
        by: ActorRef,
    ) -> EvidenceRecord:
        assert self.evidence_store is not None
        now = utc_now()
        record = EvidenceRecord(
            id="",
            tenant_id=indicator.tenant_id,
            evidence_type="threat.match",
            schema_version=1,
            subject=Subject(object_ids=[indicator.id, match.asset_id]),
            collected_at=now,
            recorded_at=now,
            collector=by,
            source_id=self.source_id,
            method="threat.matches_to_findings/v1",
            content={
                "indicator": {
                    "id": indicator.id,
                    "type": indicator.indicator_type,
                    "value": indicator.value,
                    "confidence": indicator.confidence,
                    "source_refs": [source.model_dump(mode="json") for source in indicator.sources],
                },
                "match": match.model_dump(mode="json"),
                "original_evidence_id": match.evidence_id,
                "reason": match.reason,
            },
            content_hash="",
            confidence=match.confidence,
            labels={"module": "EA-0014", "kind": "threat_match", "match_type": match.match_type},
            seq=0,
            prev_hash=None,
            record_hash="",
        )
        return await self.evidence_store.add(record)

    async def _severity_score(self, match: ThreatMatch) -> float:
        mission_factor = 1.0
        if self.mission_engine is not None:
            result = await self.mission_engine.mission_impact(match.asset_id)
            if result.impacts:
                mission_factor = max(impact.impact_score for impact in result.impacts)
        return _score(match.confidence * mission_factor * 100.0)

    async def _propose_response(
        self,
        finding: Finding,
        *,
        match: ThreatMatch,
        evidence: EvidenceRecord,
        by: ActorRef,
    ) -> None:
        if self.workflow_engine is None:
            return
        await self.workflow_engine.propose(
            _response_playbook(finding, match=match, evidence=evidence),
            by=by,
            source_finding=finding,
        )


def _finding(
    match: ThreatMatch,
    *,
    indicator: ThreatIndicator,
    asset_display_name: str,
    evidence_id: str,
    severity_score: float,
    correlation_key: str,
    at: datetime,
) -> Finding:
    return Finding(
        id="",
        tenant_id=indicator.tenant_id,
        finding_type="threat.match",
        schema_version=1,
        dedup_key=correlation_key,
        title=f"Threat indicator {indicator.value} matched {asset_display_name}",
        severity=_severity_for_score(severity_score),
        severity_score=severity_score,
        status="open",
        what_happened=(
            f"Threat indicator {indicator.value!r} matched asset {asset_display_name} "
            f"using {match.match_type} correlation."
        ),
        why_it_matters=(
            "The matched threat intelligence indicates this asset may be exposed to known "
            "malicious infrastructure or activity."
        ),
        how_determined=(
            "The Threat Intelligence Fusion Engine correlated a normalized, evidence-backed "
            "indicator against the estate and recorded match evidence."
        ),
        risk_of_inaction=(
            "If the match is not reviewed and triaged, the affected asset may remain exposed "
            "to a known threat."
        ),
        evidence_ids=[evidence_id],
        affected_object_ids=[match.asset_id],
        expert_details={
            "indicator": indicator.model_dump(mode="json"),
            "match": match.model_dump(mode="json"),
            "risk_signal_kind": "threat_intel",
            "severity_formula": "match.confidence * mission_factor * 100",
        },
        remediation=Remediation(
            summary="Review the threat match and propose a controlled response if confirmed.",
            steps=[
                "Review the indicator provenance and match evidence.",
                "Confirm whether the asset is genuinely affected.",
                "Use Workflow to propose any containment or blocking action.",
            ],
            difficulty="medium",
            estimated_effort=None,
            expected_outcome="The threat match is reviewed and any response is gated by Workflow.",
            references=["EA-0014 §0", "EA-0008"],
        ),
        automation=Automation(
            eligibility="assisted",
            action_ref=THREAT_RESPONSE_ACTION,
            requires_approval=True,
            risk_note=(
                "Threat Fusion never acts directly; response actions are proposed through Workflow."
            ),
        ),
        confidence=match.confidence,
        source_engine="threat_fusion_engine",
        correlation_id=correlation_key,
        first_detected_at=at,
        last_detected_at=at,
    )


def _risk_signal(
    finding: Finding,
    *,
    match: ThreatMatch,
    evidence: EvidenceRecord,
    correlation_key: str,
) -> CorrelationSignal:
    return CorrelationSignal(
        kind="threat_intel",
        ref_id=f"threat-match:{match.indicator_id}:{match.asset_id}",
        tenant_id=finding.tenant_id,
        correlation_key=correlation_key,
        title=finding.title,
        category="threat_intel",
        weight=match.confidence,
        impact=_unit(finding.severity_score / 100.0),
        affected_object_ids=[match.asset_id],
        evidence_id=evidence.id,
        reason=finding.why_it_matters,
        observed_at=evidence.recorded_at,
    )


def _response_playbook(
    finding: Finding, *, match: ThreatMatch, evidence: EvidenceRecord
) -> Playbook:
    return Playbook(
        id=f"threat-response-{_slug(finding.id)}",
        version=1,
        name=f"Review threat match {finding.id}",
        description="Proposed, gated response to an evidenced threat intelligence match.",
        tenant_id=finding.tenant_id,
        steps=[
            Step(
                id="review-threat-match",
                action_type=THREAT_RESPONSE_ACTION,
                inputs={
                    "finding_id": finding.id,
                    "indicator_id": match.indicator_id,
                    "asset_id": match.asset_id,
                    "match_type": match.match_type,
                    "evidence_id": evidence.id,
                    "confidence": match.confidence,
                    "reason": match.reason,
                },
                idempotency_key=f"threat:{finding.id}:{match.indicator_id}:{match.asset_id}",
                requires_approval=True,
            )
        ],
    )


def _correlation_key(indicator: ThreatIndicator, match: ThreatMatch) -> str:
    return f"threat.match:{indicator.indicator_type}:{indicator.value}:{match.asset_id}"


def _severity_for_score(score: float) -> str:
    if score >= 90.0:
        return "critical"
    if score >= 70.0:
        return "high"
    if score >= 40.0:
        return "medium"
    return "low"


def _score(value: float) -> float:
    return min(100.0, max(0.0, float(round(value, 2))))


def _unit(value: float) -> float:
    return min(1.0, max(0.0, value))


def _slug(value: str) -> str:
    return "".join(char if char.isalnum() else "-" for char in value).strip("-") or "id"
