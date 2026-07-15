"""L5 acceptance tests for DataLakeService lifecycle wiring."""

from __future__ import annotations

import importlib
import os
from typing import Any, cast

import pytest

from aqelyn.events import EventTypeRegistry
from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime, create_runtime
from aqelyn.lake import (
    LAKE_EVENTS,
    DataLakeService,
    InMemoryDatasetCatalog,
    InMemoryTelemetryRecordStore,
    PostgresDatasetCatalog,
    PostgresTelemetryRecordStore,
    RetentionEngine,
)
from aqelyn.lake.service import register_lake_events

PG_URL = os.getenv("AQELYN_DATABASE_URL")
LAKE_EVENT_TYPES = (
    "aqelyn.telemetry.ingested",
    "aqelyn.telemetry.quarantined",
    "aqelyn.lake.retention_applied",
    "aqelyn.lake.archived",
)


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_lake_service_health(backend: str) -> None:
    if backend == "postgres" and not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    if backend == "memory":
        runtime = create_inmemory_runtime()
        assert isinstance(runtime.lake_catalog, InMemoryDatasetCatalog)
        assert isinstance(runtime.lake_record_store, InMemoryTelemetryRecordStore)
    else:
        assert PG_URL is not None
        runtime = await create_runtime(AQELYNConfig(backend="postgres", database_url=PG_URL))
        assert isinstance(runtime.lake_catalog, PostgresDatasetCatalog)
        assert isinstance(runtime.lake_record_store, PostgresTelemetryRecordStore)
        record_store = cast(Any, runtime.lake_record_store)
        async with record_store._pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE aq_lake_archive, aq_lake_quarantine, aq_lake_record, aq_lake_dataset"
            )

    service = runtime.kernel.get_service("datalake_engine")
    assert service.name == "datalake_engine"
    assert tuple(service.dependencies) == (
        "event_bus",
        "policy_engine",
        "workflow_engine",
    )
    assert isinstance(runtime.lake_service, DataLakeService)
    assert isinstance(runtime.lake_retention_engine, RetentionEngine)
    assert runtime.lake_service is service
    assert runtime.lake_service.catalog is runtime.lake_catalog
    assert runtime.lake_service.record_store is runtime.lake_record_store
    assert runtime.lake_service.retention_engine is runtime.lake_retention_engine
    assert runtime.lake_service.blob_store is runtime.blob_store
    assert runtime.lake_service.audit_store is runtime.evidence_store
    assert runtime.lake_service.policy_authorizer is runtime.policy_engine_service
    assert runtime.lake_service.workflow_engine is runtime.workflow_engine
    for event_type in LAKE_EVENT_TYPES:
        assert runtime.event_bus.registry.is_registered(event_type)

    pre_start = await service.health()
    assert pre_start.status == "degraded"
    assert pre_start.ready is False
    assert pre_start.dependencies["catalog"] == "healthy"
    assert pre_start.dependencies["record_store"] == "healthy"
    assert pre_start.dependencies["blob_store"] == "healthy"
    assert pre_start.dependencies["audit_store"] == "healthy"
    assert pre_start.dependencies["retention_engine"] == "healthy"
    assert pre_start.dependencies["policy_engine"] == "healthy"
    assert pre_start.dependencies["workflow_engine"] == "healthy"

    await runtime.kernel.start()
    try:
        state = await runtime.kernel.health()
        lake_health = state.services["datalake_engine"]

        assert lake_health.status == "healthy"
        assert lake_health.ready is True
        assert lake_health.dependencies["catalog"] == "healthy"
        assert lake_health.dependencies["record_store"] == "healthy"
        assert lake_health.dependencies["blob_store"] == "healthy"
        assert lake_health.dependencies["audit_store"] == "healthy"
        assert lake_health.dependencies["retention_engine"] == "healthy"
        assert lake_health.dependencies["policy_engine"] == "healthy"
        assert lake_health.dependencies["workflow_engine"] == "healthy"
        assert state.services["policy_engine"].ready is True
        assert state.services["workflow_engine"].ready is True
        assert state.services["_kernel"].ready is True
    finally:
        await runtime.kernel.stop()


def test_lake_register_lake_events() -> None:
    registry = EventTypeRegistry(with_core=False)

    register_lake_events(registry)

    assert set(LAKE_EVENTS) == set(LAKE_EVENT_TYPES)
    for event_type in LAKE_EVENT_TYPES:
        assert registry.is_registered(event_type)


def test_lake_import_isolation() -> None:
    lake = importlib.import_module("aqelyn.lake")
    factory = importlib.import_module("aqelyn.kernel.factory")

    assert lake.DataLakeService is DataLakeService
    assert hasattr(factory, "create_runtime")
