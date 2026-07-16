"""P6 acceptance tests for ForecastingService lifecycle wiring."""

from __future__ import annotations

import importlib
import os

import pytest

from aqelyn.events import EventTypeRegistry
from aqelyn.forecast import (
    FORECAST_EVENTS,
    ForecastingEngine,
    ForecastingService,
    InMemoryForecastStore,
    InMemoryPredictionModelStore,
    PostgresForecastStore,
    PostgresPredictionModelStore,
)
from aqelyn.forecast.service import register_forecast_events
from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime, create_runtime

PG_URL = os.getenv("AQELYN_DATABASE_URL")
FORECAST_EVENT_TYPES = (
    "aqelyn.forecast.generated",
    "aqelyn.forecast.scored",
    "aqelyn.forecast.trend_detected",
)


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_fc_service_health(backend: str) -> None:
    if backend == "postgres" and not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    if backend == "memory":
        runtime = create_inmemory_runtime()
        assert isinstance(runtime.forecast_store, InMemoryForecastStore)
        assert isinstance(runtime.forecast_model_store, InMemoryPredictionModelStore)
    else:
        assert PG_URL is not None
        runtime = await create_runtime(AQELYNConfig(backend="postgres", database_url=PG_URL))
        assert isinstance(runtime.forecast_store, PostgresForecastStore)
        assert isinstance(runtime.forecast_model_store, PostgresPredictionModelStore)

    service = runtime.kernel.get_service("forecast_engine")
    assert service.name == "forecast_engine"
    assert tuple(service.dependencies) == (
        "datalake_engine",
        "trust_engine",
        "risk_engine",
    )
    assert isinstance(runtime.forecast_engine, ForecastingEngine)
    assert isinstance(runtime.forecast_engine_service, ForecastingService)
    assert runtime.forecast_engine_service is service
    assert runtime.forecast_engine_service.engine is runtime.forecast_engine
    assert runtime.forecast_engine.forecast_store is runtime.forecast_store
    assert runtime.forecast_engine.model_store is runtime.forecast_model_store
    assert runtime.forecast_engine.evidence_store is runtime.evidence_store
    assert runtime.forecast_engine.evidence_recorder is runtime.evidence_store
    assert runtime.forecast_engine.trust_engine is runtime.trust_engine
    assert runtime.forecast_engine_service.evidence_store is runtime.evidence_store
    assert runtime.forecast_engine_service.lake_service is runtime.lake_service
    assert runtime.forecast_engine_service.risk_engine is runtime.risk_engine
    for event_type in FORECAST_EVENT_TYPES:
        assert runtime.event_bus.registry.is_registered(event_type)

    pre_start = await service.health()
    assert pre_start.status == "degraded"
    assert pre_start.ready is False
    assert pre_start.dependencies["forecast_store"] == "healthy"
    assert pre_start.dependencies["model_store"] == "healthy"
    assert pre_start.dependencies["evidence_store"] == "healthy"
    assert pre_start.dependencies["trust_engine"] == "healthy"
    assert pre_start.dependencies["lake_service"] == "healthy"
    assert pre_start.dependencies["risk_engine"] == "healthy"
    assert pre_start.dependencies["history_source"] == "healthy"
    assert pre_start.dependencies["actual_source"] == "healthy"
    assert pre_start.dependencies["evidence_recorder"] == "healthy"

    await runtime.kernel.start()
    try:
        state = await runtime.kernel.health()
        forecast_health = state.services["forecast_engine"]

        assert forecast_health.status == "healthy"
        assert forecast_health.ready is True
        assert forecast_health.dependencies["forecast_store"] == "healthy"
        assert forecast_health.dependencies["model_store"] == "healthy"
        assert forecast_health.dependencies["evidence_store"] == "healthy"
        assert forecast_health.dependencies["trust_engine"] == "healthy"
        assert forecast_health.dependencies["lake_service"] == "healthy"
        assert forecast_health.dependencies["risk_engine"] == "healthy"
        assert forecast_health.dependencies["history_source"] == "healthy"
        assert forecast_health.dependencies["actual_source"] == "healthy"
        assert forecast_health.dependencies["evidence_recorder"] == "healthy"
        assert state.services["datalake_engine"].ready is True
        assert state.services["trust_engine"].ready is True
        assert state.services["risk_engine"].ready is True
        assert state.services["_kernel"].ready is True
    finally:
        await runtime.kernel.stop()


def test_fc_register_forecast_events() -> None:
    registry = EventTypeRegistry(with_core=False)

    register_forecast_events(registry)

    assert set(FORECAST_EVENTS) == set(FORECAST_EVENT_TYPES)
    for event_type in FORECAST_EVENT_TYPES:
        assert registry.is_registered(event_type)


def test_fc_import_isolation() -> None:
    forecast = importlib.import_module("aqelyn.forecast")
    factory = importlib.import_module("aqelyn.kernel.factory")

    assert forecast.ForecastingService is ForecastingService
    assert hasattr(factory, "create_runtime")
