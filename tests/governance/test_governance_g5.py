"""G5 acceptance tests for ComplianceGovernanceService lifecycle wiring."""

from __future__ import annotations

import os
from typing import Any, cast

import pytest

from aqelyn.events import EventTypeRegistry
from aqelyn.governance import (
    ComplianceEngine,
    InMemorySnapshotStore,
    PostgresSnapshotStore,
)
from aqelyn.governance.service import ComplianceGovernanceService, register_compliance_events
from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime, create_runtime

PG_URL = os.getenv("AQELYN_DATABASE_URL")


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_gov_service_health(backend: str) -> None:
    if backend == "postgres" and not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    if backend == "memory":
        runtime = create_inmemory_runtime()
        assert isinstance(runtime.compliance_snapshot_store, InMemorySnapshotStore)
    else:
        assert PG_URL is not None
        runtime = await create_runtime(AQELYNConfig(backend="postgres", database_url=PG_URL))
        assert isinstance(runtime.compliance_snapshot_store, PostgresSnapshotStore)
        snapshot_store = cast(Any, runtime.compliance_snapshot_store)
        async with snapshot_store._pool.acquire() as conn:
            await conn.execute("TRUNCATE aq_compliance_snapshot")

    service = runtime.kernel.get_service("compliance_engine")
    assert service.name == "compliance_engine"
    assert tuple(service.dependencies) == ("object_store", "policy_engine", "mission_engine")
    assert isinstance(runtime.compliance_engine, ComplianceEngine)
    assert isinstance(runtime.compliance_engine_service, ComplianceGovernanceService)
    assert runtime.compliance_engine_service.engine is runtime.compliance_engine
    assert runtime.event_bus.registry.is_registered("aqelyn.compliance.assessment_completed")
    assert runtime.event_bus.registry.is_registered("aqelyn.compliance.posture_changed")

    pre_start = await service.health()
    assert pre_start.status == "degraded"
    assert pre_start.ready is False
    assert pre_start.dependencies["object_store"] == "healthy"
    assert pre_start.dependencies["policy_engine"] == "healthy"
    assert pre_start.dependencies["snapshot_store"] == "healthy"
    assert pre_start.dependencies["evidence_store"] == "healthy"
    assert pre_start.dependencies["finding_store"] == "healthy"

    await runtime.kernel.start()
    try:
        state = await runtime.kernel.health()
        gov_health = state.services["compliance_engine"]

        assert gov_health.status == "healthy"
        assert gov_health.ready is True
        assert gov_health.dependencies["object_store"] == "healthy"
        assert gov_health.dependencies["policy_engine"] == "healthy"
        assert gov_health.dependencies["snapshot_store"] == "healthy"
        assert gov_health.dependencies["evidence_store"] == "healthy"
        assert gov_health.dependencies["finding_store"] == "healthy"
        assert state.services["object_store"].ready is True
        assert state.services["policy_engine"].ready is True
        assert state.services["mission_engine"].ready is True
        assert state.services["_kernel"].ready is True
    finally:
        await runtime.kernel.stop()


def test_gov_register_compliance_events() -> None:
    registry = EventTypeRegistry(with_core=False)

    register_compliance_events(registry)

    assert registry.is_registered("aqelyn.compliance.assessment_completed")
    assert registry.is_registered("aqelyn.compliance.posture_changed")
