"""M4 acceptance tests for MissionEngineService lifecycle wiring."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.graph import InMemoryKnowledgeGraph
from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime, create_runtime
from aqelyn.mission import MISSION_OBJECT_TYPE, MissionConfig, MissionEngine, MissionView
from aqelyn.mission.service import MissionEngineService
from aqelyn.objects import AQObject, InMemoryObjectStore, ObjectStore, SourceRef

PG_URL = os.getenv("AQELYN_DATABASE_URL")
SYS = ActorRef(actor_type="system", actor_id="mission-service-test")


def _now() -> datetime:
    return datetime.now(UTC)


def _source(method: str = "mission-service-test") -> SourceRef:
    return SourceRef(source_id=new_id("src"), observed_at=_now(), method=method)


async def _add_mission(store: ObjectStore, display_name: str, *, tier: int) -> AQObject:
    now = _now()
    return await store.upsert(
        AQObject(
            id="",
            object_type=MISSION_OBJECT_TYPE,
            schema_version=1,
            display_name=display_name,
            attributes={"criticality_tier": tier},
            sources=[_source(f"mission:{display_name}")],
            first_seen_at=now,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
            created_by=SYS,
            updated_by=SYS,
        )
    )


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_mission_service_health(backend: str) -> None:
    if backend == "postgres" and not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    if backend == "memory":
        runtime = create_inmemory_runtime()
    else:
        assert PG_URL is not None
        runtime = await create_runtime(AQELYNConfig(backend="postgres", database_url=PG_URL))
        postgres_store = cast(Any, runtime.object_store)
        async with postgres_store._pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE aq_relationship, aq_object_natural_key, aq_object_history, aq_object "
                "RESTART IDENTITY"
            )

    service = runtime.kernel.get_service("mission_engine")
    assert service.name == "mission_engine"
    assert tuple(service.dependencies) == ("object_store", "knowledge_graph")
    assert isinstance(runtime.mission_engine, MissionEngine)
    assert isinstance(runtime.mission_engine_service, MissionEngineService)
    assert runtime.mission_engine_service.engine is runtime.mission_engine

    pre_start = await service.health()
    assert pre_start.status == "degraded"
    assert pre_start.ready is False
    assert pre_start.dependencies["object_store"] == "healthy"
    assert pre_start.dependencies["knowledge_graph"] == "healthy"

    await runtime.kernel.start()
    try:
        state = await runtime.kernel.health()
        mission_health = state.services["mission_engine"]

        assert mission_health.status == "healthy"
        assert mission_health.ready is True
        assert mission_health.dependencies["object_store"] == "healthy"
        assert mission_health.dependencies["knowledge_graph"] == "healthy"
        assert state.services["knowledge_graph"].ready is True
        assert state.services["object_store"].ready is True
        assert state.services["_kernel"].ready is True

        mission = await _add_mission(runtime.object_store, "Run payroll", tier=1)
        view = await runtime.mission_engine.criticality_of(mission.id)

        assert isinstance(view, MissionView)
        assert view.id == mission.id
        assert view.criticality_tier == 1
        assert view.criticality_weight == 1.0
    finally:
        await runtime.kernel.stop()


async def test_mission_service_health_reports_invalid_config() -> None:
    invalid_config = MissionConfig.model_construct(
        tier_weights={1: 1.0},
        default_tier=1,
        severity_weights={"critical": 1.0},
        w_severity=0.5,
        w_mission=0.5,
        w_confidence=0.5,
        dependency_types=("depends_on",),
        max_depth=6,
        max_nodes=10_000,
    )
    store = InMemoryObjectStore()
    service = MissionEngineService(
        MissionEngine(store, InMemoryKnowledgeGraph(store), config=invalid_config)
    )

    health = await service.health()

    assert health.status == "unavailable"
    assert health.ready is False
    assert health.detail is not None
    assert "sum to 1" in health.detail


async def test_mission_service_health_reports_missing_knowledge_graph() -> None:
    service = MissionEngineService(MissionEngine(InMemoryObjectStore(), None))

    health = await service.health()

    assert health.status == "unavailable"
    assert health.ready is False
    assert health.dependencies["object_store"] == "healthy"
    assert health.dependencies["knowledge_graph"] == "unavailable"
    assert health.detail == "knowledge graph unavailable"
