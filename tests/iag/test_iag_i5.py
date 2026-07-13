"""I5 acceptance tests for IdentityAccessGovernanceService lifecycle wiring."""

from __future__ import annotations

import os
from typing import Any, cast

import pytest

from aqelyn.events import EventTypeRegistry
from aqelyn.iag import (
    IdentityAccessGovernanceEngine,
    InMemoryCertificationStore,
    PostgresCertificationStore,
)
from aqelyn.iag.service import IdentityAccessGovernanceService, register_iag_events
from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime, create_runtime

PG_URL = os.getenv("AQELYN_DATABASE_URL")
IAG_EVENT_TYPES = (
    "aqelyn.iag.risk_detected",
    "aqelyn.iag.certification_opened",
    "aqelyn.iag.item_decided",
    "aqelyn.iag.certification_completed",
)


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_iag_service_health(backend: str) -> None:
    if backend == "postgres" and not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    if backend == "memory":
        runtime = create_inmemory_runtime()
        assert isinstance(runtime.iag_certification_store, InMemoryCertificationStore)
    else:
        assert PG_URL is not None
        runtime = await create_runtime(AQELYNConfig(backend="postgres", database_url=PG_URL))
        assert isinstance(runtime.iag_certification_store, PostgresCertificationStore)
        cert_store = cast(Any, runtime.iag_certification_store)
        async with cert_store._pool.acquire() as conn:
            await conn.execute("TRUNCATE aq_iag_certification")

    service = runtime.kernel.get_service("iag_engine")
    assert service.name == "iag_engine"
    assert tuple(service.dependencies) == (
        "object_store",
        "knowledge_graph",
        "policy_engine",
        "mission_engine",
        "workflow_engine",
    )
    assert isinstance(runtime.iag_engine, IdentityAccessGovernanceEngine)
    assert isinstance(runtime.iag_engine_service, IdentityAccessGovernanceService)
    assert runtime.iag_engine_service.engine is runtime.iag_engine
    for event_type in IAG_EVENT_TYPES:
        assert runtime.event_bus.registry.is_registered(event_type)

    pre_start = await service.health()
    assert pre_start.status == "degraded"
    assert pre_start.ready is False
    assert pre_start.dependencies["object_store"] == "healthy"
    assert pre_start.dependencies["knowledge_graph"] == "healthy"
    assert pre_start.dependencies["policy_engine"] == "healthy"
    assert pre_start.dependencies["certification_store"] == "healthy"
    assert pre_start.dependencies["evidence_store"] == "healthy"
    assert pre_start.dependencies["finding_store"] == "healthy"
    assert pre_start.dependencies["workflow_engine"] == "healthy"

    await runtime.kernel.start()
    try:
        state = await runtime.kernel.health()
        iag_health = state.services["iag_engine"]

        assert iag_health.status == "healthy"
        assert iag_health.ready is True
        assert iag_health.dependencies["object_store"] == "healthy"
        assert iag_health.dependencies["knowledge_graph"] == "healthy"
        assert iag_health.dependencies["policy_engine"] == "healthy"
        assert iag_health.dependencies["certification_store"] == "healthy"
        assert iag_health.dependencies["evidence_store"] == "healthy"
        assert iag_health.dependencies["finding_store"] == "healthy"
        assert iag_health.dependencies["workflow_engine"] == "healthy"
        assert state.services["object_store"].ready is True
        assert state.services["knowledge_graph"].ready is True
        assert state.services["policy_engine"].ready is True
        assert state.services["workflow_engine"].ready is True
        assert state.services["_kernel"].ready is True
    finally:
        await runtime.kernel.stop()


def test_iag_register_iag_events() -> None:
    registry = EventTypeRegistry(with_core=False)

    register_iag_events(registry)

    for event_type in IAG_EVENT_TYPES:
        assert registry.is_registered(event_type)
