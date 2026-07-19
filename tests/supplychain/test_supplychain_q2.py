"""C-027 Q2 acceptance tests for SBOM parsing, routing, and persistence."""

from __future__ import annotations

import inspect
import os
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NoReturn, Protocol, cast

import pytest

import aqelyn.supplychain as supplychain
from aqelyn.conventions import ActorRef, new_id, parse_id
from aqelyn.conventions.errors import (
    OptimisticConcurrencyConflict,
    SBOMParseError,
    SupplyChainConfigInvalid,
    TenantScopeRequired,
)
from aqelyn.inventory import InMemoryAssetStore, InventoryIntelligenceEngine
from aqelyn.supplychain import (
    InMemorySBOMStore,
    PostgresSBOMStore,
    QuarantinedSBOM,
    SBOMDocument,
    SBOMStore,
    SoftwareComponent,
    SupplyChainAssessment,
    SupplyChainEngine,
    parse_sbom,
)
from aqelyn.trust import InMemorySourceReliabilityRegistry, SourceReliability

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 19, 20, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000300201"
OTHER_TENANT = "018f0000-0000-7000-8000-000000300202"
PURL_APP = "pkg:pypi/billing-api@1.0.0"
PURL_REQUESTS = "pkg:pypi/requests@2.32.4"
PURL_URLLIB3 = "pkg:pypi/urllib3@2.5.0"
ACTOR = ActorRef(actor_type="system", actor_id="supplychain-q2-test")


class _Closable(Protocol):
    async def close(self) -> None: ...


@dataclass
class _Harness:
    store: SBOMStore
    inventory_store: InMemoryAssetStore
    registry: InMemorySourceReliabilityRegistry
    engine: SupplyChainEngine


@asynccontextmanager
async def _harness(kind: str) -> AsyncIterator[_Harness]:
    closer: _Closable | None = None
    if kind == "inmemory":
        store: SBOMStore = InMemorySBOMStore(mode="enterprise")
    else:
        if not PG_URL:
            pytest.skip("AQELYN_DATABASE_URL not set")
        postgres = await PostgresSBOMStore.connect(PG_URL, mode="enterprise")
        async with postgres._pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE aq_supplychain_quarantine, aq_supplychain_assessment, "
                "aq_supplychain_component"
            )
        store = postgres
        closer = cast(_Closable, postgres)
    inventory_store = InMemoryAssetStore(mode="enterprise")
    registry = InMemorySourceReliabilityRegistry(default_reliability=0.5)
    engine = SupplyChainEngine(
        store,
        inventory=InventoryIntelligenceEngine(inventory_store),
        source_registry=registry,
    )
    try:
        yield _Harness(store, inventory_store, registry, engine)
    finally:
        if closer is not None:
            await closer.close()


def _cyclonedx(
    *,
    source_id: str | None = None,
    evidence_id: str | None = None,
    observed_at: datetime = NOW,
    licenses: list[dict[str, object]] | None = None,
    supplier: str = "Python Packaging Authority",
    raw: dict[str, object] | None = None,
) -> SBOMDocument:
    return SBOMDocument(
        format="cyclonedx",
        subject_ref="artifact:billing-api:1.0.0",
        raw=raw
        or {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "metadata": {"component": {"bom-ref": "app"}},
            "components": [
                {
                    "bom-ref": "app",
                    "type": "application",
                    "name": "billing-api",
                    "version": "1.0.0",
                    "purl": PURL_APP,
                    "licenses": [{"license": {"id": "Proprietary"}}],
                },
                {
                    "bom-ref": "requests",
                    "type": "library",
                    "name": "requests",
                    "version": "2.32.4",
                    "purl": PURL_REQUESTS,
                    "licenses": licenses or [{"license": {"id": "Apache-2.0"}}],
                    "supplier": {"name": supplier},
                    "hashes": [{"alg": "SHA-256", "content": "a" * 64}],
                },
                {
                    "bom-ref": "urllib3",
                    "type": "library",
                    "name": "urllib3",
                    "version": "2.5.0",
                    "purl": PURL_URLLIB3,
                    "licenses": [{"license": {"id": "MIT"}}],
                },
            ],
            "dependencies": [
                {"ref": "app", "dependsOn": ["requests"]},
                {"ref": "requests", "dependsOn": ["urllib3"]},
                {"ref": "urllib3", "dependsOn": []},
            ],
        },
        source_id=source_id or new_id("src"),
        observed_at=observed_at,
        evidence_id=evidence_id or new_id("evd"),
    )


