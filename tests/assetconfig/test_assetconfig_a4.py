"""A4 acceptance tests for drift evidence, findings, and delegated remediation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from aqelyn.assetconfig import (
    ACG_REMEDIATION_ACTION,
    ASSET_OBJECT_TYPE,
    ACGConfig,
    AssetConfigAnalyzer,
    Baseline,
    Check,
    FrameworkRef,
    InMemoryDriftSnapshotStore,
    MissionPrioritizer,
)
from aqelyn.conventions import ActorRef, new_id
from aqelyn.evidence import InMemoryEvidenceStore
from aqelyn.findings import Finding, InMemoryFindingStore
from aqelyn.objects import AQObject, AQRelationship, InMemoryObjectStore, ObjectQuery, SourceRef
from aqelyn.workflow import (
    ActionSpec,
    InMemoryActionRegistry,
    InMemoryRunStore,
    WorkflowEngine,
)

SYS = ActorRef(actor_type="system", actor_id="assetconfig-a4-test")


@dataclass
class _RemediationHandler:
    spec: ActionSpec = field(
        default_factory=lambda: ActionSpec(
            action_type=ACG_REMEDIATION_ACTION,
            capability="assetconfig.remediate",
            effect="reversible",
            reversible=True,
            description="Propose an asset configuration remediation.",
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
        raise AssertionError("A4 must only propose workflow runs")

    async def rollback(self, rollback_ref: str, *, tenant_id: str | None) -> None:
        raise AssertionError("A4 must not rollback workflow actions")


@dataclass(frozen=True)
class _PriorityRef:
    finding_id: str


class _ReversePrioritizer:
    def __init__(self) -> None:
        self.seen: list[str] = []

    async def prioritize(self, findings: Sequence[Finding]) -> Sequence[_PriorityRef]:
        self.seen = [finding.id for finding in findings]
        return [_PriorityRef(finding_id=finding.id) for finding in reversed(findings)]


class _MutationSpyStore:
    def __init__(self, inner: InMemoryObjectStore) -> None:
        self.inner = inner
        self.mutations: list[str] = []

    async def get(self, object_id: str, *, resolve_merged: bool = True) -> AQObject | None:
        return await self.inner.get(object_id, resolve_merged=resolve_merged)

    async def upsert(self, obj: AQObject) -> AQObject:
        self.mutations.append("upsert")
        return await self.inner.upsert(obj)

    async def update(self, obj: AQObject, *, expected_version: int) -> AQObject:
        self.mutations.append("update")
        return await self.inner.update(obj, expected_version=expected_version)

    async def query(self, q: ObjectQuery) -> tuple[list[AQObject], str | None]:
        return await self.inner.query(q)

    async def relate(self, rel: AQRelationship) -> AQRelationship:
        self.mutations.append("relate")
        return await self.inner.relate(rel)

    async def relationships(
        self, object_id: str, *, direction: str = "both", relation_type: str | None = None
    ) -> list[AQRelationship]:
        return await self.inner.relationships(
            object_id, direction=direction, relation_type=relation_type
        )

    async def merge(self, survivor_id: str, duplicate_id: str, *, by: ActorRef) -> AQObject:
        self.mutations.append("merge")
        return await self.inner.merge(survivor_id, duplicate_id, by=by)

    async def set_state(
        self, object_id: str, state: str, *, by: ActorRef, expected_version: int
    ) -> AQObject:
        self.mutations.append("set_state")
        return await self.inner.set_state(
            object_id, state, by=by, expected_version=expected_version
        )

    async def history(self, object_id: str) -> list[dict[str, Any]]:
        return await self.inner.history(object_id)


def _now() -> datetime:
    return datetime.now(UTC)


def _source(method: str = "assetconfig-a4-test") -> SourceRef:
    return SourceRef(source_id=new_id("src"), observed_at=_now(), method=method)


def _object_store() -> InMemoryObjectStore:
    store = InMemoryObjectStore()
    store.registry.register(ASSET_OBJECT_TYPE, 1, None)
    return store


def _asset(
    name: str,
    *,
    observed: dict[str, Any],
    attrs: dict[str, Any] | None = None,
) -> AQObject:
    now = _now()
    attributes = dict(attrs or {})
    attributes["observed_state"] = dict(observed)
    return AQObject(
        id="",
        object_type=ASSET_OBJECT_TYPE,
        schema_version=1,
        display_name=name,
        attributes=attributes,
        sources=[_source(f"asset:{name}")],
        first_seen_at=now,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
        created_by=SYS,
        updated_by=SYS,
    )


def _check(
    check_id: str,
    key: str,
    expected: object,
    *,
    severity: str,
) -> Check:
    return Check(
        id=check_id,
        key=key,
        expected=expected,
        comparator="eq",
        severity=severity,
        rationale=f"{key} must match the approved baseline.",
        framework_refs=[FrameworkRef(framework="CIS", requirement=f"CIS-{check_id}")],
    )


def _baseline() -> Baseline:
    return Baseline(
        id="cis-linux",
        name="CIS Linux",
        asset_class="linux_server",
        version=1,
        checks=[
            _check("ssh-root", "ssh.root", "no", severity="high"),
            _check("auditd", "auditd.enabled", True, severity="critical"),
        ],
        tenant_id=None,
        set_by=SYS,
        set_at=_now(),
    )


def _config() -> ACGConfig:
    return ACGConfig(
        classification_rules=[
            {
                "asset_class": "linux_server",
                "condition": {
                    "op": "eq",
                    "attr": "attributes.os_family",
                    "value": "linux",
                },
            }
        ]
    )


def _workflow(handler: _RemediationHandler) -> tuple[WorkflowEngine, InMemoryRunStore]:
    registry = InMemoryActionRegistry()
    registry.register(handler)
    run_store = InMemoryRunStore()
    return (
        WorkflowEngine(
            store=run_store,
            registry=registry,
            evidence_store=InMemoryEvidenceStore(),
        ),
        run_store,
    )


async def _seed_failing(store: InMemoryObjectStore) -> str:
    failed = await store.upsert(
        _asset(
            "linux-fail",
            attrs={"os_family": "linux"},
            observed={"ssh.root": "yes", "auditd.enabled": False},
        )
    )
    await store.upsert(
        _asset(
            "linux-pass",
            attrs={"os_family": "linux"},
            observed={"ssh.root": "no", "auditd.enabled": True},
        )
    )
    return failed.id


async def test_acg_evidence_recorded() -> None:
    object_store = _object_store()
    failing_id = await _seed_failing(object_store)
    snapshot_store = InMemoryDriftSnapshotStore()
    evidence_store = InMemoryEvidenceStore()
    analyzer = AssetConfigAnalyzer(
        object_store,
        [_baseline()],
        snapshot_store=snapshot_store,
        evidence_store=evidence_store,
        config=_config(),
        actor=SYS,
        source_id=new_id("src"),
    )

    snapshot = await analyzer.assess(tenant_id=None)

    assert snapshot.evidence_id is not None
    record = await evidence_store.get(snapshot.evidence_id, actor=SYS)
    assert record.evidence_type == "asset_config.drift_snapshot"
    assert record.method == "assetconfig.assess/v1"
    assert record.subject.object_ids == [failing_id]
    assert record.content is not None
    assert record.content["snapshot_id"] == snapshot.id
    assert record.content["overall_score"] == 0.5
    assert (await evidence_store.verify(snapshot.evidence_id)).ok

    stored = await snapshot_store.get(snapshot.id)
    assert stored is not None
    assert stored.evidence_id == snapshot.evidence_id


async def test_acg_drift_to_findings() -> None:
    object_store = _object_store()
    failing_id = await _seed_failing(object_store)
    evidence_store = InMemoryEvidenceStore()
    finding_store = InMemoryFindingStore(evidence_exists=evidence_store.exists)
    handler = _RemediationHandler()
    workflow, run_store = _workflow(handler)
    mission_engine = _ReversePrioritizer()
    analyzer = AssetConfigAnalyzer(
        object_store,
        [_baseline()],
        evidence_store=evidence_store,
        finding_store=finding_store,
        workflow_engine=workflow,
        mission_engine=cast(MissionPrioritizer, mission_engine),
        config=_config(),
        actor=SYS,
        source_id=new_id("src"),
    )
    snapshot = await analyzer.assess(tenant_id=None)

    finding_ids = await analyzer.drift_to_findings(snapshot, by=SYS)

    assert finding_ids == list(reversed(mission_engine.seen))
    findings = [await finding_store.get(finding_id) for finding_id in finding_ids]
    loaded = [finding for finding in findings if finding is not None]
    assert len(loaded) == 2
    assert {finding.dedup_key for finding in loaded} == {
        f"asset_config.drift:{failing_id}:cis-linux:ssh-root",
        f"asset_config.drift:{failing_id}:cis-linux:auditd",
    }
    assert all(finding.evidence_ids == [snapshot.evidence_id] for finding in loaded)
    assert all(finding.affected_object_ids == [failing_id] for finding in loaded)
    assert all(finding.source_engine == "acg_engine" for finding in loaded)
    assert all(finding.automation.eligibility == "assisted" for finding in loaded)
    assert all(finding.automation.action_ref == ACG_REMEDIATION_ACTION for finding in loaded)
    assert {finding.severity_score for finding in loaded} == {75.0, 100.0}
    assert all(
        finding.expert_details is not None and finding.expert_details["snapshot_id"] == snapshot.id
        for finding in loaded
    )

    runs = await run_store.list()
    assert len(runs) == 2
    assert all(run.status == "proposed" for run in runs)
    assert {run.source_finding_id for run in runs} == set(finding_ids)
    assert handler.simulated == 0
    assert handler.executed == 0


async def test_acg_no_direct_mutation() -> None:
    inner_store = _object_store()
    await _seed_failing(inner_store)
    spy_store = _MutationSpyStore(inner_store)
    evidence_store = InMemoryEvidenceStore()
    finding_store = InMemoryFindingStore(evidence_exists=evidence_store.exists)
    handler = _RemediationHandler()
    workflow, _run_store = _workflow(handler)
    analyzer = AssetConfigAnalyzer(
        spy_store,
        [_baseline()],
        evidence_store=evidence_store,
        finding_store=finding_store,
        workflow_engine=workflow,
        config=_config(),
        actor=SYS,
        source_id=new_id("src"),
    )

    snapshot = await analyzer.assess(tenant_id=None)
    await analyzer.drift_to_findings(snapshot, by=SYS)

    assert spy_store.mutations == []
    assert handler.executed == 0
