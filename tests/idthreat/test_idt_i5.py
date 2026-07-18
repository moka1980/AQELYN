"""I5 acceptance tests for IdentityThreatService lifecycle wiring."""

from __future__ import annotations

import importlib
import os

import pytest

from aqelyn.conventions.errors import StoreUnavailable
from aqelyn.events import EventTypeRegistry
from aqelyn.idthreat import (
    IDTHREAT_EVENTS,
    IdentityThreatEngine,
    IdentityThreatService,
    IdThreatConfig,
    InMemoryIdentityDetectionStore,
    PostgresIdentityDetectionStore,
    register_idthreat_events,
)
from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime, create_runtime

PG_URL = os.getenv("AQELYN_DATABASE_URL")
IDTHREAT_EVENT_TYPES = (
    "aqelyn.idthreat.detected",
    "aqelyn.idthreat.reviewed",
    "aqelyn.idthreat.credential_anomaly",
    "aqelyn.idthreat.privilege_use",
)


class _UnavailableProfileSource:
    async def get(self, profile_id: str, *, version: int | None = None) -> None:
        _ = (profile_id, version)
        raise StoreUnavailable("profile source is down")


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_idt_service_health(backend: str) -> None:
    if backend == "postgres" and not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    if backend == "memory":
        runtime = create_inmemory_runtime()
        assert isinstance(runtime.idthreat_store, InMemoryIdentityDetectionStore)
    else:
        assert PG_URL is not None
        runtime = await create_runtime(AQELYNConfig(backend="postgres", database_url=PG_URL))
        assert isinstance(runtime.idthreat_store, PostgresIdentityDetectionStore)
        async with runtime.idthreat_store._pool.acquire() as conn:
            await conn.execute("TRUNCATE aq_identity_review, aq_identity_detection")

    service = runtime.kernel.get_service("idthreat_engine")
    assert service.name == "idthreat_engine"
    assert tuple(service.dependencies) == (
        "detection_engine",
        "iag_engine",
        "trust_engine",
    )
    assert isinstance(runtime.idthreat_engine, IdentityThreatEngine)
    assert isinstance(runtime.idthreat_engine_service, IdentityThreatService)
    assert runtime.idthreat_engine_service is service
    assert runtime.idthreat_engine_service.engine is runtime.idthreat_engine
    assert runtime.idthreat_engine_service.store is runtime.idthreat_store
    assert runtime.idthreat_engine.store is runtime.idthreat_store
    assert runtime.idthreat_engine.profile_store is runtime.detection_profile_store
    assert runtime.idthreat_engine.entitlement_analyzer is runtime.iag_engine
    assert runtime.idthreat_engine.trust_engine is runtime.trust_engine
    assert runtime.idthreat_engine.evidence_store is runtime.evidence_store
    assert runtime.idthreat_engine.evidence_recorder is runtime.evidence_store
    assert runtime.idthreat_engine.finding_store is runtime.finding_store
    for event_type in IDTHREAT_EVENT_TYPES:
        assert runtime.event_bus.registry.is_registered(event_type)
    assert "behavior.profile.updated" not in IDTHREAT_EVENTS
    assert not runtime.event_bus.registry.is_registered("behavior.profile.updated")

    pre_start = await service.health()
    assert pre_start.status == "degraded"
    assert pre_start.ready is False
    assert pre_start.dependencies == {
        "dignity_gate": "healthy",
        "identity_detection_store": "healthy",
        "detection_engine": "healthy",
        "iag_engine": "healthy",
        "trust_engine": "healthy",
        "evidence_store": "healthy",
        "finding_store": "healthy",
    }

    valid_config = runtime.idthreat_engine.config
    runtime.idthreat_engine.config = IdThreatConfig.model_construct(
        min_corroboration=1,
        min_confidence=0.5,
        platform_default=0.5,
    )
    invalid_health = await service.health()
    assert invalid_health.status == "unavailable"
    assert invalid_health.ready is False
    assert "min_corroboration" in (invalid_health.detail or "")
    runtime.idthreat_engine.config = valid_config

    profile_source = runtime.idthreat_engine.profile_store
    runtime.idthreat_engine.profile_store = _UnavailableProfileSource()
    unavailable_health = await service.health()
    assert unavailable_health.status == "unavailable"
    assert unavailable_health.ready is False
    assert "profile source" in (unavailable_health.detail or "")
    assert unavailable_health.dependencies == {
        "dignity_gate": "healthy",
        "identity_detection_store": "healthy",
    }
    runtime.idthreat_engine.profile_store = profile_source

    await runtime.kernel.start()
    try:
        state = await runtime.kernel.health()
        idthreat_health = state.services["idthreat_engine"]

        assert idthreat_health.status == "healthy"
        assert idthreat_health.ready is True
        assert idthreat_health.dependencies == pre_start.dependencies
        assert state.services["detection_engine"].ready is True
        assert state.services["iag_engine"].ready is True
        assert state.services["trust_engine"].ready is True
        assert state.services["_kernel"].ready is True
    finally:
        await runtime.kernel.stop()


def test_idt_register_idthreat_events() -> None:
    registry = EventTypeRegistry(with_core=False)

    register_idthreat_events(registry)

    assert set(IDTHREAT_EVENTS) == set(IDTHREAT_EVENT_TYPES)
    assert "behavior.profile.updated" not in IDTHREAT_EVENTS
    for event_type in IDTHREAT_EVENT_TYPES:
        assert registry.is_registered(event_type)
    assert not registry.is_registered("behavior.profile.updated")


def test_idt_import_isolation() -> None:
    identity_threat = importlib.import_module("aqelyn.idthreat")
    factory = importlib.import_module("aqelyn.kernel.factory")

    assert identity_threat.IdentityThreatService is IdentityThreatService
    assert hasattr(factory, "create_runtime")