def _spdx() -> SBOMDocument:
    return SBOMDocument(
        format="spdx",
        subject_ref="artifact:billing-api:1.0.0",
        raw={
            "spdxVersion": "SPDX-2.3",
            "packages": [
                _spdx_package("SPDXRef-App", "billing-api", "1.0.0", PURL_APP),
                _spdx_package("SPDXRef-Requests", "requests", "2.32.4", PURL_REQUESTS),
                _spdx_package("SPDXRef-Urllib3", "urllib3", "2.5.0", PURL_URLLIB3),
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DESCRIBES",
                    "relatedSpdxElement": "SPDXRef-App",
                },
                {
                    "spdxElementId": "SPDXRef-App",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": "SPDXRef-Requests",
                },
                {
                    "spdxElementId": "SPDXRef-Requests",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": "SPDXRef-Urllib3",
                },
            ],
        },
        source_id=new_id("src"),
        observed_at=NOW,
        evidence_id=new_id("evd"),
    )


def _spdx_package(ref: str, name: str, version: str, purl: str) -> dict[str, object]:
    return {
        "SPDXID": ref,
        "name": name,
        "versionInfo": version,
        "primaryPackagePurpose": "LIBRARY",
        "externalRefs": [
            {
                "referenceType": "purl",
                "referenceLocator": purl,
            }
        ],
        "licenseConcluded": "Apache-2.0",
        "supplier": "Organization: AQELYN Test",
        "checksums": [{"algorithm": "SHA256", "checksumValue": "b" * 64}],
    }


def _component(
    *,
    purl: str = PURL_REQUESTS,
    tenant_id: str | None = TENANT,
    provenance_status: str = "unverified",
    object_id: str | None = None,
) -> SoftwareComponent:
    return SoftwareComponent.model_validate(
        {
            "object_id": object_id or new_id("obj"),
            "tenant_id": tenant_id,
            "purl": purl,
            "name": purl.rsplit("/", 1)[-1].split("@", 1)[0],
            "version": purl.rsplit("@", 1)[-1],
            "component_type": "library",
            "licenses": ["Apache-2.0"],
            "supplier": "AQELYN Test",
            "hashes": {"sha256": "a" * 64},
            "provenance_status": provenance_status,
            "direct": True,
            "source_id": new_id("src"),
            "observed_at": NOW,
            "evidence_id": new_id("evd"),
        }
    )


def _assessment(*, tenant_id: str | None = TENANT) -> SupplyChainAssessment:
    return SupplyChainAssessment(
        tenant_id=tenant_id,
        run_at=NOW,
        subject_ref="artifact:billing-api:1.0.0",
        components=3,
        direct=2,
        transitive=1,
        unverified_provenance=3,
        vulnerable_components=1,
        assessment_status="complete",
        evidence_id=new_id("evd"),
    )


async def _set_reliability(
    registry: InMemorySourceReliabilityRegistry,
    source_id: str,
    weight: float,
) -> None:
    await registry.set(
        SourceReliability(
            key=source_id,
            weight=weight,
            rationale="Q2 reconciliation fixture.",
            set_by=ACTOR,
            set_at=NOW,
        )
    )


