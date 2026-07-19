"""Z3 acceptance tests for SaaS integration risk and owner delegation."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, cast

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import (
    CrossTenantReference,
    IntegrationNotFound,
    StoreUnavailable,
)
from aqelyn.evidence import InMemoryEvidenceStore
from aqelyn.exposure import (
    AssetRef,
    ExposureBasis,
    KnownSurfaceRecord,
    StaticKnownSurfaceSource,
)
from aqelyn.graph import InMemoryKnowledgeGraph, NodeView, Subgraph
from aqelyn.inventory import InMemoryAssetStore, InventoryIntelligenceEngine
from aqelyn.objects import AQObject, AQRelationship, InMemoryObjectStore, SourceRef
from aqelyn.sspm import (
    InMemorySaaSNormalizationStore,
    IntegrationDescriptor,
    IntegrationGraph,
    InventorySaaSOwnerRouter,
    NormalizedSaaSObject,
    OverScopedStatus,
    PostgresSaaSNormalizationStore,
    SaaSAbsenceRouter,
    SaaSAppDescriptor,
    SaaSBaselineRouter,
    SaaSConfig,
    SaaSIntegration,
    SaaSIntegrationKnownSurfaceSource,
    SaaSNormalizationStore,
    SaaSOwnerRouter,
    SaaSPostureEngine,
    SharedObjectSaaSOwnerRouter,
    saas_asset_id,
)
from aqelyn.sspm.engine import WorkflowProposer
from aqelyn.trust import (
    InMemorySourceReliabilityRegistry,
    SourceReliability,
    TrustEngine,
)
from aqelyn.workflow import Playbook, Run

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 19, 18, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000290301"
OTHER_TENANT = "018f0000-0000-7000-8000-000000290302"
ACTOR = ActorRef(actor_type="system", actor_id="sspm-z3-test")


class _Closable(Protocol):
    async def close(self) -> None: ...


@dataclass
class _Harness:
    store: SaaSNormalizationStore
    object_store: InMemoryObjectStore
    evidence_store: InMemoryEvidenceStore
    registry: InMemorySourceReliabilityRegistry
    engine: SaaSPostureEngine


@dataclass
class _GraphStub:
    result: Subgraph
    calls: list[tuple[str, int]] = field(default_factory=list)
    error: Exception | None = None

    async def subgraph(
        self,
        start_id: str,
        *,
        direction: str = "both",
        relation_types: Sequence[str] | None = None,
        max_depth: int = 6,
        max_nodes: int = 10_000,
    ) -> Subgraph:
        del direction, relation_types, max_depth
        self.calls.append((start_id, max_nodes))
        if self.error is not None:
            raise self.error
        return self.result.model_copy(deep=True)


@dataclass
class _BaselineSpy:
    result: str = field(default_factory=lambda: new_id("snap"))
    calls: list[tuple[tuple[str, ...], str | None, Mapping[str, object] | None]] = field(
        default_factory=list
    )

    async def apply(
        self,
        baseline_ids: Sequence[str],
        *,
        tenant_id: str | None,
        scope: Mapping[str, object] | None = None,
    ) -> str:
        self.calls.append((tuple(baseline_ids), tenant_id, scope))
        return self.result


@dataclass
class _AbsenceSpy:
    calls: list[tuple[str, str | None]] = field(default_factory=list)

    async def mark_unreported(
        self,
        obj: NormalizedSaaSObject,
        *,
        tenant_id: str | None,
    ) -> str:
        object_id = obj.object_id
        self.calls.append((object_id, tenant_id))
        return saas_asset_id(object_id)


@dataclass
class _WorkflowSpy:
    calls: list[tuple[Playbook, ActorRef]] = field(default_factory=list)

    async def propose(self, playbook: Playbook, *, by: ActorRef) -> Run:
        self.calls.append((playbook.model_copy(deep=True), by))
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


class _OneRowIntegrationStore:
    def __init__(self, store: SaaSNormalizationStore) -> None:
        self.store = store
        self.reads = 0

    async def query_integrations(
        self,
        *,
        tenant_id: str | None,
        over_scoped: OverScopedStatus | None = None,
        limit: int = 1000,
        cursor: str | None = None,
    ) -> tuple[list[SaaSIntegration], str | None]:
        self.reads += 1
        return await self.store.query_integrations(
            tenant_id=tenant_id,
            over_scoped=over_scoped,
            limit=min(limit, 1),
            cursor=cursor,
        )


@dataclass
class _RepeatingCursorStore:
    cursor: str = field(default_factory=lambda: new_id("obj"))
    reads: int = 0

    async def query_integrations(
        self,
        *,
        tenant_id: str | None,
        over_scoped: OverScopedStatus | None = None,
        limit: int = 1000,
        cursor: str | None = None,
    ) -> tuple[list[SaaSIntegration], str | None]:
        del tenant_id, over_scoped, limit, cursor
        self.reads += 1
        return [], self.cursor


def _config() -> SaaSConfig:
    return SaaSConfig.model_validate(
        {
            "type_map": {"google_workspace:application": "saas_app"},
            "baseline_ids": ["saas-baseline-v1"],
            "sensitive_scopes": ["files.read_all", "mail.send"],
            "batch_size": 20,
            "integration_max_nodes": 7,
        },
        context={
            "known_object_types": {"saas_app"},
            "known_baseline_ids": {"saas-baseline-v1"},
        },
    )


@asynccontextmanager
async def _harness(
    kind: str,
    *,
    graph: IntegrationGraph | None = None,
    baseline_router: SaaSBaselineRouter | None = None,
    workflow: WorkflowProposer | None = None,
    absence_router: SaaSAbsenceRouter | None = None,
    owner_routers: Sequence[SaaSOwnerRouter] = (),
) -> AsyncIterator[_Harness]:
    closer: _Closable | None = None
    if kind == "inmemory":
        store: SaaSNormalizationStore = InMemorySaaSNormalizationStore(mode="enterprise")
    else:
        if not PG_URL:
            pytest.skip("AQELYN_DATABASE_URL not set")
        postgres = await PostgresSaaSNormalizationStore.connect(PG_URL, mode="enterprise")
        async with postgres._pool.acquire() as conn:
            await conn.execute("TRUNCATE aq_saas_normalization, aq_saas_integration")
        store = postgres
        closer = cast(_Closable, postgres)
    object_store = InMemoryObjectStore(mode="enterprise")
    evidence_store = InMemoryEvidenceStore(mode="enterprise")
    registry = InMemorySourceReliabilityRegistry(default_reliability=0.5)
    trust = TrustEngine(registry=registry)
    engine = SaaSPostureEngine(
        store,
        object_store=object_store,
        evidence_store=evidence_store,
        source_registry=registry,
        config=_config(),
        owner_routers=owner_routers,
        integration_graph=graph,
        trust_engine=trust,
        baseline_router=baseline_router,
        workflow_engine=workflow,
        absence_router=absence_router,
        actor=ACTOR,
    )
    try:
        yield _Harness(store, object_store, evidence_store, registry, engine)
    finally:
        if closer is not None:
            await closer.close()


async def _put_object(
    store: InMemoryObjectStore,
    *,
    object_id: str | None = None,
    tenant_id: str | None = TENANT,
    display_name: str = "fixture",
) -> AQObject:
    source_id = new_id("src")
    return await store.upsert(
        AQObject(
            id=object_id or new_id("obj"),
            object_type="generic",
            schema_version=1,
            tenant_id=tenant_id,
            display_name=display_name,
            attributes={},
            labels={},
            natural_keys=[],
            sources=[
                SourceRef(
                    source_id=source_id,
                    observed_at=NOW,
                    method="sspm.test/v1",
                )
            ],
            first_seen_at=NOW,
            last_seen_at=NOW,
            created_at=NOW,
            updated_at=NOW,
            created_by=ACTOR,
            updated_by=ACTOR,
        )
    )


async def _relate(
    store: InMemoryObjectStore,
    from_id: str,
    to_id: str,
) -> None:
    now = NOW
    await store.relate(
        AQRelationship(
            id="",
            tenant_id=TENANT,
            from_id=from_id,
            to_id=to_id,
            relation_type="accesses",
            created_at=now,
            updated_at=now,
            created_by=ACTOR,
            updated_by=ACTOR,
        )
    )


def _descriptor(
    grantor: AQObject,
    third_party: AQObject,
    *,
    source_id: str,
    integration_id: str = "oauth:calendar-helper",
    scopes: Sequence[str] = ("files.read_all",),
    raw: Mapping[str, object] | None = None,
) -> IntegrationDescriptor:
    return IntegrationDescriptor(
        integration_id=integration_id,
        grantor_ref=grantor.id,
        grantor_kind="api",
        third_party_app=third_party.id,
        third_party_external=True,
        scopes=list(scopes),
        granted_by="admin@example.com",
        granted_at=NOW,
        observed_at=NOW,
        raw=dict(raw or {"vendor_rating": 99, "grant": "reported"}),
        source_id=source_id,
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
            rationale="Z3 source reliability fixture.",
            set_by=ACTOR,
            set_at=NOW,
            version=1,
        )
    )


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_sspm_integration_graph(kind: str) -> None:
    async with _harness(kind) as harness:
        harness.engine.integration_graph = InMemoryKnowledgeGraph(harness.object_store)
        grantor = await _put_object(harness.object_store, display_name="API grantor")
        third_party = await _put_object(harness.object_store, display_name="External app")
        reached = await _put_object(harness.object_store, display_name="Customer data")
        await _relate(harness.object_store, third_party.id, reached.id)
        source_id = new_id("src")
        await _set_reliability(harness.registry, source_id, 0.9)

        integration = (
            await harness.engine.map_integration(
                [_descriptor(grantor, third_party, source_id=source_id)],
                tenant_id=TENANT,
            )
        )[0]

        assert integration.over_scoped == "over_scoped"
        assert integration.reach_status == "computed"
        assert integration.reachable_object_ids == sorted([grantor.id, reached.id])
        assert integration.claim_confidence == pytest.approx(0.9)
        assert integration.known_surface_ref == integration.object_id
        assert (
            await harness.store.get_integration(integration.object_id, tenant_id=TENANT)
            == integration
        )
        edges = await harness.object_store.relationships(
            grantor.id,
            direction="out",
            relation_type="grants",
        )
        assert len(edges) == 1
        assert edges[0].to_id == third_party.id
        assert edges[0].attributes["integration_object_id"] == integration.object_id
        assert edges[0].attributes["scopes"] == ["files.read_all"]


async def test_sspm_blast_radius_truncated() -> None:
    reached_id = new_id("obj")
    graph = _GraphStub(
        Subgraph(
            nodes=[
                NodeView(
                    id=reached_id,
                    object_type="generic",
                    display_name="Reached",
                    tenant_id=TENANT,
                )
            ],
            truncated=True,
        )
    )
    async with _harness("inmemory", graph=graph) as harness:
        grantor = await _put_object(harness.object_store)
        third_party = await _put_object(harness.object_store)
        source_id = new_id("src")
        truncated = (
            await harness.engine.map_integration(
                [_descriptor(grantor, third_party, source_id=source_id)],
                tenant_id=TENANT,
            )
        )[0]
        assert truncated.reach_status == "truncated"
        assert truncated.reachable_object_ids == [reached_id]
        assert graph.calls == [(third_party.id, 7)]

    pending_graph = _GraphStub(
        Subgraph(
            nodes=[
                NodeView(
                    id=third_party.id,
                    object_type="generic",
                    display_name="Start only",
                    tenant_id=TENANT,
                )
            ],
            truncated=True,
        )
    )
    async with _harness("inmemory", graph=pending_graph) as harness:
        grantor = await _put_object(harness.object_store)
        third_party = await _put_object(harness.object_store)
        pending_graph.result.nodes[0].id = third_party.id
        pending = (
            await harness.engine.map_integration(
                [_descriptor(grantor, third_party, source_id=new_id("src"))],
                tenant_id=TENANT,
            )
        )[0]
        assert pending.reach_status == "pending"
        assert pending.reachable_object_ids == []


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_sspm_grant_is_known_surface(kind: str) -> None:
    async with _harness(kind) as harness:
        graph = InMemoryKnowledgeGraph(harness.object_store)
        harness.engine.integration_graph = graph
        grantor = await _put_object(harness.object_store)
        third_party = await _put_object(harness.object_store)
        source_id = new_id("src")
        first = (
            await harness.engine.map_integration(
                [_descriptor(grantor, third_party, source_id=source_id)],
                tenant_id=TENANT,
            )
        )[0]
        second = (
            await harness.engine.map_integration(
                [
                    _descriptor(
                        grantor,
                        third_party,
                        source_id=source_id,
                        integration_id="oauth:second-app",
                    )
                ],
                tenant_id=TENANT,
            )
        )[0]
        preserved_ref = new_id("obj")
        upstream = StaticKnownSurfaceSource(
            [
                KnownSurfaceRecord(
                    asset_ref=AssetRef(kind="api", ref_id=first.object_id),
                    classification="placeholder",
                    basis=[ExposureBasis(kind="inventory", ref="placeholder", as_of=NOW)],
                ),
                KnownSurfaceRecord(
                    asset_ref=AssetRef(kind="asset", ref_id=preserved_ref),
                    classification="inventory_asset",
                    basis=[ExposureBasis(kind="inventory", ref="inventory", as_of=NOW)],
                ),
            ]
        )
        paged = _OneRowIntegrationStore(harness.store)
        source = SaaSIntegrationKnownSurfaceSource(
            upstream,
            cast(SaaSNormalizationStore, paged),
        )

        rows = list(await source.list_known_surface(tenant_id=TENANT))
        by_ref = {row.asset_ref.ref_id: row for row in rows}
        assert set(by_ref) == {first.object_id, second.object_id, preserved_ref}
        assert by_ref[first.object_id].classification == "saas_integration"
        assert by_ref[first.object_id].asset_ref.kind == "api"
        assert by_ref[first.object_id].reachability == "external"
        assert by_ref[first.object_id].basis[0].kind == "access"
        assert by_ref[first.object_id].basis[0].evidence_id == first.evidence_id
        assert paged.reads == 2


async def test_sspm_known_surface_rejects_repeated_cursor() -> None:
    store = _RepeatingCursorStore()
    source = SaaSIntegrationKnownSurfaceSource(
        StaticKnownSurfaceSource([]),
        cast(SaaSNormalizationStore, store),
    )

    with pytest.raises(StoreUnavailable, match="repeated pagination cursor"):
        await source.list_known_surface(tenant_id=TENANT)

    assert store.reads == 2


async def test_sspm_claim_confidence_not_vendor_score() -> None:
    async with _harness("inmemory") as harness:
        harness.engine.integration_graph = InMemoryKnowledgeGraph(harness.object_store)
        grantor = await _put_object(harness.object_store)
        third_party = await _put_object(harness.object_store)
        source_id = new_id("src")
        await _set_reliability(harness.registry, source_id, 0.73)
        integrations = await harness.engine.map_integration(
            [
                _descriptor(
                    grantor,
                    third_party,
                    source_id=source_id,
                    integration_id="oauth:high-vendor-rating",
                    raw={"vendor_score": 100},
                ),
                _descriptor(
                    grantor,
                    third_party,
                    source_id=source_id,
                    integration_id="oauth:low-vendor-rating",
                    raw={"vendor_score": 0},
                ),
            ],
            tenant_id=TENANT,
        )
        assert [item.claim_confidence for item in integrations] == pytest.approx([0.73, 0.73])


async def test_sspm_delegations() -> None:
    baseline = _BaselineSpy()
    async with _harness("inmemory", baseline_router=baseline) as harness:
        snapshot_id = await harness.engine.apply_saas_baselines(
            tenant_id=TENANT,
            scope={"object_type": "saas_app"},
        )
        assert snapshot_id == baseline.result
        assert baseline.calls == [(("saas-baseline-v1",), TENANT, {"object_type": "saas_app"})]


async def test_sspm_absence_not_removal() -> None:
    absence = _AbsenceSpy()
    async with _harness("inmemory", absence_router=absence) as harness:
        app = (
            await harness.engine.normalize(
                [
                    SaaSAppDescriptor(
                        provider="google_workspace",
                        tenant="example.com",
                        app_id="calendar-helper",
                        app_name="Calendar Helper",
                        resource_type="application",
                        raw={"mfa_enabled": True},
                        observed_at=NOW,
                        source_id=new_id("src"),
                    )
                ],
                tenant_id=TENANT,
            )
        )[0]
        asset_id = await harness.engine.mark_app_unreported(
            app.object_id,
            tenant_id=TENANT,
        )
        assert absence.calls == [(app.object_id, TENANT)]
        assert asset_id == saas_asset_id(app.object_id)
        assert not hasattr(absence, "decommission")


async def test_sspm_revoke_gated() -> None:
    workflow = _WorkflowSpy()
    async with _harness("inmemory", workflow=workflow) as harness:
        harness.engine.integration_graph = InMemoryKnowledgeGraph(harness.object_store)
        grantor = await _put_object(harness.object_store)
        third_party = await _put_object(harness.object_store)
        integration = (
            await harness.engine.map_integration(
                [_descriptor(grantor, third_party, source_id=new_id("src"))],
                tenant_id=TENANT,
            )
        )[0]

        run = await harness.engine.propose_revocation(
            integration.object_id,
            tenant_id=TENANT,
            by=ACTOR,
            reason="The grant is no longer required.",
        )

        assert run.status == "proposed"
        assert len(workflow.calls) == 1
        playbook, actor = workflow.calls[0]
        assert actor == ACTOR
        assert playbook.steps[0].action_type == "saas.integration.revoke"
        assert playbook.steps[0].requires_approval is True
        assert not hasattr(workflow, "execute")
        assert not hasattr(harness.engine, "execute")


async def test_sspm_all_delegations() -> None:
    async with _harness("inmemory") as harness:
        asset_store = InMemoryAssetStore(mode="enterprise")
        inventory = InventoryIntelligenceEngine(asset_store)
        inventory_router = InventorySaaSOwnerRouter(
            inventory,
            evidence_store=harness.evidence_store,
            source_registry=harness.registry,
            actor=ACTOR,
        )
        harness.engine.owner_routers = {
            "inventory": inventory_router,
            "assetconfig": SharedObjectSaaSOwnerRouter("assetconfig", harness.object_store),
            "compliance": SharedObjectSaaSOwnerRouter("compliance", harness.object_store),
            "iag": SharedObjectSaaSOwnerRouter("iag", harness.object_store),
        }
        app = (
            await harness.engine.normalize(
                [
                    SaaSAppDescriptor(
                        provider="google_workspace",
                        tenant="example.com",
                        app_id="delegated-app",
                        app_name="Delegated App",
                        resource_type="application",
                        raw={"mfa_enabled": True},
                        observed_at=NOW,
                        source_id=new_id("src"),
                    )
                ],
                tenant_id=TENANT,
            )
        )[0]
        routed = (await harness.engine.route([app.object_id], tenant_id=TENANT))[0]
        assert routed.routed_to == ["inventory", "assetconfig", "compliance", "iag"]
        assert routed.routing_pending == []
        assert await asset_store.get(saas_asset_id(app.object_id), tenant_id=TENANT) is not None


async def test_sspm_tenant_isolation() -> None:
    async with _harness("inmemory") as harness:
        harness.engine.integration_graph = InMemoryKnowledgeGraph(harness.object_store)
        grantor = await _put_object(harness.object_store, tenant_id=TENANT)
        third_party = await _put_object(harness.object_store, tenant_id=TENANT)
        other_party = await _put_object(harness.object_store, tenant_id=OTHER_TENANT)
        with pytest.raises(CrossTenantReference, match="tenant scope"):
            await harness.engine.map_integration(
                [_descriptor(grantor, other_party, source_id=new_id("src"))],
                tenant_id=TENANT,
            )
        integration = (
            await harness.engine.map_integration(
                [_descriptor(grantor, third_party, source_id=new_id("src"))],
                tenant_id=TENANT,
            )
        )[0]
        with pytest.raises(IntegrationNotFound):
            await harness.engine.integration_blast_radius(
                integration.object_id,
                tenant_id=OTHER_TENANT,
            )


def test_sspm_no_side_effects() -> None:
    engine_surface = set(dir(SaaSPostureEngine))
    assert not ({"decommission", "patch", "execute"} & engine_surface)
