"""C-028 P4 acceptance tests for owner delegation and propose-only remediation."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Protocol, cast

import pytest

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.conventions.errors import (
    DerivationNotReplayable,
    DSPMConfigInvalid,
    EvidenceNotFound,
    StoreUnavailable,
)
from aqelyn.decision import ClaimRef, Derivation, DerivationStep, build_derivation
from aqelyn.dspm import (
    DataAccessClaim,
    DataAsset,
    DataExposure,
    DataPostureAssessment,
    DataStoreLocation,
    DSPMConfig,
    DSPMEngine,
    DSPMScope,
    DSPMStore,
    InMemoryDSPMStore,
    PostgresDSPMStore,
)
from aqelyn.dspm.engine import DataStoreComplianceOwner, DataStoreIAGOwner, WorkflowProposer
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, InMemoryEvidenceStore
from aqelyn.findings import Finding, FindingQuery, FindingStore, InMemoryFindingStore
from aqelyn.governance import ComplianceEngine, Control, GovernanceConfig
from aqelyn.graph import KnowledgeGraph
from aqelyn.iag import (
    ACCOUNT_OBJECT_TYPE,
    ENTITLEMENT_OBJECT_TYPE,
    GRANTS_ENTITLEMENT,
    HAS_ACCOUNT,
    HAS_ROLE,
    IDENTITY_OBJECT_TYPE,
    ROLE_OBJECT_TYPE,
    AccessPath,
    AccessRiskReport,
    IdentityAccessAnalyzer,
)
from aqelyn.inventory import AssetRecord, DiscoverySource
from aqelyn.objects import (
    AQObject,
    AQRelationship,
    InMemoryObjectStore,
    NaturalKey,
    ObjectQuery,
    ObjectStore,
    SourceRef,
)
from aqelyn.policy import ComplianceResult, PolicyEngine
from aqelyn.risk import InMemoryRiskSnapshotStore, InMemoryRiskStore, RiskIntelligenceEngine
from aqelyn.trust import InMemorySourceReliabilityRegistry, TrustEngine
from aqelyn.workflow import Playbook, Run

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 20, 20, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000310401"
OTHER_TENANT = "018f0000-0000-7000-8000-000000310402"
ACTOR = ActorRef(actor_type="user", actor_id="dspm-p4-reviewer")
SYSTEM = ActorRef(actor_type="system", actor_id="dspm-p4-test")


class _Closable(Protocol):
    async def close(self) -> None: ...


class _UnusedInventory:
    async def ingest(
        self,
        *,
        reports: Sequence[Mapping[str, Any]],
        source: DiscoverySource,
        tenant_id: str | None,
    ) -> list[AssetRecord]:
        _ = reports, source, tenant_id
        raise AssertionError("inventory must not be called by P4 read paths")


class _CountingIAG:
    def __init__(self, owner: IdentityAccessAnalyzer) -> None:
        self.owner = owner
        self.path_calls: list[str] = []
        self.risk_calls = 0

    async def access_paths(
        self,
        identity_id: str,
        *,
        tenant_id: str | None = None,
    ) -> list[AccessPath]:
        self.path_calls.append(identity_id)
        return await self.owner.access_paths(identity_id, tenant_id=tenant_id)

    async def analyze_risk(
        self,
        *,
        tenant_id: str | None,
        scope: ObjectQuery | None = None,
    ) -> AccessRiskReport:
        self.risk_calls += 1
        return await self.owner.analyze_risk(tenant_id=tenant_id, scope=scope)


class _UnavailableIAG:
    async def access_paths(
        self,
        identity_id: str,
        *,
        tenant_id: str | None = None,
    ) -> list[AccessPath]:
        _ = identity_id, tenant_id
        raise StoreUnavailable("IAG is temporarily unavailable")

    async def analyze_risk(
        self,
        *,
        tenant_id: str | None,
        scope: ObjectQuery | None = None,
    ) -> AccessRiskReport:
        _ = tenant_id, scope
        raise AssertionError("risk analysis must stop after the retriable path failure")


class _DefectiveIAG(_UnavailableIAG):
    async def access_paths(
        self,
        identity_id: str,
        *,
        tenant_id: str | None = None,
    ) -> list[AccessPath]:
        _ = identity_id, tenant_id
        raise RuntimeError("adapter defect")


class _CompliancePolicy:
    async def evaluate_compliance(
        self,
        resource: dict[str, Any],
        *,
        tenant_id: str | None,
        policy_ids: set[str] | None = None,
    ) -> ComplianceResult:
        _ = tenant_id, policy_ids
        return ComplianceResult(compliant=False, evaluated=1, violations=[])


class _WorkflowSpy:
    def __init__(self) -> None:
        self.proposals: list[tuple[Playbook, Finding | None]] = []
        self.mutations: list[object] = []
        self.executions: list[object] = []
        self.handler_calls: list[object] = []

    async def propose(
        self,
        playbook: Playbook,
        *,
        by: ActorRef,
        source_finding: Finding | None = None,
    ) -> Run:
        self.proposals.append((playbook.model_copy(deep=True), source_finding))
        return Run(
            id=new_id("run"),
            playbook_id=playbook.id,
            playbook_version=playbook.version,
            tenant_id=playbook.tenant_id,
            status="proposed",
            source_finding_id=None if source_finding is None else source_finding.id,
            created_by=by,
            created_at=NOW,
            updated_at=NOW,
        )

    async def execute(self, *args: object, **kwargs: object) -> None:
        self.executions.append((args, kwargs))

    async def invoke_handler(self, *args: object, **kwargs: object) -> None:
        self.handler_calls.append((args, kwargs))


@asynccontextmanager
async def _dspm_store(backend: str) -> AsyncIterator[DSPMStore]:
    if backend == "inmemory":
        yield InMemoryDSPMStore(mode="enterprise")
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresDSPMStore.connect(PG_URL, mode="enterprise")
    async with store._pool.acquire() as connection:
        await connection.execute(
            "TRUNCATE aq_dspm_assessment, aq_dspm_exposure, aq_dspm_asset, aq_dspm_asset_key"
        )
    try:
        yield store
    finally:
        await cast(_Closable, store).close()


def _config() -> DSPMConfig:
    return DSPMConfig(
        sensitivity_factors={
            "public": 0.0,
            "internal": 0.25,
            "pii": 0.8,
            "secret": 1.0,
        },
        batch_size=20,
        max_work=100,
    )


async def _evidence(
    store: InMemoryEvidenceStore,
    *,
    tenant_id: str | None,
    object_id: str,
) -> EvidenceRecord:
    return await store.add(
        EvidenceRecord(
            id="",
            tenant_id=tenant_id,
            evidence_type="data.access_claim",
            schema_version=1,
            subject=Subject(object_ids=[object_id]),
            collected_at=NOW,
            recorded_at=NOW,
            collector=SYSTEM,
            source_id=new_id("src"),
            method="dspm.access_claim/v1",
            content={"metadata_only": True, "identity_id": object_id},
            content_hash="",
            confidence=1.0,
            seq=0,
            prev_hash=None,
            record_hash="",
        )
    )


def _asset(
    *,
    object_id: str,
    evidence_id: str,
    tenant_id: str | None,
    access_claims: list[DataAccessClaim] | None = None,
) -> DataAsset:
    return DataAsset(
        object_id=object_id,
        inventory_ref=new_id("ast"),
        tenant_id=tenant_id,
        store_id=f"store:{object_id}",
        store_type="bucket",
        location=DataStoreLocation(
            provider="aws",
            region="eu-north-1",
            resource_ref=f"arn:aws:s3:::{object_id}",
        ),
        field_classifications=[],
        max_known_sensitivity=None,
        classification_status="unknown",
        flagged=True,
        access_claims=access_claims or [],
        observed_at=NOW,
        evidence_id=evidence_id,
    )


def _source() -> SourceRef:
    return SourceRef(
        source_id=new_id("src"),
        evidence_id=new_id("evd"),
        observed_at=NOW,
        method="dspm-p4-test",
    )


def _score_derivation(score: float, evidence_id: str) -> Derivation:
    risk_unit = score / 100.0
    claims = [
        ClaimRef(kind="trust", ref_id="trust:dspm-p4", evidence_id=evidence_id),
        ClaimRef(kind="mission", ref_id="mission:dspm-p4", evidence_id=evidence_id),
        ClaimRef(kind="risk", ref_id="risk:dspm-p4", evidence_id=evidence_id),
    ]
    claim_payloads: list[dict[str, Any]] = [claim.model_dump(mode="json") for claim in claims]
    selected: dict[str, Any] = {"claims": claim_payloads, "count": 3}
    weighed_items = [{**claim, "weight": risk_unit} for claim in claim_payloads]
    weighed: dict[str, Any] = {"items": weighed_items}
    scored: dict[str, Any] = {
        "items": [{**item, "score": risk_unit} for item in weighed_items],
        "factor": 1.0,
    }
    return build_derivation(
        inputs=claims,
        steps=[
            DerivationStep(
                seq=1,
                op="select_claims",
                input_refs=[claim.ref_id for claim in claims],
                params={"kinds": ["trust", "mission", "risk"]},
                output=selected,
                note="Select the owner records used by the exposure score.",
            ),
            DerivationStep(
                seq=2,
                op="weigh",
                input_refs=["step:1"],
                params={"default": risk_unit},
                output=weighed,
                note="Carry the EA-0013 score as the owner weight.",
            ),
            DerivationStep(
                seq=3,
                op="mission_weight",
                input_refs=["step:2"],
                params={"factor": 1.0, "source_field": "weight", "target_field": "score"},
                output=scored,
                note="Emit the replayable exposure score factor.",
            ),
        ],
        model_version=1,
        engine_version="exposure-score/v2",
    )


async def _object(
    store: ObjectStore,
    object_type: str,
    name: str,
    *,
    attributes: dict[str, Any] | None = None,
) -> AQObject:
    cast(Any, store).registry.register(object_type, 1, None)
    return await store.upsert(
        AQObject(
            id="",
            object_type=object_type,
            schema_version=1,
            display_name=name,
            attributes=attributes or {},
            natural_keys=[NaturalKey(namespace=f"p4:{object_type}", value=name)],
            sources=[_source()],
            first_seen_at=NOW,
            last_seen_at=NOW,
            created_at=NOW,
            updated_at=NOW,
            created_by=SYSTEM,
            updated_by=SYSTEM,
        )
    )


async def _relate(
    store: ObjectStore,
    source: AQObject,
    target: AQObject,
    relation_type: str,
) -> None:
    await store.relate(
        AQRelationship(
            id="",
            from_id=source.id,
            to_id=target.id,
            relation_type=relation_type,
            sources=[_source()],
            created_at=NOW,
            updated_at=NOW,
            created_by=SYSTEM,
            updated_by=SYSTEM,
        )
    )


def _engine(
    store: DSPMStore,
    *,
    object_store: ObjectStore,
    evidence_store: InMemoryEvidenceStore,
    iag_owner: DataStoreIAGOwner | None = None,
    compliance_owner: DataStoreComplianceOwner | None = None,
    finding_store: FindingStore | None = None,
    workflow_engine: WorkflowProposer | None = None,
) -> DSPMEngine:
    return DSPMEngine(
        store,
        object_store=object_store,
        inventory=_UnusedInventory(),
        evidence_store=evidence_store,
        trust=TrustEngine(registry=InMemorySourceReliabilityRegistry()),
        config=_config(),
        iag_owner=iag_owner,
        compliance_owner=compliance_owner,
        finding_store=finding_store,
        workflow_engine=workflow_engine,
    )


async def test_dspm_iag_access_context(graph_harness: Any) -> None:
    object_store = cast(ObjectStore, graph_harness.object_store)
    graph = cast(KnowledgeGraph, graph_harness.graph)
    identity = await _object(object_store, IDENTITY_OBJECT_TYPE, "Ada")
    account = await _object(
        object_store,
        ACCOUNT_OBJECT_TYPE,
        "ada@example.test",
        attributes={"last_used_at": utc_now().isoformat()},
    )
    role = await _object(object_store, ROLE_OBJECT_TYPE, "Data reader")
    entitlement = await _object(object_store, ENTITLEMENT_OBJECT_TYPE, "read-secret-store")
    await _relate(object_store, identity, account, HAS_ACCOUNT)
    await _relate(object_store, account, role, HAS_ROLE)
    await _relate(object_store, role, entitlement, GRANTS_ENTITLEMENT)

    evidence_store = InMemoryEvidenceStore()
    evidence = await _evidence(evidence_store, tenant_id=None, object_id=identity.id)
    store = InMemoryDSPMStore()
    asset = await store.put_asset(
        _asset(
            object_id=new_id("obj"),
            evidence_id=evidence.id,
            tenant_id=None,
            access_claims=[
                DataAccessClaim(
                    identity_id=identity.id,
                    claim_kind="granted",
                    evidence_id=evidence.id,
                )
            ],
        )
    )
    owner = _CountingIAG(IdentityAccessAnalyzer(object_store, graph, PolicyEngine([])))
    engine = _engine(
        store,
        object_store=object_store,
        evidence_store=evidence_store,
        iag_owner=owner,
    )

    context = await engine.access_context(asset.id, tenant_id=None)

    assert context.status == "known"
    assert owner.path_calls == [identity.id]
    assert owner.risk_calls == 1
    assert len(context.paths) == 1
    assert context.paths[0].account_id == account.id
    assert context.paths[0].entitlement_ids == [entitlement.id]


async def test_dspm_access_context_pending_and_programming_error() -> None:
    object_store = cast(ObjectStore, InMemoryObjectStore())
    evidence_store = InMemoryEvidenceStore()
    identity_id = new_id("obj")
    evidence = await _evidence(evidence_store, tenant_id=None, object_id=identity_id)
    store = InMemoryDSPMStore()
    asset = await store.put_asset(
        _asset(
            object_id=new_id("obj"),
            evidence_id=evidence.id,
            tenant_id=None,
            access_claims=[
                DataAccessClaim(
                    identity_id=identity_id,
                    claim_kind="observed",
                    evidence_id=evidence.id,
                )
            ],
        )
    )

    pending = await _engine(
        store,
        object_store=object_store,
        evidence_store=evidence_store,
        iag_owner=_UnavailableIAG(),
    ).access_context(asset.id, tenant_id=None)
    assert pending.status == "pending"
    assert pending.paths == []
    assert pending.risks == []
    assert pending.claims[0].identity_id == identity_id

    with pytest.raises(RuntimeError, match="adapter defect"):
        await _engine(
            store,
            object_store=object_store,
            evidence_store=evidence_store,
            iag_owner=_DefectiveIAG(),
        ).access_context(asset.id, tenant_id=None)

    missing_claim_asset = await store.put_asset(
        _asset(
            object_id=new_id("obj"),
            evidence_id=evidence.id,
            tenant_id=None,
            access_claims=[
                DataAccessClaim(
                    identity_id=identity_id,
                    claim_kind="observed",
                    evidence_id=new_id("evd"),
                )
            ],
        )
    )
    with pytest.raises(EvidenceNotFound):
        await _engine(
            store,
            object_store=object_store,
            evidence_store=evidence_store,
        ).access_context(missing_claim_asset.id, tenant_id=None)


async def test_dspm_compliance_and_risk_handoff(graph_harness: Any) -> None:
    object_store = cast(ObjectStore, graph_harness.object_store)
    evidence_store = InMemoryEvidenceStore()
    data_store = await _object(object_store, "data_store", "secret-bucket")
    await _object(object_store, "unrelated", "unrelated-host")
    governance = ComplianceEngine(
        object_store,
        _CompliancePolicy(),
        config=GovernanceConfig(
            controls=[
                Control(
                    id="data-control",
                    name="Data store control",
                    description="Data stores must satisfy the delegated policy.",
                    policy_ids=["data-policy"],
                    severity="high",
                )
            ],
            frameworks={},
            batch_size=100,
            min_confidence=0.0,
        ),
        evidence_store=evidence_store,
    )
    engine = _engine(
        InMemoryDSPMStore(),
        object_store=object_store,
        evidence_store=evidence_store,
        compliance_owner=governance,
    )

    snapshot = await engine.data_compliance(tenant_id=None, scope=ObjectQuery(limit=100))

    assert snapshot.scope["object_type"] == "data_store"
    assert snapshot.control_results[0].evaluated == 1
    assert snapshot.control_results[0].failing_subject_ids == [data_store.id]


@pytest.mark.parametrize("backend", ["inmemory", "postgres"])
async def test_dspm_remediation_gated_and_risk_consumes_finding(backend: str) -> None:
    async with _dspm_store(backend) as store:
        evidence_id = new_id("evd")
        gap = await store.put_exposure(
            DataExposure(
                tenant_id=TENANT,
                data_asset_id=new_id("dsa"),
                object_id=new_id("obj"),
                exposure_ref=new_id("exp"),
                sensitivity="unknown",
                reachability="external",
                state="classification_gap",
                flagged=True,
                reason="Known external reachability intersects an unresolved classification.",
                evidence_ids=[evidence_id],
                detected_at=NOW,
            )
        )
        exposure = await store.put_exposure(
            DataExposure(
                tenant_id=TENANT,
                data_asset_id=new_id("dsa"),
                object_id=new_id("obj"),
                exposure_ref=new_id("exp"),
                sensitivity="secret",
                reachability="external",
                state="confirmed",
                flagged=False,
                score=80.0,
                derivation=_score_derivation(80.0, evidence_id),
                reason="Secret data has evidence-backed external reachability.",
                evidence_ids=[evidence_id],
                detected_at=NOW,
            )
        )
        assessment = await store.put_assessment(
            DataPostureAssessment(
                tenant_id=TENANT,
                run_at=NOW,
                scope=DSPMScope(limit=10),
                coverage_status="complete",
                stores_evaluated=1,
                unknown_fields=1,
                exposure_ids=[exposure.id],
                gap_ids=[gap.id],
            )
        )
        assert await store.get_exposure(exposure.id, tenant_id=OTHER_TENANT) is None
        assert await store.get_assessment(assessment.id, tenant_id=OTHER_TENANT) is None

        findings = InMemoryFindingStore(mode="enterprise")
        workflow = _WorkflowSpy()
        engine = _engine(
            store,
            object_store=InMemoryObjectStore(mode="enterprise"),
            evidence_store=InMemoryEvidenceStore(),
            finding_store=findings,
            workflow_engine=workflow,
        )
        finding_ids = await engine.exposures_to_findings(
            assessment.id,
            tenant_id=TENANT,
            by=ACTOR,
        )

        assert len(finding_ids) == 2
        raised = [await findings.get(finding_id) for finding_id in finding_ids]
        assert all(finding is not None for finding in raised)
        selected = [cast(Finding, finding) for finding in raised]
        assert {finding.finding_type for finding in selected} == {
            "data_classification_gap",
            "data_exposure",
        }
        assert all(finding.automation.eligibility == "none" for finding in selected)
        assert all(finding.automation.requires_approval is True for finding in selected)
        assert len(workflow.proposals) == 2
        assert {proposal.steps[0].action_type for proposal, _ in workflow.proposals} == {
            "data.restrict_access",
            "data.review_classification",
        }
        assert all(proposal.steps[0].requires_approval for proposal, _ in workflow.proposals)
        assert all(source_finding is None for _, source_finding in workflow.proposals)
        assert {
            proposal.steps[0].inputs["finding_id"] for proposal, _ in workflow.proposals
        } == set(finding_ids)
        assert workflow.mutations == []
        assert workflow.executions == []
        assert workflow.handler_calls == []

        risk = RiskIntelligenceEngine(
            findings,
            InMemoryRiskStore(),
            InMemoryRiskSnapshotStore(),
        )
        correlated = await risk.correlate(tenant_id=TENANT)
        assert len(correlated) == 1
        assert correlated[0].impact == 0.8
        assert {signal.kind for signal in correlated[0].signals} == {"finding"}
        assert {signal.ref_id for signal in correlated[0].signals} == set(finding_ids)


async def test_dspm_findings_refuse_incomplete_assessment() -> None:
    store = InMemoryDSPMStore(mode="enterprise")
    assessment = await store.put_assessment(
        DataPostureAssessment(
            tenant_id=TENANT,
            run_at=NOW,
            scope=DSPMScope(limit=1),
            coverage_status="truncated",
            coverage_reason="truncated",
            next_cursor=new_id("dsa"),
        )
    )
    engine = _engine(
        store,
        object_store=InMemoryObjectStore(mode="enterprise"),
        evidence_store=InMemoryEvidenceStore(),
        finding_store=InMemoryFindingStore(mode="enterprise"),
        workflow_engine=_WorkflowSpy(),
    )
    with pytest.raises(DSPMConfigInvalid, match="complete DSPM assessment"):
        await engine.exposures_to_findings(
            assessment.id,
            tenant_id=TENANT,
            by=ACTOR,
        )


async def test_dspm_tampered_exposure_derivation_is_withheld() -> None:
    store = InMemoryDSPMStore(mode="enterprise")
    evidence_id = new_id("evd")
    derivation = _score_derivation(80.0, evidence_id)
    tampered_step = derivation.steps[-1].model_copy(
        update={"output": {"items": [], "factor": 1.0}},
        deep=True,
    )
    tampered = derivation.model_copy(
        update={"steps": [*derivation.steps[:-1], tampered_step]},
        deep=True,
    )
    exposure = await store.put_exposure(
        DataExposure(
            tenant_id=TENANT,
            data_asset_id=new_id("dsa"),
            object_id=new_id("obj"),
            exposure_ref=new_id("exp"),
            sensitivity="secret",
            reachability="external",
            state="confirmed",
            flagged=False,
            score=80.0,
            derivation=tampered,
            reason="Tampered score must not become a finding.",
            evidence_ids=[evidence_id],
            detected_at=NOW,
        )
    )
    assessment = await store.put_assessment(
        DataPostureAssessment(
            tenant_id=TENANT,
            run_at=NOW,
            scope=DSPMScope(limit=1),
            coverage_status="complete",
            stores_evaluated=1,
            exposure_ids=[exposure.id],
        )
    )
    findings = InMemoryFindingStore(mode="enterprise")
    engine = _engine(
        store,
        object_store=InMemoryObjectStore(mode="enterprise"),
        evidence_store=InMemoryEvidenceStore(),
        finding_store=findings,
        workflow_engine=_WorkflowSpy(),
    )

    with pytest.raises(DerivationNotReplayable):
        await engine.exposures_to_findings(
            assessment.id,
            tenant_id=TENANT,
            by=ACTOR,
        )
    rows, _ = await findings.query(FindingQuery(tenant_id=TENANT))
    assert rows == []
