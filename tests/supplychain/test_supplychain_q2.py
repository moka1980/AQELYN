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

import asyncpg
import pytest

import aqelyn.supplychain as supplychain
from aqelyn.conventions import ActorRef, new_id, parse_id
from aqelyn.conventions.errors import (
    OptimisticConcurrencyConflict,
    SBOMParseError,
    SupplyChainConfigInvalid,
    TenantScopeRequired,
)
from aqelyn.evidence import InMemoryEvidenceStore
from aqelyn.graph import InMemoryKnowledgeGraph
from aqelyn.inventory import (
    InMemoryAssetStore,
    InventoryIntelligenceEngine,
    InventoryVulnerabilityCoverageProvider,
)
from aqelyn.objects import InMemoryObjectStore
from aqelyn.supplychain import (
    ComponentIdentity,
    InMemorySBOMStore,
    PostgresSBOMStore,
    ProvenanceStatus,
    QuarantinedSBOM,
    SBOMDocument,
    SBOMStore,
    SoftwareComponent,
    SupplyChainAssessment,
    SupplyChainEngine,
    SupplyChainReadService,
    parse_sbom,
)
from aqelyn.trust import InMemorySourceReliabilityRegistry, SourceReliability
from aqelyn.vuln import InMemoryVulnerabilityStore

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 19, 20, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000300201"
OTHER_TENANT = "018f0000-0000-7000-8000-000000300202"
PURL_APP = "pkg:pypi/billing-api@1.0.0"
PURL_REQUESTS = "pkg:pypi/requests@2.32.4"
PURL_URLLIB3 = "pkg:pypi/urllib3@2.5.0"
CPE_LAUNCHER = "cpe:2.3:a:example:simple_launcher:1.1.0.14:*:*:*:*:*:*:*"
ACTOR = ActorRef(actor_type="system", actor_id="supplychain-q2-test")


class _Closable(Protocol):
    async def close(self) -> None: ...


@dataclass
class _Harness:
    store: SBOMStore
    inventory_store: InMemoryAssetStore
    object_store: InMemoryObjectStore
    registry: InMemorySourceReliabilityRegistry
    engine: SupplyChainEngine


@asynccontextmanager
async def _harness(kind: str, *, mode: str = "enterprise") -> AsyncIterator[_Harness]:
    closer: _Closable | None = None
    if kind == "inmemory":
        store: SBOMStore = InMemorySBOMStore(mode=mode)
    else:
        if not PG_URL:
            pytest.skip("AQELYN_DATABASE_URL not set")
        postgres = await PostgresSBOMStore.connect(PG_URL, mode=mode)
        async with postgres._pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE aq_supplychain_quarantine, aq_supplychain_assessment, "
                "aq_supplychain_component"
            )
        store = postgres
        closer = cast(_Closable, postgres)
    inventory_store = InMemoryAssetStore(mode=mode)
    object_store = InMemoryObjectStore(mode=mode)
    registry = InMemorySourceReliabilityRegistry(default_reliability=0.5)
    engine = SupplyChainEngine(
        store,
        inventory=InventoryIntelligenceEngine(inventory_store),
        source_registry=registry,
        object_store=object_store,
        graph=InMemoryKnowledgeGraph(object_store),
        evidence_store=InMemoryEvidenceStore(mode=mode),
    )
    try:
        yield _Harness(store, inventory_store, object_store, registry, engine)
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


def _spdx_cpe() -> SBOMDocument:
    return SBOMDocument(
        format="spdx",
        subject_ref="artifact:simple-launcher:1.1.0.14",
        raw={
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "SPDXID": "SPDXRef-Launcher",
                    "name": "simple-launcher",
                    "versionInfo": "1.1.0.14",
                    "primaryPackagePurpose": "APPLICATION",
                    "externalRefs": [
                        {
                            "referenceType": "cpe23Type",
                            "referenceLocator": CPE_LAUNCHER,
                        }
                    ],
                }
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DESCRIBES",
                    "relatedSpdxElement": "SPDXRef-Launcher",
                }
            ],
        },
        source_id=new_id("src"),
        observed_at=NOW,
        evidence_id=new_id("evd"),
    )


