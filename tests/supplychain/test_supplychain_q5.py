"""C-027 Q5 acceptance tests for owner routing, safe remediation, and service wiring."""

from __future__ import annotations

import importlib
import os
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol, cast

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import ComponentNotFound, StoreUnavailable
from aqelyn.events import EventTypeRegistry
from aqelyn.evidence import InMemoryEvidenceStore
from aqelyn.exposure import AssetRef
from aqelyn.findings import InMemoryFindingStore
from aqelyn.graph import ImpactResult, KnowledgeGraph
from aqelyn.inventory import InMemoryAssetStore, InventoryIntelligenceEngine
from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime, create_runtime
from aqelyn.objects import InMemoryObjectStore
from aqelyn.policy.models import ComplianceResult, ComplianceViolation
from aqelyn.risk import RiskSnapshot
from aqelyn.supplychain import (
    SUPPLYCHAIN_EVENTS,
    InMemorySBOMStore,
    PostgresSBOMStore,
    SoftwareComponent,
    SupplyChainConfig,
    SupplyChainEngine,
    SupplyChainService,
    register_supplychain_events,
)
from aqelyn.trust import InMemorySourceReliabilityRegistry
from aqelyn.vuln import (
    CarriedScore,
    InMemoryVulnerabilityStore,
    PostgresVulnerabilityStore,
    VulnBasis,
    VulnerabilityIntelligenceEngine,
    VulnerabilityRecord,
    VulnerabilityStore,
)
from aqelyn.workflow import Playbook, Run

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 20, 16, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000300501"
OTHER_TENANT = "018f0000-0000-7000-8000-000000300502"
PURL = "pkg:pypi/legacy-parser@3.0.0"
ACTOR = ActorRef(actor_type="user", actor_id="supply-chain-reviewer@example.com")


class _Closable(Protocol):
    async def close(self) -> None: ...


class _TruncatedGraph:
    async def impact(
        self,
        node_id: str,
        *,
        direction: str = "in",
        relation_types: tuple[str, ...] | None = None,
        max_depth: int = 6,
        max_nodes: int = 10_000,
    ) -> ImpactResult:
        del node_id, direction, relation_types, max_depth, max_nodes
        return ImpactResult(hits=[], truncated=True)


class _LicensePolicySpy:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], str | None, set[str] | None]] = []

    async def evaluate_compliance(
        self,
        resource: dict[str, Any],
        *,
        tenant_id: str | None,
        policy_ids: set[str] | None = None,
    ) -> ComplianceResult:
        self.calls.append((resource, tenant_id, policy_ids))
        return ComplianceResult(
            compliant=False,
            evaluated=1,
            violations=[
                ComplianceViolation(
                    policy_id="license-approved-v1",
                    rule_id="approved-license",
                    subject_ref=str(resource["id"]),
                    requirement="licenses must be approved",
                    reason="GPL-3.0-only is outside the approved dependency policy",
                )
            ],
        )


class _RiskSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str | None, Mapping[str, object] | None]] = []

    async def assess(
        self,
        *,
        tenant_id: str | None,
        scope: Mapping[str, object] | None = None,
    ) -> RiskSnapshot:
        self.calls.append((tenant_id, scope))
        return RiskSnapshot(
            id="risk-snapshot-q5",
            tenant_id=tenant_id,
            run_at=NOW,
            total=0,
            band_counts={},
            top_risks=[],
            overall_exposure=0.0,
        )


class _WorkflowSpy:
    def __init__(self) -> None:
        self.proposed: list[Playbook] = []
        self.execute_calls = 0

    async def propose(
        self,
        playbook: Playbook,
        *,
        by: ActorRef,
        source_finding: object | None = None,
    ) -> Run:
        del source_finding
        self.proposed.append(playbook.model_copy(deep=True))
        return Run(
            id=new_id("run"),
            playbook_id=playbook.id,
            playbook_version=playbook.version,
            tenant_id=playbook.tenant_id,
            status="proposed",
            created_by=by,
            created_at=NOW,
            updated_at=NOW,
        )

    async def execute(self, run_id: str) -> None:
        del run_id
        self.execute_calls += 1


