"""ECR-0097 ordering witnesses for the DSPM single-column read."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from typing import Protocol, cast

import pytest

from aqelyn.conventions import new_id
from aqelyn.dspm import (
    DataAsset,
    DataStoreLocation,
    DSPMStore,
    InMemoryDSPMStore,
    PostgresDSPMStore,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000970201"
ROW_COUNT = 6


class _Closable(Protocol):
    async def close(self) -> None: ...


@asynccontextmanager
async def _store(kind: str) -> AsyncIterator[DSPMStore]:
    if kind == "inmemory":
        yield InMemoryDSPMStore(mode="enterprise")
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    postgres = await PostgresDSPMStore.connect(PG_URL, mode="enterprise")
    async with postgres._pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE aq_dspm_assessment, aq_dspm_exposure, aq_dspm_asset, aq_dspm_asset_key"
        )
    try:
        yield postgres
    finally:
        await cast(_Closable, postgres).close()


def _asset(asset_id: str, index: int) -> DataAsset:
    # DSPM also enforces a tenant/store_id natural key, so each row must carry
    # a distinct store_id before the N-row assertion can prove the fixture.
    return DataAsset(
        id=asset_id,
        object_id=new_id("obj"),
        inventory_ref=new_id("ast"),
        tenant_id=TENANT,
        store_id=f"ecr0097-store-{index}",
        store_type="bucket",
        location=DataStoreLocation(
            provider="aws",
            resource_ref=f"arn:aws:s3:::ecr0097-{index}",
        ),
        classification_status="unknown",
        flagged=True,
        observed_at=NOW,
        evidence_id=new_id("evd"),
    )


async def _assert_walk(store: DSPMStore, expected: list[str]) -> None:
    held, held_cursor = await store.query_assets(tenant_id=TENANT, limit=len(expected))
    assert len(held) == len(expected), "DSPM fixture did not retain its full population"
    assert held_cursor is None

    for limit in range(1, len(expected) + 1):
        cursor: str | None = None
        seen: list[str] = []
        for _page_number in range(len(expected) + 2):
            page, cursor = await store.query_assets(
                tenant_id=TENANT,
                limit=limit,
                cursor=cursor,
            )
            seen.extend(row.id for row in page)
            if cursor is None:
                break
        else:
            raise AssertionError("DSPM single-column ordering walk did not terminate")
        assert seen == expected
        assert len(seen) == len(set(seen))


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_dspm_single_column_ordering_witness(
    kind: str,
    forced_keyset_plan: Callable[[object], AbstractAsyncContextManager[None]],
) -> None:
    async with _store(kind) as store:
        expected = sorted(new_id("dsa") for _ in range(ROW_COUNT))
        for index, asset_id in enumerate(reversed(expected)):
            await store.put_asset(_asset(asset_id, index))

        if kind == "postgres":
            # DISTINCT ON already emits id order. The central ECR-0097 AST
            # guard pins the otherwise behaviorally unobservable outer clause.
            async with forced_keyset_plan(store):
                await _assert_walk(store, expected)
        else:
            await _assert_walk(store, expected)
