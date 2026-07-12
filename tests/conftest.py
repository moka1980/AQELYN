"""Shared pytest fixtures."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest

from aqelyn.graph import InMemoryKnowledgeGraph, KnowledgeGraph, PostgresKnowledgeGraph
from aqelyn.objects import InMemoryObjectStore, ObjectStore

PG_URL = os.getenv("AQELYN_DATABASE_URL")


@dataclass
class GraphHarness:
    kind: str
    object_store: ObjectStore
    graph: KnowledgeGraph


@pytest.fixture(params=["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def graph_harness(request: pytest.FixtureRequest) -> AsyncIterator[GraphHarness]:
    if request.param == "inmemory":
        memory_store = InMemoryObjectStore()
        yield GraphHarness(
            kind="inmemory",
            object_store=memory_store,
            graph=InMemoryKnowledgeGraph(memory_store),
        )
        return

    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    from aqelyn.objects.postgres import PostgresObjectStore

    postgres_store = await PostgresObjectStore.connect(PG_URL, mode="local")
    async with postgres_store._pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE aq_relationship, aq_object_natural_key, aq_object_history, aq_object "
            "RESTART IDENTITY"
        )
    try:
        yield GraphHarness(
            kind="postgres",
            object_store=postgres_store,
            graph=PostgresKnowledgeGraph(postgres_store._pool),
        )
    finally:
        await postgres_store.close()
