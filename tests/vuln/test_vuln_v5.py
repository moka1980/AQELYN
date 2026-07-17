"""V5 acceptance tests for VulnerabilityIntelligenceService lifecycle wiring."""

from __future__ import annotations

import importlib
import os

import pytest

from aqelyn.events import EventTypeRegistry
from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime, create_runtime
from aqelyn.vuln import (
    VULN_EVENTS,
    DriftSnapshotBlockingProvider,
    ExposureStoreReachabilityProvider,
    InertVulnerabilityCoverageProvider,
    InMemoryVulnerabilityStore,
    PostgresVulnerabilityStore,
    ThreatSignalFactorProvider,
    VulnerabilityIntelligenceEngine,
    VulnerabilityIntelligenceService,
)
from aqelyn.vuln.service import register_vuln_events

PG_URL = os.getenv("AQELYN_DATABASE_URL")
VULN_EVENT_TYPES = (
    "aqelyn.vuln.discovered",
    "aqelyn.vuln.prioritized",
    "aqelyn.vuln.exploit_correlated",
    "aqelyn.vuln.remediation_recommended",
    "aqelyn.vuln.reassessed",
)


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_vuln_service_health(backend: str) -> None:
    if backend == "postgres" and not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    if backend == "memory":
        runtime = create_inmemory_runtime()
        assert isinstance(runtime.vuln_store, InMemoryVulnerabilityStore)
    else:
        assert PG_URL is not None
        runtime = await create_runtime(AQELYNConfig(backend="postgres", database_url=PG_URL))
        assert isinstance(runtime.vuln_store, PostgresVulnerabilityStore)

    service = runtime.kernel.get_service("vuln_engine")
    assert service.name == "vuln_engine"
    assert tuple(service.dependencies) == (
        "threat_fusion_engine",
        "exposure_engine",
        "mission_engine",
        "acg_engine",
        "trust_engine",
        "forecast_engine",
    )
    assert isinstance(runtime.vuln_engine, VulnerabilityIntelligenceEngine)
    assert isinstance(runtime.vuln_engine_service, VulnerabilityIntelligenceService)
    assert runtime.vuln_engine_service is service
    assert runtime.vuln_engine_service.engine is runtime.vuln_engine
    assert runtime.vuln_engine_service.store is runtime.vuln_store
    assert runtime.vuln_engine.store is runtime.vuln_store
    assert isinstance(runtime.vuln_engine.threat_provider, ThreatSignalFactorProvider)
    assert isinstance(runtime.vuln_engine.exposure_provider, ExposureStoreReachabilityProvider)
    assert runtime.vuln_engine.mission_provider is runtime.mission_engine
    assert isinstance(runtime.vuln_engine.baseline_provider, DriftSnapshotBlockingProvider)
    assert isinstance(
        runtime.vuln_engine.coverage_provider,
        InertVulnerabilityCoverageProvider,
    )
    assert runtime.vuln_engine.trend_provider is runtime.forecast_engine
    assert runtime.vuln_engine.finding_store is runtime.finding_store
    for event_type in VULN_EVENT_TYPES:
        assert runtime.event_bus.registry.is_registered(event_type)

    pre_start = await service.health()
    assert pre_start.status == "degraded"
    assert pre_start.ready is False
    assert pre_start.dependencies["vulnerability_store"] == "healthy"
    assert pre_start.dependencies["coverage_provider"] == "inert"
    assert pre_start.dependencies["threat_fusion_engine"] == "healthy"
    assert pre_start.dependencies["exposure_engine"] == "healthy"
    assert pre_start.dependencies["mission_engine"] == "healthy"
    assert pre_start.dependencies["acg_engine"] == "healthy"
    assert pre_start.dependencies["trust_engine"] == "healthy"
    assert pre_start.dependencies["forecast_engine"] == "healthy"
    assert pre_start.dependencies["finding_store"] == "healthy"

    await runtime.kernel.start()
    try:
        state = await runtime.kernel.health()
        vuln_health = state.services["vuln_engine"]

        assert vuln_health.status == "healthy"
        assert vuln_health.ready is True
        assert vuln_health.dependencies["vulnerability_store"] == "healthy"
        assert vuln_health.dependencies["coverage_provider"] == "inert"
        assert vuln_health.dependencies["threat_fusion_engine"] == "healthy"
        assert vuln_health.dependencies["exposure_engine"] == "healthy"
        assert vuln_health.dependencies["mission_engine"] == "healthy"
        assert vuln_health.dependencies["acg_engine"] == "healthy"
        assert vuln_health.dependencies["trust_engine"] == "healthy"
        assert vuln_health.dependencies["forecast_engine"] == "healthy"
        assert vuln_health.dependencies["finding_store"] == "healthy"
        assert state.services["threat_fusion_engine"].ready is True
        assert state.services["exposure_engine"].ready is True
        assert state.services["mission_engine"].ready is True
        assert state.services["acg_engine"].ready is True
        assert state.services["trust_engine"].ready is True
        assert state.services["forecast_engine"].ready is True
        assert state.services["_kernel"].ready is True
    finally:
        await runtime.kernel.stop()


def test_vuln_register_vuln_events() -> None:
    registry = EventTypeRegistry(with_core=False)

    register_vuln_events(registry)

    assert set(VULN_EVENTS) == set(VULN_EVENT_TYPES)
    for event_type in VULN_EVENT_TYPES:
        assert registry.is_registered(event_type)


def test_vuln_import_isolation() -> None:
    vuln = importlib.import_module("aqelyn.vuln")
    factory = importlib.import_module("aqelyn.kernel.factory")

    assert vuln.VulnerabilityIntelligenceService is VulnerabilityIntelligenceService
    assert hasattr(factory, "create_runtime")


async def test_vuln_inert_coverage_refuses() -> None:
    # ECR-0013: the unwired coverage default is inert/refusing, never optimistic.
    # A wired runtime's assess() therefore refuses rather than reporting a fully
    # covered ("not scanned = clean") assessment until inventory() is wired (N6).
    from aqelyn.conventions.errors import CoverageUnavailable

    runtime = create_inmemory_runtime()
    service = runtime.vuln_engine_service
    assert isinstance(runtime.vuln_engine.coverage_provider, InertVulnerabilityCoverageProvider)

    await runtime.kernel.start()
    try:
        with pytest.raises(CoverageUnavailable):
            await service.assess(tenant_id="018f0000-0000-7000-8000-0000002400aa")
    finally:
        await runtime.kernel.stop()