def _component(*, tenant_id: str | None = TENANT) -> SoftwareComponent:
    return SoftwareComponent(
        object_id=new_id("obj"),
        tenant_id=tenant_id,
        purl=PURL,
        name="legacy-parser",
        version="3.0.0",
        component_type="library",
        licenses=["GPL-3.0-only"],
        supplier="Example OSS",
        direct=False,
        source_id=new_id("src"),
        observed_at=NOW,
        evidence_id=new_id("evd"),
    )


def _vulnerability(
    component: SoftwareComponent,
    *,
    tenant_id: str | None = TENANT,
    cve_id: str = "CVE-2026-7001",
) -> VulnerabilityRecord:
    evidence_id = new_id("evd")
    return VulnerabilityRecord(
        tenant_id=tenant_id,
        cve_id=cve_id,
        scanner="grype",
        asset_ref=AssetRef(kind="asset", ref_id=component.object_id, evidence_id=evidence_id),
        severity="high",
        cvss=CarriedScore(source="nvd:" + cve_id, value=9.1, as_of=NOW),
        epss=CarriedScore(source="first:" + cve_id, value=0.51, as_of=NOW),
        confidence=0.8,
        basis=[
            VulnBasis(
                kind="scanner",
                ref="grype:sbom:legacy-parser",
                as_of=NOW,
                evidence_id=evidence_id,
            )
        ],
        discovered_at=NOW,
    )


def _engine(
    store: InMemorySBOMStore,
    *,
    graph: KnowledgeGraph | None = None,
    vulnerability_store: VulnerabilityStore | None = None,
    vulnerability_owner: VulnerabilityIntelligenceEngine | None = None,
    license_owner: _LicensePolicySpy | None = None,
    finding_store: InMemoryFindingStore | None = None,
    risk_owner: _RiskSpy | None = None,
    workflow: _WorkflowSpy | None = None,
    batch_size: int = 100,
) -> SupplyChainEngine:
    object_store = InMemoryObjectStore(mode="enterprise")
    return SupplyChainEngine(
        store,
        inventory=InventoryIntelligenceEngine(InMemoryAssetStore(mode="enterprise")),
        source_registry=InMemorySourceReliabilityRegistry(default_reliability=0.8),
        object_store=object_store,
        graph=graph or cast(KnowledgeGraph, _TruncatedGraph()),
        evidence_store=InMemoryEvidenceStore(mode="enterprise"),
        vulnerability_store=vulnerability_store,
        vulnerability_owner=vulnerability_owner,
        license_policy_owner=license_owner,
        finding_store=finding_store,
        risk_owner=risk_owner,
        workflow_engine=workflow,
        config=SupplyChainConfig(
            license_policy_id="license-approved-v1",
            max_depth=3,
            batch_size=batch_size,
        ),
    )


async def test_sc_vulns_to_ea0024() -> None:
    supply_store = InMemorySBOMStore(mode="enterprise")
    vuln_store = InMemoryVulnerabilityStore(mode="enterprise")
    finding_store = InMemoryFindingStore(mode="enterprise")
    component = await supply_store.put_component(_component())
    vulnerability = await vuln_store.put(_vulnerability(component))
    vulnerability_owner = VulnerabilityIntelligenceEngine(
        vuln_store,
        finding_store=finding_store,
    )
    engine = _engine(
        supply_store,
        vulnerability_store=vuln_store,
        vulnerability_owner=vulnerability_owner,
        finding_store=finding_store,
    )

    [finding_id] = await engine.component_vulns_to_prioritization(
        [PURL],
        tenant_id=TENANT,
        by=ACTOR,
    )
    finding = await finding_store.get(finding_id)

    assert finding is not None
    assert finding.expert_details is not None
    factors = cast(dict[str, dict[str, object]], finding.expert_details["factors"])
    exposure = factors["exposure"]
    assert finding.expert_details["vulnerability_id"] == vulnerability.id
    assert exposure["status"] == "unknown"
    assert exposure["value"] == 0.0
    assert exposure["weight"] == 0.0
    assert cast(float, exposure["raw_weight"]) > 0.0
    assert "rather than treated as low" in str(exposure["reason"])
    assert finding.automation.eligibility == "none"
    assert finding.automation.requires_approval is True


