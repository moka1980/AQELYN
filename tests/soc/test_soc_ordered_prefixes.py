"""ECR-0098 ordered-prefix witnesses for SOC incident reads."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.soc import (
    Incident,
    InMemorySOCStore,
    PostgresSOCStore,
    SOCStore,
    TimelineEntry,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
BASE = datetime(2026, 8, 4, 19, 0, tzinfo=UTC)
ACTOR = ActorRef(actor_type="system", actor_id="ecr0098-soc")
ROW_COUNT = 6


def _incident(*, incident_id: str, priority: float, updated_at: datetime) -> Incident:
    return Incident(
        id=incident_id,
        title="ECR-0098 incident",
        status="new",
        priority=priority,
        risk_score=priority,
        timeline=[
            TimelineEntry(
                at=BASE,
                actor=ACTOR,
                kind="created",
                detail={"source": "ecr0098"},
            )
        ],
        created_by=ACTOR,
        created_at=BASE,
        updated_at=updated_at,
    )


async def _stores(kind: str) -> AsyncIterator[SOCStore]:
    if kind == "inmemory":
        yield InMemorySOCStore()
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresSOCStore.connect(PG_URL)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_soc_incident, aq_soc_alert")
    try:
        yield store
    finally:
        await store.close()


async def _assert_prefixes(store: SOCStore, expected: list[str]) -> None:
    held = await store.query_incidents(tenant_id=None, limit=len(expected))
    assert len(held) == len(expected), "SOC incident fixture lost rows"
    for limit in range(1, len(expected) + 1):
        rows = await store.query_incidents(tenant_id=None, limit=limit)
        assert [row.id for row in rows] == expected[:limit]


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_soc_incident_query_ordered_prefixes(
    kind: str,
    forced_keyset_plan: Callable[[object], AbstractAsyncContextManager[None]],
) -> None:
    ids = sorted(new_id("inc") for _ in range(ROW_COUNT))
    # Priority, update time, and ID each decide at least one comparison.
    ordering = [
        (60.0, 0),
        (60.0, 0),
        (60.0, 1),
        (50.0, 3),
        (50.0, 2),
        (50.0, 2),
    ]
    records = [
        _incident(
            incident_id=row_id, priority=priority, updated_at=BASE + timedelta(minutes=minute)
        )
        for row_id, (priority, minute) in zip(ids, ordering, strict=True)
    ]
    ordered = sorted(records, key=lambda row: (-row.priority, -row.updated_at.timestamp(), row.id))
    expected = [row.id for row in ordered]
    async for store in _stores(kind):
        for record in reversed(ordered):
            await store.upsert_incident(record)
        if kind == "postgres":
            async with forced_keyset_plan(store):
                await _assert_prefixes(store, expected)
        else:
            await _assert_prefixes(store, expected)
