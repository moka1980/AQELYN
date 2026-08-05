"""ECR-0098 ordered-prefix witnesses for exposure reads."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta

import pytest

from aqelyn.conventions import new_id
from aqelyn.exposure import (
    AssetRef,
    ExposureBasis,
    ExposureRecord,
    ExposureStore,
    InMemoryExposureStore,
    PostgresExposureStore,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
BASE = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
ROW_COUNT = 6


def _record(*, exposure_id: str, discovered_at: datetime) -> ExposureRecord:
    return ExposureRecord(
        id=exposure_id,
        asset_ref=AssetRef(kind="asset", ref_id=f"asset:{exposure_id}"),
        exposure_type="reachable_service",
        reachability="unknown",
        basis=[
            ExposureBasis(
                kind="inventory",
                ref=f"inventory:{exposure_id}",
                as_of=discovered_at,
            )
        ],
        rationale="Known inventory does not establish reachability.",
        flagged=True,
        discovered_at=discovered_at,
    )


async def _stores(kind: str) -> AsyncIterator[ExposureStore]:
    if kind == "inmemory":
        yield InMemoryExposureStore()
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresExposureStore.connect(PG_URL)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_exposure_record")
    try:
        yield store
    finally:
        await store.close()


async def _assert_prefixes(store: ExposureStore, expected: list[str]) -> None:
    held = await store.query(tenant_id=None, limit=len(expected))
    assert len(held) == len(expected), "exposure fixture lost rows"
    for limit in range(1, len(expected) + 1):
        rows = await store.query(tenant_id=None, limit=limit)
        assert [row.id for row in rows] == expected[:limit]


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_exposure_query_ordered_prefixes(
    kind: str,
    forced_keyset_plan: Callable[[object], AbstractAsyncContextManager[None]],
) -> None:
    expected = sorted(new_id("exp") for _ in range(ROW_COUNT))
    records = [
        _record(exposure_id=row_id, discovered_at=BASE + timedelta(minutes=index // 2))
        for index, row_id in enumerate(expected)
    ]
    async for store in _stores(kind):
        for record in reversed(records):
            await store.put(record)
        if kind == "postgres":
            async with forced_keyset_plan(store):
                await _assert_prefixes(store, expected)
        else:
            await _assert_prefixes(store, expected)
