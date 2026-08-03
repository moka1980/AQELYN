"""ECR-0096 ordering witnesses for the inventory single-column keyset."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from typing import Protocol, cast

import pytest

from aqelyn.conventions import new_id
from aqelyn.inventory import (
    AssetBasis,
    AssetRecord,
    AssetStore,
    InMemoryAssetStore,
    PostgresAssetStore,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000960101"
ROW_COUNT = 6


class _Closable(Protocol):
    async def close(self) -> None: ...


@asynccontextmanager
async def _store(kind: str) -> AsyncIterator[AssetStore]:
    if kind == "inmemory":
        yield InMemoryAssetStore(mode="enterprise")
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    postgres = await PostgresAssetStore.connect(PG_URL, mode="enterprise")
    async with postgres._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_inventory_asset_history, aq_inventory_asset")
    try:
        yield postgres
    finally:
        await cast(_Closable, postgres).close()


def _asset(asset_id: str, index: int) -> AssetRecord:
    return AssetRecord(
        id=asset_id,
        tenant_id=TENANT,
        asset_type="server",
        discovery_source=f"src:ecr0096:{index}",
        confidence=1.0,
        basis=[
            AssetBasis(
                kind="discovery",
                ref=f"ecr0096:inventory:{index}",
                as_of=NOW,
                evidence_id=new_id("evd"),
            )
        ],
        first_seen_at=NOW,
        last_reported_at=NOW,
    )


async def _assert_walk(store: AssetStore, expected: list[str]) -> None:
    held, held_cursor = await store.query(tenant_id=TENANT, limit=len(expected))
    assert len(held) == len(expected), "inventory fixture did not retain its full population"
    assert held_cursor is None

    for limit in range(1, len(expected) + 1):
        cursor: str | None = None
        seen: list[str] = []
        for _page_number in range(len(expected) + 2):
            page, cursor = await store.query(
                tenant_id=TENANT,
                limit=limit,
                cursor=cursor,
            )
            seen.extend(row.id for row in page)
            if cursor is None:
                break
        else:
            raise AssertionError("inventory single-column keyset walk did not terminate")
        assert seen == expected
        assert len(seen) == len(set(seen))


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_inventory_single_column_keyset_ordering_witness(
    kind: str,
    forced_keyset_plan: Callable[[object], AbstractAsyncContextManager[None]],
) -> None:
    async with _store(kind) as store:
        expected = sorted(new_id("ast") for _ in range(ROW_COUNT))
        for index, asset_id in enumerate(reversed(expected)):
            await store.put(_asset(asset_id, index))

        if kind == "postgres":
            async with forced_keyset_plan(store):
                await _assert_walk(store, expected)
        else:
            await _assert_walk(store, expected)
