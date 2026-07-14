"""Kernel construction + dependency injection (EA-0001 §7, D3)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import ConfigError, StoreUnavailable
from aqelyn.events import EventTypeRegistry, InMemoryEventBus
from aqelyn.evidence import InMemoryBlobStore, InMemoryEvidenceStore, register_evidence_events
from aqelyn.findings import InMemoryFindingStore, register_finding_events
from aqelyn.governance import (
    ComplianceEngine,
    GovernanceConfig,
    InMemorySnapshotStore,
    PostgresSnapshotStore,
    SnapshotStore,
)
from aqelyn.graph import InMemoryKnowledgeGraph, KnowledgeGraph
from aqelyn.graph.postgres import PostgresKnowledgeGraph
from aqelyn.graph.service import KnowledgeGraphService
from aqelyn.iag import (
    CertificationStore,
    IdentityAccessGovernanceEngine,
    InMemoryCertificationStore,
    PostgresCertificationStore,
)
from aqelyn.kernel.config import AQELYNConfig
from aqelyn.kernel.kernel import AQKernel
from aqelyn.kernel.service import HealthStatus
from aqelyn.kernel.wiring import BusObjectEventSink
from aqelyn.mission.engine import MissionEngine
from aqelyn.mission.service import MissionEngineService
from aqelyn.objects import InMemoryObjectStore, ObjectStore, ObjectTypeRegistry
from aqelyn.objects.postgres import PostgresObjectStore
from aqelyn.policy.memory import InMemoryPolicyStore
from aqelyn.policy.postgres import PostgresPolicyStore
from aqelyn.policy.service import PolicyEngineService, PolicyWorkflowAdapter, register_policy_events
from aqelyn.policy.store import PolicyStore
from aqelyn.trust.engine import TrustEngine
from aqelyn.trust.registry import InMemorySourceReliabilityRegistry
from aqelyn.trust.service import TrustEngineService
from aqelyn.workflow import (
    InMemoryActionRegistry,
    InMemoryRunStore,
    PostgresRunStore,
    RunStore,
    WorkflowEngine,
    register_workflow_events,
)
from aqelyn.workflow.service import WorkflowEngineService

if TYPE_CHECKING:
    from aqelyn.assetconfig.drift import AssetConfigAnalyzer
    from aqelyn.assetconfig.service import AssetConfigGovernanceService
    from aqelyn.assetconfig.store import BaselineStore, DriftSnapshotStore
    from aqelyn.governance.service import ComplianceGovernanceService
    from aqelyn.iag.service import IdentityAccessGovernanceService
    from aqelyn.risk.engine import RiskIntelligenceEngine
    from aqelyn.risk.service import RiskIntelligenceService
    from aqelyn.risk.store import RiskSnapshotStore, RiskStore
    from aqelyn.soc.engine import SecurityOperationsEngine
    from aqelyn.soc.service import SecurityOperationsService
    from aqelyn.soc.store import SOCStore
    from aqelyn.threat.engine import ThreatFusionEngine
    from aqelyn.threat.registry import ThreatSourceRegistry
    from aqelyn.threat.service import ThreatFusionService


@dataclass
class Runtime:
    """The wired kernel plus the shared infrastructure it injects."""

    kernel: AQKernel
    event_bus: InMemoryEventBus
    object_store: ObjectStore
    evidence_store: InMemoryEvidenceStore
    finding_store: InMemoryFindingStore
    blob_store: InMemoryBlobStore
    knowledge_graph: KnowledgeGraph
    knowledge_graph_service: KnowledgeGraphService
    trust_engine: TrustEngine
    trust_engine_service: TrustEngineService
    mission_engine: MissionEngine
    mission_engine_service: MissionEngineService
    compliance_snapshot_store: SnapshotStore
    compliance_engine: ComplianceEngine
    compliance_engine_service: ComplianceGovernanceService
    policy_store: PolicyStore
    policy_engine_service: PolicyEngineService
    workflow_policy_adapter: PolicyWorkflowAdapter
    workflow_run_store: RunStore
    workflow_action_registry: InMemoryActionRegistry
    workflow_engine: WorkflowEngine
    workflow_engine_service: WorkflowEngineService
    iag_certification_store: CertificationStore
    iag_engine: IdentityAccessGovernanceEngine
    iag_engine_service: IdentityAccessGovernanceService
    acg_baseline_store: BaselineStore
    acg_snapshot_store: DriftSnapshotStore
    acg_engine: AssetConfigAnalyzer
    acg_engine_service: AssetConfigGovernanceService
    risk_store: RiskStore
    risk_snapshot_store: RiskSnapshotStore
    risk_engine: RiskIntelligenceEngine
    risk_engine_service: RiskIntelligenceService
    threat_source_registry: ThreatSourceRegistry
    threat_engine: ThreatFusionEngine
    threat_engine_service: ThreatFusionService
    soc_store: SOCStore
    soc_engine: SecurityOperationsEngine
    soc_engine_service: SecurityOperationsService


class _RuntimeService:
    def __init__(
        self,
        name: str,
        *,
        dependencies: Sequence[str] = (),
        health_check: Callable[[], Awaitable[None]] | None = None,
        close: Callable[[], Awaitable[None]] | None = None,
        critical: bool = True,
    ) -> None:
        self._name = name
        self._dependencies = tuple(dependencies)
        self._health_check = health_check
        self._close = close
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def dependencies(self) -> Sequence[str]:
        return self._dependencies

    @property
    def critical(self) -> bool:
        return self._critical

    async def start(self) -> None:
        await self._check()
        self._started = True

    async def stop(self) -> None:
        try:
            if self._close is not None:
                await self._close()
        finally:
            self._started = False

    async def health(self) -> HealthStatus:
        try:
            await self._check()
        except StoreUnavailable as exc:
            return HealthStatus(status="unavailable", ready=False, detail=exc.message)
        if not self._started:
            return HealthStatus(status="degraded", ready=False, detail="service not started")
        return HealthStatus(status="healthy", ready=True)

    async def _check(self) -> None:
        if self._health_check is None:
            return
        try:
            await self._health_check()
        except StoreUnavailable:
            raise
        except Exception as exc:
            raise StoreUnavailable(str(exc)) from exc


async def _check_object_store(object_store: ObjectStore) -> None:
    await object_store.get(new_id("obj"), resolve_merged=False)


def _default_governance_config() -> GovernanceConfig:
    return GovernanceConfig.model_validate(
        {
            "controls": [
                {
                    "id": "control-governance-default",
                    "name": "Default governance readiness",
                    "description": "Default control used to wire the governance service.",
                    "policy_ids": ["policy-governance-default"],
                    "framework_refs": [{"framework": "AQELYN", "requirement": "GOV-READY"}],
                    "severity": "medium",
                }
            ],
            "frameworks": {"AQELYN": ["GOV-READY"]},
            "batch_size": 100,
            "min_confidence": 0.0,
        }
    )


def _register_runtime_services(
    kernel: AQKernel,
    *,
    object_store: ObjectStore,
    evidence_store: InMemoryEvidenceStore,
    finding_store: InMemoryFindingStore,
    knowledge_graph: KnowledgeGraph,
    trust_engine: TrustEngine,
    mission_engine: MissionEngine,
    policy_engine_service: PolicyEngineService,
    compliance_engine: ComplianceEngine,
    compliance_snapshot_store: SnapshotStore,
    workflow_run_store: RunStore,
    workflow_action_registry: InMemoryActionRegistry,
    workflow_engine: WorkflowEngine,
    iag_certification_store: CertificationStore,
    iag_engine: IdentityAccessGovernanceEngine,
    acg_baseline_store: BaselineStore,
    acg_snapshot_store: DriftSnapshotStore,
    acg_engine: AssetConfigAnalyzer,
    risk_store: RiskStore,
    risk_snapshot_store: RiskSnapshotStore,
    risk_engine: RiskIntelligenceEngine,
    threat_source_registry: ThreatSourceRegistry,
    threat_engine: ThreatFusionEngine,
    soc_store: SOCStore,
    soc_engine: SecurityOperationsEngine,
    close_object_store: Callable[[], Awaitable[None]] | None = None,
    close_compliance_snapshot_store: Callable[[], Awaitable[None]] | None = None,
    close_workflow_run_store: Callable[[], Awaitable[None]] | None = None,
    close_iag_certification_store: Callable[[], Awaitable[None]] | None = None,
    close_acg_baseline_store: Callable[[], Awaitable[None]] | None = None,
    close_acg_snapshot_store: Callable[[], Awaitable[None]] | None = None,
    close_risk_store: Callable[[], Awaitable[None]] | None = None,
    close_risk_snapshot_store: Callable[[], Awaitable[None]] | None = None,
    close_threat_source_registry: Callable[[], Awaitable[None]] | None = None,
    close_soc_store: Callable[[], Awaitable[None]] | None = None,
) -> tuple[
    KnowledgeGraphService,
    TrustEngineService,
    MissionEngineService,
    PolicyEngineService,
    ComplianceGovernanceService,
    WorkflowEngineService,
    IdentityAccessGovernanceService,
    AssetConfigGovernanceService,
    RiskIntelligenceService,
    ThreatFusionService,
    SecurityOperationsService,
]:
    from aqelyn.assetconfig.service import AssetConfigGovernanceService
    from aqelyn.governance.service import ComplianceGovernanceService
    from aqelyn.iag.service import IdentityAccessGovernanceService
    from aqelyn.risk.service import RiskIntelligenceService
    from aqelyn.soc.service import SecurityOperationsService
    from aqelyn.threat.service import ThreatFusionService

    kernel.register(_RuntimeService("event_bus"))
    trust_service = TrustEngineService(trust_engine)
    kernel.register(trust_service)
    kernel.register(
        _RuntimeService(
            "object_store",
            dependencies=("event_bus",),
            health_check=lambda: _check_object_store(object_store),
            close=close_object_store,
        )
    )
    graph_service = KnowledgeGraphService(knowledge_graph, object_store)
    kernel.register(graph_service)
    mission_service = MissionEngineService(mission_engine)
    kernel.register(mission_service)
    kernel.register(policy_engine_service)
    compliance_service = ComplianceGovernanceService(
        compliance_engine,
        snapshot_store=compliance_snapshot_store,
        evidence_store=evidence_store,
        finding_store=finding_store,
        close_snapshot_store=close_compliance_snapshot_store,
    )
    kernel.register(compliance_service)
    workflow_service = WorkflowEngineService(
        workflow_engine,
        run_store=workflow_run_store,
        registry=workflow_action_registry,
        evidence_store=evidence_store,
        close_run_store=close_workflow_run_store,
        dependencies=("event_bus", "policy_engine"),
    )
    kernel.register(workflow_service)
    iag_service = IdentityAccessGovernanceService(
        iag_engine,
        certification_store=iag_certification_store,
        close_certification_store=close_iag_certification_store,
    )
    kernel.register(iag_service)
    acg_service = AssetConfigGovernanceService(
        acg_engine,
        baseline_store=acg_baseline_store,
        snapshot_store=acg_snapshot_store,
        close_baseline_store=close_acg_baseline_store,
        close_snapshot_store=close_acg_snapshot_store,
    )
    kernel.register(acg_service)
    risk_service = RiskIntelligenceService(
        risk_engine,
        risk_store=risk_store,
        snapshot_store=risk_snapshot_store,
        close_risk_store=close_risk_store,
        close_snapshot_store=close_risk_snapshot_store,
    )
    kernel.register(risk_service)
    threat_service = ThreatFusionService(
        threat_engine,
        source_registry=threat_source_registry,
        trust_engine=trust_engine,
        close_source_registry=close_threat_source_registry,
    )
    kernel.register(threat_service)
    soc_service = SecurityOperationsService(
        soc_engine,
        store=soc_store,
        close_store=close_soc_store,
    )
    kernel.register(soc_service)
    return (
        graph_service,
        trust_service,
        mission_service,
        policy_engine_service,
        compliance_service,
        workflow_service,
        iag_service,
        acg_service,
        risk_service,
        threat_service,
        soc_service,
    )


def create_inmemory_runtime(config: AQELYNConfig | None = None) -> Runtime:
    """Build a fully wired in-memory runtime (used by C-001 and unit tests)."""
    from aqelyn.assetconfig.drift import AssetConfigAnalyzer
    from aqelyn.assetconfig.memory import InMemoryBaselineStore, InMemoryDriftSnapshotStore
    from aqelyn.assetconfig.service import register_acg_events
    from aqelyn.governance.service import (
        StoreBackedCompliancePolicyEngine,
        register_compliance_events,
    )
    from aqelyn.iag.service import StoreBackedIAGPolicyEvaluator, register_iag_events
    from aqelyn.risk.engine import RiskIntelligenceEngine
    from aqelyn.risk.memory import InMemoryRiskSnapshotStore, InMemoryRiskStore
    from aqelyn.risk.service import register_risk_events
    from aqelyn.soc.engine import SecurityOperationsEngine
    from aqelyn.soc.memory import InMemorySOCStore
    from aqelyn.soc.service import register_soc_events
    from aqelyn.threat.engine import ThreatFusionEngine
    from aqelyn.threat.registry import InMemoryThreatSourceRegistry
    from aqelyn.threat.service import register_threat_events

    cfg = config or AQELYNConfig(backend="memory")
    registry = EventTypeRegistry()
    register_evidence_events(registry)
    register_finding_events(registry)
    register_policy_events(registry)
    register_workflow_events(registry)
    register_compliance_events(registry)
    register_iag_events(registry)
    register_acg_events(registry)
    register_risk_events(registry)
    register_threat_events(registry)
    register_soc_events(registry)
    bus = InMemoryEventBus(registry=registry)

    sink = BusObjectEventSink(bus)
    object_store = InMemoryObjectStore(
        registry=ObjectTypeRegistry(), mode=cfg.tenant_mode, event_sink=sink
    )
    evidence_store = InMemoryEvidenceStore(mode=cfg.tenant_mode, event_bus=bus)
    finding_store = InMemoryFindingStore(
        mode=cfg.tenant_mode, event_bus=bus, evidence_exists=evidence_store.exists
    )
    knowledge_graph = InMemoryKnowledgeGraph(object_store)
    trust_engine = TrustEngine(registry=InMemorySourceReliabilityRegistry())
    mission_engine = MissionEngine(object_store, knowledge_graph)
    policy_store = InMemoryPolicyStore()
    policy_engine_service = PolicyEngineService(policy_store)
    compliance_snapshot_store = InMemorySnapshotStore()
    compliance_engine = ComplianceEngine(
        object_store,
        StoreBackedCompliancePolicyEngine(policy_store),
        config=_default_governance_config(),
        snapshot_store=compliance_snapshot_store,
        evidence_store=evidence_store,
        finding_store=finding_store,
        mission_engine=mission_engine,
    )
    workflow_policy_adapter = PolicyWorkflowAdapter(policy_engine_service)
    workflow_run_store = InMemoryRunStore(mode=cfg.tenant_mode)
    workflow_action_registry = InMemoryActionRegistry()
    workflow_engine = WorkflowEngine(
        store=workflow_run_store,
        registry=workflow_action_registry,
        evidence_store=evidence_store,
        event_bus=bus,
        policy_authorizer=workflow_policy_adapter,
    )
    iag_certification_store = InMemoryCertificationStore(mode=cfg.tenant_mode)
    iag_engine = IdentityAccessGovernanceEngine(
        object_store,
        knowledge_graph,
        StoreBackedIAGPolicyEvaluator(policy_store),
        iag_certification_store,
        evidence_store,
        finding_store=finding_store,
        workflow_engine=workflow_engine,
        mission_engine=mission_engine,
    )
    acg_baseline_store = InMemoryBaselineStore()
    acg_snapshot_store = InMemoryDriftSnapshotStore()
    acg_engine = AssetConfigAnalyzer(
        object_store,
        [],
        baseline_store=acg_baseline_store,
        snapshot_store=acg_snapshot_store,
        evidence_store=evidence_store,
        finding_store=finding_store,
        workflow_engine=workflow_engine,
        mission_engine=mission_engine,
    )
    risk_store = InMemoryRiskStore()
    risk_snapshot_store = InMemoryRiskSnapshotStore()
    risk_engine = RiskIntelligenceEngine(
        finding_store,
        risk_store,
        risk_snapshot_store,
        mission_engine=mission_engine,
        evidence_store=evidence_store,
        workflow_engine=workflow_engine,
    )
    threat_source_registry = InMemoryThreatSourceRegistry()
    threat_engine = ThreatFusionEngine(
        object_store,
        source_registry=threat_source_registry,
        graph=knowledge_graph,
        evidence_store=evidence_store,
        finding_store=finding_store,
        workflow_engine=workflow_engine,
        mission_engine=mission_engine,
    )
    soc_store = InMemorySOCStore(mode=cfg.tenant_mode)
    soc_engine = SecurityOperationsEngine(
        soc_store,
        evidence_store,
        graph=knowledge_graph,
        mission_engine=mission_engine,
        workflow_engine=workflow_engine,
        object_store=object_store,
    )
    kernel = AQKernel(cfg, event_bus=bus)
    (
        knowledge_graph_service,
        trust_engine_service,
        mission_engine_service,
        policy_engine_service,
        compliance_engine_service,
        workflow_engine_service,
        iag_engine_service,
        acg_engine_service,
        risk_engine_service,
        threat_engine_service,
        soc_engine_service,
    ) = _register_runtime_services(
        kernel,
        object_store=object_store,
        evidence_store=evidence_store,
        finding_store=finding_store,
        knowledge_graph=knowledge_graph,
        trust_engine=trust_engine,
        mission_engine=mission_engine,
        policy_engine_service=policy_engine_service,
        compliance_engine=compliance_engine,
        compliance_snapshot_store=compliance_snapshot_store,
        workflow_run_store=workflow_run_store,
        workflow_action_registry=workflow_action_registry,
        workflow_engine=workflow_engine,
        iag_certification_store=iag_certification_store,
        iag_engine=iag_engine,
        acg_baseline_store=acg_baseline_store,
        acg_snapshot_store=acg_snapshot_store,
        acg_engine=acg_engine,
        risk_store=risk_store,
        risk_snapshot_store=risk_snapshot_store,
        risk_engine=risk_engine,
        threat_source_registry=threat_source_registry,
        threat_engine=threat_engine,
        soc_store=soc_store,
        soc_engine=soc_engine,
    )
    return Runtime(
        kernel=kernel,
        event_bus=bus,
        object_store=object_store,
        evidence_store=evidence_store,
        finding_store=finding_store,
        blob_store=InMemoryBlobStore(),
        knowledge_graph=knowledge_graph,
        knowledge_graph_service=knowledge_graph_service,
        trust_engine=trust_engine,
        trust_engine_service=trust_engine_service,
        mission_engine=mission_engine,
        mission_engine_service=mission_engine_service,
        compliance_snapshot_store=compliance_snapshot_store,
        compliance_engine=compliance_engine,
        compliance_engine_service=compliance_engine_service,
        policy_store=policy_store,
        policy_engine_service=policy_engine_service,
        workflow_policy_adapter=workflow_policy_adapter,
        workflow_run_store=workflow_run_store,
        workflow_action_registry=workflow_action_registry,
        workflow_engine=workflow_engine,
        workflow_engine_service=workflow_engine_service,
        iag_certification_store=iag_certification_store,
        iag_engine=iag_engine,
        iag_engine_service=iag_engine_service,
        acg_baseline_store=acg_baseline_store,
        acg_snapshot_store=acg_snapshot_store,
        acg_engine=acg_engine,
        acg_engine_service=acg_engine_service,
        risk_store=risk_store,
        risk_snapshot_store=risk_snapshot_store,
        risk_engine=risk_engine,
        risk_engine_service=risk_engine_service,
        threat_source_registry=threat_source_registry,
        threat_engine=threat_engine,
        threat_engine_service=threat_engine_service,
        soc_store=soc_store,
        soc_engine=soc_engine,
        soc_engine_service=soc_engine_service,
    )


async def create_runtime(config: AQELYNConfig | None = None) -> Runtime:
    """Build the runtime selected by AQELYN_BACKEND."""
    from aqelyn.assetconfig.drift import AssetConfigAnalyzer
    from aqelyn.assetconfig.postgres import PostgresBaselineStore, PostgresDriftSnapshotStore
    from aqelyn.assetconfig.service import register_acg_events
    from aqelyn.governance.service import (
        StoreBackedCompliancePolicyEngine,
        register_compliance_events,
    )
    from aqelyn.iag.service import StoreBackedIAGPolicyEvaluator, register_iag_events
    from aqelyn.risk.engine import RiskIntelligenceEngine
    from aqelyn.risk.postgres import PostgresRiskSnapshotStore, PostgresRiskStore
    from aqelyn.risk.service import register_risk_events
    from aqelyn.soc.engine import SecurityOperationsEngine
    from aqelyn.soc.postgres import PostgresSOCStore
    from aqelyn.soc.service import register_soc_events
    from aqelyn.threat.engine import ThreatFusionEngine
    from aqelyn.threat.postgres import PostgresThreatSourceRegistry
    from aqelyn.threat.service import register_threat_events

    cfg = config or AQELYNConfig.load()
    if cfg.backend == "memory":
        return create_inmemory_runtime(cfg)
    if cfg.database_url is None:
        raise ConfigError("backend=postgres requires AQELYN_DATABASE_URL")

    registry = EventTypeRegistry()
    register_evidence_events(registry)
    register_finding_events(registry)
    register_policy_events(registry)
    register_workflow_events(registry)
    register_compliance_events(registry)
    register_iag_events(registry)
    register_acg_events(registry)
    register_risk_events(registry)
    register_threat_events(registry)
    register_soc_events(registry)
    bus = InMemoryEventBus(registry=registry)
    sink = BusObjectEventSink(bus)
    object_store = await PostgresObjectStore.connect(
        cfg.database_url,
        registry=ObjectTypeRegistry(),
        mode=cfg.tenant_mode,
        event_sink=sink,
    )
    evidence_store = InMemoryEvidenceStore(mode=cfg.tenant_mode, event_bus=bus)
    finding_store = InMemoryFindingStore(
        mode=cfg.tenant_mode, event_bus=bus, evidence_exists=evidence_store.exists
    )
    knowledge_graph = PostgresKnowledgeGraph(object_store._pool)
    trust_engine = TrustEngine(registry=InMemorySourceReliabilityRegistry())
    mission_engine = MissionEngine(object_store, knowledge_graph)
    policy_store = await PostgresPolicyStore.connect(cfg.database_url)
    policy_engine_service = PolicyEngineService(
        policy_store,
        close_store=policy_store.close,
    )
    compliance_snapshot_store = await PostgresSnapshotStore.connect(cfg.database_url)
    compliance_engine = ComplianceEngine(
        object_store,
        StoreBackedCompliancePolicyEngine(policy_store),
        config=_default_governance_config(),
        snapshot_store=compliance_snapshot_store,
        evidence_store=evidence_store,
        finding_store=finding_store,
        mission_engine=mission_engine,
    )
    workflow_policy_adapter = PolicyWorkflowAdapter(policy_engine_service)
    workflow_run_store = await PostgresRunStore.connect(
        cfg.database_url,
        mode=cfg.tenant_mode,
    )
    workflow_action_registry = InMemoryActionRegistry()
    workflow_engine = WorkflowEngine(
        store=workflow_run_store,
        registry=workflow_action_registry,
        evidence_store=evidence_store,
        event_bus=bus,
        policy_authorizer=workflow_policy_adapter,
    )
    iag_certification_store = await PostgresCertificationStore.connect(
        cfg.database_url,
        mode=cfg.tenant_mode,
    )
    iag_engine = IdentityAccessGovernanceEngine(
        object_store,
        knowledge_graph,
        StoreBackedIAGPolicyEvaluator(policy_store),
        iag_certification_store,
        evidence_store,
        finding_store=finding_store,
        workflow_engine=workflow_engine,
        mission_engine=mission_engine,
    )
    acg_baseline_store = await PostgresBaselineStore.connect(cfg.database_url)
    acg_snapshot_store = await PostgresDriftSnapshotStore.connect(cfg.database_url)
    acg_engine = AssetConfigAnalyzer(
        object_store,
        [],
        baseline_store=acg_baseline_store,
        snapshot_store=acg_snapshot_store,
        evidence_store=evidence_store,
        finding_store=finding_store,
        workflow_engine=workflow_engine,
        mission_engine=mission_engine,
    )
    risk_store = await PostgresRiskStore.connect(cfg.database_url)
    risk_snapshot_store = await PostgresRiskSnapshotStore.connect(cfg.database_url)
    risk_engine = RiskIntelligenceEngine(
        finding_store,
        risk_store,
        risk_snapshot_store,
        mission_engine=mission_engine,
        evidence_store=evidence_store,
        workflow_engine=workflow_engine,
    )
    threat_source_registry = await PostgresThreatSourceRegistry.connect(cfg.database_url)
    threat_engine = ThreatFusionEngine(
        object_store,
        source_registry=threat_source_registry,
        graph=knowledge_graph,
        evidence_store=evidence_store,
        finding_store=finding_store,
        workflow_engine=workflow_engine,
        mission_engine=mission_engine,
    )
    soc_store = await PostgresSOCStore.connect(cfg.database_url, mode=cfg.tenant_mode)
    soc_engine = SecurityOperationsEngine(
        soc_store,
        evidence_store,
        graph=knowledge_graph,
        mission_engine=mission_engine,
        workflow_engine=workflow_engine,
        object_store=object_store,
    )
    kernel = AQKernel(cfg, event_bus=bus)
    (
        knowledge_graph_service,
        trust_engine_service,
        mission_engine_service,
        policy_engine_service,
        compliance_engine_service,
        workflow_engine_service,
        iag_engine_service,
        acg_engine_service,
        risk_engine_service,
        threat_engine_service,
        soc_engine_service,
    ) = _register_runtime_services(
        kernel,
        object_store=object_store,
        evidence_store=evidence_store,
        finding_store=finding_store,
        knowledge_graph=knowledge_graph,
        trust_engine=trust_engine,
        mission_engine=mission_engine,
        policy_engine_service=policy_engine_service,
        compliance_engine=compliance_engine,
        compliance_snapshot_store=compliance_snapshot_store,
        workflow_run_store=workflow_run_store,
        workflow_action_registry=workflow_action_registry,
        workflow_engine=workflow_engine,
        iag_certification_store=iag_certification_store,
        iag_engine=iag_engine,
        acg_baseline_store=acg_baseline_store,
        acg_snapshot_store=acg_snapshot_store,
        acg_engine=acg_engine,
        risk_store=risk_store,
        risk_snapshot_store=risk_snapshot_store,
        risk_engine=risk_engine,
        threat_source_registry=threat_source_registry,
        threat_engine=threat_engine,
        soc_store=soc_store,
        soc_engine=soc_engine,
        close_object_store=object_store.close,
        close_compliance_snapshot_store=compliance_snapshot_store.close,
        close_workflow_run_store=workflow_run_store.close,
        close_iag_certification_store=iag_certification_store.close,
        close_acg_baseline_store=acg_baseline_store.close,
        close_acg_snapshot_store=acg_snapshot_store.close,
        close_risk_store=risk_store.close,
        close_risk_snapshot_store=risk_snapshot_store.close,
        close_threat_source_registry=threat_source_registry.close,
        close_soc_store=soc_store.close,
    )
    return Runtime(
        kernel=kernel,
        event_bus=bus,
        object_store=object_store,
        evidence_store=evidence_store,
        finding_store=finding_store,
        blob_store=InMemoryBlobStore(),
        knowledge_graph=knowledge_graph,
        knowledge_graph_service=knowledge_graph_service,
        trust_engine=trust_engine,
        trust_engine_service=trust_engine_service,
        mission_engine=mission_engine,
        mission_engine_service=mission_engine_service,
        compliance_snapshot_store=compliance_snapshot_store,
        compliance_engine=compliance_engine,
        compliance_engine_service=compliance_engine_service,
        policy_store=policy_store,
        policy_engine_service=policy_engine_service,
        workflow_policy_adapter=workflow_policy_adapter,
        workflow_run_store=workflow_run_store,
        workflow_action_registry=workflow_action_registry,
        workflow_engine=workflow_engine,
        workflow_engine_service=workflow_engine_service,
        iag_certification_store=iag_certification_store,
        iag_engine=iag_engine,
        iag_engine_service=iag_engine_service,
        acg_baseline_store=acg_baseline_store,
        acg_snapshot_store=acg_snapshot_store,
        acg_engine=acg_engine,
        acg_engine_service=acg_engine_service,
        risk_store=risk_store,
        risk_snapshot_store=risk_snapshot_store,
        risk_engine=risk_engine,
        risk_engine_service=risk_engine_service,
        threat_source_registry=threat_source_registry,
        threat_engine=threat_engine,
        threat_engine_service=threat_engine_service,
        soc_store=soc_store,
        soc_engine=soc_engine,
        soc_engine_service=soc_engine_service,
    )
