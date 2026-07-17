"""N5 acceptance tests for InventoryIntelligenceService lifecycle wiring."""

from __future__ import annotations

import importlib
import os
from typing import Any, cast

import pytest

from aqelyn.events import EventTypeRegistry
from aqelyn.inventory import (
    INVENTORY_EVENTS,
    InMemoryAssetStore,
    InventoryIntelligenceEngine,
    InventoryIntelligenceService,
    PostgresAssetStore,
)
from aqelyn.inventory.service import register_inventory_events
from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime, create_runtime

PG_URL = os.getenv("AQELYN_DATABASE_URL")
INVENTORY_EVENT_TYPES = (
    "aqelyn.inventory.asset_discovered",
    "aqelyn.inventory.asset_reconciled",
    "aqelyn.inventory.asset_unreported",
    "aqelyn.inventory.lifecycle_changed",
    "aqelyn.inventory.relationship_updated",
)


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_inv_service_health(backend: str) -> None:
    if backend == "postgres" and not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    if backend == "memory":
        runtime = create_inmemory_runtime()
        assert isinstance(runtime.inventory_store, InMemoryAssetStore)
    else:
        assert PG_URL is not None
        runtime = await create_runtime(AQELYNConfig(backend="postgres", database_url=PG_URL))
        assert isinstance(runtime.inventory_store, PostgresAssetStore)
        inventory_store = cast(Any, runtime.inventory_store)
        async with inventory_store._pool.acquire() as conn:
            await conn.execute("TRUNCATE aq_inventory_asset_history, aq_inventory_asset")

    service = runtime.kernel.get_service("inventory_engine")
    assert service.name == "inventory_engine"
    assert tuple(service.dependencies) == (
        "acg_engine",
        "object_store",
        "knowledge_graph",
        "trust_engine",
        "mission_engine",
    )
    assert isinstance(runtime.inventory_engine, InventoryIntelligenceEngine)
    assert isinstance(runtime.inventory_engine_service, InventoryIntelligenceService)
    assert runtime.inventory_engine_service is service
    assert runtime.inventory_engine_service.engine is runtime.inventory_engine
    assert runtime.inventory_engine_service.store is runtime.inventory_store
    assert runtime.inventory_engine_service.object_store is runtime.object_store
    assert runtime.inventory_engine_service.trust_engine is runtime.trust_engine
    assert runtime.inventory_engine_service.mission_engine is runtime.mission_engine
    assert runtime.inventory_engine_service.evidence_store is runtime.evidence_store
    assert runtime.inventory_engine.store is runtime.inventory_store
    assert runtime.inventory_engine.classifier is runtime.acg_engine
    assert runtime.inventory_engine.relationship_store is runtime.object_store
    assert runtime.inventory_engine.graph is runtime.knowledge_graph
    for event_type in INVENTORY_EVENT_TYPES:
        assert runtime.event_bus.registry.is_registered(event_type)

    pre_start = await service.health()
    assert pre_start.status == "degraded"
    assert pre_start.ready is False
    assert pre_start.dependencies["asset_store"] == "healthy"
    assert pre_start.dependencies["acg_engine"] == "healthy"
    assert pre_start.dependencies["object_store"] == "healthy"
    assert pre_start.dependencies["knowledge_graph"] == "healthy"
    assert pre_start.dependencies["trust_engine"] == "healthy"
    assert pre_start.dependencies["mission_engine"] == "healthy"
    assert pre_start.dependencies["evidence_store"] == "healthy"

    await runtime.kernel.start()
    try:
        state = await runtime.kernel.health()
        inventory_health = state.services["inventory_engine"]

        assert inventory_health.status == "healthy"
        assert inventory_health.ready is True
        assert inventory_health.dependencies["asset_store"] == "healthy"
        assert inventory_health.dependencies["acg_engine"] == "healthy"
        assert inventory_health.dependencies["object_store"] == "healthy"
        assert inventory_health.dependencies["knowledge_graph"] == "healthy"
        assert inventory_health.dependencies["trust_engine"] == "healthy"
        assert inventory_health.dependencies["mission_engine"] == "healthy"
        assert inventory_health.dependencies["evidence_store"] == "healthy"
        assert state.services["acg_engine"].ready is True
        assert state.services["object_store"].ready is True
        assert state.services["knowledge_graph"].ready is True
        assert state.services["trust_engine"].ready is True
        assert state.services["mission_engine"].ready is True
        assert state.services["_kernel"].ready is True
    finally:
        await runtime.kernel.stop()


def test_inv_register_inventory_events() -> None:
    registry = EventTypeRegistry(with_core=False)

    register_inventory_events(registry)

    assert set(INVENTORY_EVENTS) == set(INVENTORY_EVENT_TYPES)
    for event_type in INVENTORY_EVENT_TYPES:
        assert registry.is_registered(event_type)


def test_inv_import_isolation() -> None:
    inventory = importlib.import_module("aqelyn.inventory")
    factory = importlib.import_module("aqelyn.kernel.factory")

    assert inventory.InventoryIntelligenceService is InventoryIntelligenceService
    assert hasattr(factory, "create_runtime")
