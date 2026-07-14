"""T4 acceptance tests for threat findings, evidence, and risk-signal delegation."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import ActionFailed, EvidenceNotFound
from aqelyn.evidence import EvidenceStore, InMemoryEvidenceStore
from aqelyn.evidence.postgres import PostgresEvidenceStore
from aqelyn.findings import Finding, FindingStore, InMemoryFindingStore
from aqelyn.findings.postgres import PostgresFindingStore
from aqelyn.graph import InMemoryKnowledgeGraph, KnowledgeGraph, Path, PostgresKnowledgeGraph
from aqelyn.mission import MissionImpact, MissionImpactResult, MissionView
from aqelyn.objects import (
    AQObject,
    AQRelationship,
    InMemoryObjectStore,
    ObjectQuery,
    ObjectStore,
    SourceRef,
)
from aqelyn.objects.postgres import PostgresObjectStore
from aqelyn.objects.registry import ObjectTypeRegistry
from aqelyn.risk import RiskCorrelator
from aqelyn.threat import (
    THREAT_RESPONSE_ACTION,
    FeedRecord,
    MatchReport,
    ThreatFusionEngine,
    ThreatMatch,
)
from aqelyn.workflow import (
    ActionSpec,
    InMemoryActionRegistry,
    InMemoryRunStore,
    PostgresRunStore,
    RunStore,
    WorkflowEngine,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 14, 16, 0, tzinfo=UTC)
TENANT_A = "018f0000-0000-7000-8000-000000000141"
SYS = ActorRef(actor_type="system", actor_id="threat-t4-test")


@dataclass
class ThreatT4Harness:
    kind: str
    object_store: ObjectStore
    graph: KnowledgeGraph
    evidence_store: EvidenceStore
    finding_store: FindingStore
    run_store: RunStore


@dataclass
class _Seed:
    engine: ThreatFusionEngine
    report: MatchReport
    match: ThreatMatch
    asset: AQObject


class _MissionStub:
    def __init__(self, impact_score: float) -> None:
        self.impact_score = impact_score

    async def mission_impact(self, object_id: str) -> MissionImpactResult:
        mission_id = new_id("obj")
        return MissionImpactResult(
            impacts=[
                MissionImpact(
                    mission=MissionView(
                        id=mission_id,
                        display_name="Critical payments mission",
                        criticality_tier=1,
                        criticality_weight=self.impact_score,
                        reason="T4 test mission impact.",
                    ),
                    impact_score=self.impact_score,
                    via=Path(node_ids=[object_id, mission_id], edges=[], length=1),
                    source_object_id=object_id,
                    reason="Threat match affects a critical mission.",
                )
            ]
        )


@dataclass
class _ThreatResponseHandler:
    spec: ActionSpec = field(
        default_factory=lambda: ActionSpec(
            action_type=THREAT_RESPONSE_ACTION,
            capability="threat.respond",
            effect="reversible",
            reversible=True,
            description="Proposed threat response action",
        )
    )
    simulated: int = 0
    executed: int = 0

    async def simulate(self, inputs: dict[str, Any], *, tenant_id: str | None) -> dict[str, Any]:
        self.simulated += 1
        return {"inputs": dict(inputs), "tenant_id": tenant_id}

    async def execute(
        self,
        inputs: dict[str, Any],
        *,
        tenant_id: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.executed += 1
        raise ActionFailed("T4 must only propose response runs")

    async def rollback(self, rollback_ref: str, *, tenant_id: str | None) -> None:
        raise ActionFailed("T4 must not roll back response runs")


class _MutationSpyStore:
    def __init__(self, inner: InMemoryObjectStore) -> None:
        self.inner = inner
        self.registry = inner.registry
        self.mutations: list[str] = []

    async def get(self, object_id: str, *, resolve_merged: bool = True) -> AQObject | None:
        return await self.inner.get(object_id, resolve_merged=resolve_merged)

    async def query(self, q: ObjectQuery) -> tuple[list[AQObject], str | None]:
        return await self.inner.query(q)

    async def relationships(
        self,
        object_id: str,
        *,
        direction: str = "both",
        relation_type: str | None = None,
    ) -> list[AQRelationship]:
        return await self.inner.relationships(
            object_id,
            direction=direction,
            relation_type=relation_type,
        )

    async def history(self, object_id: str) -> list[dict[str, Any]]:
        return await self.inner.history(object_id)

    async def upsert(self, obj: AQObject) -> AQObject:
        self.mutations.append("upsert")
        return await self.inner.upsert(obj)

    async def update(self, obj: AQObject, *, expected_version: int) -> AQObject:
        self.mutations.append("update")
        return await self.inner.update(obj, expected_version=expected_version)

    async def relate(self, rel: AQRelationship) -> AQRelationship:
        self.mutations.append("relate")
        return await self.inner.relate(rel)

    async def merge(self, survivor_id: str, duplicate_id: str, *, by: ActorRef) -> AQObject:
        self.mutations.append("merge")
        return await self.inner.merge(survivor_id, duplicate_id, by=by)

    async def set_state(
        self,
        object_id: str,
        state: str,
        *,
        by: ActorRef,
        expected_version: int,
    ) -> AQObject:
        self.mutations.append("set_state")
        return await self.inner.set_state(
            object_id,
            state,
            by=by,
            expected_version=expected_version,
        )


@pytest.fixture(params=["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def threat_t4_harness(
    request: pytest.FixtureRequest,
) -> AsyncIterator[ThreatT4Harness]:
    if request.param == "inmemory":
        memory_evidence: EvidenceStore = InMemoryEvidenceStore(mode="enterprise")

        async def memory_evidence_exists(evidence_id: str) -> bool:
            return await _evidence_exists(memory_evidence, evidence_id)

        memory_finding: FindingStore = InMemoryFindingStore(
            mode="enterprise",
            evidence_exists=memory_evidence_exists,
        )
        memory_run: RunStore = InMemoryRunStore(mode="enterprise")
        memory_object = InMemoryObjectStore(registry=ObjectTypeRegistry(), mode="enterprise")
        yield ThreatT4Harness(
            kind="inmemory",
            object_store=memory_object,
            graph=InMemoryKnowledgeGraph(memory_object),
            evidence_store=memory_evidence,
            finding_store=memory_finding,
            run_store=memory_run,
        )
        return

    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    postgres_object = await PostgresObjectStore.connect(
        PG_URL,
        registry=ObjectTypeRegistry(),
        mode="enterprise",
    )
    postgres_evidence = await PostgresEvidenceStore.connect(PG_URL, mode="enterprise")

    async def postgres_evidence_exists(evidence_id: str) -> bool:
        return await _evidence_exists(postgres_evidence, evidence_id)

    postgres_finding = await PostgresFindingStore.connect(
        PG_URL,
        mode="enterprise",
        evidence_exists=postgres_evidence_exists,
    )
    postgres_run = await PostgresRunStore.connect(PG_URL, mode="enterprise")
    async with postgres_object._pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE aq_workflow_run, aq_finding_audit, aq_finding_evidence, "
            "aq_finding_asset, aq_finding, aq_evidence_custody, aq_evidence_package, "
            "aq_evidence, aq_relationship, aq_object_natural_key, aq_object_history, "
            "aq_object RESTART IDENTITY CASCADE"
        )
    try:
        yield ThreatT4Harness(
            kind="postgres",
            object_store=postgres_object,
            graph=PostgresKnowledgeGraph(postgres_object._pool),
            evidence_store=postgres_evidence,
            finding_store=postgres_finding,
            run_store=postgres_run,
        )
    finally:
        await postgres_run.close()
        await postgres_finding.close()
        await postgres_evidence.close()
        await postgres_object.close()


async def test_tif_matches_to_findings(threat_t4_harness: ThreatT4Harness) -> None:
    seed = await _seed(threat_t4_harness, mission_engine=_MissionStub(0.9))

    finding_ids = await seed.engine.matches_to_findings(seed.report, by=SYS)

    assert len(finding_ids) == 1
    finding = await _finding(threat_t4_harness.finding_store, finding_ids[0])
    assert finding.finding_type == "threat.match"
    assert finding.source_engine == "threat_fusion_engine"
    assert finding.affected_object_ids == [seed.asset.id]
    assert finding.evidence_ids
    assert finding.automation.eligibility == "assisted"
    assert finding.automation.action_ref == THREAT_RESPONSE_ACTION
    assert finding.automation.requires_approval is True
    assert finding.severity_score == pytest.approx(72.0)
    assert finding.severity == "high"
    assert finding.expert_details is not None
    assert finding.expert_details["risk_signal_kind"] == "threat_intel"


async def test_tif_risk_signal(threat_t4_harness: ThreatT4Harness) -> None:
    seed = await _seed(threat_t4_harness)

    await seed.engine.matches_to_findings(seed.report, by=SYS)

    [signal] = seed.engine.risk_signals
    assert signal.kind == "threat_intel"
    assert signal.tenant_id == TENANT_A
    assert signal.affected_object_ids == [seed.asset.id]
    assert signal.evidence_id is not None
    assert signal.weight == seed.match.confidence
    risks = await RiskCorrelator(
        InMemoryFindingStore(mode="enterprise"),
        clock=lambda: NOW,
    ).correlate(tenant_id=TENANT_A, signals=[signal])
    assert risks[0].signals[0].kind == "threat_intel"
    assert risks[0].signals[0].evidence_id == signal.evidence_id


async def test_tif_actions_delegated(threat_t4_harness: ThreatT4Harness) -> None:
    handler = _ThreatResponseHandler()
    workflow = _workflow(threat_t4_harness, handler)
    seed = await _seed(threat_t4_harness, workflow_engine=workflow)

    finding_ids = await seed.engine.matches_to_findings(seed.report, by=SYS)

    runs = await threat_t4_harness.run_store.list(tenant_id=TENANT_A)
    assert len(runs) == 1
    [run] = runs
    assert run.status == "proposed"
    assert run.source_finding_id == finding_ids[0]
    assert handler.simulated == 0
    assert handler.executed == 0


async def test_tif_evidence_bound(threat_t4_harness: ThreatT4Harness) -> None:
    seed = await _seed(threat_t4_harness)

    [finding_id] = await seed.engine.matches_to_findings(seed.report, by=SYS)

    finding = await _finding(threat_t4_harness.finding_store, finding_id)
    evidence = await threat_t4_harness.evidence_store.get(finding.evidence_ids[0], actor=SYS)
    assert evidence.evidence_type == "threat.match"
    assert evidence.method == "threat.matches_to_findings/v1"
    assert evidence.subject.object_ids == [seed.match.indicator_id, seed.match.asset_id]
    assert evidence.content is not None
    assert evidence.content["original_evidence_id"] == seed.match.evidence_id
    assert seed.engine.risk_signals[0].evidence_id == evidence.id
    verified = await threat_t4_harness.evidence_store.verify(evidence.id)
    assert verified.ok is True


async def test_tif_no_side_effects() -> None:
    inner = InMemoryObjectStore(registry=ObjectTypeRegistry(), mode="enterprise")
    evidence_store: EvidenceStore = InMemoryEvidenceStore(mode="enterprise")

    async def evidence_exists(evidence_id: str) -> bool:
        return await _evidence_exists(evidence_store, evidence_id)

    finding_store: FindingStore = InMemoryFindingStore(
        mode="enterprise",
        evidence_exists=evidence_exists,
    )
    base_harness = ThreatT4Harness(
        kind="inmemory",
        object_store=inner,
        graph=InMemoryKnowledgeGraph(inner),
        evidence_store=evidence_store,
        finding_store=finding_store,
        run_store=InMemoryRunStore(mode="enterprise"),
    )
    seed = await _seed(base_harness)
    spy = _MutationSpyStore(inner)
    engine = ThreatFusionEngine(
        spy,
        graph=InMemoryKnowledgeGraph(inner),
        evidence_store=evidence_store,
        finding_store=finding_store,
        source_id=new_id("src"),
    )

    await engine.matches_to_findings(seed.report, by=SYS)

    assert spy.mutations == []


async def _seed(
    harness: ThreatT4Harness,
    *,
    workflow_engine: WorkflowEngine | None = None,
    mission_engine: _MissionStub | None = None,
) -> _Seed:
    engine = ThreatFusionEngine(
        harness.object_store,
        graph=harness.graph,
        evidence_store=harness.evidence_store,
        finding_store=harness.finding_store,
        workflow_engine=workflow_engine,
        mission_engine=mission_engine,
        source_id=new_id("src"),
    )
    await engine.ingest(
        [
            FeedRecord(
                source_id=new_id("src"),
                evidence_id=new_id("evd"),
                received_at=NOW,
                raw={"type": "domain", "value": "evil.example", "confidence": 0.8},
            )
        ],
        tenant_id=TENANT_A,
    )
    asset = await _asset(
        harness.object_store,
        "payments-api",
        attributes={"domains": ["evil.example"]},
    )
    report = await engine.correlate(tenant_id=TENANT_A, now=NOW)
    assert len(report.matches) == 1
    return _Seed(engine=engine, report=report, match=report.matches[0], asset=asset)


def _workflow(harness: ThreatT4Harness, handler: _ThreatResponseHandler) -> WorkflowEngine:
    registry = InMemoryActionRegistry()
    registry.register(handler)
    return WorkflowEngine(
        store=harness.run_store,
        registry=registry,
        evidence_store=harness.evidence_store,
        granted_capabilities=frozenset({handler.spec.capability}),
    )


async def _asset(
    store: ObjectStore,
    display_name: str,
    *,
    attributes: dict[str, Any],
) -> AQObject:
    return await store.upsert(
        AQObject(
            id="",
            object_type="generic",
            schema_version=1,
            tenant_id=TENANT_A,
            display_name=display_name,
            attributes=attributes,
            sources=[_source("asset.inventory/v1")],
            first_seen_at=NOW,
            last_seen_at=NOW,
            created_at=NOW,
            updated_at=NOW,
            created_by=SYS,
            updated_by=SYS,
        )
    )


def _source(method: str) -> SourceRef:
    return SourceRef(
        source_id=new_id("src"),
        evidence_id=new_id("evd"),
        observed_at=NOW,
        method=method,
    )


async def _evidence_exists(store: EvidenceStore, evidence_id: str) -> bool:
    try:
        await store.get(evidence_id, actor=SYS)
    except EvidenceNotFound:
        return False
    return True


async def _finding(store: FindingStore, finding_id: str) -> Finding:
    finding = await store.get(finding_id)
    assert finding is not None
    return finding
