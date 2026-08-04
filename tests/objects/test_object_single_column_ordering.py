"""ECR-0097 ordering witnesses for the object-store single-column read."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from typing import Protocol, cast

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.objects import (
    AQObject,
    InMemoryObjectStore,
    NaturalKey,
    ObjectQuery,
    ObjectStore,
    ObjectTypeRegistry,
    SourceRef,
)
from aqelyn.objects.postgres import PostgresObjectStore

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)
ACTOR = ActorRef(actor_type="system", actor_id="ecr0097-object-ordering")
ROW_COUNT = 6


class _Closable(Protocol):
    async def close(self) -> None: ...


@asynccontextmanager
async def _store(kind: str) -> AsyncIterator[ObjectStore]:
    registry = ObjectTypeRegistry()
    if kind == "inmemory":
        yield InMemoryObjectStore(registry=registry)
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    postgres = await PostgresObjectStore.connect(PG_URL, registry=registry)
    async with postgres._pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE aq_relationship, aq_object_natural_key, aq_object_history, aq_object "
            "RESTART IDENTITY"
        )
    try:
        yield postgres
    finally:
        await cast(_Closable, postgres).close()


def _object(object_id: str, index: int) -> AQObject:
    return AQObject(
        id=object_id,
        object_type="generic",
        schema_version=1,
        display_name=f"ecr0097-object-{index}",
        natural_keys=[NaturalKey(namespace="ecr0097.object", value=str(index))],
        sources=[
            SourceRef(
                source_id=new_id("src"),
                observed_at=NOW,
                method="ecr0097-ordering",
            )
        ],
        first_seen_at=NOW,
        last_seen_at=NOW,
        created_at=NOW,
        updated_at=NOW,
        created_by=ACTOR,
        updated_by=ACTOR,
    )


async def _assert_walk(store: ObjectStore, expected: list[str]) -> None:
    held, held_cursor = await store.query(ObjectQuery(limit=len(expected)))
    assert len(held) == len(expected), "object fixture did not retain its full population"
    assert held_cursor is None

    for limit in range(1, len(expected) + 1):
        cursor: str | None = None
        seen: list[str] = []
        for _page_number in range(len(expected) + 2):
            page, cursor = await store.query(ObjectQuery(limit=limit, cursor=cursor))
            seen.extend(row.id for row in page)
            if cursor is None:
                break
        else:
            raise AssertionError("object single-column ordering walk did not terminate")
        assert seen == expected
        assert len(seen) == len(set(seen))


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_object_single_column_ordering_witness(
    kind: str,
    forced_keyset_plan: Callable[[object], AbstractAsyncContextManager[None]],
) -> None:
    async with _store(kind) as store:
        expected = sorted(new_id("obj") for _ in range(ROW_COUNT))
        for index, object_id in enumerate(reversed(expected)):
            await store.upsert(_object(object_id, index))

        if kind == "postgres":
            async with forced_keyset_plan(store):
                await _assert_walk(store, expected)
        else:
            await _assert_walk(store, expected)
