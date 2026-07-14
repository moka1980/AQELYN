"""S5 acceptance tests for SecurityOperationsService lifecycle wiring."""

from __future__ import annotations

import importlib
import os
from typing import Any, cast

import pytest

from aqelyn.events import EventTypeRegistry
from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime, create_runtime
from aqelyn.soc import (
    SOC_EVENTS,
    InMemorySOCStore,
    PostgresSOCStore,
    SecurityOperationsEngine,
    SecurityOperationsService,
)
from aqelyn.soc.service import register_soc_events

PG_URL = os.getenv("AQELYN_DATABASE_URL")
SOC_EVENT_TYPES = (
    "aqelyn.soc.alert_raised",
    "aqelyn.soc.incident_created",
    "aqelyn.soc.incident_status_changed",
    "aqelyn.soc.response_proposed",
)


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_soc_service_health(backend: str) -> None:
    if backend == "postgres" and not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    if backend == "memory":
        runtime = create_inmemory_runtime()
        assert isinstance(runtime.soc_store, InMemorySOCStore)
    else:
        assert PG_URL is not None
        runtime = await create_runtime(AQELYNConfig(backend="postgres", database_url=PG_URL))
        assert isinstance(runtime.soc_store, PostgresSOCStore)
        soc_store = cast(Any, runtime.soc_store)
        async with soc_store._pool.acquire() as conn:
            await conn.execute("TRUNCATE aq_soc_incident, aq_soc_alert RESTART IDENTITY")

    service = runtime.kernel.get_service("soc_engine")
    assert service.name == "soc_engine"
    assert tuple(service.dependencies) == (
        "object_store",
        "knowledge_graph",
        "mission_engine",
        "workflow_engine",
        "risk_engine",
        "threat_fusion_engine",
    )
    assert isinstance(runtime.soc_engine, SecurityOperationsEngine)
    assert isinstance(runtime.soc_engine_service, SecurityOperationsService)
    assert runtime.soc_engine_service.engine is runtime.soc_engine
    assert runtime.soc_engine.store is runtime.soc_store
    assert runtime.soc_engine.evidence_store is runtime.evidence_store
    assert runtime.soc_engine.graph is runtime.knowledge_graph
    assert runtime.soc_engine.mission_engine is runtime.mission_engine
    assert runtime.soc_engine.workflow_engine is runtime.workflow_engine
    assert runtime.soc_engine.object_store is runtime.object_store
    for event_type in SOC_EVENT_TYPES:
        assert runtime.event_bus.registry.is_registered(event_type)

    pre_start = await service.health()
    assert pre_start.status == "degraded"
    assert pre_start.ready is False
    assert pre_start.dependencies["soc_store"] == "healthy"
    assert pre_start.dependencies["evidence_store"] == "healthy"
    assert pre_start.dependencies["object_store"] == "healthy"
    assert pre_start.dependencies["knowledge_graph"] == "healthy"
    assert pre_start.dependencies["mission_engine"] == "healthy"
    assert pre_start.dependencies["workflow_engine"] == "healthy"

    await runtime.kernel.start()
    try:
        state = await runtime.kernel.health()
        soc_health = state.services["soc_engine"]

        assert soc_health.status == "healthy"
        assert soc_health.ready is True
        assert soc_health.dependencies["soc_store"] == "healthy"
        assert soc_health.dependencies["evidence_store"] == "healthy"
        assert soc_health.dependencies["object_store"] == "healthy"
        assert soc_health.dependencies["knowledge_graph"] == "healthy"
        assert soc_health.dependencies["mission_engine"] == "healthy"
        assert soc_health.dependencies["workflow_engine"] == "healthy"
        assert state.services["object_store"].ready is True
        assert state.services["knowledge_graph"].ready is True
        assert state.services["mission_engine"].ready is True
        assert state.services["workflow_engine"].ready is True
        assert state.services["risk_engine"].ready is True
        assert state.services["threat_fusion_engine"].ready is True
        assert state.services["_kernel"].ready is True
    finally:
        await runtime.kernel.stop()


def test_soc_register_soc_events() -> None:
    registry = EventTypeRegistry(with_core=False)

    register_soc_events(registry)

    assert set(SOC_EVENTS) == set(SOC_EVENT_TYPES)
    for event_type in SOC_EVENT_TYPES:
        assert registry.is_registered(event_type)


def test_soc_import_isolation() -> None:
    soc = importlib.import_module("aqelyn.soc")

    assert soc.SecurityOperationsEngine is SecurityOperationsEngine
    assert soc.SecurityOperationsService is SecurityOperationsService
