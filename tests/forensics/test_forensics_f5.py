"""F5 acceptance tests for DigitalForensicsService lifecycle wiring."""

from __future__ import annotations

import importlib
import os
from typing import Any, cast

import pytest

from aqelyn.events import EventTypeRegistry
from aqelyn.forensics import (
    FORENSICS_EVENTS,
    DigitalForensicsService,
    InMemoryArtifactStore,
    PostgresArtifactStore,
)
from aqelyn.forensics.service import register_forensics_events
from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime, create_runtime

PG_URL = os.getenv("AQELYN_DATABASE_URL")
FORENSICS_EVENT_TYPES = (
    "aqelyn.forensics.artifact_cataloged",
    "aqelyn.forensics.evidence_verified",
    "aqelyn.forensics.case_packaged",
)


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_dfe_service_health(backend: str) -> None:
    if backend == "postgres" and not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    if backend == "memory":
        runtime = create_inmemory_runtime()
        assert isinstance(runtime.forensics_artifact_store, InMemoryArtifactStore)
    else:
        assert PG_URL is not None
        runtime = await create_runtime(AQELYNConfig(backend="postgres", database_url=PG_URL))
        assert isinstance(runtime.forensics_artifact_store, PostgresArtifactStore)
        artifact_store = cast(Any, runtime.forensics_artifact_store)
        async with artifact_store._pool.acquire() as conn:
            await conn.execute("TRUNCATE aq_forensics_artifact")

    service = runtime.kernel.get_service("forensics_engine")
    assert service.name == "forensics_engine"
    assert tuple(service.dependencies) == (
        "object_store",
        "knowledge_graph",
        "soc_engine",
    )
    assert isinstance(runtime.forensics_engine_service, DigitalForensicsService)
    assert runtime.forensics_engine_service is service
    assert runtime.forensics_engine_service.artifact_store is runtime.forensics_artifact_store
    assert runtime.forensics_engine_service.evidence_store is runtime.evidence_store
    assert runtime.forensics_engine_service.blob_store is runtime.blob_store
    assert runtime.forensics_engine_service.object_store is runtime.object_store
    assert runtime.forensics_engine_service.graph is runtime.knowledge_graph
    assert runtime.forensics_engine_service.finding_store is runtime.finding_store
    for event_type in FORENSICS_EVENT_TYPES:
        assert runtime.event_bus.registry.is_registered(event_type)

    pre_start = await service.health()
    assert pre_start.status == "degraded"
    assert pre_start.ready is False
    assert pre_start.dependencies["artifact_store"] == "healthy"
    assert pre_start.dependencies["evidence_store"] == "healthy"
    assert pre_start.dependencies["object_store"] == "healthy"
    assert pre_start.dependencies["knowledge_graph"] == "healthy"
    assert pre_start.dependencies["finding_store"] == "healthy"

    await runtime.kernel.start()
    try:
        state = await runtime.kernel.health()
        forensics_health = state.services["forensics_engine"]

        assert forensics_health.status == "healthy"
        assert forensics_health.ready is True
        assert forensics_health.dependencies["artifact_store"] == "healthy"
        assert forensics_health.dependencies["evidence_store"] == "healthy"
        assert forensics_health.dependencies["object_store"] == "healthy"
        assert forensics_health.dependencies["knowledge_graph"] == "healthy"
        assert forensics_health.dependencies["finding_store"] == "healthy"
        assert state.services["object_store"].ready is True
        assert state.services["knowledge_graph"].ready is True
        assert state.services["soc_engine"].ready is True
        assert state.services["_kernel"].ready is True
    finally:
        await runtime.kernel.stop()


def test_dfe_register_forensics_events() -> None:
    registry = EventTypeRegistry(with_core=False)

    register_forensics_events(registry)

    assert set(FORENSICS_EVENTS) == set(FORENSICS_EVENT_TYPES)
    for event_type in FORENSICS_EVENT_TYPES:
        assert registry.is_registered(event_type)


def test_dfe_import_isolation() -> None:
    forensics = importlib.import_module("aqelyn.forensics")

    assert forensics.DigitalForensicsService is DigitalForensicsService