async def test_sc_license_delegates() -> None:
    store = InMemorySBOMStore(mode="enterprise")
    component = await store.put_component(_component())
    policy = _LicensePolicySpy()
    findings = InMemoryFindingStore(mode="enterprise")
    engine = _engine(store, license_owner=policy, finding_store=findings)

    [finding_id] = await engine.license_findings(tenant_id=TENANT, by=ACTOR)
    finding = await findings.get(finding_id)

    assert finding is not None
    assert finding.finding_type == "supplychain.license_compliance"
    assert finding.affected_object_ids == [component.object_id]
    assert finding.evidence_ids
    assert finding.automation.eligibility == "none"
    assert len(policy.calls) == 1
    resource, tenant_id, policy_ids = policy.calls[0]
    assert resource["attributes"]["licenses"] == ["GPL-3.0-only"]
    assert tenant_id == TENANT
    assert policy_ids == {"license-approved-v1"}


async def test_sc_delegations() -> None:
    store = InMemorySBOMStore(mode="enterprise")
    component = await store.put_component(_component())
    vuln_store = InMemoryVulnerabilityStore(mode="enterprise")
    await vuln_store.put(_vulnerability(component))
    risk = _RiskSpy()
    engine = _engine(store, vulnerability_store=vuln_store, risk_owner=risk)

    snapshot_id = await engine.aggregate_risk(tenant_id=TENANT)
    assessment = await engine.assess(subject_ref="release:payments:2026.07", tenant_id=TENANT)

    assert snapshot_id == "risk-snapshot-q5"
    assert risk.calls == [(TENANT, {"limit": 100})]
    assert assessment.assessment_status == "complete"
    assert assessment.components == 1
    assert assessment.vulnerable_components == 1
    assert assessment.evidence_id.startswith("evd_")


async def test_sc_assessment_partial_not_clean() -> None:
    store = InMemorySBOMStore(mode="enterprise")
    first = await store.put_component(_component())
    await store.put_component(
        _component().model_copy(
            update={
                "object_id": new_id("obj"),
                "purl": "pkg:pypi/second@1.0.0",
                "name": "second",
            },
            deep=True,
        )
    )
    vuln_store = InMemoryVulnerabilityStore(mode="enterprise")
    await vuln_store.put(_vulnerability(first))

    assessment = await _engine(
        store,
        vulnerability_store=vuln_store,
        batch_size=1,
    ).assess(subject_ref="release:bounded", tenant_id=TENANT)

    assert assessment.assessment_status == "truncated"
    assert assessment.components == 1

    with pytest.raises(StoreUnavailable, match="vulnerability catalog"):
        await _engine(store).assess(subject_ref="release:unwired", tenant_id=TENANT)


async def test_sc_remediation_gated() -> None:
    store = InMemorySBOMStore(mode="enterprise")
    await store.put_component(_component())
    workflow = _WorkflowSpy()
    engine = _engine(store, workflow=workflow)

    run_id = await engine.propose_remediation(
        PURL,
        action="upgrade",
        tenant_id=TENANT,
        by=ACTOR,
    )

    assert run_id.startswith("run_")
    assert workflow.execute_calls == 0
    assert len(workflow.proposed) == 1
    [step] = workflow.proposed[0].steps
    assert step.action_type == "supplychain.dependency.upgrade"
    assert step.requires_approval is True


async def test_sc_no_side_effects() -> None:
    store = InMemorySBOMStore(mode="enterprise")
    component = await store.put_component(_component())
    workflow = _WorkflowSpy()
    engine = _engine(store, workflow=workflow)
    before = await store.get_component(PURL, tenant_id=TENANT)

    await engine.propose_remediation(
        PURL,
        action="remove",
        tenant_id=TENANT,
        by=ACTOR,
    )
    after = await store.get_component(PURL, tenant_id=TENANT)

    assert before == component == after
    assert workflow.execute_calls == 0
    assert not hasattr(engine, "execute")


