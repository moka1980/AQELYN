"""C-027 Q4 acceptance tests for evidence-backed provenance verification."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import (
    DependencyUnavailable,
    StoreUnavailable,
    SupplyChainConfigInvalid,
)
from aqelyn.events import Subject
from aqelyn.evidence import (
    EvidenceRecord,
    EvidenceStore,
    InMemoryEvidenceStore,
)
from aqelyn.evidence.postgres import PostgresEvidenceStore
from aqelyn.graph import InMemoryKnowledgeGraph
from aqelyn.inventory import InMemoryAssetStore, InventoryIntelligenceEngine
from aqelyn.objects import InMemoryObjectStore
from aqelyn.supplychain import (
    InMemorySBOMStore,
    ProvenanceAttestation,
    ProvenanceCheck,
    ProvenanceResult,
    ProvenanceVerifier,
    SBOMDocument,
    SoftwareComponent,
    SupplyChainEngine,
)
from aqelyn.trust import InMemorySourceReliabilityRegistry

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 20, 8, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000300401"
PURL = "pkg:pypi/payments@1.0.0"
ACTOR = ActorRef(actor_type="system", actor_id="supplychain-q4-test")


class _Closable(Protocol):
    async def close(self) -> None: ...


class _Verifier:
    def __init__(self, *, valid: bool, detail: str) -> None:
        self.valid = valid
        self.detail = detail
        self.calls: list[tuple[str, str]] = []

    async def verify(
        self,
        attestation: ProvenanceAttestation,
        *,
        component: SoftwareComponent,
    ) -> ProvenanceCheck:
        self.calls.append((attestation.kind, component.purl))
        return ProvenanceCheck(valid=self.valid, detail=self.detail)


class _UnavailableEvidenceStore:
    async def add(self, record: EvidenceRecord) -> EvidenceRecord:
        raise StoreUnavailable("evidence backbone unavailable")

    async def verify(self, evidence_id: str) -> object:
        raise StoreUnavailable("evidence backbone unavailable")


class _UnavailableVerifier:
    async def verify(
        self,
        attestation: ProvenanceAttestation,
        *,
        component: SoftwareComponent,
    ) -> ProvenanceCheck:
        raise DependencyUnavailable("signature verifier unavailable")


@dataclass
class _Harness:
    evidence_store: EvidenceStore
    sbom_store: InMemorySBOMStore
    object_store: InMemoryObjectStore
    inventory_store: InMemoryAssetStore
    engine: SupplyChainEngine
    source_id: str


@asynccontextmanager
async def _harness(kind: str, *, verifier: ProvenanceVerifier | None) -> AsyncIterator[_Harness]:
    closer: _Closable | None = None
    if kind == "inmemory":
        evidence_store: EvidenceStore = InMemoryEvidenceStore(mode="enterprise")
    else:
        if not PG_URL:
            pytest.skip("AQELYN_DATABASE_URL not set")
        postgres = await PostgresEvidenceStore.connect(PG_URL, mode="enterprise")
        async with postgres._pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE aq_evidence_custody, aq_evidence_package, aq_evidence RESTART IDENTITY"
            )
        evidence_store = postgres
        closer = cast(_Closable, postgres)

    source_id = new_id("src")
    sbom_store = InMemorySBOMStore(mode="enterprise")
    object_store = InMemoryObjectStore(mode="enterprise")
    inventory_store = InMemoryAssetStore(mode="enterprise")
    engine = SupplyChainEngine(
        sbom_store,
        inventory=InventoryIntelligenceEngine(inventory_store),
        source_registry=InMemorySourceReliabilityRegistry(default_reliability=0.8),
        object_store=object_store,
        graph=InMemoryKnowledgeGraph(object_store),
        evidence_store=evidence_store,
        provenance_verifier=verifier,
    )
    try:
        yield _Harness(
            evidence_store,
            sbom_store,
            object_store,
            inventory_store,
            engine,
            source_id,
        )
    finally:
        if closer is not None:
            await closer.close()


def _document(source_id: str) -> SBOMDocument:
    return SBOMDocument(
        format="cyclonedx",
        subject_ref="artifact:payments:1.0.0",
        raw={
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "metadata": {"component": {"bom-ref": "app"}},
            "components": [
                {
                    "bom-ref": "app",
                    "type": "application",
                    "name": "payments",
                    "version": "1.0.0",
                    "purl": PURL,
                    "licenses": [{"license": {"id": "Apache-2.0"}}],
                }
            ],
            "dependencies": [{"ref": "app", "dependsOn": []}],
        },
        source_id=source_id,
        observed_at=NOW,
        evidence_id=new_id("evd"),
    )


async def _basis_evidence(
    evidence_store: EvidenceStore,
    *,
    object_id: str,
    source_id: str,
) -> EvidenceRecord:
    return await evidence_store.add(
        EvidenceRecord(
            id="",
            tenant_id=TENANT,
            evidence_type="supplychain.provenance_attestation",
            schema_version=1,
            subject=Subject(object_ids=[object_id]),
            collected_at=NOW,
            recorded_at=NOW,
            collector=ACTOR,
            source_id=source_id,
            method="supplychain.attestation_intake/v1",
            content={"bundle": "handed-in"},
            content_hash="",
            labels={"module": "EA-0030", "kind": "provenance_attestation"},
            seq=0,
            prev_hash=None,
            record_hash="",
        )
    )


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_sc_provenance_verify(kind: str) -> None:
    verifier = _Verifier(valid=True, detail="Sigstore bundle and publisher identity verified")
    async with _harness(kind, verifier=verifier) as harness:
        [component] = await harness.engine.ingest_sbom(
            _document(harness.source_id),
            tenant_id=TENANT,
        )
        basis = await _basis_evidence(
            harness.evidence_store,
            object_id=component.object_id,
            source_id=harness.source_id,
        )
        [result] = await harness.engine.verify_provenance(
            [
                ProvenanceAttestation(
                    component_purl=PURL,
                    kind="sigstore",
                    raw={"bundle": "handed-in"},
                    evidence_id=basis.id,
                )
            ],
            tenant_id=TENANT,
        )
        stored_component = await harness.sbom_store.get_component(PURL, tenant_id=TENANT)
        stored_object = await harness.object_store.get(component.object_id)
        assert result.evidence_id is not None
        result_evidence = await harness.evidence_store.get(result.evidence_id, actor=ACTOR)
        integrity = await harness.evidence_store.verify(result.evidence_id)
        [substituted] = await harness.engine.verify_provenance(
            [
                ProvenanceAttestation(
                    component_purl=PURL,
                    kind="sigstore",
                    raw={"bundle": "substituted"},
                    evidence_id=basis.id,
                )
            ],
            tenant_id=TENANT,
        )

    assert result.status == "verified"
    assert result.flagged is False
    assert result.basis_evidence_id == basis.id
    assert verifier.calls == [("sigstore", PURL)]
    assert substituted.status == "unverified"
    assert "does not match" in substituted.detail
    assert integrity.ok is True
    assert result_evidence.content is not None
    assert result_evidence.content["status"] == "verified"
    assert stored_component is not None
    assert stored_component.provenance_status == "verified"
    assert stored_object is not None
    assert stored_object.attributes["provenance_status"] == "verified"

    with pytest.raises(SupplyChainConfigInvalid, match="recorded result evidence"):
        ProvenanceResult(
            component_purl=PURL,
            status="verified",
            detail="cannot exist without result evidence",
            flagged=False,
        )
    with pytest.raises(SupplyChainConfigInvalid, match="must remain flagged"):
        ProvenanceResult(
            component_purl=PURL,
            status="unverified",
            detail="cannot be presented without a flag",
            flagged=False,
        )


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_sc_provenance_failure(kind: str) -> None:
    verifier = _Verifier(valid=False, detail="signature does not match the artifact digest")
    async with _harness(kind, verifier=verifier) as harness:
        await harness.engine.ingest_sbom(
            _document(harness.source_id),
            tenant_id=TENANT,
        )
        [failed] = await harness.engine.verify_provenance(
            [
                ProvenanceAttestation(
                    component_purl=PURL,
                    kind="signature",
                    raw={"signature": "invalid"},
                )
            ],
            tenant_id=TENANT,
        )
        stored = await harness.sbom_store.get_component(PURL, tenant_id=TENANT)

        no_verifier = SupplyChainEngine(
            harness.sbom_store,
            inventory=InventoryIntelligenceEngine(harness.inventory_store),
            source_registry=InMemorySourceReliabilityRegistry(default_reliability=0.8),
            object_store=harness.object_store,
            graph=InMemoryKnowledgeGraph(harness.object_store),
            evidence_store=harness.evidence_store,
        )
        [unverified] = await no_verifier.verify_provenance(
            [
                ProvenanceAttestation(
                    component_purl=PURL,
                    kind="slsa",
                    raw={"statement": "handed-in"},
                )
            ],
            tenant_id=TENANT,
        )

        verifier_down = SupplyChainEngine(
            harness.sbom_store,
            inventory=InventoryIntelligenceEngine(harness.inventory_store),
            source_registry=InMemorySourceReliabilityRegistry(default_reliability=0.8),
            object_store=harness.object_store,
            graph=InMemoryKnowledgeGraph(harness.object_store),
            evidence_store=harness.evidence_store,
            provenance_verifier=_UnavailableVerifier(),
        )
        [verifier_unavailable] = await verifier_down.verify_provenance(
            [
                ProvenanceAttestation(
                    component_purl=PURL,
                    kind="signature",
                    raw={"signature": "not checked"},
                )
            ],
            tenant_id=TENANT,
        )

        unavailable = SupplyChainEngine(
            harness.sbom_store,
            inventory=InventoryIntelligenceEngine(harness.inventory_store),
            source_registry=InMemorySourceReliabilityRegistry(default_reliability=0.8),
            object_store=harness.object_store,
            graph=InMemoryKnowledgeGraph(harness.object_store),
            evidence_store=cast(EvidenceStore, _UnavailableEvidenceStore()),
            provenance_verifier=_Verifier(valid=True, detail="signature valid"),
        )
        [backbone_down] = await unavailable.verify_provenance(
            [
                ProvenanceAttestation(
                    component_purl=PURL,
                    kind="signature",
                    raw={"signature": "valid"},
                )
            ],
            tenant_id=TENANT,
        )

    assert failed.status == "failed"
    assert failed.flagged is True
    assert failed.evidence_id is not None
    assert "does not match" in failed.detail
    assert stored is not None
    assert stored.provenance_status == "failed"
    assert unverified.status == "unverified"
    assert unverified.flagged is True
    assert unverified.evidence_id is not None
    assert "no attestation authenticity verifier" in unverified.detail
    assert verifier_unavailable.status == "unverified"
    assert verifier_unavailable.flagged is True
    assert verifier_unavailable.evidence_id is not None
    assert "DependencyUnavailable" in verifier_unavailable.detail
    assert backbone_down.status == "unverified"
    assert backbone_down.flagged is True
    assert backbone_down.evidence_id is None
    assert "result recording was unavailable" in backbone_down.detail
