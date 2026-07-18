"""Y4 acceptance tests for CSPM service, events, and runtime wiring."""

from __future__ import annotations

import importlib
import os

import pytest

from aqelyn.cspm import (
    CLOUD_EVENTS,
    ROUTE_OWNERS,
    AssetConfigCloudBaselineRouter,
    CloudPostureEngine,
    CloudPostureService,
    InMemoryCloudNormalizationStore,
    InventoryCloudOwnerRouter,
    PostgresCloudNormalizationStore,
    RouteOwner,
    SharedObjectCloudOwnerRouter,
)
from aqelyn.cspm.service import register_cloud_events
from aqelyn.events import EventTypeRegistry
from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime, create_runtime
from aqelyn.kernel.service import HealthStatus

PG_URL = os.getenv("AQELYN_DATABASE_URL")
CLOUD_EVENT_TYPES = (
    "aqelyn.cloud.resource_normalized",
    "aqelyn.cloud.resource_unclassified",
)
FORBIDDEN_CLOUD_EVENTS = (
    "aqelyn.cloud.misconfiguration_detected",
    "aqelyn.cloud.resource_deleted",
)


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_cspm_service_health(backend: str) -> None:
    if backend == "postgres" and not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    if backend == "memory":
        runtime = create_inmemory_runtime()
        assert isinstance(
            runtime.cloud_normalization_store,
            InMemoryCloudNormalizationStore,
        )
    else:
        assert PG_URL is not None
        runtime = await create_runtime(AQELYNConfig(backend="postgres", database_url=PG_URL))
        assert isinstance(
            runtime.cloud_normalization_store,
            PostgresCloudNormalizationStore,
        )

    service = runtime.kernel.get_service("cspm_engine")
    assert service.name == "cspm_engine"
    assert tuple(service.dependencies) == (
        "object_store",
        "inventory_engine",
        "acg_engine",
        "compliance_engine",
        "exposure_engine",
        "iag_engine",
        "risk_engine",
        "trust_engine",
    )
    assert isinstance(runtime.cloud_posture_engine, CloudPostureEngine)
    assert isinstance(runtime.cloud_posture_service, CloudPostureService)
    assert runtime.cloud_posture_service is service
    assert runtime.cloud_posture_service.engine is runtime.cloud_posture_engine
    assert runtime.cloud_posture_service.store is runtime.cloud_normalization_store
    assert runtime.cloud_posture_engine.store is runtime.cloud_normalization_store
    assert runtime.cloud_posture_engine.object_store is runtime.object_store
    assert runtime.cloud_posture_engine.evidence_store is runtime.evidence_store
    assert runtime.cloud_posture_engine.source_registry is runtime.trust_engine.registry
    assert isinstance(
        runtime.cloud_posture_engine.baseline_router,
        AssetConfigCloudBaselineRouter,
    )
    assert set(runtime.cloud_posture_engine.owner_routers) == ROUTE_OWNERS
    assert isinstance(
        runtime.cloud_posture_engine.owner_routers["inventory"],
        InventoryCloudOwnerRouter,
    )
    shared_owners: tuple[RouteOwner, ...] = (
        "assetconfig",
        "compliance",
        "exposure",
        "iag",
        "risk",
    )
    for owner in shared_owners:
        assert isinstance(
            runtime.cloud_posture_engine.owner_routers[owner],
            SharedObjectCloudOwnerRouter,
        )

    for event_type in CLOUD_EVENT_TYPES:
        assert runtime.event_bus.registry.is_registered(event_type)
    for event_type in FORBIDDEN_CLOUD_EVENTS:
        assert not runtime.event_bus.registry.is_registered(event_type)

    pre_start = await service.health()
    assert pre_start.status == "degraded"
    assert pre_start.ready is False
    assert pre_start.dependencies == {
        "cloud_normalization_store": "healthy",
        "object_store": "healthy",
        "evidence_store": "healthy",
        "trust_engine": "healthy",
        "acg_engine": "healthy",
        "compliance_engine": "healthy",
        "exposure_engine": "healthy",
        "iag_engine": "healthy",
        "inventory_engine": "healthy",
        "risk_engine": "healthy",
    }

    await runtime.kernel.start()
    try:
        state = await runtime.kernel.health()
        cloud_health = state.services["cspm_engine"]
        assert cloud_health.status == "healthy"
        assert cloud_health.ready is True
        for dependency in service.dependencies:
            assert state.services[dependency].ready is True
        assert state.services["_kernel"].ready is True
    finally:
        await runtime.kernel.stop()


def test_cspm_register_cloud_events_exactly_two() -> None:
    registry = EventTypeRegistry(with_core=False)

    register_cloud_events(registry)

    assert set(CLOUD_EVENTS) == set(CLOUD_EVENT_TYPES)
    assert len(CLOUD_EVENTS) == 2
    for event_type in CLOUD_EVENT_TYPES:
        assert registry.is_registered(event_type)
    for event_type in FORBIDDEN_CLOUD_EVENTS:
        assert not registry.is_registered(event_type)


async def test_cspm_health_reports_invalid_config() -> None:
    runtime = create_inmemory_runtime()
    runtime.cloud_posture_engine.config = runtime.cloud_posture_engine.config.model_copy(
        update={"batch_size": 0}
    )

    health = await runtime.cloud_posture_service.health()

    assert health.status == "unavailable"
    assert health.ready is False
    assert health.detail == "batch_size must be >= 1"


async def test_cspm_health_reports_owner_unavailable() -> None:
    class _UnavailableOwner:
        async def health(self) -> HealthStatus:
            return HealthStatus(
                status="unavailable",
                ready=False,
                detail="risk owner unavailable",
            )

    runtime = create_inmemory_runtime()
    runtime.cloud_posture_service.owner_services["risk_engine"] = _UnavailableOwner()

    health = await runtime.cloud_posture_service.health()

    assert health.status == "unavailable"
    assert health.ready is False
    assert health.detail == "risk owner unavailable"


def test_cspm_import_isolation() -> None:
    cspm = importlib.import_module("aqelyn.cspm")
    factory = importlib.import_module("aqelyn.kernel.factory")

    assert cspm.CloudPostureService is CloudPostureService
    assert hasattr(factory, "create_runtime")
