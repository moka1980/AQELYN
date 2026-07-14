"""T5 acceptance tests for ThreatFusionService lifecycle wiring."""

from __future__ import annotations

import importlib
import os
from typing import Any, cast

import pytest

from aqelyn.events import EventTypeRegistry
from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime, create_runtime
from aqelyn.threat import (
    THREAT_EVENTS,
    InMemoryThreatSourceRegistry,
    ThreatFusionEngine,
    ThreatFusionService,
)
from aqelyn.threat.postgres import PostgresThreatSourceRegistry
from aqelyn.threat.service import register_threat_events

PG_URL = os.getenv("AQELYN_DATABASE_URL")
THREAT_EVENT_TYPES = (
    "aqelyn.threat.indicator_ingested",
    "aqelyn.threat.match_detected",
    "aqelyn.threat.updated",
)


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_tif_service_health(backend: str) -> None:
    if backend == "postgres" and not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    if backend == "memory":
        runtime = create_inmemory_runtime()
        assert isinstance(runtime.threat_source_registry, InMemoryThreatSourceRegistry)
    else:
        assert PG_URL is not None
        runtime = await create_runtime(AQELYNConfig(backend="postgres", database_url=PG_URL))
        assert isinstance(runtime.threat_source_registry, PostgresThreatSourceRegistry)
        source_registry = cast(Any, runtime.threat_source_registry)
        async with source_registry._pool.acquire() as conn:
            await conn.execute("TRUNCATE aq_threat_source")

    service = runtime.kernel.get_service("threat_fusion_engine")
    assert service.name == "threat_fusion_engine"
    assert tuple(service.dependencies) == (
        "object_store",
        "knowledge_graph",
        "trust_engine",
        "mission_engine",
        "workflow_engine",
    )
    assert isinstance(runtime.threat_engine, ThreatFusionEngine)
    assert isinstance(runtime.threat_engine_service, ThreatFusionService)
    assert runtime.threat_engine_service.engine is runtime.threat_engine
    assert runtime.threat_engine.object_store is runtime.object_store
    assert runtime.threat_engine.graph is runtime.knowledge_graph
    assert runtime.threat_engine.source_registry is runtime.threat_source_registry
    assert runtime.threat_engine.evidence_store is runtime.evidence_store
    assert runtime.threat_engine.finding_store is runtime.finding_store
    assert runtime.threat_engine.mission_engine is runtime.mission_engine
    assert runtime.threat_engine.workflow_engine is runtime.workflow_engine
    for event_type in THREAT_EVENT_TYPES:
        assert runtime.event_bus.registry.is_registered(event_type)

    pre_start = await service.health()
    assert pre_start.status == "degraded"
    assert pre_start.ready is False
    assert pre_start.dependencies["object_store"] == "healthy"
    assert pre_start.dependencies["knowledge_graph"] == "healthy"
    assert pre_start.dependencies["source_registry"] == "healthy"
    assert pre_start.dependencies["trust_engine"] == "healthy"
    assert pre_start.dependencies["evidence_store"] == "healthy"
    assert pre_start.dependencies["finding_store"] == "healthy"
    assert pre_start.dependencies["mission_engine"] == "healthy"
    assert pre_start.dependencies["workflow_engine"] == "healthy"

    await runtime.kernel.start()
    try:
        state = await runtime.kernel.health()
        threat_health = state.services["threat_fusion_engine"]

        assert threat_health.status == "healthy"
        assert threat_health.ready is True
        assert threat_health.dependencies["object_store"] == "healthy"
        assert threat_health.dependencies["knowledge_graph"] == "healthy"
        assert threat_health.dependencies["source_registry"] == "healthy"
        assert threat_health.dependencies["trust_engine"] == "healthy"
        assert threat_health.dependencies["evidence_store"] == "healthy"
        assert threat_health.dependencies["finding_store"] == "healthy"
        assert threat_health.dependencies["mission_engine"] == "healthy"
        assert threat_health.dependencies["workflow_engine"] == "healthy"
        assert state.services["object_store"].ready is True
        assert state.services["knowledge_graph"].ready is True
        assert state.services["trust_engine"].ready is True
        assert state.services["mission_engine"].ready is True
        assert state.services["workflow_engine"].ready is True
        assert state.services["_kernel"].ready is True
    finally:
        await runtime.kernel.stop()


def test_tif_register_threat_events() -> None:
    registry = EventTypeRegistry(with_core=False)

    register_threat_events(registry)

    assert set(THREAT_EVENTS) == set(THREAT_EVENT_TYPES)
    for event_type in THREAT_EVENT_TYPES:
        assert registry.is_registered(event_type)


def test_tif_import_isolation() -> None:
    threat = importlib.import_module("aqelyn.threat")

    assert threat.ThreatFusionEngine is ThreatFusionEngine
    assert threat.ThreatFusionService is ThreatFusionService
