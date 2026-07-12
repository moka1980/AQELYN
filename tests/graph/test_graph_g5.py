"""G5 acceptance tests for KnowledgeGraphService lifecycle wiring."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.graph import InMemoryKnowledgeGraph, PostgresKnowledgeGraph
from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime, create_runtime
from aqelyn.objects import AQObject, ObjectStore, SourceRef

PG_URL = os.getenv("AQELYN_DATABASE_URL")
SYS = ActorRef(actor_type="system", actor_id="graph-service-test")


def _now() -> datetime:
    return datetime.now(UTC)


async def _add_object(store: ObjectStore, display_name: str) -> AQObject:
    now = _now()
    return await store.upsert(
        AQObject(
            id="",
            object_type="generic",
            schema_version=1,
            display_name=display_name,
            sources=[
                SourceRef(
                    source_id=new_id("src"),
                    evidence_id=new_id("evd"),
                    observed_at=now,
                    method="graph-service-test",
                )
            ],
            first_seen_at=now,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
            created_by=SYS,
            updated_by=SYS,
        )
    )


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_kg_service_health(backend: str) -> None:
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

    service = runtime.kernel.get_service("knowledge_graph")
    assert service.name == "knowledge_graph"
    assert tuple(service.dependencies) == ("object_store",)
    assert tuple(runtime.kernel.get_service("object_store").dependencies) == ("event_bus",)
    if backend == "memory":
        assert isinstance(runtime.knowledge_graph, InMemoryKnowledgeGraph)
    else:
        assert isinstance(runtime.knowledge_graph, PostgresKnowledgeGraph)

    pre_start = await service.health()
    assert pre_start.status == "degraded"
    assert pre_start.ready is False

    await runtime.kernel.start()
    try:
        state = await runtime.kernel.health()
        kg_health = state.services["knowledge_graph"]
        store_health = state.services["object_store"]

        assert kg_health.status == "healthy"
        assert kg_health.ready is True
        assert kg_health.dependencies["object_store"] == "healthy"
        assert store_health.status == "healthy"
        assert store_health.ready is True
        assert state.services["_kernel"].ready is True

        obj = await _add_object(runtime.object_store, "service-node")
        assert await runtime.knowledge_graph.neighbors(obj.id) == []
    finally:
        await runtime.kernel.stop()
