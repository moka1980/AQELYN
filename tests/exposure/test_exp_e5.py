"""E5 acceptance tests for ExposureManagementService lifecycle wiring."""

from __future__ import annotations

import importlib
import os

import pytest

from aqelyn.dspm import (
    DataStoreKnownSurfaceSource,
    InMemoryDSPMStore,
    PostgresDSPMStore,
)
from aqelyn.events import EventTypeRegistry
from aqelyn.exposure import (
    EXPOSURE_EVENTS,
    ExposureManagementService,
    InMemoryExposureStore,
    KnownDataExposureEngine,
    PostgresExposureStore,
)
from aqelyn.exposure.service import register_exposure_events
from aqelyn.inventory import InventoryKnownSurfaceSource
from aqelyn.ispm import IdentityKnownSurfaceSource
from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime, create_runtime
from aqelyn.secrets import CryptoKnownSurfaceSource
from aqelyn.sspm import SaaSIntegrationKnownSurfaceSource

PG_URL = os.getenv("AQELYN_DATABASE_URL")
EXPOSURE_EVENT_TYPES = (
    "aqelyn.exposure.asset_discovered",
    "aqelyn.exposure.detected",
    "aqelyn.exposure.attack_surface_updated",
    "aqelyn.exposure.score_updated",
    "aqelyn.exposure.closed",
)


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_exp_service_health(backend: str) -> None:
    if backend == "postgres" and not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    if backend == "memory":
        runtime = create_inmemory_runtime()
        assert isinstance(runtime.exposure_store, InMemoryExposureStore)
        assert isinstance(runtime.dspm_store, InMemoryDSPMStore)
    else:
        assert PG_URL is not None
        runtime = await create_runtime(AQELYNConfig(backend="postgres", database_url=PG_URL))
        assert isinstance(runtime.exposure_store, PostgresExposureStore)
        assert isinstance(runtime.dspm_store, PostgresDSPMStore)

    service = runtime.kernel.get_service("exposure_engine")
    assert service.name == "exposure_engine"
    assert tuple(service.dependencies) == (
        "inventory_engine",
        "acg_engine",
        "knowledge_graph",
        "iag_engine",
        "mission_engine",
        "trust_engine",
        "risk_engine",
        "forecast_engine",
    )
    assert isinstance(runtime.exposure_engine, KnownDataExposureEngine)
    assert isinstance(runtime.exposure_engine_service, ExposureManagementService)
    assert runtime.exposure_engine_service is service
    assert runtime.exposure_engine_service.engine is runtime.exposure_engine
    assert runtime.exposure_engine_service.store is runtime.exposure_store
    assert runtime.exposure_engine.store is runtime.exposure_store
    identity_source = runtime.exposure_engine.source
    assert isinstance(identity_source, IdentityKnownSurfaceSource)
    crypto_source = identity_source.upstream
    assert isinstance(crypto_source, CryptoKnownSurfaceSource)
    assert isinstance(crypto_source.upstream, SaaSIntegrationKnownSurfaceSource)
    assert isinstance(crypto_source.upstream.upstream, DataStoreKnownSurfaceSource)
    assert crypto_source.upstream.upstream.store is runtime.dspm_store
    assert isinstance(
        crypto_source.upstream.upstream.upstream,
        InventoryKnownSurfaceSource,
    )
    assert crypto_source.upstream.upstream.upstream.inventory is runtime.inventory_engine
    assert runtime.exposure_engine.graph is runtime.knowledge_graph
    assert runtime.exposure_engine.identity_provider is runtime.iag_engine
    assert runtime.exposure_engine.trend_provider is runtime.forecast_engine
    assert runtime.exposure_engine.evidence_lookup is runtime.evidence_store
    assert runtime.exposure_engine.trust_provider is runtime.trust_engine
    assert runtime.exposure_engine.mission_provider is runtime.mission_engine
    assert runtime.exposure_engine.finding_store is runtime.finding_store
    assert runtime.exposure_engine_service.risk_engine is runtime.risk_engine
    for event_type in EXPOSURE_EVENT_TYPES:
        assert runtime.event_bus.registry.is_registered(event_type)

    pre_start = await service.health()
    assert pre_start.status == "degraded"
    assert pre_start.ready is False
    assert pre_start.dependencies["exposure_store"] == "healthy"
    assert pre_start.dependencies["known_surface_source"] == "healthy"
    assert pre_start.dependencies["knowledge_graph"] == "healthy"
    assert pre_start.dependencies["iag_engine"] == "healthy"
    assert pre_start.dependencies["forecast_engine"] == "healthy"
    assert pre_start.dependencies["evidence_store"] == "healthy"
    assert pre_start.dependencies["trust_engine"] == "healthy"
    assert pre_start.dependencies["mission_engine"] == "healthy"
    assert pre_start.dependencies["finding_store"] == "healthy"
    assert pre_start.dependencies["risk_engine"] == "healthy"

    await runtime.kernel.start()
    try:
        state = await runtime.kernel.health()
        exposure_health = state.services["exposure_engine"]

        assert exposure_health.status == "healthy"
        assert exposure_health.ready is True
        assert exposure_health.dependencies["exposure_store"] == "healthy"
        assert exposure_health.dependencies["known_surface_source"] == "healthy"
        assert exposure_health.dependencies["knowledge_graph"] == "healthy"
        assert exposure_health.dependencies["iag_engine"] == "healthy"
        assert exposure_health.dependencies["forecast_engine"] == "healthy"
        assert exposure_health.dependencies["evidence_store"] == "healthy"
        assert exposure_health.dependencies["trust_engine"] == "healthy"
        assert exposure_health.dependencies["mission_engine"] == "healthy"
        assert exposure_health.dependencies["finding_store"] == "healthy"
        assert exposure_health.dependencies["risk_engine"] == "healthy"
        assert state.services["acg_engine"].ready is True
        assert state.services["knowledge_graph"].ready is True
        assert state.services["iag_engine"].ready is True
        assert state.services["mission_engine"].ready is True
        assert state.services["trust_engine"].ready is True
        assert state.services["risk_engine"].ready is True
        assert state.services["forecast_engine"].ready is True
        assert state.services["_kernel"].ready is True
    finally:
        await runtime.kernel.stop()


def test_exp_register_exposure_events() -> None:
    registry = EventTypeRegistry(with_core=False)

    register_exposure_events(registry)

    assert set(EXPOSURE_EVENTS) == set(EXPOSURE_EVENT_TYPES)
    for event_type in EXPOSURE_EVENT_TYPES:
        assert registry.is_registered(event_type)


def test_exp_import_isolation() -> None:
    exposure = importlib.import_module("aqelyn.exposure")
    factory = importlib.import_module("aqelyn.kernel.factory")

    assert exposure.ExposureManagementService is ExposureManagementService
    assert hasattr(factory, "create_runtime")
