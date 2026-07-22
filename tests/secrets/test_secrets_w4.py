"""C-029 W4 acceptance tests for owner handoffs and gated remediation."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import (
    CrossTenantReference,
    EvidenceNotFound,
    UnauthorizedAction,
)
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, EvidenceStore, InMemoryEvidenceStore, VerifyResult
from aqelyn.exposure import (
    ExposureStore,
    InMemoryExposureStore,
    KnownDataExposureEngine,
    KnownSurfaceRecord,
    KnownSurfaceSource,
    PostgresExposureStore,
    validate_replayable_exposure,
)
from aqelyn.findings import FindingQuery, InMemoryFindingStore
from aqelyn.governance import ComplianceEngine, Control, GovernanceConfig
from aqelyn.inventory import (
    InMemoryAssetStore,
    InventoryIntelligenceEngine,
    InventoryKnownSurfaceSource,
)
from aqelyn.mission import MissionImpactResult
from aqelyn.objects import InMemoryObjectStore, ObjectQuery
from aqelyn.policy import ComplianceResult
from aqelyn.risk import InMemoryRiskSnapshotStore, InMemoryRiskStore, RiskIntelligenceEngine
from aqelyn.secrets import (
    CertificateAsset,
    CertificateDescriptor,
    CryptographicKey,
    CryptographicKeyDescriptor,
    CryptoKnownSurfaceSource,
    CryptoStore,
    InMemoryCryptoStore,
    PostgresCryptoStore,
    SecretsIntelligenceEngine,
)
from aqelyn.trust import InMemorySourceReliabilityRegistry, TrustEngine
from aqelyn.workflow import (
    ActionSpec,
    Approval,
    InMemoryActionRegistry,
    InMemoryRunStore,
    WorkflowEngine,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 21, 10, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000320401"
OTHER_TENANT = "018f0000-0000-7000-8000-000000320402"
ACTOR = ActorRef(actor_type="user", actor_id="crypto-w4-reviewer")
SYSTEM = ActorRef(actor_type="system", actor_id="crypto-w4-test")


class _Closable(Protocol):
    async def close(self) -> None: ...


class _MissionProvider:
    async def mission_impact(self, object_id: str) -> MissionImpactResult:
        _ = object_id
        return MissionImpactResult()


class _ReachableInventorySource:
    """Add a handed-in reachability claim without replacing real inventory."""

    def __init__(self, upstream: KnownSurfaceSource) -> None:
        self.upstream = upstream

    async def list_known_surface(
        self,
        *,
        tenant_id: str | None,
    ) -> Sequence[KnownSurfaceRecord]:
        rows = await self.upstream.list_known_surface(tenant_id=tenant_id)
        return [
            row.model_copy(
                update={
                    "reachability": "external",
                    "rationale": "Handed-in network data establishes external reachability.",
                },
                deep=True,
            )
            for row in rows
        ]


class _CompliancePolicy:
    async def evaluate_compliance(
        self,
        resource: dict[str, Any],
        *,
        tenant_id: str | None,
        policy_ids: set[str] | None = None,
    ) -> ComplianceResult:
        _ = resource, tenant_id, policy_ids
        return ComplianceResult(compliant=False, evaluated=1, violations=[])


class _ExecutionCountingHandler:
    def __init__(self, action_type: str = "crypto.rotate") -> None:
        self.spec = ActionSpec(
            action_type=action_type,
            capability=f"capability:{action_type}",
            effect="reversible",
            reversible=True,
            description="Exercise the crypto remediation eligibility gate.",
        )
        self.executed = 0

    async def simulate(
        self,
        inputs: dict[str, Any],
        *,
        tenant_id: str | None,
    ) -> dict[str, Any]:
        return {"inputs": dict(inputs), "tenant_id": tenant_id}

    async def execute(
        self,
        inputs: dict[str, Any],
        *,
        tenant_id: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.executed += 1
        return {
            "inputs": dict(inputs),
            "tenant_id": tenant_id,
            "idempotency_key": idempotency_key,
        }

    async def rollback(self, rollback_ref: str, *, tenant_id: str | None) -> None:
        raise AssertionError("eligibility refusal must not reach rollback")


class _MissingOneEvidence:
    def __init__(self, owner: EvidenceStore, missing_id: str) -> None:
        self.owner = owner
        self.missing_id = missing_id

    async def add(self, record: EvidenceRecord) -> EvidenceRecord:
        return await self.owner.add(record)

    async def get(self, evidence_id: str, *, actor: ActorRef) -> EvidenceRecord:
        if evidence_id == self.missing_id:
            raise EvidenceNotFound(f"evidence not found: {evidence_id}")
        return await self.owner.get(evidence_id, actor=actor)

    async def verify(self, evidence_id: str) -> VerifyResult:
        return await self.owner.verify(evidence_id)


@dataclass
class _Harness:
    crypto_store: CryptoStore
    exposure_store: ExposureStore
    object_store: InMemoryObjectStore
    inventory: InventoryIntelligenceEngine
    evidence: InMemoryEvidenceStore
    findings: InMemoryFindingStore
    trust: TrustEngine
    engine: SecretsIntelligenceEngine
    asset: CryptographicKey


@asynccontextmanager
async def _harness(backend: str) -> AsyncIterator[_Harness]:
    closers: list[_Closable] = []
    if backend == "inmemory":
        crypto_store: CryptoStore = InMemoryCryptoStore(mode="enterprise")
        exposure_store: ExposureStore = InMemoryExposureStore(mode="enterprise")
    else:
        if not PG_URL:
            pytest.skip("AQELYN_DATABASE_URL not set")
        postgres_crypto = await PostgresCryptoStore.connect(PG_URL, mode="enterprise")
        postgres_exposure = await PostgresExposureStore.connect(PG_URL, mode="enterprise")
        async with postgres_crypto._pool.acquire() as connection:
            await connection.execute(
                "TRUNCATE aq_crypto_asset_revision, aq_crypto_asset_identity, "
                "aq_crypto_assessment RESTART IDENTITY CASCADE"
            )
        async with postgres_exposure._pool.acquire() as connection:
            await connection.execute("TRUNCATE aq_exposure_record")
        crypto_store = postgres_crypto
        exposure_store = postgres_exposure
        closers.extend([cast(_Closable, postgres_crypto), cast(_Closable, postgres_exposure)])

    object_store = InMemoryObjectStore(mode="enterprise")
    inventory = InventoryIntelligenceEngine(InMemoryAssetStore(mode="enterprise"))
    evidence = InMemoryEvidenceStore(mode="enterprise")
    findings = InMemoryFindingStore(mode="enterprise")
    trust = TrustEngine(registry=InMemorySourceReliabilityRegistry(default_reliability=0.8))
    source_id = new_id("src")
    fingerprint = f"hmac-sha256:{401:064x}"
    basis = await _evidence(evidence, source_id=source_id, fingerprint=fingerprint)
    ingest_engine = SecretsIntelligenceEngine(
        crypto_store,
        object_store=object_store,
        inventory=inventory,
        evidence_store=evidence,
        trust=trust,
        actor=SYSTEM,
    )
    [stored] = await ingest_engine.ingest_crypto_assets(
        [
            CryptographicKeyDescriptor(
                tenant_id=TENANT,
                external_key_ref="urn:aqelyn:key:payments-signing",
                fingerprint=fingerprint,
                algorithm="rsa",
                key_size=4096,
                usages=["signing"],
                last_rotated_at=NOW,
                source_id=source_id,
                observed_at=NOW,
                evidence_id=basis.id,
            )
        ],
        [],
        tenant_id=TENANT,
    )
    if not isinstance(stored, CryptographicKey):
        raise AssertionError("key ingest returned the wrong crypto asset kind")

    inventory_source = InventoryKnownSurfaceSource(inventory)
    crypto_source = CryptoKnownSurfaceSource(
        _ReachableInventorySource(inventory_source),
        crypto_store,
    )
    exposure_owner = KnownDataExposureEngine(
        exposure_store,
        crypto_source,
        evidence_lookup=evidence,
        trust_provider=trust,
        mission_provider=_MissionProvider(),
        finding_store=findings,
    )
    engine = SecretsIntelligenceEngine(
        crypto_store,
        object_store=object_store,
        inventory=inventory,
        evidence_store=evidence,
        trust=trust,
        exposure_owner=exposure_owner,
        finding_store=findings,
        actor=SYSTEM,
    )
    try:
        yield _Harness(
            crypto_store=crypto_store,
            exposure_store=exposure_store,
            object_store=object_store,
            inventory=inventory,
            evidence=evidence,
            findings=findings,
            trust=trust,
            engine=engine,
            asset=stored,
        )
    finally:
        for closer in reversed(closers):
            await closer.close()


async def _evidence(
    store: InMemoryEvidenceStore,
    *,
    source_id: str,
    fingerprint: str,
) -> EvidenceRecord:
    return await store.add(
        EvidenceRecord(
            id="",
            tenant_id=TENANT,
            evidence_type="crypto_descriptor",
            schema_version=1,
            subject=Subject(object_ids=[]),
            collected_at=NOW,
            recorded_at=NOW,
            collector=SYSTEM,
            source_id=source_id,
            method="handed_in_descriptor",
            content={"fingerprint": fingerprint, "descriptor_kind": "metadata_only"},
            content_hash="",
            confidence=1.0,
            seq=0,
            prev_hash=None,
            record_hash="",
        )
    )


def _governance_config() -> GovernanceConfig:
    return GovernanceConfig.model_validate(
        {
            "controls": [
                Control(
                    id="crypto-key-strength",
                    name="Cryptographic key posture",
                    description="Cryptographic keys must meet the configured baseline.",
                    policy_ids=["crypto-policy"],
                    framework_refs=[],
                    severity="high",
                )
            ],
            "frameworks": {},
            "batch_size": 100,
            "min_confidence": 0.0,
        },
        context={"known_policy_ids": {"crypto-policy"}},
    )


@pytest.mark.parametrize("backend", ["inmemory", "postgres"])
async def test_crypto_exposure_owner_connectivity(backend: str) -> None:
    async with _harness(backend) as harness:
        inventory_rows = await InventoryKnownSurfaceSource(harness.inventory).list_known_surface(
            tenant_id=TENANT
        )
        composed_rows = await CryptoKnownSurfaceSource(
            InventoryKnownSurfaceSource(harness.inventory),
            harness.crypto_store,
        ).list_known_surface(tenant_id=TENANT)

        assert len(inventory_rows) == 1
        assert len(composed_rows) == 1
        assert composed_rows[0].asset_ref.ref_id == harness.asset.inventory_ref
        assert composed_rows[0].asset_ref.object_id == harness.asset.object_id
        assert composed_rows[0].reachability is None
        assert composed_rows[0].asset_ref.evidence_id == harness.asset.evidence_id

        [crypto_exposure] = await harness.engine.analyze_exposure(tenant_id=TENANT)
        assert crypto_exposure.status == "confirmed"
        assert crypto_exposure.impact_context.kind == "credential_sensitivity"
        exposure_id = crypto_exposure.exposure_record_id
        assert exposure_id is not None
        owner_record = await harness.exposure_store.get(exposure_id, tenant_id=TENANT)
        assert owner_record is not None
        assert owner_record.impact_context == crypto_exposure.impact_context
        assert owner_record.derivation is not None
        assert owner_record.derivation.engine_version == "exposure-score/v2"
        assert owner_record.derivation.steps[1].params["impact_context"]["kind"] == (
            "credential_sensitivity"
        )
        assert validate_replayable_exposure(owner_record) == owner_record

        owner = cast(KnownDataExposureEngine, harness.engine.exposure_owner)
        raw = await owner.analyze_exposure(
            asset_ref=owner_record.asset_ref,
            tenant_id=TENANT,
        )
        omitted_kind = await owner.score_exposure(raw)
        assert omitted_kind.impact_context is None
        assert omitted_kind.derivation is not None
        assert omitted_kind.derivation.engine_version == "exposure-score/v1"
        assert omitted_kind.score == owner_record.score


async def test_crypto_owner_delegations() -> None:
    async with _harness("inmemory") as harness:
        compliance = ComplianceEngine(
            harness.object_store,
            _CompliancePolicy(),
            config=_governance_config(),
            evidence_store=harness.evidence,
        )
        harness.engine.compliance_owner = compliance
        snapshot = await harness.engine.crypto_compliance(
            tenant_id=TENANT,
            scope=ObjectQuery(tenant_id=TENANT, object_type="cryptographic_key"),
        )
        assert snapshot.control_results[0].evaluated == 1
        assert snapshot.control_results[0].failed == 1
        assert snapshot.evidence_id is not None

        exposures = await harness.engine.analyze_exposure(tenant_id=TENANT)
        finding_ids = await harness.engine.exposures_to_findings(
            exposures,
            tenant_id=TENANT,
            by=ACTOR,
        )
        assert len(finding_ids) == 1
        finding = await harness.findings.get(finding_ids[0])
        assert finding is not None
        assert finding.automation.eligibility == "none"
        assert finding.automation.requires_approval is True
        assert finding.affected_object_ids == [harness.asset.object_id]
        assert finding.expert_details is not None
        assert finding.expert_details["impact_context"]["kind"] == ("credential_sensitivity")

        risk = RiskIntelligenceEngine(
            harness.findings,
            InMemoryRiskStore(),
            InMemoryRiskSnapshotStore(),
        )
        [correlated] = await risk.correlate(tenant_id=TENANT)
        assert {signal.kind for signal in correlated.signals} == {"finding"}
        assert {signal.ref_id for signal in correlated.signals} == set(finding_ids)

        rows, cursor = await harness.findings.query(FindingQuery(tenant_id=TENANT))
        assert [row.id for row in rows] == finding_ids
        assert cursor is None


async def test_crypto_rotation_gated() -> None:
    async with _harness("inmemory") as harness:
        exposures = await harness.engine.analyze_exposure(tenant_id=TENANT)
        [finding_id] = await harness.engine.exposures_to_findings(
            exposures,
            tenant_id=TENANT,
            by=ACTOR,
        )
        handler = _ExecutionCountingHandler()
        registry = InMemoryActionRegistry()
        registry.register(handler)
        workflow = WorkflowEngine(
            store=InMemoryRunStore(mode="enterprise"),
            registry=registry,
            evidence_store=harness.evidence,
            granted_capabilities={handler.spec.capability},
        )
        harness.engine.workflow_engine = workflow

        with pytest.raises(CrossTenantReference, match="finding tenant"):
            await harness.engine.propose_rotation(
                finding_id,
                tenant_id=OTHER_TENANT,
                by=ACTOR,
                reason="Cross-tenant proposal must be refused.",
            )

        run = await harness.engine.propose_rotation(
            finding_id,
            tenant_id=TENANT,
            by=ACTOR,
            reason="Rotate the exposed signing key after human review.",
        )
        assert run.source_finding_id == finding_id
        assert run.status == "proposed"
        assert handler.executed == 0

        approved = await workflow.approve(
            run.id,
            Approval(
                step_ids=["review-and-remediate"],
                approver=ACTOR,
                reason="Human reviewed the proposed key rotation.",
                at=NOW,
            ),
        )
        assert approved.status == "approved"
        with pytest.raises(UnauthorizedAction, match="eligibility 'none'"):
            await workflow.execute(run.id, by=ACTOR)
        assert handler.executed == 0
        assert not hasattr(harness.engine, "execute")
        assert not hasattr(harness.engine, "rotate")
        assert not hasattr(harness.engine, "revoke")


@pytest.mark.parametrize("backend", ["inmemory", "postgres"])
async def test_crypto_conformance_exposure_and_proposal(backend: str) -> None:
    async with _harness(backend) as harness:
        source_id = new_id("src")
        fingerprint = f"hmac-sha256:{402:064x}"
        basis = await _evidence(
            harness.evidence,
            source_id=source_id,
            fingerprint=fingerprint,
        )
        [certificate] = await harness.engine.ingest_crypto_assets(
            [],
            [
                CertificateDescriptor(
                    tenant_id=TENANT,
                    fingerprint=fingerprint,
                    serial="40:02",
                    subject="CN=conformance.internal",
                    issuer="CN=AQELYN Test CA",
                    not_after=NOW,
                    source_id=source_id,
                    observed_at=NOW,
                    evidence_id=basis.id,
                )
            ],
            tenant_id=TENANT,
        )
        assert isinstance(certificate, CertificateAsset)

        exposures = await harness.engine.analyze_exposure(tenant_id=TENANT)
        assert {item.asset_id for item in exposures} == {
            harness.asset.id,
            certificate.id,
        }
        assert all(item.status == "confirmed" for item in exposures)
        assert all(item.impact_context.kind == "credential_sensitivity" for item in exposures)
        assert all(item.exposure_record_id is not None for item in exposures)

        handlers = {
            "crypto.rotate": _ExecutionCountingHandler(),
            "crypto.revoke_certificate": _ExecutionCountingHandler("crypto.revoke_certificate"),
        }
        registry = InMemoryActionRegistry()
        for handler in handlers.values():
            registry.register(handler)
        workflow = WorkflowEngine(
            store=InMemoryRunStore(mode="enterprise"),
            registry=registry,
            evidence_store=harness.evidence,
            granted_capabilities={handler.spec.capability for handler in handlers.values()},
        )
        harness.engine.workflow_engine = workflow
        actions_by_asset = {
            harness.asset.id: "crypto.rotate",
            certificate.id: "crypto.revoke_certificate",
        }
        for exposure in exposures:
            [finding_id] = await harness.engine.exposures_to_findings(
                [exposure],
                tenant_id=TENANT,
                by=ACTOR,
            )
            finding = await harness.findings.get(finding_id)
            assert finding is not None
            assert finding.automation.eligibility == "none"

            action = actions_by_asset[exposure.asset_id]
            run = await harness.engine.propose_rotation(
                finding_id,
                tenant_id=TENANT,
                by=ACTOR,
                reason="Exercise the shipped credential-governance proposal path.",
            )
            assert run.source_finding_id == finding_id
            assert run.playbook_id.startswith(f"secrets-{action.replace('.', '-')}")
            assert run.status == "proposed"

            approved = await workflow.approve(
                run.id,
                Approval(
                    step_ids=["review-and-remediate"],
                    approver=ACTOR,
                    reason="Human reviewed the conformance proposal.",
                    at=NOW,
                ),
            )
            assert approved.status == "approved"
            with pytest.raises(UnauthorizedAction, match="eligibility 'none'"):
                await workflow.execute(run.id, by=ACTOR)

        assert all(handler.executed == 0 for handler in handlers.values())


async def test_crypto_batch_missing_evidence_unknown() -> None:
    async with _harness("inmemory") as harness:
        harness.engine.evidence_store = cast(
            EvidenceStore,
            _MissingOneEvidence(
                harness.evidence,
                harness.asset.evidence_id,
            ),
        )

        with pytest.raises(EvidenceNotFound):
            await harness.engine.assess_key(harness.asset.id, tenant_id=TENANT)

        assessment = await harness.engine.assess(tenant_id=TENANT)
        loaded = await harness.crypto_store.get_asset(harness.asset.id, tenant_id=TENANT)
        assert isinstance(loaded, CryptographicKey)
        assert loaded.strength.status == "unknown"
        assert loaded.rotation.status == "unknown"
        assert assessment.status == "complete"
        assert assessment.assets_evaluated == 1
        assert assessment.unknown_lifecycle == 1
