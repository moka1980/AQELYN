"""A5 acceptance tests for AssetConfigGovernanceService lifecycle wiring."""

from __future__ import annotations

import os
from typing import Any, cast

import pytest

from aqelyn.assetconfig import (
    AssetConfigAnalyzer,
    AssetConfigGovernanceService,
    InMemoryBaselineStore,
    InMemoryDriftSnapshotStore,
    PostgresBaselineStore,
    PostgresDriftSnapshotStore,
)
from aqelyn.assetconfig.service import register_acg_events
from aqelyn.events import EventTypeRegistry
from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime, create_runtime

PG_URL = os.getenv("AQELYN_DATABASE_URL")
ACG_EVENT_TYPES = (
    "aqelyn.config.drift_detected",
    "aqelyn.config.assessment_completed",
)


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_acg_service_health(backend: str) -> None:
    if backend == "postgres" and not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    if backend == "memory":
        runtime = create_inmemory_runtime()
        assert isinstance(runtime.acg_baseline_store, InMemoryBaselineStore)
        assert isinstance(runtime.acg_snapshot_store, InMemoryDriftSnapshotStore)
    else:
        assert PG_URL is not None
        runtime = await create_runtime(AQELYNConfig(backend="postgres", database_url=PG_URL))
        assert isinstance(runtime.acg_baseline_store, PostgresBaselineStore)
        assert isinstance(runtime.acg_snapshot_store, PostgresDriftSnapshotStore)
        baseline_store = cast(Any, runtime.acg_baseline_store)
        async with baseline_store._pool.acquire() as conn:
            await conn.execute("TRUNCATE aq_acg_drift_snapshot, aq_acg_baseline")

    service = runtime.kernel.get_service("acg_engine")
    assert service.name == "acg_engine"
    assert tuple(service.dependencies) == (
        "object_store",
        "mission_engine",
        "workflow_engine",
    )
    assert isinstance(runtime.acg_engine, AssetConfigAnalyzer)
    assert isinstance(runtime.acg_engine_service, AssetConfigGovernanceService)
    assert runtime.acg_engine_service.engine is runtime.acg_engine
    assert runtime.acg_engine.baseline_store is runtime.acg_baseline_store
    assert runtime.acg_engine.snapshot_store is runtime.acg_snapshot_store
    assert runtime.acg_engine.evidence_store is runtime.evidence_store
    assert runtime.acg_engine.finding_store is runtime.finding_store
    assert runtime.acg_engine.workflow_engine is runtime.workflow_engine
    assert runtime.acg_engine.mission_engine is runtime.mission_engine
    assert runtime.acg_engine.trend_provider is runtime.forecast_engine
    for event_type in ACG_EVENT_TYPES:
        assert runtime.event_bus.registry.is_registered(event_type)

    pre_start = await service.health()
    assert pre_start.status == "degraded"
    assert pre_start.ready is False
    assert pre_start.dependencies["object_store"] == "healthy"
    assert pre_start.dependencies["baseline_store"] == "healthy"
    assert pre_start.dependencies["snapshot_store"] == "healthy"
    assert pre_start.dependencies["evidence_store"] == "healthy"
    assert pre_start.dependencies["finding_store"] == "healthy"
    assert pre_start.dependencies["mission_engine"] == "healthy"
    assert pre_start.dependencies["workflow_engine"] == "healthy"
    assert pre_start.dependencies["forecast_engine"] == "healthy"

    await runtime.kernel.start()
    try:
        state = await runtime.kernel.health()
        acg_health = state.services["acg_engine"]

        assert acg_health.status == "healthy"
        assert acg_health.ready is True
        assert acg_health.dependencies["object_store"] == "healthy"
        assert acg_health.dependencies["baseline_store"] == "healthy"
        assert acg_health.dependencies["snapshot_store"] == "healthy"
        assert acg_health.dependencies["evidence_store"] == "healthy"
        assert acg_health.dependencies["finding_store"] == "healthy"
        assert acg_health.dependencies["mission_engine"] == "healthy"
        assert acg_health.dependencies["workflow_engine"] == "healthy"
        assert acg_health.dependencies["forecast_engine"] == "healthy"
        assert state.services["object_store"].ready is True
        assert state.services["mission_engine"].ready is True
        assert state.services["workflow_engine"].ready is True
        assert state.services["forecast_engine"].ready is True
        assert state.services["_kernel"].ready is True
    finally:
        await runtime.kernel.stop()


def test_acg_register_acg_events() -> None:
    registry = EventTypeRegistry(with_core=False)

    register_acg_events(registry)

    for event_type in ACG_EVENT_TYPES:
        assert registry.is_registered(event_type)
