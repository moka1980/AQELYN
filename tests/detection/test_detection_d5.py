"""D5 acceptance tests for ThreatDetectionService lifecycle wiring."""

from __future__ import annotations

import importlib
import os
from typing import Any, cast

import pytest

from aqelyn.detection import (
    DETECTION_EVENTS,
    InMemoryProfileStore,
    InMemoryRuleStore,
    ThreatDetectionEngine,
    ThreatDetectionService,
)
from aqelyn.detection.postgres import PostgresProfileStore, PostgresRuleStore
from aqelyn.detection.service import register_detection_events
from aqelyn.events import EventTypeRegistry
from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime, create_runtime

PG_URL = os.getenv("AQELYN_DATABASE_URL")
DETECTION_EVENT_TYPES = (
    "aqelyn.detection.threat_detected",
    "aqelyn.detection.anomaly_detected",
    "aqelyn.detection.profile_updated",
)


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_det_service_health(backend: str) -> None:
    if backend == "postgres" and not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    if backend == "memory":
        runtime = create_inmemory_runtime()
        assert isinstance(runtime.detection_rule_store, InMemoryRuleStore)
        assert isinstance(runtime.detection_profile_store, InMemoryProfileStore)
    else:
        assert PG_URL is not None
        runtime = await create_runtime(AQELYNConfig(backend="postgres", database_url=PG_URL))
        assert isinstance(runtime.detection_rule_store, PostgresRuleStore)
        assert isinstance(runtime.detection_profile_store, PostgresProfileStore)
        rule_store = cast(Any, runtime.detection_rule_store)
        async with rule_store._pool.acquire() as conn:
            await conn.execute("TRUNCATE aq_behavior_profile, aq_detection_rule")

    service = runtime.kernel.get_service("detection_engine")
    assert service.name == "detection_engine"
    assert tuple(service.dependencies) == (
        "trust_engine",
        "mission_engine",
        "threat_fusion_engine",
    )
    assert isinstance(runtime.detection_engine, ThreatDetectionEngine)
    assert isinstance(runtime.detection_engine_service, ThreatDetectionService)
    assert runtime.detection_engine_service.engine is runtime.detection_engine
    assert runtime.detection_engine.rule_store is runtime.detection_rule_store
    assert runtime.detection_engine.profile_store is runtime.detection_profile_store
    assert runtime.detection_engine.trust_engine is runtime.trust_engine
    assert runtime.detection_engine.mission_engine is runtime.mission_engine
    assert runtime.detection_engine.evidence_store is runtime.evidence_store
    assert runtime.detection_engine.finding_store is runtime.finding_store
    assert runtime.detection_engine_service.threat_engine is runtime.threat_engine
    for event_type in DETECTION_EVENT_TYPES:
        assert runtime.event_bus.registry.is_registered(event_type)

    pre_start = await service.health()
    assert pre_start.status == "degraded"
    assert pre_start.ready is False
    assert pre_start.dependencies["rule_store"] == "healthy"
    assert pre_start.dependencies["profile_store"] == "healthy"
    assert pre_start.dependencies["trust_engine"] == "healthy"
    assert pre_start.dependencies["evidence_store"] == "healthy"
    assert pre_start.dependencies["finding_store"] == "healthy"
    assert pre_start.dependencies["mission_engine"] == "healthy"
    assert pre_start.dependencies["threat_fusion_engine"] == "healthy"

    await runtime.kernel.start()
    try:
        state = await runtime.kernel.health()
        detection_health = state.services["detection_engine"]

        assert detection_health.status == "healthy"
        assert detection_health.ready is True
        assert detection_health.dependencies["rule_store"] == "healthy"
        assert detection_health.dependencies["profile_store"] == "healthy"
        assert detection_health.dependencies["trust_engine"] == "healthy"
        assert detection_health.dependencies["evidence_store"] == "healthy"
        assert detection_health.dependencies["finding_store"] == "healthy"
        assert detection_health.dependencies["mission_engine"] == "healthy"
        assert detection_health.dependencies["threat_fusion_engine"] == "healthy"
        assert state.services["trust_engine"].ready is True
        assert state.services["mission_engine"].ready is True
        assert state.services["threat_fusion_engine"].ready is True
        assert state.services["_kernel"].ready is True
    finally:
        await runtime.kernel.stop()


def test_det_register_detection_events() -> None:
    registry = EventTypeRegistry(with_core=False)

    register_detection_events(registry)

    assert set(DETECTION_EVENTS) == set(DETECTION_EVENT_TYPES)
    for event_type in DETECTION_EVENT_TYPES:
        assert registry.is_registered(event_type)


def test_det_import_isolation() -> None:
    detection = importlib.import_module("aqelyn.detection")
    factory = importlib.import_module("aqelyn.kernel.factory")

    assert detection.ThreatDetectionEngine is ThreatDetectionEngine
    assert detection.ThreatDetectionService is ThreatDetectionService
    assert hasattr(factory, "create_runtime")
