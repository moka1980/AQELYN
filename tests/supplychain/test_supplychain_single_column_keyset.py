"""ECR-0096 ordering witnesses for the supply-chain single-column keyset."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from typing import Protocol, cast

import pytest

from aqelyn.conventions import new_id
from aqelyn.supplychain import (
    InMemorySBOMStore,
    PostgresSBOMStore,
    SBOMStore,
    SoftwareComponent,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000960401"
ROW_COUNT = 6


class _Closable(Protocol):
    async def close(self) -> None: ...


@asynccontextmanager
async def _store(kind: str) -> AsyncIterator[SBOMStore]:
    if kind == "inmemory":
        yield InMemorySBOMStore(mode="enterprise")
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    postgres = await PostgresSBOMStore.connect(PG_URL, mode="enterprise")
    async with postgres._pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE aq_supplychain_quarantine, aq_supplychain_assessment, "
            "aq_supplychain_component"
        )
    try:
        yield postgres
    finally:
        await cast(_Closable, postgres).close()


def _component(object_id: str, index: int) -> SoftwareComponent:
    return SoftwareComponent(
        object_id=object_id,
        tenant_id=TENANT,
        identity_kind="purl",
        purl=f"pkg:pypi/ecr0096-{index}@1.0.0",
        name=f"ecr0096-{index}",
        version="1.0.0",
        component_type="library",
        direct=False,
        source_id=new_id("src"),
        observed_at=NOW,
        evidence_id=new_id("evd"),
    )


async def _assert_walk(store: SBOMStore, expected: list[str]) -> None:
    held, held_cursor = await store.query(tenant_id=TENANT, limit=len(expected))
    assert len(held) == len(expected), "supply-chain fixture did not retain its full population"
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
            seen.extend(row.object_id for row in page)
            if cursor is None:
                break
        else:
            raise AssertionError("supply-chain single-column keyset walk did not terminate")
        assert seen == expected
        assert len(seen) == len(set(seen))


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_supplychain_single_column_keyset_ordering_witness(
    kind: str,
    forced_keyset_plan: Callable[[object], AbstractAsyncContextManager[None]],
) -> None:
    async with _store(kind) as store:
        expected = sorted(new_id("obj") for _ in range(ROW_COUNT))
        for index, object_id in enumerate(reversed(expected)):
            await store.put_component(_component(object_id, index))

        if kind == "postgres":
            async with forced_keyset_plan(store):
                await _assert_walk(store, expected)
        else:
            await _assert_walk(store, expected)
