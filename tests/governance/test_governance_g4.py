"""G4 acceptance tests for governance coverage, evidence, and findings."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from aqelyn.conventions import ActorRef, new_id
from aqelyn.evidence import InMemoryEvidenceStore
from aqelyn.findings import Finding, InMemoryFindingStore
from aqelyn.governance import ComplianceEngine, GovernanceConfig, InMemorySnapshotStore
from aqelyn.governance.engine import MissionPrioritizer
from aqelyn.objects import AQObject, InMemoryObjectStore, ObjectStore, SourceRef
from aqelyn.policy import Condition, Policy, PolicyEngine, Rule, Target

SYS = ActorRef(actor_type="system", actor_id="governance-g4-test")


def _now() -> datetime:
    return datetime.now(UTC)


def _source(method: str = "governance-g4-test") -> SourceRef:
    return SourceRef(source_id=new_id("src"), observed_at=_now(), method=method)


def _obj(name: str, *, attrs: dict[str, Any]) -> AQObject:
    now = _now()
    return AQObject(
        id="",
        object_type="generic",
        schema_version=1,
        display_name=name,
        attributes=attrs,
        sources=[_source(f"governance:{name}")],
        first_seen_at=now,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
        created_by=SYS,
        updated_by=SYS,
    )


def _condition(payload: dict[str, object]) -> Condition:
    return Condition.model_validate(payload)


def _policy(policy_id: str, *, attr: str, expected: object = True) -> Policy:
    return Policy(
        id=policy_id,
        version=1,
        name=f"Policy {policy_id}",
        description=f"Require {attr}",
        rules=[
            Rule(
                id=f"{policy_id}-rule",
                kind="compliance",
                description=f"{attr} must be {expected!r}",
                target=Target(actions=None, resource_types=["generic"]),
                condition=_condition(
                    {"op": "eq", "attr": f"resource.attributes.{attr}", "value": expected}
                ),
                effect="require",
                obligations=[],
                priority=0,
            )
        ],
        standard="aqelyn/governance-test",
        set_by=SYS,
        set_at=_now(),
    )


def _policies() -> list[Policy]:
    return [
        _policy("policy-mfa", attr="mfa_enabled"),
        _policy("policy-disk", attr="disk_encrypted"),
    ]


def _config() -> GovernanceConfig:
    return GovernanceConfig.model_validate(
        {
            "controls": [
                {
                    "id": "control-mfa",
                    "name": "MFA enabled",
                    "description": "Generic objects must have MFA enabled.",
                    "policy_ids": ["policy-mfa"],
                    "framework_refs": [
                        {"framework": "AQ", "requirement": "AQ-1"},
                        {"framework": "GOV", "requirement": "GOV-1"},
                    ],
                    "severity": "high",
                },
                {
                    "id": "control-disk",
                    "name": "Disk encrypted",
                    "description": "Generic objects must encrypt local storage.",
                    "policy_ids": ["policy-disk"],
                    "framework_refs": [{"framework": "AQ", "requirement": "AQ-2"}],
                    "severity": "critical",
                },
            ],
            "frameworks": {"AQ": ["AQ-1", "AQ-2", "AQ-3"], "GOV": ["GOV-1"]},
            "batch_size": 100,
            "min_confidence": 0.0,
        },
        context={"known_policy_ids": {"policy-mfa", "policy-disk"}},
    )


def _engine(
    object_store: ObjectStore,
    *,
    snapshot_store: InMemorySnapshotStore | None = None,
    evidence_store: InMemoryEvidenceStore | None = None,
    finding_store: InMemoryFindingStore | None = None,
    mission_engine: _ReversePrioritizer | None = None,
) -> ComplianceEngine:
    return ComplianceEngine(
        object_store,
        PolicyEngine(_policies()),
        config=_config(),
        snapshot_store=snapshot_store,
        evidence_store=evidence_store,
        finding_store=finding_store,
        mission_engine=cast(MissionPrioritizer | None, mission_engine),
        actor=SYS,
        source_id=new_id("src"),
    )


async def _seed_scores(store: ObjectStore) -> str:
    await store.upsert(_obj("passing", attrs={"mfa_enabled": True, "disk_encrypted": True}))
    failing = await store.upsert(
        _obj("disk-gap", attrs={"mfa_enabled": True, "disk_encrypted": False})
    )
    return failing.id


async def test_gov_coverage() -> None:
    engine = _engine(InMemoryObjectStore())

    rows = await engine.coverage(tenant_id=None)

    by_framework = {row.framework: row for row in rows}
    assert by_framework["AQ"].requirements == 3
    assert by_framework["AQ"].covered == 2
    assert by_framework["AQ"].coverage == 2 / 3
    assert by_framework["AQ"].score == 0.0
    assert by_framework["GOV"].requirements == 1
    assert by_framework["GOV"].covered == 1
    assert by_framework["GOV"].coverage == 1.0


async def test_gov_framework_scores(graph_harness: Any) -> None:
    store = cast(ObjectStore, graph_harness.object_store)
    await _seed_scores(store)
    engine = _engine(store)

    snapshot = await engine.assess(tenant_id=None, record_evidence=False)
    coverage = await engine.coverage(tenant_id=None)

    assert snapshot.framework_scores == {"AQ": 0.75, "GOV": 1.0}
    assert {row.framework: row.score for row in coverage} == {"AQ": 0.75, "GOV": 1.0}


async def test_gov_evidence_recorded(graph_harness: Any) -> None:
    store = cast(ObjectStore, graph_harness.object_store)
    failing_id = await _seed_scores(store)
    snapshot_store = InMemorySnapshotStore()
    evidence_store = InMemoryEvidenceStore()
    engine = _engine(store, snapshot_store=snapshot_store, evidence_store=evidence_store)

    snapshot = await engine.assess(tenant_id=None)

    assert snapshot.evidence_id is not None
    record = await evidence_store.get(snapshot.evidence_id, actor=SYS)
    assert record.evidence_type == "governance.compliance_snapshot"
    assert record.method == "governance.assess/v1"
    assert record.subject.object_ids == [failing_id]
    assert record.content is not None
    assert record.content["snapshot_id"] == snapshot.id
    assert record.content["framework_scores"] == {"AQ": 0.75, "GOV": 1.0}
    assert (await evidence_store.verify(snapshot.evidence_id)).ok

    stored = await snapshot_store.get(snapshot.id)
    assert stored is not None
    assert stored.evidence_id == snapshot.evidence_id


async def test_gov_gaps_to_findings(graph_harness: Any) -> None:
    store = cast(ObjectStore, graph_harness.object_store)
    failed = await store.upsert(
        _obj("two-gaps", attrs={"mfa_enabled": False, "disk_encrypted": False})
    )
    evidence_store = InMemoryEvidenceStore()
    finding_store = InMemoryFindingStore(evidence_exists=evidence_store.exists)
    mission_engine = _ReversePrioritizer()
    engine = _engine(
        store,
        evidence_store=evidence_store,
        finding_store=finding_store,
        mission_engine=mission_engine,
    )
    snapshot = await engine.assess(tenant_id=None)
    assert snapshot.evidence_id is not None

    finding_ids = await engine.gaps_to_findings(snapshot, by=SYS)

    assert finding_ids == list(reversed(mission_engine.seen))
    findings = [await finding_store.get(finding_id) for finding_id in finding_ids]
    assert all(finding is not None for finding in findings)
    loaded = [finding for finding in findings if finding is not None]
    assert {finding.dedup_key for finding in loaded} == {
        "governance.control_gap:control-mfa",
        "governance.control_gap:control-disk",
    }
    assert all(finding.evidence_ids == [snapshot.evidence_id] for finding in loaded)
    assert all(finding.affected_object_ids == [failed.id] for finding in loaded)
    assert all(finding.source_engine == "compliance_engine" for finding in loaded)
    assert all(finding.remediation.steps for finding in loaded)
    assert {finding.severity_score for finding in loaded} == {75.0, 100.0}
    assert all(
        finding.expert_details is not None and finding.expert_details["snapshot_id"] == snapshot.id
        for finding in loaded
    )


@dataclass(frozen=True)
class _PriorityRef:
    finding_id: str


class _ReversePrioritizer:
    def __init__(self) -> None:
        self.seen: list[str] = []

    async def prioritize(self, findings: Sequence[Finding]) -> Sequence[_PriorityRef]:
        self.seen = [finding.id for finding in findings]
        return [_PriorityRef(finding_id=finding.id) for finding in reversed(findings)]
