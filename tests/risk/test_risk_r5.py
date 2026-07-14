"""R5 acceptance tests for RiskIntelligenceService lifecycle wiring."""

from __future__ import annotations

import os
from typing import Any, cast

import pytest

from aqelyn.events import EventTypeRegistry
from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime, create_runtime
from aqelyn.risk import (
    InMemoryRiskSnapshotStore,
    InMemoryRiskStore,
    RiskIntelligenceEngine,
    RiskIntelligenceService,
)
from aqelyn.risk.postgres import PostgresRiskSnapshotStore, PostgresRiskStore
from aqelyn.risk.service import register_risk_events

PG_URL = os.getenv("AQELYN_DATABASE_URL")
RISK_EVENT_TYPES = (
    "aqelyn.risk.identified",
    "aqelyn.risk.score_changed",
    "aqelyn.risk.treated",
)


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_risk_service_health(backend: str) -> None:
    if backend == "postgres" and not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    if backend == "memory":
        runtime = create_inmemory_runtime()
        assert isinstance(runtime.risk_store, InMemoryRiskStore)
        assert isinstance(runtime.risk_snapshot_store, InMemoryRiskSnapshotStore)
    else:
        assert PG_URL is not None
        runtime = await create_runtime(AQELYNConfig(backend="postgres", database_url=PG_URL))
        assert isinstance(runtime.risk_store, PostgresRiskStore)
        assert isinstance(runtime.risk_snapshot_store, PostgresRiskSnapshotStore)
        risk_store = cast(Any, runtime.risk_store)
        async with risk_store._pool.acquire() as conn:
            await conn.execute("TRUNCATE aq_risk_snapshot, aq_risk RESTART IDENTITY")

    service = runtime.kernel.get_service("risk_engine")
    assert service.name == "risk_engine"
    assert tuple(service.dependencies) == (
        "mission_engine",
        "workflow_engine",
        "compliance_engine",
        "iag_engine",
        "acg_engine",
    )
    assert isinstance(runtime.risk_engine, RiskIntelligenceEngine)
    assert isinstance(runtime.risk_engine_service, RiskIntelligenceService)
    assert runtime.risk_engine_service.engine is runtime.risk_engine
    assert runtime.risk_engine.finding_store is runtime.finding_store
    assert runtime.risk_engine.risk_store is runtime.risk_store
    assert runtime.risk_engine.snapshot_store is runtime.risk_snapshot_store
    assert runtime.risk_engine.evidence_store is runtime.evidence_store
    assert runtime.risk_engine.mission_engine is runtime.mission_engine
    assert runtime.risk_engine.workflow_engine is runtime.workflow_engine
    for event_type in RISK_EVENT_TYPES:
        assert runtime.event_bus.registry.is_registered(event_type)

    pre_start = await service.health()
    assert pre_start.status == "degraded"
    assert pre_start.ready is False
    assert pre_start.dependencies["risk_store"] == "healthy"
    assert pre_start.dependencies["snapshot_store"] == "healthy"
    assert pre_start.dependencies["evidence_store"] == "healthy"
    assert pre_start.dependencies["finding_store"] == "healthy"
    assert pre_start.dependencies["mission_engine"] == "healthy"
    assert pre_start.dependencies["workflow_engine"] == "healthy"

    await runtime.kernel.start()
    try:
        state = await runtime.kernel.health()
        risk_health = state.services["risk_engine"]

        assert risk_health.status == "healthy"
        assert risk_health.ready is True
        assert risk_health.dependencies["risk_store"] == "healthy"
        assert risk_health.dependencies["snapshot_store"] == "healthy"
        assert risk_health.dependencies["evidence_store"] == "healthy"
        assert risk_health.dependencies["finding_store"] == "healthy"
        assert risk_health.dependencies["mission_engine"] == "healthy"
        assert risk_health.dependencies["workflow_engine"] == "healthy"
        assert state.services["mission_engine"].ready is True
        assert state.services["workflow_engine"].ready is True
        assert state.services["compliance_engine"].ready is True
        assert state.services["iag_engine"].ready is True
        assert state.services["acg_engine"].ready is True
        assert state.services["_kernel"].ready is True
    finally:
        await runtime.kernel.stop()


def test_risk_register_risk_events() -> None:
    registry = EventTypeRegistry(with_core=False)

    register_risk_events(registry)

    for event_type in RISK_EVENT_TYPES:
        assert registry.is_registered(event_type)
