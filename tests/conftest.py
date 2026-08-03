"""Shared pytest fixtures."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from types import TracebackType
from typing import Protocol, cast

import asyncpg
import pytest

from aqelyn.graph import InMemoryKnowledgeGraph, KnowledgeGraph, PostgresKnowledgeGraph
from aqelyn.objects import InMemoryObjectStore, ObjectStore

PG_URL = os.getenv("AQELYN_DATABASE_URL")


class _PinnedAcquire:
    def __init__(self, connection: asyncpg.Connection) -> None:
        self._connection = connection

    async def __aenter__(self) -> asyncpg.Connection:
        return self._connection

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback


class _PinnedPool:
    def __init__(self, connection: asyncpg.Connection) -> None:
        self._connection = connection

    def acquire(self) -> _PinnedAcquire:
        return _PinnedAcquire(self._connection)


class _PoolOwner(Protocol):
    _pool: asyncpg.Pool


@asynccontextmanager
async def _forced_keyset_plan(store: object) -> AsyncIterator[None]:
    owner = cast(_PoolOwner, store)
    pool = owner._pool
    if not isinstance(pool, asyncpg.Pool):
        raise AssertionError("forced keyset plans require a Postgres-backed store")
    async with pool.acquire() as connection:
        await connection.execute("SET enable_indexscan = off")
        await connection.execute("SET enable_bitmapscan = off")
        owner._pool = cast(asyncpg.Pool, _PinnedPool(connection))
        try:
            yield
        finally:
            owner._pool = pool
            await connection.execute("RESET enable_bitmapscan")
            await connection.execute("RESET enable_indexscan")


@pytest.fixture
def forced_keyset_plan() -> Callable[[object], AbstractAsyncContextManager[None]]:
    return _forced_keyset_plan


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