async def test_sc_no_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    forbidden = {"fetch", "clone", "registry"}
    public_callables = {
        name
        for name, value in inspect.getmembers(supplychain)
        if not name.startswith("_") and callable(value)
    }
    assert not (public_callables & forbidden)

    attempts: list[str] = []

    def blocked(*_args: object, **_kwargs: object) -> NoReturn:
        attempts.append("network")
        raise AssertionError("supply-chain ingestion must not open a network connection")

    async with _harness("inmemory") as harness:
        monkeypatch.setattr(socket, "socket", blocked)
        monkeypatch.setattr(socket, "create_connection", blocked)
        components = await harness.engine.ingest_sbom(_cyclonedx(), tenant_id=TENANT)

    assert len(components) == 3
    assert attempts == []


@pytest.mark.parametrize("document", [_cyclonedx(), _spdx()])
def test_sc_parse_formats(document: SBOMDocument) -> None:
    parsed = parse_sbom(document, tenant_id=TENANT)

    assert [component.purl for component in parsed.components] == [
        PURL_APP,
        PURL_REQUESTS,
        PURL_URLLIB3,
    ]
    assert [(edge.from_purl, edge.to_purl) for edge in parsed.relationships] == [
        (PURL_APP, PURL_REQUESTS),
        (PURL_REQUESTS, PURL_URLLIB3),
    ]
    assert {component.purl for component in parsed.components if component.direct} == {
        PURL_APP,
        PURL_REQUESTS,
    }


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_sc_components_to_inventory(kind: str) -> None:
    async with _harness(kind) as harness:
        components = await harness.engine.ingest_sbom(_cyclonedx(), tenant_id=TENANT)

        for component in components:
            prefix, payload = parse_id(component.object_id)
            assert prefix == "obj"
            asset = await harness.inventory_store.get(f"ast_{payload}", tenant_id=TENANT)
            assert asset is not None
            assert asset.asset_type == "software_component"
            assert asset.classification == component.component_type


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_sc_quarantine(kind: str) -> None:
    partial = _cyclonedx(
        raw={
            "bomFormat": "CycloneDX",
            "components": [
                {
                    "bom-ref": "missing-purl",
                    "type": "library",
                    "name": "partial",
                    "version": "1.0.0",
                }
            ],
        }
    )
    async with _harness(kind) as harness:
        with pytest.raises(SBOMParseError, match="purl"):
            await harness.engine.ingest_sbom(partial, tenant_id=TENANT)

        quarantined = await harness.store.get_quarantine(
            partial.doc_id,
            tenant_id=TENANT,
        )
        rows, cursor = await harness.store.query(tenant_id=TENANT)

    assert quarantined is not None
    assert quarantined.flagged is True
    assert quarantined.raw == partial.raw
    assert "purl" in quarantined.reason
    assert rows == []
    assert cursor is None

    with pytest.raises(SupplyChainConfigInvalid, match="must remain flagged"):
        QuarantinedSBOM(
            doc_id=new_id("sbm"),
            tenant_id=TENANT,
            source_id=new_id("src"),
            observed_at=NOW,
            raw={"partial": True},
            reason="invalid unflagged quarantine",
            flagged=False,
            quarantined_at=NOW,
        )


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_sc_sbom_conflict(kind: str) -> None:
    weak_source = new_id("src")
    strong_source = new_id("src")
    weak = _cyclonedx(
        source_id=weak_source,
        licenses=[{"license": {"id": "MIT"}}],
        supplier="Weak source",
    )
    strong = _cyclonedx(
        source_id=strong_source,
        observed_at=NOW + timedelta(minutes=1),
        licenses=[{"license": {"id": "Apache-2.0"}}],
        supplier="Strong source",
    )
    async with _harness(kind) as harness:
        await _set_reliability(harness.registry, weak_source, 0.2)
        await _set_reliability(harness.registry, strong_source, 0.9)
        await harness.engine.ingest_sbom(weak, tenant_id=TENANT)
        await harness.engine.ingest_sbom(strong, tenant_id=TENANT)
        component = await harness.store.get_component(PURL_REQUESTS, tenant_id=TENANT)

    assert component is not None
    assert component.source_id == strong_source
    assert component.licenses == ["Apache-2.0"]
    assert component.supplier == "Strong source"
    [conflict] = component.conflicts
    assert conflict.unresolved is False
    assert conflict.resolved_by == strong_source
    assert {candidate.source_id for candidate in conflict.candidates} == {
        weak_source,
        strong_source,
    }
    assert {candidate.reliability for candidate in conflict.candidates} == {0.2, 0.9}


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_sc_sbom_conflict_tie_stays_unresolved(kind: str) -> None:
    first_source = new_id("src")
    second_source = new_id("src")
    first = _cyclonedx(source_id=first_source, supplier="First claim")
    second = _cyclonedx(
        source_id=second_source,
        supplier="Second claim",
        observed_at=NOW + timedelta(minutes=1),
    )
    async with _harness(kind) as harness:
        await _set_reliability(harness.registry, first_source, 0.5)
        await _set_reliability(harness.registry, second_source, 0.5)
        await harness.engine.ingest_sbom(first, tenant_id=TENANT)
        await harness.engine.ingest_sbom(second, tenant_id=TENANT)
        component = await harness.store.get_component(PURL_REQUESTS, tenant_id=TENANT)

    assert component is not None
    assert component.supplier == "Second claim"
    [conflict] = component.conflicts
    assert conflict.unresolved is True
    assert conflict.resolved_by is None
    assert conflict.resolved_evidence_id is None


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_sc_store_contract(kind: str) -> None:
    async with _harness(kind) as harness:
        first = await harness.store.put_component(_component())
        replacement = await harness.store.put_component(_component(object_id=new_id("obj")))
        assert replacement.object_id == first.object_id
        assert await harness.store.get_component(PURL_REQUESTS, tenant_id=TENANT) == replacement

        verified = await harness.store.put_component(
            _component(purl="pkg:pypi/aiohttp@3.12.0", provenance_status="verified")
        )
        second_unverified = await harness.store.put_component(_component(purl=PURL_URLLIB3))

        page_one, cursor = await harness.store.query(
            tenant_id=TENANT,
            provenance="unverified",
            limit=1,
        )
        assert len(page_one) == 1
        assert cursor == page_one[-1].object_id
        page_two, final_cursor = await harness.store.query(
            tenant_id=TENANT,
            provenance="unverified",
            limit=1,
            cursor=cursor,
        )
        assert {row.object_id for row in [*page_one, *page_two]} == {
            first.object_id,
            second_unverified.object_id,
        }
        assert final_cursor is None

        exact, exact_cursor = await harness.store.query(
            tenant_id=TENANT,
            provenance="verified",
            limit=1,
        )
        assert [row.object_id for row in exact] == [verified.object_id]
        assert exact_cursor is None

        assessment = await harness.store.put_assessment(_assessment())
        assert await harness.store.get_assessment(assessment.id, tenant_id=TENANT) == assessment
        with pytest.raises(OptimisticConcurrencyConflict):
            await harness.store.put_assessment(assessment)

        quarantine = QuarantinedSBOM(
            doc_id=new_id("sbm"),
            tenant_id=TENANT,
            source_id=new_id("src"),
            observed_at=NOW,
            evidence_id=new_id("evd"),
            raw={"partial": True},
            reason="contract fixture",
            quarantined_at=NOW,
        )
        await harness.store.quarantine(quarantine)
        assert await harness.store.get_quarantine(quarantine.doc_id, tenant_id=TENANT) == quarantine

        rows, _ = await harness.store.query(tenant_id=OTHER_TENANT)
        assert rows == []
        assert await harness.store.get_component(PURL_REQUESTS, tenant_id=OTHER_TENANT) is None


async def test_sc_store_requires_enterprise_scope() -> None:
    store = InMemorySBOMStore(mode="enterprise")
    with pytest.raises(TenantScopeRequired):
        await store.query(tenant_id=None)
    with pytest.raises(TenantScopeRequired):
        await store.put_component(_component(tenant_id=None))
