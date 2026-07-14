"""R4 acceptance tests for Risk Intelligence treatment and delegation."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import OptimisticConcurrencyConflict
from aqelyn.evidence import EvidenceRecord, InMemoryEvidenceStore
from aqelyn.findings import Finding, FindingQuery, InMemoryFindingStore
from aqelyn.risk import InMemoryRiskSnapshotStore, InMemoryRiskStore, Risk, RiskIntelligenceEngine
from aqelyn.risk.store import RiskStore
from aqelyn.workflow import Playbook, Run

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 14, 15, 0, tzinfo=UTC)
ACTOR = ActorRef(actor_type="user", actor_id="risk-owner")


@pytest.fixture(params=["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def risk_store(request: pytest.FixtureRequest) -> AsyncIterator[RiskStore]:
    if request.param == "inmemory":
        yield InMemoryRiskStore()
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    from aqelyn.risk.postgres import PostgresRiskStore

    store = await PostgresRiskStore.connect(PG_URL)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_risk_snapshot, aq_risk RESTART IDENTITY")
    try:
        yield store
    finally:
        await store.close()


class WorkflowSpy:
    def __init__(self) -> None:
        self.proposals: list[tuple[Playbook, ActorRef, Finding | None]] = []
        self.execute_calls = 0

    async def propose(
        self,
        playbook: Playbook,
        *,
        by: ActorRef,
        source_finding: Finding | None = None,
    ) -> Run:
        self.proposals.append((playbook, by, source_finding))
        return Run(
            id=new_id("run"),
            playbook_id=playbook.id,
            playbook_version=playbook.version,
            tenant_id=playbook.tenant_id,
            status="proposed",
            source_finding_id=source_finding.id if source_finding is not None else None,
            created_by=by,
            created_at=NOW,
            updated_at=NOW,
            version=1,
        )

    async def execute(self, run_id: str, *, by: ActorRef) -> Run:
        self.execute_calls += 1
        raise AssertionError(f"Risk treatment must not execute workflow run {run_id}")


def _risk(
    *,
    risk_id: str,
    correlation_key: str,
    score: float = 82.0,
    band: str = "over_tolerance",
    version: int = 1,
) -> Risk:
    return Risk.model_validate(
        {
            "id": risk_id,
            "tenant_id": None,
            "correlation_key": correlation_key,
            "title": "Privileged access and exposed service risk",
            "category": "aggregate",
            "likelihood": 0.65,
            "impact": 0.8,
            "score": score,
            "band": band,
            "signals": [
                {
                    "kind": "finding",
                    "ref_id": new_id("fnd"),
                    "weight": 0.7,
                    "evidence_id": new_id("evd"),
                }
            ],
            "affected_object_ids": [new_id("obj")],
            "lifecycle": "assessed",
            "treatment": "none",
            "reason": "Correlated governance signals indicate material exposure.",
            "factors": {"likelihood": 65.0, "impact": 80.0},
            "first_seen_at": NOW,
            "last_scored_at": NOW,
            "version": version,
        }
    )


def _engine(
    risk_store: RiskStore,
    evidence_store: InMemoryEvidenceStore,
    finding_store: InMemoryFindingStore,
    workflow: WorkflowSpy | None = None,
) -> RiskIntelligenceEngine:
    return RiskIntelligenceEngine(
        finding_store,
        risk_store,
        InMemoryRiskSnapshotStore(),
        evidence_store=evidence_store,
        workflow_engine=workflow,
        source_id=new_id("src"),
        clock=lambda: NOW,
    )


def _evidence_records(store: InMemoryEvidenceStore) -> list[EvidenceRecord]:
    return sorted(store._by_id.values(), key=lambda record: record.seq)


async def test_risk_treat_evidence(risk_store: RiskStore) -> None:
    evidence_store = InMemoryEvidenceStore()
    finding_store = InMemoryFindingStore()
    risk = await risk_store.upsert(
        _risk(risk_id="risk:r4:treat-evidence", correlation_key="risk:r4:treat-evidence")
    )
    engine = _engine(risk_store, evidence_store, finding_store)

    treated = await engine.treat(
        risk.id,
        decision="accept",
        by=ACTOR,
        note="Accepted until the next quarterly review.",
        expected_version=risk.version,
    )

    assert treated.version == 2
    assert treated.lifecycle == "treated"
    assert treated.treatment == "accept"
    assert treated.treatment_note == "Accepted until the next quarterly review."
    assert treated.treated_by == ACTOR
    [record] = _evidence_records(evidence_store)
    assert record.evidence_type == "risk.treatment"
    assert record.method == "risk.treat/v1"
    assert record.content is not None
    assert record.content["risk_id"] == risk.id
    assert record.content["decision"] == "accept"
    assert record.content["expected_version"] == 1
    assert record.labels["decision"] == "accept"

    with pytest.raises(OptimisticConcurrencyConflict):
        await engine.treat(
            risk.id,
            decision="transfer",
            by=ACTOR,
            note="This stale write must fail.",
            expected_version=risk.version,
        )
    assert len(_evidence_records(evidence_store)) == 1


async def test_risk_mitigate_delegates(risk_store: RiskStore) -> None:
    evidence_store = InMemoryEvidenceStore()
    finding_store = InMemoryFindingStore()
    workflow = WorkflowSpy()
    risk = await risk_store.upsert(
        _risk(risk_id="risk:r4:mitigate", correlation_key="risk:r4:mitigate")
    )
    engine = _engine(risk_store, evidence_store, finding_store, workflow)

    treated = await engine.treat(
        risk.id,
        decision="mitigate",
        by=ACTOR,
        note="Mitigate through the approved remediation workflow.",
        expected_version=risk.version,
    )

    assert treated.version == 2
    assert treated.lifecycle == "treated"
    assert treated.treatment == "mitigate"
    [evidence] = _evidence_records(evidence_store)
    findings, _ = await finding_store.query(FindingQuery(limit=10))
    [finding] = findings
    assert finding.finding_type == "risk.mitigation"
    assert finding.evidence_ids == [evidence.id]
    assert finding.automation.eligibility == "assisted"
    assert finding.automation.requires_approval is True
    assert finding.automation.action_ref == "risk.mitigate"
    [(playbook, by, source_finding)] = workflow.proposals
    assert by == ACTOR
    assert source_finding == finding
    assert playbook.tenant_id is None
    [step] = playbook.steps
    assert step.action_type == "risk.mitigate"
    assert step.requires_approval is True
    assert step.inputs["risk_id"] == risk.id
    assert step.inputs["finding_id"] == finding.id
    assert workflow.execute_calls == 0


async def test_risk_accept_transfer(risk_store: RiskStore) -> None:
    evidence_store = InMemoryEvidenceStore()
    finding_store = InMemoryFindingStore()
    workflow = WorkflowSpy()
    accepted = await risk_store.upsert(
        _risk(risk_id="risk:r4:accept", correlation_key="risk:r4:accept")
    )
    transferred = await risk_store.upsert(
        _risk(risk_id="risk:r4:transfer", correlation_key="risk:r4:transfer", score=45.0)
    )
    engine = _engine(risk_store, evidence_store, finding_store, workflow)

    accepted_after = await engine.treat(
        accepted.id,
        decision="accept",
        by=ACTOR,
        note="Business accepts this risk for the review window.",
        expected_version=accepted.version,
    )
    transferred_after = await engine.treat(
        transferred.id,
        decision="transfer",
        by=ACTOR,
        note="Transferred to the supplier risk owner.",
        expected_version=transferred.version,
    )

    assert accepted_after.treatment == "accept"
    assert transferred_after.treatment == "transfer"
    decisions: list[object] = []
    for record in _evidence_records(evidence_store):
        assert record.content is not None
        decisions.append(record.content["decision"])
    assert decisions == ["accept", "transfer"]
    findings, _ = await finding_store.query(FindingQuery(limit=10))
    assert findings == []
    assert workflow.proposals == []
    assert workflow.execute_calls == 0
