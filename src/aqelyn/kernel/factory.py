"""Kernel construction + dependency injection (EA-0001 §7, D3)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import ConfigError, StoreUnavailable
from aqelyn.events import EventTypeRegistry, InMemoryEventBus
from aqelyn.evidence import (
    BlobStore,
    InMemoryBlobStore,
    InMemoryEvidenceStore,
    register_evidence_events,
)
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
    from aqelyn.assetconfig.models import ACGConfig
    from aqelyn.assetconfig.service import AssetConfigGovernanceService
    from aqelyn.assetconfig.store import BaselineStore, DriftSnapshotStore
    from aqelyn.cspm import (
        CloudNormalizationConfig,
        CloudNormalizationStore,
        CloudPostureEngine,
        CloudPostureService,
    )
    from aqelyn.decision.recommend import DecisionIntelligenceEngine
    from aqelyn.decision.service import DecisionIntelligenceService
    from aqelyn.decision.store import ModelVersionStore, RecommendationStore
    from aqelyn.detection.engine import ThreatDetectionEngine
    from aqelyn.detection.service import ThreatDetectionService
    from aqelyn.detection.store import ProfileStore, RuleStore
    from aqelyn.dspm import (
        DataStoreKnownSurfaceSource,
        DSPMConfig,
        DSPMEngine,
        DSPMService,
        DSPMStore,
    )
    from aqelyn.executive import (
        ExecutiveIntelligenceService,
        ExecutiveKPIEngine,
        ExecutiveReportEngine,
        KPIDefinitionStore,
        ReportStore,
    )
    from aqelyn.exposure import ExposureManagementService, ExposureStore, KnownDataExposureEngine
    from aqelyn.forecast.engine import ForecastingEngine
    from aqelyn.forecast.service import ForecastingService
    from aqelyn.forecast.store import ForecastStore, PredictionModelStore
    from aqelyn.forensics.service import DigitalForensicsService
    from aqelyn.forensics.store import ArtifactStore
    from aqelyn.governance.service import ComplianceGovernanceService
    from aqelyn.iag.service import IdentityAccessGovernanceService
    from aqelyn.idthreat.engine import IdentityThreatEngine
    from aqelyn.idthreat.service import IdentityThreatService
    from aqelyn.idthreat.store import IdentityDetectionStore
    from aqelyn.inventory import (
        AssetStore,
        InventoryIntelligenceEngine,
        InventoryIntelligenceService,
    )
    from aqelyn.lake.retention import RetentionEngine
    from aqelyn.lake.service import DataLakeService
    from aqelyn.lake.store import DatasetCatalogStore, TelemetryRecordStore
    from aqelyn.response.campaign import ResponseOrchestrationEngine
    from aqelyn.response.service import ResponseOrchestrationService
    from aqelyn.response.store import CampaignStore, TriggerStore
    from aqelyn.risk.engine import RiskIntelligenceEngine
    from aqelyn.risk.service import RiskIntelligenceService
    from aqelyn.risk.store import RiskSnapshotStore, RiskStore
    from aqelyn.soc.engine import SecurityOperationsEngine
    from aqelyn.soc.service import SecurityOperationsService
    from aqelyn.soc.store import SOCStore
    from aqelyn.sspm import (
        SaaSConfig,
        SaaSNormalizationStore,
        SaaSPostureEngine,
        SaaSPostureService,
    )
    from aqelyn.supplychain import SBOMStore, SupplyChainEngine, SupplyChainService
    from aqelyn.threat.engine import ThreatFusionEngine
    from aqelyn.threat.registry import ThreatSourceRegistry
    from aqelyn.threat.service import ThreatFusionService
    from aqelyn.vuln import (
        VulnerabilityIntelligenceEngine,
        VulnerabilityIntelligenceService,
        VulnerabilityStore,
    )


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
    detection_rule_store: RuleStore
    detection_profile_store: ProfileStore
    detection_engine: ThreatDetectionEngine
    detection_engine_service: ThreatDetectionService
    idthreat_store: IdentityDetectionStore
    idthreat_engine: IdentityThreatEngine
    idthreat_engine_service: IdentityThreatService
    soc_store: SOCStore
    soc_engine: SecurityOperationsEngine
    soc_engine_service: SecurityOperationsService
    decision_recommendation_store: RecommendationStore
    decision_model_store: ModelVersionStore
    decision_engine: DecisionIntelligenceEngine
    decision_engine_service: DecisionIntelligenceService
    response_campaign_store: CampaignStore
    response_trigger_store: TriggerStore
    response_engine: ResponseOrchestrationEngine
    response_engine_service: ResponseOrchestrationService
    forensics_artifact_store: ArtifactStore
    forensics_engine_service: DigitalForensicsService
    lake_catalog: DatasetCatalogStore
    lake_record_store: TelemetryRecordStore
    lake_retention_engine: RetentionEngine
    lake_service: DataLakeService
    forecast_store: ForecastStore
    forecast_model_store: PredictionModelStore
    forecast_engine: ForecastingEngine
    forecast_engine_service: ForecastingService
    executive_definition_store: KPIDefinitionStore
    executive_report_store: ReportStore
    executive_kpi_engine: ExecutiveKPIEngine
    executive_report_engine: ExecutiveReportEngine
    executive_engine_service: ExecutiveIntelligenceService
    inventory_store: AssetStore
    inventory_engine: InventoryIntelligenceEngine
    inventory_engine_service: InventoryIntelligenceService
    dspm_store: DSPMStore
    dspm_engine: DSPMEngine
    dspm_engine_service: DSPMService
    exposure_store: ExposureStore
    exposure_engine: KnownDataExposureEngine
    exposure_engine_service: ExposureManagementService
    vuln_store: VulnerabilityStore
    vuln_engine: VulnerabilityIntelligenceEngine
    vuln_engine_service: VulnerabilityIntelligenceService
    cloud_normalization_store: CloudNormalizationStore
    cloud_posture_engine: CloudPostureEngine
    cloud_posture_service: CloudPostureService
    saas_normalization_store: SaaSNormalizationStore
    saas_posture_engine: SaaSPostureEngine
    saas_posture_service: SaaSPostureService
    supplychain_store: SBOMStore
    supplychain_engine: SupplyChainEngine
    supplychain_engine_service: SupplyChainService


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


class _FailClosedLakeReferenceChecker:
    async def is_referenced(self, _record: object) -> bool:
        raise StoreUnavailable("lake reference checker unavailable")


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


def _runtime_acg_config(config: AQELYNConfig) -> ACGConfig:
    from aqelyn.assetconfig.models import ACGConfig

    return ACGConfig(
        batch_size=config.acg_batch_size,
        assessable_object_types=config.acg_assessable_object_types,
        classification_rules=config.acg_classification_rules,
        unknown_is_fail=config.acg_unknown_is_fail,
    )


def _runtime_cloud_config(config: AQELYNConfig) -> CloudNormalizationConfig:
    from aqelyn.cspm import CloudNormalizationConfig

    return CloudNormalizationConfig.model_validate(
        {
            "type_map": config.cspm_type_map,
            "fact_paths": config.cspm_fact_paths,
            "baseline_ids": config.cspm_baseline_ids,
        },
        context={
            "known_object_types": set(config.acg_assessable_object_types),
            "known_baseline_ids": set(config.cspm_baseline_ids),
        },
    )


def _runtime_saas_config(config: AQELYNConfig) -> SaaSConfig:
    from aqelyn.sspm import SaaSConfig

    return SaaSConfig.model_validate(
        {
            "type_map": config.sspm_type_map,
            "baseline_ids": config.sspm_baseline_ids,
            "sensitive_scopes": config.sspm_sensitive_scopes,
            "batch_size": config.sspm_batch_size,
            "integration_max_nodes": config.sspm_integration_max_nodes,
        },
        context={
            "known_object_types": set(config.acg_assessable_object_types),
            "known_baseline_ids": set(config.sspm_baseline_ids),
        },
    )


def _runtime_dspm_config(config: AQELYNConfig) -> DSPMConfig:
    from aqelyn.dspm import DSPMConfig

    return DSPMConfig.model_validate(
        {
            "classifier_rules": config.dspm_classifier_rules,
            "sensitivity_factors": config.dspm_sensitivity_factors,
            "batch_size": config.dspm_batch_size,
            "max_work": config.dspm_max_work,
            "max_fields_per_store": config.dspm_max_fields_per_store,
            "max_signals_per_field": config.dspm_max_signals_per_field,
        }
    )


def _register_runtime_services(
    kernel: AQKernel,
    *,
    object_store: ObjectStore,
    evidence_store: InMemoryEvidenceStore,
    blob_store: BlobStore,
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
    detection_rule_store: RuleStore,
    detection_profile_store: ProfileStore,
    detection_engine: ThreatDetectionEngine,
    idthreat_store: IdentityDetectionStore,
    idthreat_engine: IdentityThreatEngine,
    soc_store: SOCStore,
    soc_engine: SecurityOperationsEngine,
    decision_recommendation_store: RecommendationStore,
    decision_model_store: ModelVersionStore,
    decision_engine: DecisionIntelligenceEngine,
    response_campaign_store: CampaignStore,
    response_trigger_store: TriggerStore,
    response_engine: ResponseOrchestrationEngine,
    forensics_artifact_store: ArtifactStore,
    lake_catalog: DatasetCatalogStore,
    lake_record_store: TelemetryRecordStore,
    lake_retention_engine: RetentionEngine,
    forecast_store: ForecastStore,
    forecast_model_store: PredictionModelStore,
    forecast_engine: ForecastingEngine,
    executive_definition_store: KPIDefinitionStore,
    executive_report_store: ReportStore,
    executive_kpi_engine: ExecutiveKPIEngine,
    executive_report_engine: ExecutiveReportEngine,
    inventory_store: AssetStore,
    inventory_engine: InventoryIntelligenceEngine,
    dspm_store: DSPMStore,
    dspm_engine: DSPMEngine,
    dspm_known_surface_source: DataStoreKnownSurfaceSource,
    exposure_store: ExposureStore,
    exposure_engine: KnownDataExposureEngine,
    vuln_store: VulnerabilityStore,
    vuln_engine: VulnerabilityIntelligenceEngine,
    cloud_normalization_store: CloudNormalizationStore,
    cloud_posture_engine: CloudPostureEngine,
    saas_normalization_store: SaaSNormalizationStore,
    saas_posture_engine: SaaSPostureEngine,
    supplychain_store: SBOMStore,
    supplychain_engine: SupplyChainEngine,
    close_object_store: Callable[[], Awaitable[None]] | None = None,
    close_compliance_snapshot_store: Callable[[], Awaitable[None]] | None = None,
    close_workflow_run_store: Callable[[], Awaitable[None]] | None = None,
    close_iag_certification_store: Callable[[], Awaitable[None]] | None = None,
    close_acg_baseline_store: Callable[[], Awaitable[None]] | None = None,
    close_acg_snapshot_store: Callable[[], Awaitable[None]] | None = None,
    close_risk_store: Callable[[], Awaitable[None]] | None = None,
    close_risk_snapshot_store: Callable[[], Awaitable[None]] | None = None,
    close_threat_source_registry: Callable[[], Awaitable[None]] | None = None,
    close_detection_rule_store: Callable[[], Awaitable[None]] | None = None,
    close_detection_profile_store: Callable[[], Awaitable[None]] | None = None,
    close_idthreat_store: Callable[[], Awaitable[None]] | None = None,
    close_soc_store: Callable[[], Awaitable[None]] | None = None,
    close_decision_recommendation_store: Callable[[], Awaitable[None]] | None = None,
    close_decision_model_store: Callable[[], Awaitable[None]] | None = None,
    close_response_campaign_store: Callable[[], Awaitable[None]] | None = None,
    close_response_trigger_store: Callable[[], Awaitable[None]] | None = None,
    close_forensics_artifact_store: Callable[[], Awaitable[None]] | None = None,
    close_lake_catalog: Callable[[], Awaitable[None]] | None = None,
    close_lake_record_store: Callable[[], Awaitable[None]] | None = None,
    close_forecast_store: Callable[[], Awaitable[None]] | None = None,
    close_forecast_model_store: Callable[[], Awaitable[None]] | None = None,
    close_executive_definition_store: Callable[[], Awaitable[None]] | None = None,
    close_executive_report_store: Callable[[], Awaitable[None]] | None = None,
    close_inventory_store: Callable[[], Awaitable[None]] | None = None,
    close_exposure_store: Callable[[], Awaitable[None]] | None = None,
    close_dspm_store: Callable[[], Awaitable[None]] | None = None,
    close_vuln_store: Callable[[], Awaitable[None]] | None = None,
    close_cloud_normalization_store: Callable[[], Awaitable[None]] | None = None,
    close_saas_normalization_store: Callable[[], Awaitable[None]] | None = None,
    close_supplychain_store: Callable[[], Awaitable[None]] | None = None,
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
    ThreatDetectionService,
    IdentityThreatService,
    SecurityOperationsService,
    DecisionIntelligenceService,
    ResponseOrchestrationService,
    DigitalForensicsService,
    DataLakeService,
    ForecastingService,
    ExecutiveIntelligenceService,
    InventoryIntelligenceService,
    ExposureManagementService,
    DSPMService,
    VulnerabilityIntelligenceService,
    CloudPostureService,
    SaaSPostureService,
    SupplyChainService,
]:
    from aqelyn.assetconfig.service import AssetConfigGovernanceService
    from aqelyn.cspm.service import CloudPostureService
    from aqelyn.decision.service import DecisionIntelligenceService
    from aqelyn.detection.service import ThreatDetectionService
    from aqelyn.dspm.service import DSPMService
    from aqelyn.executive.service import ExecutiveIntelligenceService
    from aqelyn.exposure.service import ExposureManagementService
    from aqelyn.forecast.service import ForecastingService
    from aqelyn.forensics.service import DigitalForensicsService
    from aqelyn.governance.service import ComplianceGovernanceService
    from aqelyn.iag.service import IdentityAccessGovernanceService
    from aqelyn.idthreat.service import IdentityThreatService
    from aqelyn.inventory.service import InventoryIntelligenceService
    from aqelyn.lake.service import DataLakeService
    from aqelyn.response.service import ResponseOrchestrationService
    from aqelyn.risk.service import RiskIntelligenceService
    from aqelyn.soc.service import SecurityOperationsService
    from aqelyn.sspm.service import SaaSPostureService
    from aqelyn.supplychain.service import SupplyChainService
    from aqelyn.threat.service import ThreatFusionService
    from aqelyn.vuln.service import VulnerabilityIntelligenceService

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
    lake_service = DataLakeService(
        catalog=lake_catalog,
        record_store=lake_record_store,
        retention_engine=lake_retention_engine,
        blob_store=blob_store,
        audit_store=evidence_store,
        policy_authorizer=policy_engine_service,
        workflow_engine=workflow_engine,
        close_catalog=close_lake_catalog,
        close_record_store=close_lake_record_store,
    )
    kernel.register(lake_service)
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
    detection_service = ThreatDetectionService(
        detection_engine,
        rule_store=detection_rule_store,
        profile_store=detection_profile_store,
        threat_engine=threat_engine,
        close_rule_store=close_detection_rule_store,
        close_profile_store=close_detection_profile_store,
    )
    kernel.register(detection_service)
    idthreat_service = IdentityThreatService(
        idthreat_engine,
        store=idthreat_store,
        close_store=close_idthreat_store,
    )
    kernel.register(idthreat_service)
    soc_service = SecurityOperationsService(
        soc_engine,
        store=soc_store,
        close_store=close_soc_store,
    )
    kernel.register(soc_service)
    decision_service = DecisionIntelligenceService(
        decision_engine,
        recommendation_store=decision_recommendation_store,
        model_store=decision_model_store,
        evidence_store=evidence_store,
        close_recommendation_store=close_decision_recommendation_store,
        close_model_store=close_decision_model_store,
    )
    kernel.register(decision_service)
    response_service = ResponseOrchestrationService(
        response_engine,
        campaign_store=response_campaign_store,
        trigger_store=response_trigger_store,
        evidence_store=evidence_store,
        finding_store=finding_store,
        workflow_engine=workflow_engine,
        policy_authorizer=policy_engine_service,
        incident_reader=soc_store,
        close_campaign_store=close_response_campaign_store,
        close_trigger_store=close_response_trigger_store,
    )
    kernel.register(response_service)
    forensics_service = DigitalForensicsService(
        artifact_store=forensics_artifact_store,
        evidence_store=evidence_store,
        blob_store=blob_store,
        object_store=object_store,
        graph=knowledge_graph,
        finding_store=finding_store,
        close_artifact_store=close_forensics_artifact_store,
    )
    kernel.register(forensics_service)
    forecast_service = ForecastingService(
        forecast_engine,
        forecast_store=forecast_store,
        model_store=forecast_model_store,
        evidence_store=evidence_store,
        lake_service=lake_service,
        risk_engine=risk_engine,
        close_forecast_store=close_forecast_store,
        close_model_store=close_forecast_model_store,
    )
    kernel.register(forecast_service)
    executive_service = ExecutiveIntelligenceService(
        executive_report_engine,
        kpi_engine=executive_kpi_engine,
        definition_store=executive_definition_store,
        report_store=executive_report_store,
        evidence_store=evidence_store,
        owner_sources=executive_kpi_engine.sources,
        section_sources=executive_report_engine.section_sources,
        close_definition_store=close_executive_definition_store,
        close_report_store=close_executive_report_store,
    )
    kernel.register(executive_service)
    inventory_service = InventoryIntelligenceService(
        inventory_engine,
        store=inventory_store,
        object_store=object_store,
        trust_engine=trust_engine,
        mission_engine=mission_engine,
        evidence_store=evidence_store,
        close_store=close_inventory_store,
    )
    kernel.register(inventory_service)
    exposure_service = ExposureManagementService(
        exposure_engine,
        store=exposure_store,
        risk_engine=risk_engine,
        close_store=close_exposure_store,
    )
    kernel.register(exposure_service)
    dspm_service = DSPMService(
        dspm_engine,
        store=dspm_store,
        known_surface_source=dspm_known_surface_source,
        owner_services={
            "inventory_engine": inventory_service,
            "exposure_engine": exposure_service,
            "iag_engine": iag_service,
            "compliance_engine": compliance_service,
            "trust_engine": trust_service,
            "workflow_engine": workflow_service,
        },
        close_store=close_dspm_store,
    )
    kernel.register(dspm_service)
    vuln_service = VulnerabilityIntelligenceService(
        vuln_engine,
        store=vuln_store,
        close_store=close_vuln_store,
    )
    kernel.register(vuln_service)
    cloud_service = CloudPostureService(
        cloud_posture_engine,
        store=cloud_normalization_store,
        owner_services={
            "inventory_engine": inventory_service,
            "acg_engine": acg_service,
            "compliance_engine": compliance_service,
            "exposure_engine": exposure_service,
            "iag_engine": iag_service,
            "risk_engine": risk_service,
            "trust_engine": trust_service,
        },
        close_store=close_cloud_normalization_store,
    )
    kernel.register(cloud_service)
    saas_service = SaaSPostureService(
        saas_posture_engine,
        store=saas_normalization_store,
        owner_services={
            "inventory_engine": inventory_service,
            "acg_engine": acg_service,
            "compliance_engine": compliance_service,
            "iag_engine": iag_service,
            "exposure_engine": exposure_service,
            "risk_engine": risk_service,
            "workflow_engine": workflow_service,
        },
        close_store=close_saas_normalization_store,
    )
    kernel.register(saas_service)
    supplychain_service = SupplyChainService(
        supplychain_engine,
        store=supplychain_store,
        owner_services={
            "knowledge_graph": graph_service,
            "inventory_engine": inventory_service,
            "vuln_engine": vuln_service,
            "compliance_engine": compliance_service,
            "risk_engine": risk_service,
            "trust_engine": trust_service,
            "workflow_engine": workflow_service,
        },
        close_store=close_supplychain_store,
    )
    kernel.register(supplychain_service)
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
        detection_service,
        idthreat_service,
        soc_service,
        decision_service,
        response_service,
        forensics_service,
        lake_service,
        forecast_service,
        executive_service,
        inventory_service,
        exposure_service,
        dspm_service,
        vuln_service,
        cloud_service,
        saas_service,
        supplychain_service,
    )


def create_inmemory_runtime(config: AQELYNConfig | None = None) -> Runtime:
    """Build a fully wired in-memory runtime (used by C-001 and unit tests)."""
    from aqelyn.assetconfig.drift import AssetConfigAnalyzer
    from aqelyn.assetconfig.memory import InMemoryBaselineStore, InMemoryDriftSnapshotStore
    from aqelyn.assetconfig.service import register_acg_events
    from aqelyn.cspm import (
        AssetConfigCloudBaselineRouter,
        CloudOwnerRouter,
        CloudPostureEngine,
        InMemoryCloudNormalizationStore,
        InventoryCloudOwnerRouter,
        SharedObjectCloudOwnerRouter,
        register_cloud_events,
    )
    from aqelyn.decision import (
        DecisionIntelligenceEngine,
        EmptyDecisionClaimSource,
        InMemoryModelVersionStore,
        InMemoryRecommendationStore,
        register_decision_events,
    )
    from aqelyn.detection.engine import ThreatDetectionEngine
    from aqelyn.detection.memory import InMemoryProfileStore, InMemoryRuleStore
    from aqelyn.detection.service import register_detection_events
    from aqelyn.dspm import (
        DataStoreKnownSurfaceSource,
        DSPMEngine,
        InMemoryDSPMStore,
        register_dspm_events,
    )
    from aqelyn.executive import (
        EmptyExecutiveValueSource,
        EmptyMaterialExceptionSource,
        ExecutiveKPIEngine,
        ExecutiveReportEngine,
        InMemoryKPIDefinitionStore,
        InMemoryReportStore,
        register_executive_events,
    )
    from aqelyn.exposure import (
        InMemoryExposureStore,
        KnownDataExposureEngine,
        register_exposure_events,
    )
    from aqelyn.forecast import (
        EmptyActualValueSource,
        EmptyMetricHistorySource,
        ForecastingEngine,
        InMemoryForecastStore,
        InMemoryPredictionModelStore,
        register_forecast_events,
    )
    from aqelyn.forensics.memory import InMemoryArtifactStore
    from aqelyn.forensics.service import register_forensics_events
    from aqelyn.governance.service import (
        StoreBackedCompliancePolicyEngine,
        register_compliance_events,
    )
    from aqelyn.iag.service import StoreBackedIAGPolicyEvaluator, register_iag_events
    from aqelyn.idthreat import (
        IdentityThreatEngine,
        IdThreatConfig,
        InMemoryIdentityDetectionStore,
        register_idthreat_events,
    )
    from aqelyn.inventory import (
        InMemoryAssetStore,
        InventoryIntelligenceEngine,
        InventoryKnownSurfaceSource,
        InventoryVulnerabilityCoverageProvider,
        register_inventory_events,
    )
    from aqelyn.lake.memory import InMemoryDatasetCatalog, InMemoryTelemetryRecordStore
    from aqelyn.lake.retention import ReferenceCheckers, RetentionEngine
    from aqelyn.lake.service import register_lake_events
    from aqelyn.response import (
        InMemoryCampaignStore,
        InMemoryTriggerStore,
        ResponseOrchestrationEngine,
        register_response_events,
    )
    from aqelyn.risk.engine import RiskIntelligenceEngine
    from aqelyn.risk.memory import InMemoryRiskSnapshotStore, InMemoryRiskStore
    from aqelyn.risk.service import register_risk_events
    from aqelyn.soc.engine import SecurityOperationsEngine
    from aqelyn.soc.memory import InMemorySOCStore
    from aqelyn.soc.service import register_soc_events
    from aqelyn.sspm import (
        AssetConfigSaaSBaselineRouter,
        InMemorySaaSNormalizationStore,
        InventorySaaSOwnerRouter,
        SaaSIntegrationKnownSurfaceSource,
        SaaSOwnerRouter,
        SaaSPostureEngine,
        SharedObjectSaaSOwnerRouter,
        register_saas_events,
    )
    from aqelyn.supplychain import (
        InMemorySBOMStore,
        SupplyChainConfig,
        SupplyChainEngine,
        register_supplychain_events,
    )
    from aqelyn.threat.engine import ThreatFusionEngine
    from aqelyn.threat.registry import InMemoryThreatSourceRegistry
    from aqelyn.threat.service import register_threat_events
    from aqelyn.vuln import (
        DriftSnapshotBlockingProvider,
        ExposureStoreReachabilityProvider,
        InMemoryVulnerabilityStore,
        ThreatSignalFactorProvider,
        VulnerabilityIntelligenceEngine,
        register_vuln_events,
    )

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
    register_detection_events(registry)
    register_idthreat_events(registry)
    register_soc_events(registry)
    register_response_events(registry)
    register_forensics_events(registry)
    register_lake_events(registry)
    register_decision_events(registry)
    register_forecast_events(registry)
    register_executive_events(registry)
    register_inventory_events(registry)
    register_dspm_events(registry)
    register_exposure_events(registry)
    register_vuln_events(registry)
    register_cloud_events(registry)
    register_saas_events(registry)
    register_supplychain_events(registry)
    bus = InMemoryEventBus(registry=registry)

    sink = BusObjectEventSink(bus)
    object_store = InMemoryObjectStore(
        registry=ObjectTypeRegistry(), mode=cfg.tenant_mode, event_sink=sink
    )
    evidence_store = InMemoryEvidenceStore(mode=cfg.tenant_mode, event_bus=bus)
    blob_store = InMemoryBlobStore()
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
        config=_runtime_acg_config(cfg),
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
    detection_rule_store = InMemoryRuleStore()
    detection_profile_store = InMemoryProfileStore()
    detection_engine = ThreatDetectionEngine(
        rule_store=detection_rule_store,
        profile_store=detection_profile_store,
        trust_engine=trust_engine,
        mission_engine=mission_engine,
        evidence_store=evidence_store,
        finding_store=finding_store,
    )
    idthreat_store = InMemoryIdentityDetectionStore(
        config=IdThreatConfig(
            min_corroboration=2,
            min_confidence=0.75,
            platform_default=0.5,
        ),
        mode=cfg.tenant_mode,
    )
    idthreat_engine = IdentityThreatEngine(
        idthreat_store,
        evidence_store=evidence_store,
        trust_engine=trust_engine,
        profile_store=detection_profile_store,
        entitlement_analyzer=iag_engine,
        config=idthreat_store.config,
        finding_store=finding_store,
        evidence_recorder=evidence_store,
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
    decision_recommendation_store = InMemoryRecommendationStore(mode=cfg.tenant_mode)
    decision_model_store = InMemoryModelVersionStore(mode=cfg.tenant_mode)
    decision_engine = DecisionIntelligenceEngine(
        decision_recommendation_store,
        decision_model_store,
        claim_source=EmptyDecisionClaimSource(),
        evidence_store=evidence_store,
        trust_engine=trust_engine,
        workflow_engine=workflow_engine,
    )
    response_campaign_store = InMemoryCampaignStore(mode=cfg.tenant_mode)
    response_trigger_store = InMemoryTriggerStore(mode=cfg.tenant_mode)
    response_engine = ResponseOrchestrationEngine(
        campaign_store=response_campaign_store,
        workflow=workflow_engine,
        run_store=workflow_run_store,
        trigger_store=response_trigger_store,
        policy_authorizer=policy_engine_service,
        evidence_store=evidence_store,
        finding_store=finding_store,
        incident_reader=soc_store,
    )
    forensics_artifact_store = InMemoryArtifactStore()
    lake_catalog = InMemoryDatasetCatalog()
    lake_record_store = InMemoryTelemetryRecordStore(mode=cfg.tenant_mode)
    lake_retention_engine = RetentionEngine(
        store=lake_record_store,
        blob_store=blob_store,
        evidence_store=evidence_store,
        reference_checkers=ReferenceCheckers(
            evidence=_FailClosedLakeReferenceChecker(),
            finding=_FailClosedLakeReferenceChecker(),
            case=_FailClosedLakeReferenceChecker(),
        ),
        workflow_engine=workflow_engine,
    )
    forecast_store = InMemoryForecastStore(mode=cfg.tenant_mode)
    forecast_model_store = InMemoryPredictionModelStore(mode=cfg.tenant_mode)
    forecast_engine = ForecastingEngine(
        forecast_store,
        forecast_model_store,
        history_source=EmptyMetricHistorySource(),
        evidence_store=evidence_store,
        actual_source=EmptyActualValueSource(),
        evidence_recorder=evidence_store,
        trust_engine=trust_engine,
    )
    acg_engine.trend_provider = forecast_engine
    executive_definition_store = InMemoryKPIDefinitionStore()
    executive_report_store = InMemoryReportStore(mode=cfg.tenant_mode)
    executive_kpi_sources = {
        source_engine: EmptyExecutiveValueSource(source_engine)
        for source_engine in ("compliance", "risk", "forecast", "mission")
    }
    executive_kpi_engine = ExecutiveKPIEngine(
        executive_definition_store,
        executive_kpi_sources,
    )
    executive_report_engine = ExecutiveReportEngine(
        report_store=executive_report_store,
        exception_source=EmptyMaterialExceptionSource(),
        kpi_engine=executive_kpi_engine,
        evidence_store=evidence_store,
    )
    inventory_store = InMemoryAssetStore(mode=cfg.tenant_mode)
    inventory_engine = InventoryIntelligenceEngine(
        inventory_store,
        classifier=acg_engine,
        relationship_store=object_store,
        graph=knowledge_graph,
    )
    dspm_store = InMemoryDSPMStore(mode=cfg.tenant_mode)
    dspm_known_surface_source = DataStoreKnownSurfaceSource(
        InventoryKnownSurfaceSource(inventory_engine),
        dspm_store,
    )
    saas_normalization_store = InMemorySaaSNormalizationStore(mode=cfg.tenant_mode)
    saas_actor = ActorRef(actor_type="system", actor_id="sspm_engine")
    saas_inventory_router = InventorySaaSOwnerRouter(
        inventory_engine,
        evidence_store=evidence_store,
        source_registry=trust_engine.registry,
        actor=saas_actor,
    )
    saas_owner_routers: list[SaaSOwnerRouter] = [
        saas_inventory_router,
        SharedObjectSaaSOwnerRouter("assetconfig", object_store),
        SharedObjectSaaSOwnerRouter("compliance", object_store),
        SharedObjectSaaSOwnerRouter("iag", object_store),
    ]
    saas_posture_engine = SaaSPostureEngine(
        saas_normalization_store,
        object_store=object_store,
        evidence_store=evidence_store,
        source_registry=trust_engine.registry,
        config=_runtime_saas_config(cfg),
        owner_routers=saas_owner_routers,
        integration_graph=knowledge_graph,
        trust_engine=trust_engine,
        baseline_router=AssetConfigSaaSBaselineRouter(acg_engine, acg_baseline_store),
        workflow_engine=workflow_engine,
        absence_router=saas_inventory_router,
        actor=saas_actor,
    )
    exposure_store = InMemoryExposureStore(mode=cfg.tenant_mode)
    exposure_engine = KnownDataExposureEngine(
        exposure_store,
        SaaSIntegrationKnownSurfaceSource(
            dspm_known_surface_source,
            saas_normalization_store,
        ),
        graph=knowledge_graph,
        identity_provider=iag_engine,
        trend_provider=forecast_engine,
        evidence_lookup=evidence_store,
        trust_provider=trust_engine,
        mission_provider=mission_engine,
        finding_store=finding_store,
    )
    dspm_engine = DSPMEngine(
        dspm_store,
        object_store=object_store,
        inventory=inventory_engine,
        evidence_store=evidence_store,
        trust=trust_engine,
        config=_runtime_dspm_config(cfg),
        exposure_owner=exposure_engine,
        iag_owner=iag_engine,
        compliance_owner=compliance_engine,
        finding_store=finding_store,
        workflow_engine=workflow_engine,
    )
    vuln_store = InMemoryVulnerabilityStore(mode=cfg.tenant_mode)
    vuln_engine = VulnerabilityIntelligenceEngine(
        vuln_store,
        threat_provider=ThreatSignalFactorProvider(threat_engine),
        exposure_provider=ExposureStoreReachabilityProvider(exposure_store),
        mission_provider=mission_engine,
        baseline_provider=DriftSnapshotBlockingProvider(acg_snapshot_store),
        coverage_provider=InventoryVulnerabilityCoverageProvider(inventory_engine, vuln_store),
        trend_provider=forecast_engine,
        finding_store=finding_store,
    )
    supplychain_store = InMemorySBOMStore(mode=cfg.tenant_mode)
    supplychain_engine = SupplyChainEngine(
        supplychain_store,
        inventory=inventory_engine,
        source_registry=trust_engine.registry,
        object_store=object_store,
        graph=knowledge_graph,
        evidence_store=evidence_store,
        vulnerability_store=vuln_store,
        vulnerability_owner=vuln_engine,
        license_policy_owner=compliance_engine.policy_engine,
        finding_store=finding_store,
        risk_owner=risk_engine,
        workflow_engine=workflow_engine,
        config=SupplyChainConfig(
            license_policy_id=cfg.supplychain_license_policy_id,
            sensitive_scopes=cfg.supplychain_sensitive_scopes,
            max_depth=cfg.supplychain_max_depth,
            batch_size=cfg.supplychain_batch_size,
        ),
    )
    cloud_normalization_store = InMemoryCloudNormalizationStore(mode=cfg.tenant_mode)
    cloud_owner_routers: list[CloudOwnerRouter] = [
        InventoryCloudOwnerRouter(inventory_engine),
        SharedObjectCloudOwnerRouter("assetconfig", object_store),
        SharedObjectCloudOwnerRouter("compliance", object_store),
        SharedObjectCloudOwnerRouter("exposure", object_store),
        SharedObjectCloudOwnerRouter("iag", object_store),
        SharedObjectCloudOwnerRouter("risk", object_store),
    ]
    cloud_posture_engine = CloudPostureEngine(
        cloud_normalization_store,
        object_store=object_store,
        evidence_store=evidence_store,
        source_registry=trust_engine.registry,
        config=_runtime_cloud_config(cfg),
        owner_routers=cloud_owner_routers,
        baseline_router=AssetConfigCloudBaselineRouter(acg_engine, acg_baseline_store),
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
        detection_engine_service,
        idthreat_engine_service,
        soc_engine_service,
        decision_engine_service,
        response_engine_service,
        forensics_engine_service,
        lake_service,
        forecast_engine_service,
        executive_engine_service,
        inventory_engine_service,
        exposure_engine_service,
        dspm_engine_service,
        vuln_engine_service,
        cloud_posture_service,
        saas_posture_service,
        supplychain_engine_service,
    ) = _register_runtime_services(
        kernel,
        object_store=object_store,
        evidence_store=evidence_store,
        blob_store=blob_store,
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
        detection_rule_store=detection_rule_store,
        detection_profile_store=detection_profile_store,
        detection_engine=detection_engine,
        idthreat_store=idthreat_store,
        idthreat_engine=idthreat_engine,
        soc_store=soc_store,
        soc_engine=soc_engine,
        decision_recommendation_store=decision_recommendation_store,
        decision_model_store=decision_model_store,
        decision_engine=decision_engine,
        response_campaign_store=response_campaign_store,
        response_trigger_store=response_trigger_store,
        response_engine=response_engine,
        forensics_artifact_store=forensics_artifact_store,
        lake_catalog=lake_catalog,
        lake_record_store=lake_record_store,
        lake_retention_engine=lake_retention_engine,
        forecast_store=forecast_store,
        forecast_model_store=forecast_model_store,
        forecast_engine=forecast_engine,
        executive_definition_store=executive_definition_store,
        executive_report_store=executive_report_store,
        executive_kpi_engine=executive_kpi_engine,
        executive_report_engine=executive_report_engine,
        inventory_store=inventory_store,
        inventory_engine=inventory_engine,
        dspm_store=dspm_store,
        dspm_engine=dspm_engine,
        dspm_known_surface_source=dspm_known_surface_source,
        exposure_store=exposure_store,
        exposure_engine=exposure_engine,
        vuln_store=vuln_store,
        vuln_engine=vuln_engine,
        cloud_normalization_store=cloud_normalization_store,
        cloud_posture_engine=cloud_posture_engine,
        saas_normalization_store=saas_normalization_store,
        saas_posture_engine=saas_posture_engine,
        supplychain_store=supplychain_store,
        supplychain_engine=supplychain_engine,
    )
    return Runtime(
        kernel=kernel,
        event_bus=bus,
        object_store=object_store,
        evidence_store=evidence_store,
        finding_store=finding_store,
        blob_store=blob_store,
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
        detection_rule_store=detection_rule_store,
        detection_profile_store=detection_profile_store,
        detection_engine=detection_engine,
        detection_engine_service=detection_engine_service,
        idthreat_store=idthreat_store,
        idthreat_engine=idthreat_engine,
        idthreat_engine_service=idthreat_engine_service,
        soc_store=soc_store,
        soc_engine=soc_engine,
        soc_engine_service=soc_engine_service,
        decision_recommendation_store=decision_recommendation_store,
        decision_model_store=decision_model_store,
        decision_engine=decision_engine,
        decision_engine_service=decision_engine_service,
        response_campaign_store=response_campaign_store,
        response_trigger_store=response_trigger_store,
        response_engine=response_engine,
        response_engine_service=response_engine_service,
        forensics_artifact_store=forensics_artifact_store,
        forensics_engine_service=forensics_engine_service,
        lake_catalog=lake_catalog,
        lake_record_store=lake_record_store,
        lake_retention_engine=lake_retention_engine,
        lake_service=lake_service,
        forecast_store=forecast_store,
        forecast_model_store=forecast_model_store,
        forecast_engine=forecast_engine,
        forecast_engine_service=forecast_engine_service,
        executive_definition_store=executive_definition_store,
        executive_report_store=executive_report_store,
        executive_kpi_engine=executive_kpi_engine,
        executive_report_engine=executive_report_engine,
        executive_engine_service=executive_engine_service,
        inventory_store=inventory_store,
        inventory_engine=inventory_engine,
        inventory_engine_service=inventory_engine_service,
        dspm_store=dspm_store,
        dspm_engine=dspm_engine,
        dspm_engine_service=dspm_engine_service,
        exposure_store=exposure_store,
        exposure_engine=exposure_engine,
        exposure_engine_service=exposure_engine_service,
        vuln_store=vuln_store,
        vuln_engine=vuln_engine,
        vuln_engine_service=vuln_engine_service,
        cloud_normalization_store=cloud_normalization_store,
        cloud_posture_engine=cloud_posture_engine,
        cloud_posture_service=cloud_posture_service,
        saas_normalization_store=saas_normalization_store,
        saas_posture_engine=saas_posture_engine,
        saas_posture_service=saas_posture_service,
        supplychain_store=supplychain_store,
        supplychain_engine=supplychain_engine,
        supplychain_engine_service=supplychain_engine_service,
    )


async def create_runtime(config: AQELYNConfig | None = None) -> Runtime:
    """Build the runtime selected by AQELYN_BACKEND."""
    from aqelyn.assetconfig.drift import AssetConfigAnalyzer
    from aqelyn.assetconfig.postgres import PostgresBaselineStore, PostgresDriftSnapshotStore
    from aqelyn.assetconfig.service import register_acg_events
    from aqelyn.cspm import (
        AssetConfigCloudBaselineRouter,
        CloudOwnerRouter,
        CloudPostureEngine,
        InventoryCloudOwnerRouter,
        PostgresCloudNormalizationStore,
        SharedObjectCloudOwnerRouter,
        register_cloud_events,
    )
    from aqelyn.decision import (
        DecisionIntelligenceEngine,
        EmptyDecisionClaimSource,
        register_decision_events,
    )
    from aqelyn.decision.postgres import (
        PostgresModelVersionStore,
        PostgresRecommendationStore,
    )
    from aqelyn.detection.engine import ThreatDetectionEngine
    from aqelyn.detection.postgres import PostgresProfileStore, PostgresRuleStore
    from aqelyn.detection.service import register_detection_events
    from aqelyn.dspm import (
        DataStoreKnownSurfaceSource,
        DSPMEngine,
        PostgresDSPMStore,
        register_dspm_events,
    )
    from aqelyn.executive import (
        EmptyExecutiveValueSource,
        EmptyMaterialExceptionSource,
        ExecutiveKPIEngine,
        ExecutiveReportEngine,
        PostgresKPIDefinitionStore,
        PostgresReportStore,
        register_executive_events,
    )
    from aqelyn.exposure import (
        KnownDataExposureEngine,
        PostgresExposureStore,
        register_exposure_events,
    )
    from aqelyn.forecast import (
        EmptyActualValueSource,
        EmptyMetricHistorySource,
        ForecastingEngine,
        PostgresForecastStore,
        PostgresPredictionModelStore,
        register_forecast_events,
    )
    from aqelyn.forensics.postgres import PostgresArtifactStore
    from aqelyn.forensics.service import register_forensics_events
    from aqelyn.governance.service import (
        StoreBackedCompliancePolicyEngine,
        register_compliance_events,
    )
    from aqelyn.iag.service import StoreBackedIAGPolicyEvaluator, register_iag_events
    from aqelyn.idthreat import (
        IdentityThreatEngine,
        IdThreatConfig,
        PostgresIdentityDetectionStore,
        register_idthreat_events,
    )
    from aqelyn.inventory import (
        InventoryIntelligenceEngine,
        InventoryKnownSurfaceSource,
        InventoryVulnerabilityCoverageProvider,
        PostgresAssetStore,
        register_inventory_events,
    )
    from aqelyn.lake.postgres import PostgresDatasetCatalog, PostgresTelemetryRecordStore
    from aqelyn.lake.retention import ReferenceCheckers, RetentionEngine
    from aqelyn.lake.service import register_lake_events
    from aqelyn.response import (
        PostgresCampaignStore,
        PostgresTriggerStore,
        ResponseOrchestrationEngine,
        register_response_events,
    )
    from aqelyn.risk.engine import RiskIntelligenceEngine
    from aqelyn.risk.postgres import PostgresRiskSnapshotStore, PostgresRiskStore
    from aqelyn.risk.service import register_risk_events
    from aqelyn.soc.engine import SecurityOperationsEngine
    from aqelyn.soc.postgres import PostgresSOCStore
    from aqelyn.soc.service import register_soc_events
    from aqelyn.sspm import (
        AssetConfigSaaSBaselineRouter,
        InventorySaaSOwnerRouter,
        PostgresSaaSNormalizationStore,
        SaaSIntegrationKnownSurfaceSource,
        SaaSOwnerRouter,
        SaaSPostureEngine,
        SharedObjectSaaSOwnerRouter,
        register_saas_events,
    )
    from aqelyn.supplychain import (
        PostgresSBOMStore,
        SupplyChainConfig,
        SupplyChainEngine,
        register_supplychain_events,
    )
    from aqelyn.threat.engine import ThreatFusionEngine
    from aqelyn.threat.postgres import PostgresThreatSourceRegistry
    from aqelyn.threat.service import register_threat_events
    from aqelyn.vuln import (
        DriftSnapshotBlockingProvider,
        ExposureStoreReachabilityProvider,
        PostgresVulnerabilityStore,
        ThreatSignalFactorProvider,
        VulnerabilityIntelligenceEngine,
        register_vuln_events,
    )

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
    register_detection_events(registry)
    register_idthreat_events(registry)
    register_soc_events(registry)
    register_response_events(registry)
    register_forensics_events(registry)
    register_lake_events(registry)
    register_decision_events(registry)
    register_forecast_events(registry)
    register_executive_events(registry)
    register_inventory_events(registry)
    register_dspm_events(registry)
    register_exposure_events(registry)
    register_vuln_events(registry)
    register_cloud_events(registry)
    register_saas_events(registry)
    register_supplychain_events(registry)
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
    blob_store = InMemoryBlobStore()
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
        config=_runtime_acg_config(cfg),
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
    detection_rule_store = await PostgresRuleStore.connect(cfg.database_url)
    detection_profile_store = await PostgresProfileStore.connect(cfg.database_url)
    detection_engine = ThreatDetectionEngine(
        rule_store=detection_rule_store,
        profile_store=detection_profile_store,
        trust_engine=trust_engine,
        mission_engine=mission_engine,
        evidence_store=evidence_store,
        finding_store=finding_store,
    )
    idthreat_store = await PostgresIdentityDetectionStore.connect(
        cfg.database_url,
        config=IdThreatConfig(
            min_corroboration=2,
            min_confidence=0.75,
            platform_default=0.5,
        ),
        mode=cfg.tenant_mode,
    )
    idthreat_engine = IdentityThreatEngine(
        idthreat_store,
        evidence_store=evidence_store,
        trust_engine=trust_engine,
        profile_store=detection_profile_store,
        entitlement_analyzer=iag_engine,
        config=idthreat_store.config,
        finding_store=finding_store,
        evidence_recorder=evidence_store,
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
    decision_recommendation_store = await PostgresRecommendationStore.connect(
        cfg.database_url,
        mode=cfg.tenant_mode,
    )
    decision_model_store = await PostgresModelVersionStore.connect(
        cfg.database_url,
        mode=cfg.tenant_mode,
    )
    decision_engine = DecisionIntelligenceEngine(
        decision_recommendation_store,
        decision_model_store,
        claim_source=EmptyDecisionClaimSource(),
        evidence_store=evidence_store,
        trust_engine=trust_engine,
        workflow_engine=workflow_engine,
    )
    response_campaign_store = await PostgresCampaignStore.connect(
        cfg.database_url,
        mode=cfg.tenant_mode,
    )
    response_trigger_store = await PostgresTriggerStore.connect(
        cfg.database_url,
        mode=cfg.tenant_mode,
    )
    response_engine = ResponseOrchestrationEngine(
        campaign_store=response_campaign_store,
        workflow=workflow_engine,
        run_store=workflow_run_store,
        trigger_store=response_trigger_store,
        policy_authorizer=policy_engine_service,
        evidence_store=evidence_store,
        finding_store=finding_store,
        incident_reader=soc_store,
    )
    forensics_artifact_store = await PostgresArtifactStore.connect(cfg.database_url)
    lake_catalog = await PostgresDatasetCatalog.connect(
        cfg.database_url,
        mode=cfg.tenant_mode,
    )
    lake_record_store = await PostgresTelemetryRecordStore.connect(
        cfg.database_url,
        mode=cfg.tenant_mode,
    )
    lake_retention_engine = RetentionEngine(
        store=lake_record_store,
        blob_store=blob_store,
        evidence_store=evidence_store,
        reference_checkers=ReferenceCheckers(
            evidence=_FailClosedLakeReferenceChecker(),
            finding=_FailClosedLakeReferenceChecker(),
            case=_FailClosedLakeReferenceChecker(),
        ),
        workflow_engine=workflow_engine,
    )
    forecast_store = await PostgresForecastStore.connect(
        cfg.database_url,
        mode=cfg.tenant_mode,
    )
    forecast_model_store = await PostgresPredictionModelStore.connect(
        cfg.database_url,
        mode=cfg.tenant_mode,
    )
    forecast_engine = ForecastingEngine(
        forecast_store,
        forecast_model_store,
        history_source=EmptyMetricHistorySource(),
        evidence_store=evidence_store,
        actual_source=EmptyActualValueSource(),
        evidence_recorder=evidence_store,
        trust_engine=trust_engine,
    )
    acg_engine.trend_provider = forecast_engine
    executive_definition_store = await PostgresKPIDefinitionStore.connect(cfg.database_url)
    executive_report_store = await PostgresReportStore.connect(
        cfg.database_url,
        mode=cfg.tenant_mode,
    )
    executive_kpi_sources = {
        source_engine: EmptyExecutiveValueSource(source_engine)
        for source_engine in ("compliance", "risk", "forecast", "mission")
    }
    executive_kpi_engine = ExecutiveKPIEngine(
        executive_definition_store,
        executive_kpi_sources,
    )
    executive_report_engine = ExecutiveReportEngine(
        report_store=executive_report_store,
        exception_source=EmptyMaterialExceptionSource(),
        kpi_engine=executive_kpi_engine,
        evidence_store=evidence_store,
    )
    inventory_store = await PostgresAssetStore.connect(
        cfg.database_url,
        mode=cfg.tenant_mode,
    )
    inventory_engine = InventoryIntelligenceEngine(
        inventory_store,
        classifier=acg_engine,
        relationship_store=object_store,
        graph=knowledge_graph,
    )
    dspm_store = await PostgresDSPMStore.connect(
        cfg.database_url,
        mode=cfg.tenant_mode,
    )
    dspm_known_surface_source = DataStoreKnownSurfaceSource(
        InventoryKnownSurfaceSource(inventory_engine),
        dspm_store,
    )
    saas_normalization_store = await PostgresSaaSNormalizationStore.connect(
        cfg.database_url,
        mode=cfg.tenant_mode,
    )
    saas_actor = ActorRef(actor_type="system", actor_id="sspm_engine")
    saas_inventory_router = InventorySaaSOwnerRouter(
        inventory_engine,
        evidence_store=evidence_store,
        source_registry=trust_engine.registry,
        actor=saas_actor,
    )
    saas_owner_routers: list[SaaSOwnerRouter] = [
        saas_inventory_router,
        SharedObjectSaaSOwnerRouter("assetconfig", object_store),
        SharedObjectSaaSOwnerRouter("compliance", object_store),
        SharedObjectSaaSOwnerRouter("iag", object_store),
    ]
    saas_posture_engine = SaaSPostureEngine(
        saas_normalization_store,
        object_store=object_store,
        evidence_store=evidence_store,
        source_registry=trust_engine.registry,
        config=_runtime_saas_config(cfg),
        owner_routers=saas_owner_routers,
        integration_graph=knowledge_graph,
        trust_engine=trust_engine,
        baseline_router=AssetConfigSaaSBaselineRouter(acg_engine, acg_baseline_store),
        workflow_engine=workflow_engine,
        absence_router=saas_inventory_router,
        actor=saas_actor,
    )
    exposure_store = await PostgresExposureStore.connect(
        cfg.database_url,
        mode=cfg.tenant_mode,
    )
    exposure_engine = KnownDataExposureEngine(
        exposure_store,
        SaaSIntegrationKnownSurfaceSource(
            dspm_known_surface_source,
            saas_normalization_store,
        ),
        graph=knowledge_graph,
        identity_provider=iag_engine,
        trend_provider=forecast_engine,
        evidence_lookup=evidence_store,
        trust_provider=trust_engine,
        mission_provider=mission_engine,
        finding_store=finding_store,
    )
    dspm_engine = DSPMEngine(
        dspm_store,
        object_store=object_store,
        inventory=inventory_engine,
        evidence_store=evidence_store,
        trust=trust_engine,
        config=_runtime_dspm_config(cfg),
        exposure_owner=exposure_engine,
        iag_owner=iag_engine,
        compliance_owner=compliance_engine,
        finding_store=finding_store,
        workflow_engine=workflow_engine,
    )
    vuln_store = await PostgresVulnerabilityStore.connect(
        cfg.database_url,
        mode=cfg.tenant_mode,
    )
    vuln_engine = VulnerabilityIntelligenceEngine(
        vuln_store,
        threat_provider=ThreatSignalFactorProvider(threat_engine),
        exposure_provider=ExposureStoreReachabilityProvider(exposure_store),
        mission_provider=mission_engine,
        baseline_provider=DriftSnapshotBlockingProvider(acg_snapshot_store),
        coverage_provider=InventoryVulnerabilityCoverageProvider(inventory_engine, vuln_store),
        trend_provider=forecast_engine,
        finding_store=finding_store,
    )
    supplychain_store = await PostgresSBOMStore.connect(
        cfg.database_url,
        mode=cfg.tenant_mode,
    )
    supplychain_engine = SupplyChainEngine(
        supplychain_store,
        inventory=inventory_engine,
        source_registry=trust_engine.registry,
        object_store=object_store,
        graph=knowledge_graph,
        evidence_store=evidence_store,
        vulnerability_store=vuln_store,
        vulnerability_owner=vuln_engine,
        license_policy_owner=compliance_engine.policy_engine,
        finding_store=finding_store,
        risk_owner=risk_engine,
        workflow_engine=workflow_engine,
        config=SupplyChainConfig(
            license_policy_id=cfg.supplychain_license_policy_id,
            sensitive_scopes=cfg.supplychain_sensitive_scopes,
            max_depth=cfg.supplychain_max_depth,
            batch_size=cfg.supplychain_batch_size,
        ),
    )
    cloud_normalization_store = await PostgresCloudNormalizationStore.connect(
        cfg.database_url,
        mode=cfg.tenant_mode,
    )
    cloud_owner_routers: list[CloudOwnerRouter] = [
        InventoryCloudOwnerRouter(inventory_engine),
        SharedObjectCloudOwnerRouter("assetconfig", object_store),
        SharedObjectCloudOwnerRouter("compliance", object_store),
        SharedObjectCloudOwnerRouter("exposure", object_store),
        SharedObjectCloudOwnerRouter("iag", object_store),
        SharedObjectCloudOwnerRouter("risk", object_store),
    ]
    cloud_posture_engine = CloudPostureEngine(
        cloud_normalization_store,
        object_store=object_store,
        evidence_store=evidence_store,
        source_registry=trust_engine.registry,
        config=_runtime_cloud_config(cfg),
        owner_routers=cloud_owner_routers,
        baseline_router=AssetConfigCloudBaselineRouter(acg_engine, acg_baseline_store),
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
        detection_engine_service,
        idthreat_engine_service,
        soc_engine_service,
        decision_engine_service,
        response_engine_service,
        forensics_engine_service,
        lake_service,
        forecast_engine_service,
        executive_engine_service,
        inventory_engine_service,
        exposure_engine_service,
        dspm_engine_service,
        vuln_engine_service,
        cloud_posture_service,
        saas_posture_service,
        supplychain_engine_service,
    ) = _register_runtime_services(
        kernel,
        object_store=object_store,
        evidence_store=evidence_store,
        blob_store=blob_store,
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
        detection_rule_store=detection_rule_store,
        detection_profile_store=detection_profile_store,
        detection_engine=detection_engine,
        idthreat_store=idthreat_store,
        idthreat_engine=idthreat_engine,
        soc_store=soc_store,
        soc_engine=soc_engine,
        decision_recommendation_store=decision_recommendation_store,
        decision_model_store=decision_model_store,
        decision_engine=decision_engine,
        response_campaign_store=response_campaign_store,
        response_trigger_store=response_trigger_store,
        response_engine=response_engine,
        forensics_artifact_store=forensics_artifact_store,
        lake_catalog=lake_catalog,
        lake_record_store=lake_record_store,
        lake_retention_engine=lake_retention_engine,
        forecast_store=forecast_store,
        forecast_model_store=forecast_model_store,
        forecast_engine=forecast_engine,
        executive_definition_store=executive_definition_store,
        executive_report_store=executive_report_store,
        executive_kpi_engine=executive_kpi_engine,
        executive_report_engine=executive_report_engine,
        inventory_store=inventory_store,
        inventory_engine=inventory_engine,
        dspm_store=dspm_store,
        dspm_engine=dspm_engine,
        dspm_known_surface_source=dspm_known_surface_source,
        exposure_store=exposure_store,
        exposure_engine=exposure_engine,
        vuln_store=vuln_store,
        vuln_engine=vuln_engine,
        cloud_normalization_store=cloud_normalization_store,
        cloud_posture_engine=cloud_posture_engine,
        saas_normalization_store=saas_normalization_store,
        saas_posture_engine=saas_posture_engine,
        supplychain_store=supplychain_store,
        supplychain_engine=supplychain_engine,
        close_object_store=object_store.close,
        close_compliance_snapshot_store=compliance_snapshot_store.close,
        close_workflow_run_store=workflow_run_store.close,
        close_iag_certification_store=iag_certification_store.close,
        close_acg_baseline_store=acg_baseline_store.close,
        close_acg_snapshot_store=acg_snapshot_store.close,
        close_risk_store=risk_store.close,
        close_risk_snapshot_store=risk_snapshot_store.close,
        close_threat_source_registry=threat_source_registry.close,
        close_detection_rule_store=detection_rule_store.close,
        close_detection_profile_store=detection_profile_store.close,
        close_idthreat_store=idthreat_store.close,
        close_soc_store=soc_store.close,
        close_decision_recommendation_store=decision_recommendation_store.close,
        close_decision_model_store=decision_model_store.close,
        close_response_campaign_store=response_campaign_store.close,
        close_response_trigger_store=response_trigger_store.close,
        close_forensics_artifact_store=forensics_artifact_store.close,
        close_lake_catalog=lake_catalog.close,
        close_lake_record_store=lake_record_store.close,
        close_forecast_store=forecast_store.close,
        close_forecast_model_store=forecast_model_store.close,
        close_executive_definition_store=executive_definition_store.close,
        close_executive_report_store=executive_report_store.close,
        close_inventory_store=inventory_store.close,
        close_exposure_store=exposure_store.close,
        close_dspm_store=dspm_store.close,
        close_vuln_store=vuln_store.close,
        close_cloud_normalization_store=cloud_normalization_store.close,
        close_saas_normalization_store=saas_normalization_store.close,
        close_supplychain_store=supplychain_store.close,
    )
    return Runtime(
        kernel=kernel,
        event_bus=bus,
        object_store=object_store,
        evidence_store=evidence_store,
        finding_store=finding_store,
        blob_store=blob_store,
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
        detection_rule_store=detection_rule_store,
        detection_profile_store=detection_profile_store,
        detection_engine=detection_engine,
        detection_engine_service=detection_engine_service,
        idthreat_store=idthreat_store,
        idthreat_engine=idthreat_engine,
        idthreat_engine_service=idthreat_engine_service,
        soc_store=soc_store,
        soc_engine=soc_engine,
        soc_engine_service=soc_engine_service,
        decision_recommendation_store=decision_recommendation_store,
        decision_model_store=decision_model_store,
        decision_engine=decision_engine,
        decision_engine_service=decision_engine_service,
        response_campaign_store=response_campaign_store,
        response_trigger_store=response_trigger_store,
        response_engine=response_engine,
        response_engine_service=response_engine_service,
        forensics_artifact_store=forensics_artifact_store,
        forensics_engine_service=forensics_engine_service,
        lake_catalog=lake_catalog,
        lake_record_store=lake_record_store,
        lake_retention_engine=lake_retention_engine,
        lake_service=lake_service,
        forecast_store=forecast_store,
        forecast_model_store=forecast_model_store,
        forecast_engine=forecast_engine,
        forecast_engine_service=forecast_engine_service,
        executive_definition_store=executive_definition_store,
        executive_report_store=executive_report_store,
        executive_kpi_engine=executive_kpi_engine,
        executive_report_engine=executive_report_engine,
        executive_engine_service=executive_engine_service,
        inventory_store=inventory_store,
        inventory_engine=inventory_engine,
        inventory_engine_service=inventory_engine_service,
        dspm_store=dspm_store,
        dspm_engine=dspm_engine,
        dspm_engine_service=dspm_engine_service,
        exposure_store=exposure_store,
        exposure_engine=exposure_engine,
        exposure_engine_service=exposure_engine_service,
        vuln_store=vuln_store,
        vuln_engine=vuln_engine,
        vuln_engine_service=vuln_engine_service,
        cloud_normalization_store=cloud_normalization_store,
        cloud_posture_engine=cloud_posture_engine,
        cloud_posture_service=cloud_posture_service,
        saas_normalization_store=saas_normalization_store,
        saas_posture_engine=saas_posture_engine,
        saas_posture_service=saas_posture_service,
        supplychain_store=supplychain_store,
        supplychain_engine=supplychain_engine,
        supplychain_engine_service=supplychain_engine_service,
    )
