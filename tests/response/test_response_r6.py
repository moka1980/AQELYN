"""R6 acceptance tests for ResponseOrchestrationService lifecycle wiring."""

from __future__ import annotations

import importlib
import os
from typing import Any, cast

import pytest

from aqelyn.events import EventTypeRegistry
from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime, create_runtime
from aqelyn.response import (
    RESPONSE_EVENTS,
    InMemoryCampaignStore,
    InMemoryTriggerStore,
    PostgresCampaignStore,
    PostgresTriggerStore,
    ResponseOrchestrationEngine,
    ResponseOrchestrationService,
)
from aqelyn.response.service import register_response_events

PG_URL = os.getenv("AQELYN_DATABASE_URL")
RESPONSE_EVENT_TYPES = (
    "aqelyn.response.campaign_planned",
    "aqelyn.response.started",
    "aqelyn.response.phase_completed",
    "aqelyn.response.approval_routed",
    "aqelyn.response.campaign_completed",
)


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_resp_service_health(backend: str) -> None:
    if backend == "postgres" and not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    if backend == "memory":
        runtime = create_inmemory_runtime()
        assert isinstance(runtime.response_campaign_store, InMemoryCampaignStore)
        assert isinstance(runtime.response_trigger_store, InMemoryTriggerStore)
    else:
        assert PG_URL is not None
        runtime = await create_runtime(AQELYNConfig(backend="postgres", database_url=PG_URL))
        assert isinstance(runtime.response_campaign_store, PostgresCampaignStore)
        assert isinstance(runtime.response_trigger_store, PostgresTriggerStore)
        campaign_store = cast(Any, runtime.response_campaign_store)
        async with campaign_store._pool.acquire() as conn:
            await conn.execute("TRUNCATE aq_response_trigger, aq_response_campaign")

    service = runtime.kernel.get_service("response_engine")
    assert service.name == "response_engine"
    assert tuple(service.dependencies) == (
        "workflow_engine",
        "policy_engine",
        "soc_engine",
    )
    assert isinstance(runtime.response_engine, ResponseOrchestrationEngine)
    assert isinstance(runtime.response_engine_service, ResponseOrchestrationService)
    assert runtime.response_engine_service is service
    assert runtime.response_engine_service.engine is runtime.response_engine
    assert runtime.response_engine_service.campaign_store is runtime.response_campaign_store
    assert runtime.response_engine_service.trigger_store is runtime.response_trigger_store
    assert runtime.response_engine_service.evidence_store is runtime.evidence_store
    assert runtime.response_engine_service.finding_store is runtime.finding_store
    assert runtime.response_engine_service.workflow_engine is runtime.workflow_engine
    assert runtime.response_engine_service.policy_authorizer is runtime.policy_engine_service
    assert runtime.response_engine_service.incident_reader is runtime.soc_store
    for event_type in RESPONSE_EVENT_TYPES:
        assert runtime.event_bus.registry.is_registered(event_type)

    pre_start = await service.health()
    assert pre_start.status == "degraded"
    assert pre_start.ready is False
    assert pre_start.dependencies["campaign_store"] == "healthy"
    assert pre_start.dependencies["trigger_store"] == "healthy"
    assert pre_start.dependencies["evidence_store"] == "healthy"
    assert pre_start.dependencies["finding_store"] == "healthy"
    assert pre_start.dependencies["workflow_engine"] == "healthy"
    assert pre_start.dependencies["policy_engine"] == "healthy"
    assert pre_start.dependencies["soc_engine"] == "healthy"

    await runtime.kernel.start()
    try:
        state = await runtime.kernel.health()
        response_health = state.services["response_engine"]

        assert response_health.status == "healthy"
        assert response_health.ready is True
        assert response_health.dependencies["campaign_store"] == "healthy"
        assert response_health.dependencies["trigger_store"] == "healthy"
        assert response_health.dependencies["evidence_store"] == "healthy"
        assert response_health.dependencies["finding_store"] == "healthy"
        assert response_health.dependencies["workflow_engine"] == "healthy"
        assert response_health.dependencies["policy_engine"] == "healthy"
        assert response_health.dependencies["soc_engine"] == "healthy"
        assert state.services["workflow_engine"].ready is True
        assert state.services["policy_engine"].ready is True
        assert state.services["soc_engine"].ready is True
        assert state.services["_kernel"].ready is True
    finally:
        await runtime.kernel.stop()


def test_resp_register_response_events() -> None:
    registry = EventTypeRegistry(with_core=False)

    register_response_events(registry)

    assert set(RESPONSE_EVENTS) == set(RESPONSE_EVENT_TYPES)
    for event_type in RESPONSE_EVENT_TYPES:
        assert registry.is_registered(event_type)


def test_resp_import_isolation() -> None:
    response = importlib.import_module("aqelyn.response")
    factory = importlib.import_module("aqelyn.kernel.factory")

    assert response.ResponseOrchestrationService is ResponseOrchestrationService
    assert hasattr(factory, "create_runtime")
