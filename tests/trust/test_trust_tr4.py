"""TR4 acceptance tests for TrustEngineService lifecycle wiring."""

from __future__ import annotations

import os

import pytest

from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime, create_runtime
from aqelyn.trust import SourceReliability, TrustConfig, TrustEngine, TrustThresholds
from aqelyn.trust.service import TrustEngineService

PG_URL = os.getenv("AQELYN_DATABASE_URL")


class UnavailableRegistry:
    async def get(
        self, *, source_id: str | None = None, method: str | None = None
    ) -> SourceReliability:
        raise RuntimeError("offline")

    async def set(self, entry: SourceReliability) -> SourceReliability:
        return entry

    async def list(self) -> list[SourceReliability]:
        return []


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_trust_service_health(backend: str) -> None:
    if backend == "postgres" and not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    if backend == "memory":
        runtime = create_inmemory_runtime()
    else:
        assert PG_URL is not None
        runtime = await create_runtime(AQELYNConfig(backend="postgres", database_url=PG_URL))

    service = runtime.kernel.get_service("trust_engine")
    assert service.name == "trust_engine"
    assert tuple(service.dependencies) == ()
    assert isinstance(runtime.trust_engine, TrustEngine)
    assert isinstance(runtime.trust_engine_service, TrustEngineService)

    pre_start = await service.health()
    assert pre_start.status == "degraded"
    assert pre_start.ready is False

    await runtime.kernel.start()
    try:
        state = await runtime.kernel.health()
        trust_health = state.services["trust_engine"]

        assert trust_health.status == "healthy"
        assert trust_health.ready is True
        assert state.services["_kernel"].ready is True
    finally:
        await runtime.kernel.stop()


async def test_trust_service_health_reports_invalid_config() -> None:
    invalid_config = TrustConfig.model_construct(
        type_weights={},
        thresholds=TrustThresholds(),
        half_life_days=0.0,
        recency_floor=0.1,
        default_reliability=0.5,
    )
    service = TrustEngineService(TrustEngine(config=invalid_config))

    health = await service.health()

    assert health.status == "unavailable"
    assert health.ready is False
    assert health.detail is not None
    assert "half_life_days" in health.detail


async def test_trust_service_health_reports_registry_unavailable() -> None:
    service = TrustEngineService(TrustEngine(registry=UnavailableRegistry()))

    health = await service.health()

    assert health.status == "unavailable"
    assert health.ready is False
    assert health.detail is not None
    assert "registry unavailable" in health.detail