async def _vuln_store(kind: str) -> AsyncIterator[VulnerabilityStore]:
    if kind == "inmemory":
        yield InMemoryVulnerabilityStore(mode="enterprise")
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresVulnerabilityStore.connect(PG_URL, mode="enterprise")
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_vuln_history, aq_vuln_record")
    try:
        yield store
    finally:
        await cast(_Closable, store).close()


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_sc_tenant_isolation(kind: str) -> None:
    target = _component()
    other = _component(tenant_id=OTHER_TENANT).model_copy(
        update={"purl": "pkg:pypi/other@1.0.0"},
        deep=True,
    )
    async for store in _vuln_store(kind):
        expected = await store.put(_vulnerability(target))
        await store.put(
            _vulnerability(
                other,
                tenant_id=OTHER_TENANT,
                cve_id="CVE-2026-9999",
            )
        )

        rows = await store.query(
            tenant_id=TENANT,
            asset_ref_id=target.object_id,
            limit=10,
        )
        wrong_tenant = await store.query(
            tenant_id=OTHER_TENANT,
            asset_ref_id=target.object_id,
            limit=10,
        )

        assert [row.id for row in rows] == [expected.id]
        assert wrong_tenant == []

    supply_store = InMemorySBOMStore(mode="enterprise")
    await supply_store.put_component(target)
    vuln_store = InMemoryVulnerabilityStore(mode="enterprise")
    with pytest.raises(ComponentNotFound):
        await _engine(
            supply_store,
            vulnerability_store=vuln_store,
            vulnerability_owner=VulnerabilityIntelligenceEngine(vuln_store),
        ).component_vulns_to_prioritization(
            [PURL],
            tenant_id=OTHER_TENANT,
            by=ACTOR,
        )


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_sc_service_health(backend: str) -> None:
    if backend == "postgres" and not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    if backend == "memory":
        runtime = create_inmemory_runtime()
        assert isinstance(runtime.supplychain_store, InMemorySBOMStore)
    else:
        assert PG_URL is not None
        runtime = await create_runtime(AQELYNConfig(backend="postgres", database_url=PG_URL))
        assert isinstance(runtime.supplychain_store, PostgresSBOMStore)

    service = runtime.kernel.get_service("supplychain_engine")
    assert isinstance(service, SupplyChainService)
    assert runtime.supplychain_engine_service is service
    assert runtime.supplychain_engine.vulnerability_owner is runtime.vuln_engine
    assert runtime.supplychain_engine.risk_owner is runtime.risk_engine
    assert runtime.supplychain_engine.workflow_engine is runtime.workflow_engine
    assert tuple(service.dependencies) == (
        "object_store",
        "knowledge_graph",
        "inventory_engine",
        "vuln_engine",
        "compliance_engine",
        "risk_engine",
        "trust_engine",
        "workflow_engine",
    )
    for event_type in SUPPLYCHAIN_EVENTS:
        assert runtime.event_bus.registry.is_registered(event_type)

    pre_start = await service.health()
    assert pre_start.status == "degraded"
    assert pre_start.ready is False

    await runtime.kernel.start()
    try:
        health = await runtime.kernel.health()
        supplychain = health.services["supplychain_engine"]
        assert supplychain.status == "degraded"
        assert supplychain.ready is True
        assert supplychain.dependencies["provenance_verifier"] == "unconfigured"
        assert supplychain.dependencies["vuln_engine"] == "healthy"
        assert supplychain.dependencies["risk_engine"] == "healthy"
        assert health.services["_kernel"].ready is True
    finally:
        await runtime.kernel.stop()


def test_sc_register_events_and_import_isolation() -> None:
    registry = EventTypeRegistry(with_core=False)
    register_supplychain_events(registry)

    assert set(SUPPLYCHAIN_EVENTS) == {
        "aqelyn.supplychain.sbom_ingested",
        "aqelyn.supplychain.dependency_risk_detected",
        "aqelyn.supplychain.provenance_failed",
    }
    assert len(SUPPLYCHAIN_EVENTS) == 3
    assert all(registry.is_registered(event_type) for event_type in SUPPLYCHAIN_EVENTS)
    assert importlib.import_module("aqelyn.supplychain").SupplyChainService is SupplyChainService
    assert hasattr(importlib.import_module("aqelyn.kernel.factory"), "create_runtime")
