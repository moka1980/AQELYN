"""Z4 acceptance tests for SSPM service, events, and runtime wiring."""

from __future__ import annotations

import importlib
import os
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from aqelyn.conventions import new_id
from aqelyn.events import EventTypeRegistry
from aqelyn.inventory import DiscoverySource, InventoryKnownSurfaceSource
from aqelyn.kernel import AQELYNConfig, Runtime, create_inmemory_runtime, create_runtime
from aqelyn.kernel.service import HealthStatus
from aqelyn.sspm import (
    SAAS_EVENTS,
    AssetConfigSaaSBaselineRouter,
    InMemorySaaSNormalizationStore,
    InventorySaaSOwnerRouter,
    PostgresSaaSNormalizationStore,
    SaaSIntegration,
    SaaSIntegrationKnownSurfaceSource,
    SaaSPostureEngine,
    SaaSPostureService,
    SharedObjectSaaSOwnerRouter,
    register_saas_events,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 19, 20, 0, tzinfo=UTC)
SAAS_EVENT_TYPES = (
    "aqelyn.saas.app_normalized",
    "aqelyn.saas.integration_detected",
    "aqelyn.saas.app_unclassified",
)


async def _runtime(backend: str) -> Runtime:
    config = AQELYNConfig(
        backend=backend,
        database_url=PG_URL if backend == "postgres" else None,
        sspm_type_map={"google_workspace:application": "saas_app"},
        sspm_sensitive_scopes=["files.read_all"],
    )
    if backend == "memory":
        return create_inmemory_runtime(config)
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    return await create_runtime(config)


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_sspm_service_health(backend: str) -> None:
    runtime = await _runtime(backend)
    service = runtime.kernel.get_service("sspm_engine")

    if backend == "memory":
        assert isinstance(runtime.saas_normalization_store, InMemorySaaSNormalizationStore)
    else:
        assert isinstance(runtime.saas_normalization_store, PostgresSaaSNormalizationStore)
    assert isinstance(runtime.saas_posture_engine, SaaSPostureEngine)
    assert isinstance(runtime.saas_posture_service, SaaSPostureService)
    assert runtime.saas_posture_service is service
    assert runtime.saas_posture_service.engine is runtime.saas_posture_engine
    assert runtime.saas_posture_service.store is runtime.saas_normalization_store
    assert runtime.saas_posture_engine.store is runtime.saas_normalization_store
    assert runtime.saas_posture_engine.object_store is runtime.object_store
    assert runtime.saas_posture_engine.evidence_store is runtime.evidence_store
    assert runtime.saas_posture_engine.source_registry is runtime.trust_engine.registry
    assert runtime.saas_posture_engine.integration_graph is runtime.knowledge_graph
    assert runtime.saas_posture_engine.trust_engine is runtime.trust_engine
    assert runtime.saas_posture_engine.workflow_engine is runtime.workflow_engine
    assert isinstance(runtime.saas_posture_engine.baseline_router, AssetConfigSaaSBaselineRouter)
    assert isinstance(runtime.saas_posture_engine.absence_router, InventorySaaSOwnerRouter)
    assert set(runtime.saas_posture_engine.owner_routers) == {
        "inventory",
        "assetconfig",
        "compliance",
        "iag",
    }
    assert isinstance(
        runtime.saas_posture_engine.owner_routers["inventory"],
        InventorySaaSOwnerRouter,
    )
    for owner in ("assetconfig", "compliance", "iag"):
        assert isinstance(
            runtime.saas_posture_engine.owner_routers[owner],
            SharedObjectSaaSOwnerRouter,
        )
    assert {"saas_app", "saas_unknown"}.issubset(runtime.acg_engine.config.assessable_object_types)
    assert tuple(service.dependencies) == (
        "object_store",
        "knowledge_graph",
        "inventory_engine",
        "acg_engine",
        "compliance_engine",
        "iag_engine",
        "exposure_engine",
        "risk_engine",
        "trust_engine",
        "workflow_engine",
    )
    for event_type in SAAS_EVENT_TYPES:
        assert runtime.event_bus.registry.is_registered(event_type)

    pre_start = await service.health()
    assert pre_start.status == "degraded"
    assert pre_start.ready is False
    assert pre_start.dependencies == {
        "saas_normalization_store": "healthy",
        "object_store": "healthy",
        "evidence_store": "healthy",
        "trust_engine": "healthy",
        "knowledge_graph": "healthy",
        "acg_engine": "healthy",
        "compliance_engine": "healthy",
        "exposure_engine": "healthy",
        "iag_engine": "healthy",
        "inventory_engine": "healthy",
        "risk_engine": "healthy",
        "workflow_engine": "healthy",
    }

    await runtime.kernel.start()
    try:
        state = await runtime.kernel.health()
        health = state.services["sspm_engine"]
        assert health.status == "healthy"
        assert health.ready is True
        for dependency in service.dependencies:
            assert state.services[dependency].ready is True
        assert state.services["_kernel"].ready is True
    finally:
        await runtime.kernel.stop()


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_sspm_surface_source_wired(backend: str) -> None:
    runtime = await _runtime(backend)
    if backend == "postgres":
        inventory_store = cast(Any, runtime.inventory_store)
        saas_store = cast(Any, runtime.saas_normalization_store)
        async with inventory_store._pool.acquire() as connection:
            await connection.execute("TRUNCATE aq_inventory_asset_history, aq_inventory_asset")
        async with saas_store._pool.acquire() as connection:
            await connection.execute("TRUNCATE aq_saas_normalization, aq_saas_integration")
    source = runtime.exposure_engine.source
    assert isinstance(source, SaaSIntegrationKnownSurfaceSource)
    assert isinstance(source.upstream, InventoryKnownSurfaceSource)
    assert source.store is runtime.saas_normalization_store

    await runtime.kernel.start()
    try:
        inventory_id = new_id("ast")
        await runtime.inventory_engine.ingest(
            reports=[
                {
                    "id": inventory_id,
                    "asset_type": "server",
                    "classification": "application",
                    "ref": f"cmdb:{inventory_id}",
                    "evidence_id": new_id("evd"),
                }
            ],
            source=DiscoverySource(
                source_id=new_id("src"),
                reliability=0.9,
                health="ok",
                as_of=NOW,
            ),
            tenant_id=None,
        )
        integration_id = new_id("obj")
        await runtime.saas_normalization_store.put_integration(
            SaaSIntegration(
                object_id=integration_id,
                integration_id="oauth:external-app",
                grantor_ref=new_id("obj"),
                grantor_kind="api",
                third_party_app=new_id("obj"),
                third_party_external=True,
                scopes=["files.read_all"],
                over_scoped="over_scoped",
                reach_status="computed",
                known_surface_ref=integration_id,
                claim_confidence=0.9,
                evidence_id=new_id("evd"),
                observed_at=NOW,
                reason="External grant exceeds configured scope policy.",
            )
        )

        derived = await runtime.exposure_engine.derive_surface(tenant_id=None)
        by_ref = {asset.asset_ref.ref_id: asset for asset in derived}

        assert set(by_ref) == {inventory_id, integration_id}
        assert by_ref[inventory_id].asset_ref.kind == "asset"
        assert by_ref[integration_id].asset_ref.kind == "api"
        assert by_ref[integration_id].classification == "saas_integration"
        assert by_ref[integration_id].exposure_level == "high"
        assert by_ref[integration_id].basis[0].evidence_id is not None
    finally:
        await runtime.kernel.stop()


