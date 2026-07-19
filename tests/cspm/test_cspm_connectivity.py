"""End-to-end owner connectivity checks for the EA-0028 routing seams."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from aqelyn.assetconfig import (
    ACGConfig,
    AssetConfigAnalyzer,
    Baseline,
    Check,
    InMemoryBaselineStore,
    InMemoryDriftSnapshotStore,
)
from aqelyn.conventions import ActorRef, new_id
from aqelyn.cspm import (
    AssetConfigCloudBaselineRouter,
    CloudBaselineRouter,
    CloudNormalizationConfig,
    CloudOwnerRouter,
    CloudPostureEngine,
    CloudResourceDescriptor,
    InMemoryCloudNormalizationStore,
    InventoryCloudOwnerRouter,
    NormalizedCloudObject,
    OwnerRouteOutcome,
    RouteOwner,
    SharedObjectCloudOwnerRouter,
    cloud_asset_id,
)
from aqelyn.evidence import InMemoryEvidenceStore
from aqelyn.exposure import AssetRef, InMemoryExposureStore, KnownDataExposureEngine
from aqelyn.findings import InMemoryFindingStore
from aqelyn.governance import ComplianceEngine, GovernanceConfig
from aqelyn.graph import InMemoryKnowledgeGraph
from aqelyn.iag import IdentityAccessGovernanceEngine, InMemoryCertificationStore
from aqelyn.inventory import (
    InMemoryAssetStore,
    InventoryIntelligenceEngine,
    InventoryKnownSurfaceSource,
)
from aqelyn.objects import InMemoryObjectStore, ObjectQuery
from aqelyn.policy import Condition, Policy, PolicyEngine, Rule, Target
from aqelyn.risk import InMemoryRiskSnapshotStore, InMemoryRiskStore, RiskIntelligenceEngine
from aqelyn.trust import InMemorySourceReliabilityRegistry

NOW = datetime(2026, 7, 18, 20, 30, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000280701"
ACTOR = ActorRef(actor_type="system", actor_id="cspm-connectivity-test")
BASELINE_ID = "cis-aws-s3-v1"


@dataclass(frozen=True)
class _CloudStack:
    engine: CloudPostureEngine
    object_store: InMemoryObjectStore
    evidence_store: InMemoryEvidenceStore
    normalized: NormalizedCloudObject


def _cloud_config(
    object_type: str,
    *,
    baseline_ids: Sequence[str] = (),
) -> CloudNormalizationConfig:
    return CloudNormalizationConfig.model_validate(
        {
            "type_map": {"aws:s3:bucket": object_type},
            "fact_paths": {
                "aws:s3:bucket": {
                    "encryption_enabled": "/configuration/encryptionEnabled",
                    "network_public": "/configuration/network/public",
                }
            },
            "baseline_ids": list(baseline_ids),
        },
        context={
            "known_object_types": {object_type},
            "known_baseline_ids": set(baseline_ids),
        },
    )


def _descriptor(source_id: str) -> CloudResourceDescriptor:
    return CloudResourceDescriptor(
        provider="aws",
        account="123456789012",
        region="eu-north-1",
        resource_type="s3:bucket",
        resource_id="arn:aws:s3:::connectivity-test",
        raw={
            "configuration": {
                "encryptionEnabled": False,
                "network": {"public": True},
            }
        },
        observed_at=NOW,
        source_id=source_id,
    )


async def _cloud_stack(
    object_type: str,
    *,
    shared_owners: Sequence[RouteOwner] = (),
    inventory: InventoryIntelligenceEngine | None = None,
    baseline_router: CloudBaselineRouter | None = None,
    baseline_ids: Sequence[str] = (),
) -> _CloudStack:
    object_store = InMemoryObjectStore(mode="enterprise")
    evidence_store = InMemoryEvidenceStore(mode="enterprise")
    routers: list[CloudOwnerRouter] = [
        SharedObjectCloudOwnerRouter(owner, object_store) for owner in shared_owners
    ]
    if inventory is not None:
        routers.append(InventoryCloudOwnerRouter(inventory))
    engine = CloudPostureEngine(
        InMemoryCloudNormalizationStore(mode="enterprise"),
        object_store=object_store,
        evidence_store=evidence_store,
        source_registry=InMemorySourceReliabilityRegistry(default_reliability=0.8),
        config=_cloud_config(object_type, baseline_ids=baseline_ids),
        owner_routers=routers,
        baseline_router=baseline_router,
        actor=ACTOR,
    )
    normalized = (await engine.normalize([_descriptor(new_id("src"))], tenant_id=TENANT))[0]
    return _CloudStack(engine, object_store, evidence_store, normalized)


def _outcome(
    outcomes: Sequence[OwnerRouteOutcome],
    owner: RouteOwner,
) -> OwnerRouteOutcome:
    return next(outcome for outcome in outcomes if outcome.owner == owner)


def _baseline() -> Baseline:
    return Baseline(
        id=BASELINE_ID,
        name="CIS AWS S3 encryption",
        asset_class="cloud_storage",
        version=1,
        checks=[
            Check(
                id="s3-encryption",
                key="encryption_enabled",
                expected=True,
                comparator="eq",
                severity="high",
                rationale="Cloud storage must be encrypted.",
            )
        ],
        tenant_id=TENANT,
        set_by=ACTOR,
        set_at=NOW,
    )


def _acg_config() -> ACGConfig:
    return ACGConfig(
        assessable_object_types=["asset", "cloud_storage"],
        classification_rules=[
            {
                "asset_class": "cloud_storage",
                "condition": {
                    "op": "eq",
                    "attr": "object_type",
                    "value": "cloud_storage",
                },
            }
        ],
    )


async def test_cspm_cloud_baseline_assessed_end_to_end() -> None:
    object_store = InMemoryObjectStore(mode="enterprise")
    evidence_store = InMemoryEvidenceStore(mode="enterprise")
    baseline_store = InMemoryBaselineStore()
    snapshot_store = InMemoryDriftSnapshotStore()
    await baseline_store.put(_baseline())
    acg = AssetConfigAnalyzer(
        object_store,
        [],
        baseline_store=baseline_store,
        snapshot_store=snapshot_store,
        evidence_store=evidence_store,
        config=_acg_config(),
    )
    cloud = CloudPostureEngine(
        InMemoryCloudNormalizationStore(mode="enterprise"),
        object_store=object_store,
        evidence_store=evidence_store,
        source_registry=InMemorySourceReliabilityRegistry(default_reliability=0.8),
        config=_cloud_config("cloud_storage", baseline_ids=(BASELINE_ID,)),
        baseline_router=AssetConfigCloudBaselineRouter(acg, baseline_store),
        actor=ACTOR,
    )
    normalized = (await cloud.normalize([_descriptor(new_id("src"))], tenant_id=TENANT))[0]

    snapshot_id = await cloud.apply_cloud_baselines(
        tenant_id=TENANT,
        scope={"object_type": "cloud_storage"},
    )

    snapshot = await snapshot_store.get(snapshot_id)
    assert snapshot is not None
    assert snapshot.baseline_ids == [BASELINE_ID]
    assert snapshot.evidence_id is not None
    assert await evidence_store.exists(snapshot.evidence_id)
    assert snapshot.scope["object_type"] == "cloud_storage"
    assert len(snapshot.asset_drifts) == 1
    assert snapshot.asset_drifts[0].asset_id == normalized.object_id
    assert snapshot.asset_drifts[0].failed == 1
    assert snapshot.overall_score == 0.0


async def test_cspm_inventory_connectivity_end_to_end() -> None:
    inventory = InventoryIntelligenceEngine(InMemoryAssetStore(mode="enterprise"))
    stack = await _cloud_stack("cloud_storage", inventory=inventory)

    routed = (await stack.engine.route([stack.normalized.object_id], tenant_id=TENANT))[0]
    asset_id = cloud_asset_id(stack.normalized.object_id)
    report = await inventory.inventory(tenant_id=TENANT)

    assert _outcome(routed.outcomes, "inventory").status == "accepted"
    assert report.assets == [asset_id]
    assert report.total == 1
    stored = await inventory.store.get(asset_id, tenant_id=TENANT)
    assert stored is not None
    assert stored.asset_type == "cloud_storage"


async def test_cspm_compliance_connectivity_end_to_end() -> None:
    stack = await _cloud_stack("cloud_storage", shared_owners=("compliance",))
    routed = (await stack.engine.route([stack.normalized.object_id], tenant_id=TENANT))[0]
    policy = Policy(
        id="cloud-storage-encryption",
        version=1,
        name="Cloud storage encryption",
        description="Cloud storage must be encrypted.",
        tenant_id=None,
        rules=[
            Rule(
                id="require-encryption",
                kind="compliance",
                description="Encryption must be enabled.",
                target=Target(resource_types=["cloud_storage"]),
                condition=Condition.model_validate(
                    {
                        "op": "eq",
                        "attr": "resource.attributes.observed_state.encryption_enabled",
                        "value": True,
                    }
                ),
                effect="require",
            )
        ],
        standard="cspm/connectivity",
        set_by=ACTOR,
        set_at=NOW,
    )
    config = GovernanceConfig.model_validate(
        {
            "controls": [
                {
                    "id": "cloud-storage-encryption",
                    "name": "Cloud storage encryption",
                    "description": "Cloud storage must be encrypted.",
                    "policy_ids": [policy.id],
                    "framework_refs": [{"framework": "CIS-AWS", "requirement": "2.1"}],
                    "severity": "high",
                }
            ],
            "frameworks": {"CIS-AWS": ["2.1"]},
        },
        context={"known_policy_ids": {policy.id}},
    )
    compliance = ComplianceEngine(stack.object_store, PolicyEngine([policy]), config=config)

    snapshot = await compliance.assess(
        tenant_id=TENANT,
        scope=ObjectQuery(object_type="cloud_storage", labels={"module": "EA-0028"}),
        record_evidence=False,
    )

    assert _outcome(routed.outcomes, "compliance").status == "accepted"
    assert snapshot.control_results[0].evaluated == 1
    assert snapshot.control_results[0].failed == 1
    assert snapshot.control_results[0].failing_subject_ids == [stack.normalized.object_id]


async def test_cspm_exposure_connectivity_end_to_end() -> None:
    inventory = InventoryIntelligenceEngine(InMemoryAssetStore(mode="enterprise"))
    stack = await _cloud_stack(
        "cloud_storage",
        shared_owners=("exposure",),
        inventory=inventory,
    )
    routed = (await stack.engine.route([stack.normalized.object_id], tenant_id=TENANT))[0]
    asset_id = cloud_asset_id(stack.normalized.object_id)
    exposure = KnownDataExposureEngine(
        InMemoryExposureStore(mode="enterprise"),
        InventoryKnownSurfaceSource(inventory),
    )

    surface = await exposure.derive_surface(tenant_id=TENANT)
    record = await exposure.analyze_exposure(
        asset_ref=AssetRef(kind="asset", ref_id=asset_id),
        tenant_id=TENANT,
    )

    assert _outcome(routed.outcomes, "inventory").status == "accepted"
    assert _outcome(routed.outcomes, "exposure").status == "accepted"
    assert [item.asset_ref.ref_id for item in surface] == [asset_id]
    assert record.asset_ref.ref_id == asset_id
    assert record.reachability == "unknown"
    assert record.flagged is True


async def test_cspm_iag_connectivity_end_to_end() -> None:
    stack = await _cloud_stack("account", shared_owners=("iag",))
    routed = (await stack.engine.route([stack.normalized.object_id], tenant_id=TENANT))[0]
    iag = IdentityAccessGovernanceEngine(
        stack.object_store,
        InMemoryKnowledgeGraph(stack.object_store),
        PolicyEngine([]),
        InMemoryCertificationStore(mode="enterprise"),
        stack.evidence_store,
    )

    report = await iag.analyze_risk(
        tenant_id=TENANT,
        scope=ObjectQuery(labels={"module": "EA-0028"}),
    )

    assert _outcome(routed.outcomes, "iag").status == "accepted"
    assert report.evaluated == 1
    assert {risk.kind for risk in report.risks} == {"dormant", "orphaned"}
    assert {risk.subject_id for risk in report.risks} == {stack.normalized.object_id}


async def test_cspm_risk_connectivity_end_to_end() -> None:
    stack = await _cloud_stack("cloud_storage", shared_owners=("risk",))
    routed = (await stack.engine.route([stack.normalized.object_id], tenant_id=TENANT))[0]
    baseline_store = InMemoryBaselineStore()
    snapshot_store = InMemoryDriftSnapshotStore()
    finding_store = InMemoryFindingStore(
        mode="enterprise",
        evidence_exists=stack.evidence_store.exists,
    )
    await baseline_store.put(_baseline())
    acg = AssetConfigAnalyzer(
        stack.object_store,
        [],
        baseline_store=baseline_store,
        snapshot_store=snapshot_store,
        evidence_store=stack.evidence_store,
        finding_store=finding_store,
        config=_acg_config(),
    )
    drift = await acg.assess(
        tenant_id=TENANT,
        scope=ObjectQuery(object_type="cloud_storage", labels={"module": "EA-0028"}),
    )
    finding_ids = await acg.drift_to_findings(
        drift,
        by=ACTOR,
        propose_remediation=False,
        prioritize=False,
    )
    risk_store = InMemoryRiskStore()
    risk = RiskIntelligenceEngine(
        finding_store,
        risk_store,
        InMemoryRiskSnapshotStore(),
    )

    risk_snapshot = await risk.assess(tenant_id=TENANT)
    risks = await risk_store.query(tenant_id=TENANT)

    assert _outcome(routed.outcomes, "risk").status == "accepted"
    assert len(finding_ids) == 1
    assert risk_snapshot.total == 1
    assert len(risks) == 1
    assert [signal.ref_id for signal in risks[0].signals] == finding_ids
    assert risks[0].affected_object_ids == [stack.normalized.object_id]