def _mixed_identity_cyclonedx() -> SBOMDocument:
    cpe_components = [
        {
            "bom-ref": f"launcher-{index}",
            "type": "library",
            "name": "simple-launcher",
            "version": "1.1.0.14",
            "cpe": CPE_LAUNCHER,
            "properties": [
                {
                    "name": f"syft:location:{index}:path",
                    "value": f"/synthetic/bin/launcher-{index}",
                }
            ],
        }
        for index in range(24)
    ]
    return _cyclonedx(
        raw={
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
                    "cpe": "cpe:2.3:a:example:billing_api:1.0.0:*:*:*:*:*:*:*",
                    "evidence": {"occurrences": [{"location": "/synthetic/apps/billing-api"}]},
                },
                *cpe_components,
            ],
            "dependencies": [
                {"ref": "app", "dependsOn": ["launcher-0"]},
                *[{"ref": f"launcher-{index}", "dependsOn": []} for index in range(24)],
            ],
        }
    )


def _duplicate_component_cyclonedx(
    first: dict[str, object],
    second: dict[str, object],
) -> SBOMDocument:
    base: dict[str, object] = {
        "type": "library",
        "name": "requests",
        "version": "2.32.4",
        "purl": PURL_REQUESTS,
    }
    return _cyclonedx(
        raw={
            "bomFormat": "CycloneDX",
            "components": [
                {"bom-ref": "first", **base, **first},
                {"bom-ref": "second", **base, **second},
            ],
        }
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
            "identity_kind": "purl",
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


def _cpe_component(
    *,
    cpe: str = CPE_LAUNCHER,
    tenant_id: str | None = TENANT,
    object_id: str | None = None,
    locations: list[str] | None = None,
) -> SoftwareComponent:
    return SoftwareComponent(
        object_id=object_id or new_id("obj"),
        tenant_id=tenant_id,
        identity_kind="cpe",
        purl=None,
        cpe=cpe,
        name="simple-launcher",
        version="1.1.0.14",
        component_type="library",
        locations=locations or ["/synthetic/bin/launcher"],
        direct=False,
        source_id=new_id("src"),
        observed_at=NOW,
        evidence_id=new_id("evd"),
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


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_component_read_keyset_is_exhaustive(kind: str) -> None:
    async with _harness(kind) as harness:
        stored = [
            await harness.store.put_component(_component(purl=f"pkg:pypi/read-{index}@1.0.0"))
            for index in range(5)
        ]
        expected = [
            record.object_id
            for record in sorted(stored, key=lambda item: (item.provenance_status, item.object_id))
        ]

        for limit in (1, 2, 3, 4, 5):
            after: tuple[ProvenanceStatus, str] | None = None
            seen: list[str] = []
            while True:
                store_page, after = await harness.store.query_components_for_read(
                    tenant_id=TENANT,
                    after=after,
                    limit=limit,
                )
                seen.extend(record.object_id for record in store_page)
                if after is None:
                    break
            assert seen == expected
            assert len(seen) == len(set(seen))

        read_service = SupplyChainReadService(harness.store, tenant_mode="enterprise")
        read_page = await read_service.list_components(tenant_id=TENANT, limit=5, cursor=None)
        assert all(item.explain is None for item in read_page.items)


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
    assert [
        (edge.from_identity.value, edge.to_identity.value) for edge in parsed.relationships
    ] == [
        (PURL_APP, PURL_REQUESTS),
        (PURL_REQUESTS, PURL_URLLIB3),
    ]
    assert {component.purl for component in parsed.components if component.direct} == {
        PURL_APP,
        PURL_REQUESTS,
    }


def test_sc_purlless_with_cpe_admitted_and_locations_retained() -> None:
    parsed = parse_sbom(_mixed_identity_cyclonedx(), tenant_id=TENANT)

    assert len(parsed.components) == 2
    by_kind = {component.identity_kind: component for component in parsed.components}
    purl_component = by_kind["purl"]
    cpe_component = by_kind["cpe"]
    assert purl_component.purl == PURL_APP
    assert purl_component.cpe == "cpe:2.3:a:example:billing_api:1.0.0:*:*:*:*:*:*:*"
    assert purl_component.locations == ["/synthetic/apps/billing-api"]
    assert cpe_component.purl is None
    assert cpe_component.cpe == CPE_LAUNCHER
    assert cpe_component.locations == sorted(
        f"/synthetic/bin/launcher-{index}" for index in range(24)
    )
    assert [(edge.from_identity, edge.to_identity) for edge in parsed.relationships] == [
        (
            ComponentIdentity(kind="purl", value=PURL_APP),
            ComponentIdentity(kind="cpe", value=CPE_LAUNCHER),
        )
    ]


def test_sc_spdx_cpe_identity_is_format_level() -> None:
    parsed = parse_sbom(_spdx_cpe(), tenant_id=TENANT)

    [component] = parsed.components
    assert component.identity == ComponentIdentity(kind="cpe", value=CPE_LAUNCHER)
    assert component.purl is None


def test_sc_malformed_claimed_purl_does_not_fall_back_to_cpe() -> None:
    document = _mixed_identity_cyclonedx()
    raw = document.raw.copy()
    components = [dict(item) for item in raw["components"]]
    components[0]["purl"] = "not-a-package-url"
    raw["components"] = components

    with pytest.raises(SBOMParseError, match="package URL"):
        parse_sbom(document.model_copy(update={"raw": raw}, deep=True), tenant_id=TENANT)


def test_sc_conflicting_secondary_coordinate_is_not_smoothed() -> None:
    document = _cyclonedx(
        raw={
            "bomFormat": "CycloneDX",
            "components": [
                {
                    "bom-ref": "first",
                    "type": "library",
                    "name": "requests",
                    "version": "2.32.4",
                    "purl": PURL_REQUESTS,
                    "cpe": "cpe:2.3:a:example:requests:2.32.4:*:*:*:*:*:*:*",
                },
                {
                    "bom-ref": "second",
                    "type": "library",
                    "name": "requests",
                    "version": "2.32.4",
                    "purl": PURL_REQUESTS,
                    "cpe": "cpe:2.3:a:other:requests:2.32.4:*:*:*:*:*:*:*",
                },
            ],
        }
    )

    with pytest.raises(SBOMParseError, match="conflicting duplicate"):
        parse_sbom(document, tenant_id=TENANT)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("licenses", [{"license": {"id": "MIT"}}], ["MIT"]),
        (
            "cpe",
            "cpe:2.3:a:example:requests:2.32.4:*:*:*:*:*:*:*",
            "cpe:2.3:a:example:requests:2.32.4:*:*:*:*:*:*:*",
        ),
        ("supplier", {"name": "Python Packaging Authority"}, "Python Packaging Authority"),
        (
            "hashes",
            [{"alg": "SHA-256", "content": "a" * 64}],
            {"sha-256": "a" * 64},
        ),
    ],
    ids=["licenses", "secondary-coordinate", "supplier", "hashes"],
)
def test_sc_absence_merges_informative_value(
    field: str,
    value: object,
    expected: object,
) -> None:
    for first, second in (({}, {field: value}), ({field: value}, {})):
        parsed = parse_sbom(
            _duplicate_component_cyclonedx(first, second),
            tenant_id=TENANT,
        )

        [component] = parsed.components
        assert getattr(component, field) == expected


