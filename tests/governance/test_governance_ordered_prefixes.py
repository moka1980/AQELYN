"""ECR-0098 ordered-prefix witnesses for compliance snapshot history."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta

import pytest

from aqelyn.conventions import new_id
from aqelyn.governance import (
    ComplianceSnapshot,
    InMemorySnapshotStore,
    PostgresSnapshotStore,
    SnapshotStore,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
BASE = datetime(2026, 8, 4, 13, 0, tzinfo=UTC)
ROW_COUNT = 6


async def _stores(kind: str) -> AsyncIterator[SnapshotStore]:
    if kind == "inmemory":
        yield InMemorySnapshotStore()
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresSnapshotStore.connect(PG_URL)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_compliance_snapshot")
    try:
        yield store
    finally:
        await store.close()


async def _assert_prefixes(store: SnapshotStore, expected: list[str]) -> None:
    held = await store.history(tenant_id=None, limit=len(expected))
    assert len(held) == len(expected), "compliance snapshot fixture lost rows"
    for limit in range(1, len(expected) + 1):
        rows = await store.history(tenant_id=None, limit=limit)
        assert [row.id for row in rows] == expected[:limit]


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_compliance_snapshot_history_ordered_prefixes(
    kind: str,
    forced_keyset_plan: Callable[[object], AbstractAsyncContextManager[None]],
) -> None:
    ids = sorted(new_id("snap") for _ in range(ROW_COUNT))
    # Leading-key groups descend across ascending IDs; IDs still decide each tie.
    records = [
        ComplianceSnapshot(
            id=row_id,
            run_at=BASE + timedelta(minutes=((ROW_COUNT // 2) - 1) - (index // 2)),
            overall_score=1.0,
        )
        for index, row_id in enumerate(ids)
    ]
    ordered = sorted(records, key=lambda row: (row.run_at, row.id))
    expected = [row.id for row in ordered]
    async for store in _stores(kind):
        for record in reversed(ordered):
            await store.put(record)
        if kind == "postgres":
            async with forced_keyset_plan(store):
                await _assert_prefixes(store, expected)
        else:
            await _assert_prefixes(store, expected)
