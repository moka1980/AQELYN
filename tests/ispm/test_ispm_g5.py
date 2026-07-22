"""C-030 G5 acceptance tests for exposure, assessments, proposals, and service wiring."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.decision import replay
from aqelyn.events import EventTypeRegistry, Subject
from aqelyn.evidence import EvidenceRecord, InMemoryEvidenceStore
from aqelyn.exposure import (
    AssetRef,
    ExposureBasis,
    ExposureImpactContext,
    InMemoryExposureStore,
    KnownDataExposureEngine,
    KnownSurfaceRecord,
    StaticKnownSurfaceSource,
)
from aqelyn.exposure.engine import validate_replayable_exposure
from aqelyn.findings import InMemoryFindingStore
from aqelyn.graph import InMemoryKnowledgeGraph
from aqelyn.iag import (
    AccessRisk,
    AccessRiskReport,
    IdentityAccessGovernanceEngine,
    InMemoryCertificationStore,
)
from aqelyn.inventory import InMemoryAssetStore, InventoryIntelligenceEngine
from aqelyn.ispm import (
    ISPM_EVENTS,
    ControlFact,
    IdentityControls,
    IdentityGovernanceOwner,
    IdentityKnownSurfaceSource,
    IdentityPostureScore,
    InMemoryISPMStore,
    ISPMAssessment,
    ISPMEngine,
    ISPMService,
    NormalizedIdentity,
    PostgresISPMStore,
    register_ispm_events,
)
from aqelyn.ispm.normalize import inventory_ref
from aqelyn.kernel import AQELYNConfig, Runtime, create_inmemory_runtime, create_runtime
from aqelyn.mission import MissionImpactResult
from aqelyn.objects import InMemoryObjectStore, ObjectQuery
from aqelyn.policy import PolicyEngine
from aqelyn.trust import InMemorySourceReliabilityRegistry, TrustEngine
from aqelyn.workflow import (
    InMemoryActionRegistry,
    InMemoryRunStore,
    ReadOnlyEchoHandler,
    WorkflowEngine,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
TENANT = "018f0000-0000-7000-8000-000000330501"
NOW = datetime(2026, 7, 22, 18, 0, tzinfo=UTC)
ACTOR = ActorRef(actor_type="user", actor_id="ispm-g5-reviewer")
EVENT_TYPES = {
    "aqelyn.ispm.identity_normalized",
    "aqelyn.ispm.posture_scored",
    "aqelyn.ispm.posture_drift_detected",
    "aqelyn.ispm.controls_unknown",
}


class _GovernanceOwner:
    def __init__(self, report: AccessRiskReport) -> None:
        self.report = report

    async def analyze_risk(
        self,
        *,
        tenant_id: str | None,
        scope: ObjectQuery | None = None,
    ) -> AccessRiskReport:
        _ = tenant_id, scope
        return self.report


class _MissionOwner:
    async def mission_impact(self, object_id: str) -> MissionImpactResult:
        _ = object_id
        return MissionImpactResult()


async def _evidence(
    store: InMemoryEvidenceStore,
    *,
    tenant_id: str | None,
    object_ids: list[str],
) -> EvidenceRecord:
    return await store.add(
        EvidenceRecord(
            id="",
            tenant_id=tenant_id,
            evidence_type="identity.controls",
            schema_version=1,
            subject=Subject(object_ids=object_ids),
            collected_at=NOW,
            recorded_at=NOW,
            collector=ACTOR,
            source_id=new_id("src"),
            method="ispm-g5-fixture/v1",
            content={"metadata_only": True},
            content_hash="",
            confidence=1.0,
            seq=0,
            prev_hash=None,
            record_hash="",
        )
    )


async def _scored_engine(
    *,
    risks: list[AccessRisk] | None = None,
) -> tuple[
    ISPMEngine,
    IdentityPostureScore,
    InMemoryISPMStore,
    InMemoryEvidenceStore,
    str,
]:
    store = InMemoryISPMStore(mode="enterprise")
    evidence_store = InMemoryEvidenceStore(mode="enterprise")
    identity_id = new_id("obj")
    account_id = new_id("obj")
    evidence = await _evidence(
        evidence_store,
        tenant_id=TENANT,
        object_ids=[identity_id, account_id],
    )
    known = ControlFact(
        state="present",
        established_by="provider:entra",
        evidence_id=evidence.id,
        reason="The handed-in provider record established this control.",
    )
    identity = NormalizedIdentity(
        object_id=identity_id,
        tenant_id=TENANT,
        external_id="identity:g5",
        provider="entra",
        identity_kind="human",
        account_object_ids=[account_id],
        relationship_ids=[new_id("rel")],
        controls=IdentityControls(mfa=known, lifecycle=known, last_activity=known),
        field_provenance={"identity_kind": "provider:/identity/type"},
        evidence_id=evidence.id,
    )
    await store.upsert_identity(identity)
    selected_risks = [
        risk.model_copy(update={"subject_id": account_id}, deep=True) for risk in risks or []
    ]
    engine = ISPMEngine(
        store,
        object_store=InMemoryObjectStore(mode="enterprise"),
        inventory=InventoryIntelligenceEngine(InMemoryAssetStore(mode="enterprise")),
        evidence_store=evidence_store,
        trust=TrustEngine(registry=InMemorySourceReliabilityRegistry()),
        governance_owner=cast(
            IdentityGovernanceOwner,
            _GovernanceOwner(AccessRiskReport(risks=selected_risks, evaluated=1, truncated=False)),
        ),
        mission_owner=_MissionOwner(),
    )
    score = await engine.score_identity(account_id, tenant_id=TENANT)
    return engine, score, store, evidence_store, identity.evidence_id


async def test_ispm_identity_sensitivity_kind_and_exposure_replay() -> None:
    engine, score, store, evidence_store, identity_evidence_id = await _scored_engine()
    upstream = StaticKnownSurfaceSource(
        [
            KnownSurfaceRecord(
                asset_ref=AssetRef(kind="asset", ref_id=inventory_ref(score.subject_ref)),
                reachability="external",
                basis=[
                    ExposureBasis(
                        kind="inventory",
                        ref=f"inventory:{inventory_ref(score.subject_ref)}",
                        as_of=NOW,
                    )
                ],
            )
        ]
    )
    source = IdentityKnownSurfaceSource(upstream, store, evidence_store)
    exposure_store = InMemoryExposureStore(mode="enterprise")
    exposure_owner = KnownDataExposureEngine(
        exposure_store,
        source,
        evidence_lookup=evidence_store,
        trust_provider=TrustEngine(registry=InMemorySourceReliabilityRegistry()),
        mission_provider=_MissionOwner(),
    )
    engine.exposure_owner = exposure_owner

    rows = await source.list_known_surface(tenant_id=TENANT)
    matching = [row for row in rows if row.asset_ref.ref_id == inventory_ref(score.subject_ref)]
    assert len(matching) == 1
    assert matching[0].asset_ref.kind == "identity"
    assert matching[0].asset_ref.object_id == score.subject_ref
    assert matching[0].reachability == "external"
    assert any(item.evidence_id == identity_evidence_id for item in matching[0].basis)

    exposure = await engine.analyze_identity_exposure(score.id, tenant_id=TENANT)
    persisted = await exposure_store.get(exposure.id, tenant_id=TENANT)

    assert persisted is not None
    assert persisted.impact_context is not None
    assert persisted.impact_context.kind == "identity_sensitivity"
    assert persisted.impact_context.source_ref == score.id
    assert persisted.impact_context.evidence_id == score.evidence_id
    assert validate_replayable_exposure(persisted) == persisted
    assert persisted.derivation is not None
    assert replay(persisted.derivation) == persisted.derivation.result
    assert any(
        step.params.get("impact_context", {}).get("kind") == "identity_sensitivity"
        for step in persisted.derivation.steps
    )
    assert (
        ExposureImpactContext(
            status="known",
            factor=1.0,
            source_ref="legacy",
            evidence_id=new_id("evd"),
            reason="legacy",
        ).kind
        == "data_sensitivity"
    )


async def test_ispm_assessment_is_durable_and_inventory_not_exhaustive() -> None:
    engine, _, store, _, _ = await _scored_engine()

    assessment = await engine.assess(tenant_id=TENANT)
    loaded = await store.get_assessment(assessment.id, tenant_id=TENANT)

    assert loaded == assessment
    assert assessment.status == "computed"
    assert assessment.scored == 1
    assert len(assessment.score_ids) == 1
    assert assessment.inventory_complete is False
    assert "ECR-0034" in assessment.inventory_note


async def test_ispm_propose_binds_real_iag_finding() -> None:
    risk = AccessRisk(
        kind="dormant",
        subject_id=new_id("obj"),
        detail={"last_used_days": 180},
        severity="medium",
        reason="EA-0011 observed a dormant identity account.",
    )
    engine, score, store, evidence_store, _ = await _scored_engine(risks=[risk])
    finding_store = InMemoryFindingStore(
        mode="enterprise",
        evidence_exists=evidence_store.exists,
    )
    action_registry = InMemoryActionRegistry()
    action_registry.register(
        ReadOnlyEchoHandler(
            action_type="iag.remediate_access",
            capability="iag.remediate_access",
        )
    )
    run_store = InMemoryRunStore(mode="enterprise")
    workflow = WorkflowEngine(
        store=run_store,
        registry=action_registry,
        evidence_store=evidence_store,
    )
    iag_objects = InMemoryObjectStore(mode="enterprise")
    iag_owner = IdentityAccessGovernanceEngine(
        iag_objects,
        InMemoryKnowledgeGraph(iag_objects),
        PolicyEngine([]),
        InMemoryCertificationStore(mode="enterprise"),
        evidence_store,
        finding_store=finding_store,
        workflow_engine=workflow,
    )
    engine.governance_owner = iag_owner
    engine.finding_store = finding_store
    engine.workflow_engine = workflow
    assessment_evidence = await _evidence(
        evidence_store,
        tenant_id=TENANT,
        object_ids=[score.subject_ref],
    )
    assessment = await store.put_assessment(
        ISPMAssessment(
            tenant_id=TENANT,
            run_at=NOW,
            identities_evaluated=1,
            scored=1,
            score_ids=[score.id],
            status="computed",
            inventory_complete=False,
            inventory_note="ECR-0034 inventory completeness is unresolved.",
            evidence_id=assessment_evidence.id,
        )
    )

    finding_ids = await engine.posture_to_findings(
        assessment.id,
        tenant_id=TENANT,
        by=ACTOR,
    )
    runs = await run_store.list(tenant_id=TENANT)

    assert len(finding_ids) == 1
    assert len(runs) == 1
    assert runs[0].source_finding_id == finding_ids[0]
    finding = await finding_store.get(finding_ids[0])
    assert finding is not None
    assert finding.tenant_id == TENANT
    assert finding.source_engine == "iag_engine"
    assert finding.automation.action_ref == "iag.remediate_access"
    assert runs[0].status == "proposed"


async def _runtime(backend: str, *, tenant_mode: str) -> Runtime:
    config = AQELYNConfig(backend=backend, tenant_mode=tenant_mode)
    if backend == "memory":
        return create_inmemory_runtime(config)
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    return await create_runtime(config.model_copy(update={"database_url": PG_URL}))


async def _clear_ispm_store(runtime: Runtime, *, backend: str) -> None:
    if backend != "postgres":
        return
    store = cast(Any, runtime.ispm_store)
    async with store._pool.acquire() as connection:
        await connection.execute(
            "TRUNCATE aq_ispm_assessment, aq_ispm_drift_snapshot, "
            "aq_ispm_baseline_revision, aq_ispm_posture_score, "
            "aq_ispm_identity_revision, aq_ispm_identity_key RESTART IDENTITY CASCADE"
        )


@pytest.mark.parametrize("backend", ["memory", "postgres"])
@pytest.mark.parametrize("tenant_mode", ["local", "enterprise"])
async def test_ispm_service_health_and_factory_wiring(
    backend: str,
    tenant_mode: str,
) -> None:
    runtime = await _runtime(backend, tenant_mode=tenant_mode)
    await _clear_ispm_store(runtime, backend=backend)
    service = runtime.kernel.get_service("ispm_engine")

    assert isinstance(runtime.ispm_engine_service, ISPMService)
    assert runtime.ispm_engine_service is service
    assert runtime.ispm_engine.store is runtime.ispm_store
    assert runtime.ispm_engine.object_store is runtime.object_store
    assert runtime.ispm_engine.inventory is runtime.inventory_engine
    assert runtime.ispm_engine.governance_owner is runtime.iag_engine
    assert runtime.ispm_engine.exposure_owner is runtime.exposure_engine
    assert runtime.ispm_engine.finding_store is runtime.finding_store
    assert runtime.ispm_engine.workflow_engine is runtime.workflow_engine
    assert runtime.exposure_engine.source is runtime.ispm_engine_service.known_surface_source
    assert isinstance(runtime.exposure_engine.source, IdentityKnownSurfaceSource)
    assert runtime.exposure_engine.source.upstream is (
        runtime.secrets_engine_service.known_surface_source
    )
    assert isinstance(runtime.ispm_store, InMemoryISPMStore | PostgresISPMStore)

    pre_start = await service.health()
    assert pre_start.status == "degraded"
    assert pre_start.ready is False
    assert pre_start.dependencies["ispm_store"] == "healthy"
    assert pre_start.dependencies["known_surface_source"] == "healthy"

    await service.start()
    try:
        health = await service.health()
        assert health.status == "degraded"
        assert health.ready is True
        assert health.dependencies["ispm_store"] == "healthy"
        assert health.dependencies["known_surface_source"] == "healthy"
        assert len(runtime.ispm_engine_service.owner_services) == 10
    finally:
        await _clear_ispm_store(runtime, backend=backend)
        await service.stop()


def test_ispm_events_and_import_isolation() -> None:
    registry = EventTypeRegistry(with_core=False)
    register_ispm_events(registry)

    assert set(ISPM_EVENTS) == EVENT_TYPES
    assert len(ISPM_EVENTS) == 4
    assert all(registry.is_registered(event_type) for event_type in EVENT_TYPES)
    assert not any(event_type.startswith("aqelyn.iag.") for event_type in ISPM_EVENTS)

    source = str(Path(__file__).resolve().parents[2] / "src")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (source, environment.get("PYTHONPATH", "")) if part
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import aqelyn.ispm; import aqelyn.kernel.factory",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