@pytest.mark.parametrize(
    ("field", "first", "second"),
    [
        (
            "licenses",
            [{"license": {"id": "MIT"}}],
            [{"license": {"id": "Apache-2.0"}}],
        ),
        (
            "cpe",
            "cpe:2.3:a:example:requests:2.32.4:*:*:*:*:*:*:*",
            "cpe:2.3:a:other:requests:2.32.4:*:*:*:*:*:*:*",
        ),
        (
            "supplier",
            {"name": "First Supplier"},
            {"name": "Second Supplier"},
        ),
        (
            "hashes",
            [{"alg": "SHA-256", "content": "a" * 64}],
            [{"alg": "SHA-256", "content": "b" * 64}],
        ),
    ],
    ids=["licenses", "secondary-coordinate", "supplier", "hashes"],
)
def test_sc_contradiction_still_quarantines(
    field: str,
    first: object,
    second: object,
) -> None:
    document = _duplicate_component_cyclonedx(
        {field: first},
        {field: second},
    )

    with pytest.raises(SBOMParseError, match="conflicting duplicate"):
        parse_sbom(document, tenant_id=TENANT)


@pytest.mark.parametrize("field", ["name", "version", "type"])
def test_sc_contradiction_only_fields_refuse_on_absence(field: str) -> None:
    document = _duplicate_component_cyclonedx({}, {})
    raw = dict(document.raw)
    components = [dict(item) for item in cast(list[dict[str, object]], raw["components"])]
    del components[1][field]
    raw["components"] = components

    with pytest.raises(SBOMParseError):
        parse_sbom(document.model_copy(update={"raw": raw}, deep=True), tenant_id=TENANT)


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
@pytest.mark.parametrize("mode", ["local", "enterprise"])
async def test_sc_cpe_component_real_owner_round_trip(kind: str, mode: str) -> None:
    document = _mixed_identity_cyclonedx()
    tenant_id = None if mode == "local" else TENANT
    async with _harness(kind, mode=mode) as harness:
        first = await harness.engine.ingest_sbom(document, tenant_id=tenant_id)
        second = await harness.engine.ingest_sbom(document, tenant_id=tenant_id)
        rows, cursor = await harness.store.query(tenant_id=tenant_id)
        cpe = await harness.store.get_component(
            ComponentIdentity(kind="cpe", value=CPE_LAUNCHER),
            tenant_id=tenant_id,
        )

        assert cpe is not None
        object_record = await harness.object_store.get(cpe.object_id)
        prefix, payload = parse_id(cpe.object_id)
        asset = await harness.inventory_store.get(
            f"ast_{payload}",
            tenant_id=tenant_id,
        )

    assert prefix == "obj"
    assert len(first) == len(second) == len(rows) == 2
    assert {component.object_id for component in first} == {
        component.object_id for component in second
    }
    assert cursor is None
    assert cpe.locations == sorted(f"/synthetic/bin/launcher-{index}" for index in range(24))
    assert object_record is not None
    assert [(key.namespace, key.value) for key in object_record.natural_keys] == [
        ("cpe", CPE_LAUNCHER)
    ]
    assert object_record.attributes["purl"] is None
    assert object_record.attributes["cpe"] == CPE_LAUNCHER
    assert asset is not None
    assert asset.asset_type == "software_component"


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
@pytest.mark.parametrize("mode", ["local", "enterprise"])
async def test_vuln_cpe_only_named_unassessable(kind: str, mode: str) -> None:
    tenant_id = None if mode == "local" else TENANT
    async with _harness(kind, mode=mode) as harness:
        components = await harness.engine.ingest_sbom(
            _mixed_identity_cyclonedx(),
            tenant_id=tenant_id,
        )
        coverage = await InventoryVulnerabilityCoverageProvider(
            InventoryIntelligenceEngine(harness.inventory_store),
            InMemoryVulnerabilityStore(mode=mode),
            harness.object_store,
        ).coverage(tenant_id=tenant_id)

    cpe = next(component for component in components if component.identity_kind == "cpe")
    _, payload = parse_id(cpe.object_id)
    inventory_ref = f"ast_{payload}"
    [gap] = coverage.unassessable
    assert gap.asset_ref == inventory_ref
    assert gap.reason == "no provider matches identity_kind=cpe"
    assert gap.status == "unknown"
    assert gap.unknown_cause == "provider_unconfigured"
    assert inventory_ref not in coverage.scanned
    assert inventory_ref not in coverage.unscanned


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
        await harness.engine.ingest_sbom(strong, tenant_id=TENANT)
        await harness.engine.ingest_sbom(weak, tenant_id=TENANT)
        component = await harness.store.get_component(PURL_REQUESTS, tenant_id=TENANT)
        assert component is not None
        object_record = await harness.object_store.get(component.object_id)

    assert object_record is not None
    assert object_record.confidence == 0.9
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
        assert (
            await harness.store.get_component(
                ComponentIdentity(kind="purl", value=PURL_REQUESTS),
                tenant_id=TENANT,
            )
            == replacement
        )
        cpe = await harness.store.put_component(_cpe_component())
        assert (
            await harness.store.get_component(
                ComponentIdentity(kind="cpe", value=CPE_LAUNCHER),
                tenant_id=TENANT,
            )
            == cpe
        )
        merged_cpe = await harness.store.put_component(
            _cpe_component(
                object_id=new_id("obj"),
                locations=["/synthetic/alternate/launcher"],
            )
        )
        assert merged_cpe.object_id == cpe.object_id
        assert merged_cpe.locations == [
            "/synthetic/alternate/launcher",
            "/synthetic/bin/launcher",
        ]
        with pytest.raises(SupplyChainConfigInvalid, match="identity kind or value"):
            await harness.store.put_component(
                _cpe_component(
                    cpe="cpe:2.3:a:example:other:1.0:*:*:*:*:*:*:*",
                    object_id=cpe.object_id,
                )
            )
        with pytest.raises(SupplyChainConfigInvalid, match="identity kind or value"):
            await harness.store.put_component(_cpe_component(object_id=first.object_id))

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
        unverified = list(page_one)
        while cursor is not None:
            page, cursor = await harness.store.query(
                tenant_id=TENANT,
                provenance="unverified",
                limit=1,
                cursor=cursor,
            )
            unverified.extend(page)
        assert {row.object_id for row in unverified} == {
            first.object_id,
            cpe.object_id,
            second_unverified.object_id,
        }

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


