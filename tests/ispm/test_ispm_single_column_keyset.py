"""ECR-0096 ordering witnesses for the ISPM single-column keyset."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol, cast

import pytest

from aqelyn.conventions import new_id
from aqelyn.ispm import (
    InMemoryISPMStore,
    ISPMStore,
    NormalizedIdentity,
    PostgresISPMStore,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
TENANT = "018f0000-0000-7000-8000-000000960301"
ROW_COUNT = 6


class _Closable(Protocol):
    async def close(self) -> None: ...


@asynccontextmanager
async def _store(kind: str) -> AsyncIterator[ISPMStore]:
    if kind == "inmemory":
        yield InMemoryISPMStore(mode="enterprise")
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    postgres = await PostgresISPMStore.connect(PG_URL, mode="enterprise")
    async with postgres._pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE aq_ispm_identity_revision, aq_ispm_identity_key RESTART IDENTITY CASCADE"
        )
    try:
        yield postgres
    finally:
        await cast(_Closable, postgres).close()


def _identity(object_id: str, index: int) -> NormalizedIdentity:
    return NormalizedIdentity(
        object_id=object_id,
        tenant_id=TENANT,
        external_id=f"identity:ecr0096:{index}",
        provider="fixture",
        identity_kind="human",
        field_provenance={"identity_kind": f"fixture:/identities/{index}/kind"},
        evidence_id=new_id("evd"),
    )


async def _assert_walk(store: ISPMStore, expected: list[str]) -> None:
    held, held_cursor = await store.query_identities(
        tenant_id=TENANT,
        limit=len(expected),
    )
    assert len(held) == len(expected), "ISPM fixture did not retain its full population"
    assert held_cursor is None

    for limit in range(1, len(expected) + 1):
        cursor: str | None = None
        seen: list[str] = []
        for _page_number in range(len(expected) + 2):
            page, cursor = await store.query_identities(
                tenant_id=TENANT,
                limit=limit,
                cursor=cursor,
            )
            seen.extend(row.object_id for row in page)
            if cursor is None:
                break
        else:
            raise AssertionError("ISPM single-column keyset walk did not terminate")
        assert seen == expected
        assert len(seen) == len(set(seen))


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_ispm_single_column_keyset_ordering_witness(
    kind: str,
    forced_keyset_plan: Callable[[object], AbstractAsyncContextManager[None]],
) -> None:
    async with _store(kind) as store:
        expected = sorted(new_id("obj") for _ in range(ROW_COUNT))
        for index, object_id in enumerate(reversed(expected)):
            await store.upsert_identity(_identity(object_id, index))

        if kind == "postgres":
            # DISTINCT ON already orders the CTE by id. The behavioral output
            # cannot distinguish deletion of the identical outer order clause;
            # the executed SQL is pinned by the central ECR-0096 AST guard.
            async with forced_keyset_plan(store):
                await _assert_walk(store, expected)
        else:
            await _assert_walk(store, expected)