def test_sspm_register_saas_events_exactly_three() -> None:
    registry = EventTypeRegistry(with_core=False)

    register_saas_events(registry)

    assert set(SAAS_EVENTS) == set(SAAS_EVENT_TYPES)
    assert len(SAAS_EVENTS) == 3
    for event_type in SAAS_EVENT_TYPES:
        assert registry.is_registered(event_type)


async def test_sspm_health_reports_invalid_config() -> None:
    runtime = create_inmemory_runtime()
    runtime.saas_posture_engine.config = runtime.saas_posture_engine.config.model_copy(
        update={"batch_size": 0}
    )

    health = await runtime.saas_posture_service.health()

    assert health.status == "unavailable"
    assert health.ready is False
    assert health.detail == "batch_size must be >= 1"


async def test_sspm_health_reports_owner_unavailable() -> None:
    class _UnavailableOwner:
        async def health(self) -> HealthStatus:
            return HealthStatus(
                status="unavailable",
                ready=False,
                detail="exposure owner unavailable",
            )

    runtime = create_inmemory_runtime()
    runtime.saas_posture_service.owner_services["exposure_engine"] = _UnavailableOwner()

    health = await runtime.saas_posture_service.health()

    assert health.status == "unavailable"
    assert health.ready is False
    assert health.detail == "exposure owner unavailable"


def test_sspm_import_isolation() -> None:
    sspm = importlib.import_module("aqelyn.sspm")
    factory = importlib.import_module("aqelyn.kernel.factory")

    assert sspm.SaaSPostureService is SaaSPostureService
    assert hasattr(factory, "create_runtime")