async def test_sc_migration_backfills_identity_kind() -> None:
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresSBOMStore.connect(PG_URL, mode="enterprise")
    old_object_id = new_id("obj")
    try:
        async with store._pool.acquire() as conn:
            await conn.execute("DROP TABLE aq_supplychain_component")
            await conn.execute(
                """
                CREATE TABLE aq_supplychain_component (
                    object_id text PRIMARY KEY,
                    tenant_id text NULL,
                    purl text NOT NULL CHECK (purl LIKE 'pkg:%'),
                    name text NOT NULL,
                    version text NOT NULL,
                    component_type text NOT NULL,
                    licenses jsonb NOT NULL,
                    supplier text NULL,
                    hashes jsonb NOT NULL,
                    provenance_status text NOT NULL,
                    direct boolean NOT NULL,
                    source_id text NOT NULL,
                    observed_at timestamptz NOT NULL,
                    evidence_id text NOT NULL,
                    conflicts jsonb NOT NULL DEFAULT '[]',
                    UNIQUE NULLS NOT DISTINCT (tenant_id, purl)
                )
                """
            )
            await conn.execute(
                """
                INSERT INTO aq_supplychain_component (
                    object_id, tenant_id, purl, name, version, component_type,
                    licenses, supplier, hashes, provenance_status, direct,
                    source_id, observed_at, evidence_id, conflicts
                )
                VALUES (
                    $1, $2, $3, 'requests', '2.32.4', 'library',
                    '["Apache-2.0"]'::jsonb, 'AQELYN Test', '{}'::jsonb,
                    'unverified', true, $4, $5, $6, '[]'::jsonb
                )
                """,
                old_object_id,
                TENANT,
                PURL_REQUESTS,
                new_id("src"),
                NOW,
                new_id("evd"),
            )
    finally:
        await store.close()

    migrated = await PostgresSBOMStore.connect(PG_URL, mode="enterprise")
    try:
        component = await migrated.get_component(PURL_REQUESTS, tenant_id=TENANT)
        assert component is not None
        assert component.object_id == old_object_id
        assert component.identity_kind == "purl"
        assert component.cpe is None
        assert component.locations == []

        async with migrated._pool.acquire() as conn:
            constraints = {
                str(row["conname"])
                for row in await conn.fetch(
                    """
                    SELECT conname
                    FROM pg_constraint
                    WHERE conrelid = 'aq_supplychain_component'::regclass
                    """
                )
            }
            indexes = {
                str(row["indexname"])
                for row in await conn.fetch(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE tablename = 'aq_supplychain_component'
                    """
                )
            }
            insert_identity = """
                INSERT INTO aq_supplychain_component (
                    object_id, tenant_id, identity_kind, purl, cpe, name, version,
                    component_type, locations, licenses, supplier, hashes,
                    provenance_status, direct, source_id, observed_at, evidence_id,
                    conflicts
                )
                VALUES (
                    $1, $2, $3, $4, $5, 'component', '1.0', 'library',
                    '[]'::jsonb, '[]'::jsonb, NULL, '{}'::jsonb, 'unverified',
                    false, $6, $7, $8, '[]'::jsonb
                )
            """
            await conn.execute(
                insert_identity,
                new_id("obj"),
                TENANT,
                "cpe",
                None,
                CPE_LAUNCHER,
                new_id("src"),
                NOW,
                new_id("evd"),
            )
            with pytest.raises(asyncpg.UniqueViolationError):
                await conn.execute(
                    insert_identity,
                    new_id("obj"),
                    TENANT,
                    "cpe",
                    None,
                    CPE_LAUNCHER,
                    new_id("src"),
                    NOW,
                    new_id("evd"),
                )
            await conn.execute(
                insert_identity,
                new_id("obj"),
                TENANT,
                "purl",
                "pkg:generic/component@1.0",
                CPE_LAUNCHER,
                new_id("src"),
                NOW,
                new_id("evd"),
            )
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(
                    insert_identity,
                    new_id("obj"),
                    TENANT,
                    "cpe",
                    "pkg:generic/invalid@1.0",
                    CPE_LAUNCHER,
                    new_id("src"),
                    NOW,
                    new_id("evd"),
                )
        assert "ck_supplychain_component_identity" in constraints
        assert "ck_supplychain_component_locations" in constraints
        assert {
            "uq_supplychain_component_purl",
            "uq_supplychain_component_cpe",
        } <= indexes
    finally:
        await migrated.close()
