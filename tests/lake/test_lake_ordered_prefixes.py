"""ECR-0098 ordered-prefix witnesses for lake reads."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta

import pytest

from aqelyn.conventions import new_id
from aqelyn.lake import (
    InMemoryTelemetryRecordStore,
    Quarantine,
    TelemetryRecord,
    TelemetryRecordStore,
)
from aqelyn.lake.postgres import PostgresTelemetryRecordStore

PG_URL = os.getenv("AQELYN_DATABASE_URL")
BASE = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)
ROW_COUNT = 6


async def _stores(kind: str) -> AsyncIterator[TelemetryRecordStore]:
    if kind == "inmemory":
        yield InMemoryTelemetryRecordStore()
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresTelemetryRecordStore.connect(PG_URL)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_lake_quarantine, aq_lake_record RESTART IDENTITY")
    try:
        yield store
    finally:
        await store.close()


async def _assert_record_prefixes(store: TelemetryRecordStore, expected: list[str]) -> None:
    held = await store.query(dataset="endpoint_process", tenant_id=None, limit=len(expected))
    assert len(held) == len(expected), "telemetry fixture lost rows"
    for limit in range(1, len(expected) + 1):
        rows = await store.query(dataset="endpoint_process", tenant_id=None, limit=limit)
        assert [row.id for row in rows] == expected[:limit]


async def _assert_quarantine_prefixes(
    store: TelemetryRecordStore, expected: list[str]
) -> None:
    held = await store.list_quarantine(tenant_id=None, limit=len(expected))
    assert len(held) == len(expected), "quarantine fixture lost rows"
    for limit in range(1, len(expected) + 1):
        rows = await store.list_quarantine(tenant_id=None, limit=limit)
        assert [row.source_id for row in rows] == expected[:limit]


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_lake_query_ordered_prefixes(
    kind: str,
    forced_keyset_plan: Callable[[object], AbstractAsyncContextManager[None]],
) -> None:
    expected = sorted(new_id("tlm") for _ in range(ROW_COUNT))
    records = [
        TelemetryRecord(
            id=row_id,
            dataset="endpoint_process",
            source_id=new_id("src"),
            occurred_at=BASE + timedelta(minutes=index),
            ingested_at=BASE + timedelta(minutes=index),
            fields={"pid": index},
        )
        for index, row_id in enumerate(expected)
    ]
    async for store in _stores(kind):
        for record in reversed(records):
            await store.append(record)
        if kind == "postgres":
            async with forced_keyset_plan(store):
                await _assert_record_prefixes(store, expected)
        else:
            await _assert_record_prefixes(store, expected)


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_lake_quarantine_ordered_prefixes(
    kind: str,
    forced_keyset_plan: Callable[[object], AbstractAsyncContextManager[None]],
) -> None:
    source_ids = [new_id("src") for _ in range(ROW_COUNT)]
    minute_offsets = [2, 0, 0, 3, 1, 1]
    items = [
        Quarantine(
            source_id=source_id,
            reason=f"reason-{index}",
            received_at=BASE + timedelta(minutes=minute_offsets[index]),
        )
        for index, source_id in enumerate(source_ids)
    ]
    expected = [source_ids[index] for index in (1, 2, 4, 5, 0, 3)]
    async for store in _stores(kind):
        for item in items:
            await store.quarantine(item, tenant_id=None)
        if kind == "postgres":
            async with forced_keyset_plan(store):
                await _assert_quarantine_prefixes(store, expected)
        else:
            await _assert_quarantine_prefixes(store, expected)
