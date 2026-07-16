"""E5 acceptance tests for DecisionIntelligenceService lifecycle wiring."""

from __future__ import annotations

import importlib
import os
from typing import Any, cast

import pytest

from aqelyn.decision import (
    DECISION_EVENTS,
    DecisionIntelligenceEngine,
    DecisionIntelligenceService,
    InMemoryModelVersionStore,
    InMemoryRecommendationStore,
)
from aqelyn.decision.postgres import PostgresModelVersionStore, PostgresRecommendationStore
from aqelyn.decision.service import register_decision_events
from aqelyn.events import EventTypeRegistry
from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime, create_runtime

PG_URL = os.getenv("AQELYN_DATABASE_URL")
DECISION_EVENT_TYPES = (
    "aqelyn.decision.recommendation_generated",
    "aqelyn.decision.decision_recorded",
    "aqelyn.decision.model_promoted",
)


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_decision_service_health(backend: str) -> None:
    if backend == "postgres" and not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    if backend == "memory":
        runtime = create_inmemory_runtime()
        assert isinstance(runtime.decision_recommendation_store, InMemoryRecommendationStore)
        assert isinstance(runtime.decision_model_store, InMemoryModelVersionStore)
    else:
        assert PG_URL is not None
        runtime = await create_runtime(AQELYNConfig(backend="postgres", database_url=PG_URL))
        assert isinstance(runtime.decision_recommendation_store, PostgresRecommendationStore)
        assert isinstance(runtime.decision_model_store, PostgresModelVersionStore)
        rec_store = cast(Any, runtime.decision_recommendation_store)
        async with rec_store._pool.acquire() as conn:
            await conn.execute("TRUNCATE aq_decision_recommendation, aq_decision_model_version")

    service = runtime.kernel.get_service("decision_engine")
    assert service.name == "decision_engine"
    assert tuple(service.dependencies) == (
        "trust_engine",
        "mission_engine",
        "risk_engine",
        "soc_engine",
        "workflow_engine",
    )
    assert isinstance(runtime.decision_engine, DecisionIntelligenceEngine)
    assert isinstance(runtime.decision_engine_service, DecisionIntelligenceService)
    assert runtime.decision_engine_service is service
    assert runtime.decision_engine_service.engine is runtime.decision_engine
    assert runtime.decision_engine.recommendation_store is runtime.decision_recommendation_store
    assert runtime.decision_engine.model_store is runtime.decision_model_store
    assert runtime.decision_engine.evidence_store is runtime.evidence_store
    assert runtime.decision_engine.trust_engine is runtime.trust_engine
    assert runtime.decision_engine.workflow_engine is runtime.workflow_engine
    for event_type in DECISION_EVENT_TYPES:
        assert runtime.event_bus.registry.is_registered(event_type)

    pre_start = await service.health()
    assert pre_start.status == "degraded"
    assert pre_start.ready is False
    assert pre_start.dependencies["recommendation_store"] == "healthy"
    assert pre_start.dependencies["model_store"] == "healthy"
    assert pre_start.dependencies["evidence_store"] == "healthy"
    assert pre_start.dependencies["trust_engine"] == "healthy"
    assert pre_start.dependencies["workflow_engine"] == "healthy"
    assert pre_start.dependencies["claim_source"] == "healthy"

    await runtime.kernel.start()
    try:
        state = await runtime.kernel.health()
        decision_health = state.services["decision_engine"]

        assert decision_health.status == "healthy"
        assert decision_health.ready is True
        assert decision_health.dependencies["recommendation_store"] == "healthy"
        assert decision_health.dependencies["model_store"] == "healthy"
        assert decision_health.dependencies["evidence_store"] == "healthy"
        assert decision_health.dependencies["trust_engine"] == "healthy"
        assert decision_health.dependencies["workflow_engine"] == "healthy"
        assert decision_health.dependencies["claim_source"] == "healthy"
        assert state.services["trust_engine"].ready is True
        assert state.services["mission_engine"].ready is True
        assert state.services["risk_engine"].ready is True
        assert state.services["soc_engine"].ready is True
        assert state.services["workflow_engine"].ready is True
        assert state.services["_kernel"].ready is True
    finally:
        await runtime.kernel.stop()


def test_decision_register_decision_events() -> None:
    registry = EventTypeRegistry(with_core=False)

    register_decision_events(registry)

    assert set(DECISION_EVENTS) == set(DECISION_EVENT_TYPES)
    for event_type in DECISION_EVENT_TYPES:
        assert registry.is_registered(event_type)


def test_decision_import_isolation() -> None:
    decision = importlib.import_module("aqelyn.decision")
    factory = importlib.import_module("aqelyn.kernel.factory")

    assert decision.DecisionIntelligenceService is DecisionIntelligenceService
    assert hasattr(factory, "create_runtime")
