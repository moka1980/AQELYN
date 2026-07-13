"""I4 acceptance tests for IAG findings and delegated remediation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.evidence import InMemoryEvidenceStore
from aqelyn.findings import Finding, FindingQuery, InMemoryFindingStore
from aqelyn.graph import EdgeView, ImpactResult, KnowledgeGraph, Path, Subgraph
from aqelyn.iag import (
    IdentityAccessGovernanceEngine,
    InMemoryCertificationStore,
)
from aqelyn.iag.models import AccessRisk, AccessRiskReport, Certification, ReviewItem
from aqelyn.objects import AQObject, AQRelationship, InMemoryObjectStore, ObjectQuery, ObjectStore
from aqelyn.policy import PolicyEngine
from aqelyn.workflow import Playbook, Run

SYS = ActorRef(actor_type="system", actor_id="iag-i4-test")


def _now() -> datetime:
    return datetime.now(UTC)


def _path(*node_ids: str) -> Path:
    return Path(node_ids=list(node_ids), edges=[], length=max(0, len(node_ids) - 1))


def _risk(kind: str, *, subject_id: str, entitlement_id: str | None = None) -> AccessRisk:
    detail: dict[str, Any] = {"identity_id": subject_id}
    if entitlement_id is not None:
        detail["entitlement_id"] = entitlement_id
    return AccessRisk(
        kind=kind,
        subject_id=subject_id,
        detail=detail,
        severity="high",
        evidence_path=_path(subject_id, entitlement_id) if entitlement_id is not None else None,
        reason=f"{kind} requires review.",
    )


def _review_item(*, evidence_id: str, decision: str = "revoked") -> ReviewItem:
    now = _now()
    return ReviewItem(
        id=new_id("rvi"),
        identity_id=new_id("obj"),
        account_id=new_id("obj"),
        entitlement_id=new_id("obj"),
        current_state={"granted": True},
        recommendation="Revoke access.",
        decision=decision,
        decided_by=SYS,
        decided_at=now,
        evidence_id=evidence_id,
        note="No longer required.",
    )


def _cert(item: ReviewItem) -> Certification:
    now = _now()
    return Certification(
        id=new_id("cert"),
        name="Privileged access review",
        scope={"object_type": "identity"},
        status="in_progress",
        items=[item],
        created_by=SYS,
        created_at=now,
    )


async def _decision_evidence(store: InMemoryEvidenceStore, item: ReviewItem | None = None) -> str:
    from aqelyn.events import Subject
    from aqelyn.evidence import EvidenceRecord

    now = utc_now()
    object_ids = [new_id("obj")] if item is None else [item.identity_id]
    record = await store.add(
        EvidenceRecord(
            id="",
            evidence_type="iag.certification_decision",
            schema_version=1,
            subject=Subject(object_ids=object_ids),
            collected_at=now,
            recorded_at=now,
            collector=SYS,
            source_id=new_id("src"),
            method="iag.decide_item/v1",
            content={"decision": "revoked"},
            content_hash="",
            seq=0,
            prev_hash=None,
            record_hash="",
        )
    )
    return record.id


def _engine(
    *,
    object_store: ObjectStore | None = None,
    cert_store: InMemoryCertificationStore | None = None,
    evidence_store: InMemoryEvidenceStore | None = None,
    finding_store: InMemoryFindingStore | None = None,
    workflow: _WorkflowRecorder | None = None,
    mission: _ReversePrioritizer | None = None,
) -> IdentityAccessGovernanceEngine:
    selected_evidence = evidence_store or InMemoryEvidenceStore()
    return IdentityAccessGovernanceEngine(
        object_store or InMemoryObjectStore(),
        cast(KnowledgeGraph, _EmptyGraph()),
        PolicyEngine([]),
        cert_store or InMemoryCertificationStore(),
        selected_evidence,
        finding_store=finding_store,
        workflow_engine=workflow,
        mission_engine=cast(Any, mission),
    )


async def test_iag_risks_to_findings() -> None:
    evidence_store = InMemoryEvidenceStore()
    finding_store = InMemoryFindingStore(evidence_exists=evidence_store.exists)
    mission = _ReversePrioritizer()
    identity_a = new_id("obj")
    identity_b = new_id("obj")
    entitlement_b = new_id("obj")
    report = AccessRiskReport(
        evaluated=2,
        truncated=False,
        risks=[
            _risk("dormant", subject_id=identity_a),
            _risk("over_privilege", subject_id=identity_b, entitlement_id=entitlement_b),
        ],
    )
    engine = _engine(
        evidence_store=evidence_store,
        finding_store=finding_store,
        mission=mission,
    )

    finding_ids = await engine.risks_to_findings(report, by=SYS)

    assert finding_ids == list(reversed(mission.seen))
    findings = [await finding_store.get(finding_id) for finding_id in finding_ids]
    assert all(finding is not None for finding in findings)
    loaded = [finding for finding in findings if finding is not None]
    assert {finding.finding_type for finding in loaded} == {
        "iag.dormant",
        "iag.over_privilege",
    }
    assert all(finding.evidence_ids for finding in loaded)
    assert all(finding.automation.action_ref == "iag.remediate_access" for finding in loaded)
    assert all(finding.source_engine == "iag_engine" for finding in loaded)
    for finding in loaded:
        evidence = await evidence_store.get(finding.evidence_ids[0], actor=SYS)
        assert evidence.evidence_type == "iag.access_risk"
        assert evidence.content is not None
        assert evidence.content["risk"]["kind"] in {"dormant", "over_privilege"}
        assert (await evidence_store.verify(evidence.id)).ok


async def test_iag_complete_delegates() -> None:
    evidence_store = InMemoryEvidenceStore()
    finding_store = InMemoryFindingStore(evidence_exists=evidence_store.exists)
    workflow = _WorkflowRecorder()
    evidence_id = await _decision_evidence(evidence_store)
    item = _review_item(evidence_id=evidence_id)
    cert = _cert(item)
    cert_store = InMemoryCertificationStore()
    saved = await cert_store.put(cert)
    engine = _engine(
        cert_store=cert_store,
        evidence_store=evidence_store,
        finding_store=finding_store,
        workflow=workflow,
    )

    run_ids = await engine.complete_certification(saved.id, by=SYS)

    assert run_ids == [workflow.runs[0].id]
    completed = await cert_store.get(saved.id)
    assert completed is not None
    assert completed.status == "completed"
    rows, _ = await finding_store.query(FindingQuery(limit=10))
    assert len(rows) == 1
    finding = rows[0]
    assert finding.finding_type == "iag.certification_revocation"
    assert finding.evidence_ids == [evidence_id]
    expected_affected = [
        value
        for value in (item.identity_id, item.account_id, item.entitlement_id)
        if value is not None
    ]
    assert finding.affected_object_ids == sorted(expected_affected)
    assert len(workflow.playbooks) == 1
    playbook = workflow.playbooks[0]
    assert playbook.steps[0].action_type == "iag.remediate_access"
    assert playbook.steps[0].requires_approval is True
    assert playbook.steps[0].inputs["certification_id"] == saved.id
    assert playbook.steps[0].inputs["review_item_id"] == item.id
    assert workflow.source_findings[0].id == finding.id


async def test_iag_no_direct_access_mutation() -> None:
    evidence_store = InMemoryEvidenceStore()
    evidence_id = await _decision_evidence(evidence_store)
    item = _review_item(evidence_id=evidence_id)
    cert_store = InMemoryCertificationStore()
    saved = await cert_store.put(_cert(item))
    finding_store = InMemoryFindingStore(evidence_exists=evidence_store.exists)
    workflow = _WorkflowRecorder()
    tracking_store = _TrackingObjectStore(InMemoryObjectStore())
    engine = _engine(
        object_store=cast(ObjectStore, tracking_store),
        cert_store=cert_store,
        evidence_store=evidence_store,
        finding_store=finding_store,
        workflow=workflow,
    )

    await engine.complete_certification(saved.id, by=SYS)

    assert tracking_store.mutations == []
    assert len(workflow.playbooks) == 1


@dataclass(frozen=True)
class _PriorityRef:
    finding_id: str


class _ReversePrioritizer:
    def __init__(self) -> None:
        self.seen: list[str] = []

    async def prioritize(self, findings: Sequence[Finding]) -> Sequence[_PriorityRef]:
        self.seen = [finding.id for finding in findings]
        return [_PriorityRef(finding_id=finding.id) for finding in reversed(findings)]


@dataclass
class _WorkflowRecorder:
    playbooks: list[Playbook] = field(default_factory=list)
    source_findings: list[Finding] = field(default_factory=list)
    runs: list[Run] = field(default_factory=list)

    async def propose(
        self,
        playbook: Playbook,
        *,
        by: ActorRef,
        source_finding: Finding | None = None,
    ) -> Run:
        assert source_finding is not None
        now = utc_now()
        run = Run(
            id=new_id("run"),
            playbook_id=playbook.id,
            playbook_version=playbook.version,
            tenant_id=playbook.tenant_id,
            status="proposed",
            source_finding_id=source_finding.id,
            created_by=by,
            created_at=now,
            updated_at=now,
            version=1,
        )
        self.playbooks.append(playbook)
        self.source_findings.append(source_finding)
        self.runs.append(run)
        return run


class _TrackingObjectStore:
    def __init__(self, inner: InMemoryObjectStore) -> None:
        self._inner = inner
        self.mutations: list[str] = []

    @property
    def registry(self) -> Any:
        return self._inner.registry

    async def get(self, object_id: str, *, resolve_merged: bool = True) -> AQObject | None:
        return await self._inner.get(object_id, resolve_merged=resolve_merged)

    async def upsert(self, obj: AQObject) -> AQObject:
        self.mutations.append("upsert")
        return await self._inner.upsert(obj)

    async def update(self, obj: AQObject, *, expected_version: int) -> AQObject:
        self.mutations.append("update")
        return await self._inner.update(obj, expected_version=expected_version)

    async def query(self, q: ObjectQuery) -> tuple[list[AQObject], str | None]:
        return await self._inner.query(q)

    async def relate(self, rel: AQRelationship) -> AQRelationship:
        self.mutations.append("relate")
        return await self._inner.relate(rel)

    async def relationships(
        self,
        object_id: str,
        *,
        direction: str = "both",
        relation_type: str | None = None,
    ) -> list[AQRelationship]:
        return await self._inner.relationships(
            object_id,
            direction=direction,
            relation_type=relation_type,
        )

    async def merge(self, survivor_id: str, duplicate_id: str, *, by: ActorRef) -> AQObject:
        self.mutations.append("merge")
        return await self._inner.merge(survivor_id, duplicate_id, by=by)

    async def set_state(
        self,
        object_id: str,
        state: str,
        *,
        by: ActorRef,
        expected_version: int,
    ) -> AQObject:
        self.mutations.append("set_state")
        return await self._inner.set_state(
            object_id,
            state,
            by=by,
            expected_version=expected_version,
        )

    async def history(self, object_id: str) -> list[dict[str, Any]]:
        return await self._inner.history(object_id)


class _EmptyGraph:
    async def neighbors(
        self,
        node_id: str,
        *,
        direction: str = "both",
        relation_types: list[str] | tuple[str, ...] | None = None,
    ) -> list[EdgeView]:
        return []

    async def subgraph(
        self,
        start_id: str,
        *,
        direction: str = "both",
        relation_types: list[str] | tuple[str, ...] | None = None,
        max_depth: int = 6,
        max_nodes: int = 10_000,
    ) -> Subgraph:
        return Subgraph()

    async def shortest_path(
        self,
        from_id: str,
        to_id: str,
        *,
        direction: str = "both",
        relation_types: list[str] | tuple[str, ...] | None = None,
        max_depth: int = 6,
    ) -> Path | None:
        return None

    async def paths(
        self,
        from_id: str,
        to_id: str,
        *,
        direction: str = "both",
        relation_types: list[str] | tuple[str, ...] | None = None,
        max_depth: int = 6,
        max_paths: int = 10,
        max_work: int = 50_000,
    ) -> list[Path]:
        return []

    async def impact(
        self,
        node_id: str,
        *,
        direction: str = "in",
        relation_types: list[str] | tuple[str, ...] | None = None,
        max_depth: int = 6,
        max_nodes: int = 10_000,
    ) -> ImpactResult:
        return ImpactResult()

    async def correlate(
        self,
        seed_ids: list[str] | tuple[str, ...],
        *,
        within_hops: int = 2,
        relation_types: list[str] | tuple[str, ...] | None = None,
        max_nodes: int = 10_000,
    ) -> Subgraph:
        return Subgraph()

    async def explain_path(self, path: Path) -> list[dict[str, object]]:
        return []
