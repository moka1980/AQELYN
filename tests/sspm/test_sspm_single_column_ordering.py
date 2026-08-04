"""ECR-0097 ordering witnesses for the SSPM single-column read."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol, cast

import pytest

from aqelyn.conventions import new_id
from aqelyn.sspm import (
    InMemorySaaSNormalizationStore,
    NormalizedSaaSObject,
    PostgresSaaSNormalizationStore,
    SaaSNormalizationStore,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
TENANT = "018f0000-0000-7000-8000-000000970301"
ROW_COUNT = 6


class _Closable(Protocol):
    async def close(self) -> None: ...


@asynccontextmanager
async def _store(kind: str) -> AsyncIterator[SaaSNormalizationStore]:
    if kind == "inmemory":
        yield InMemorySaaSNormalizationStore(mode="enterprise")
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    postgres = await PostgresSaaSNormalizationStore.connect(PG_URL, mode="enterprise")
    async with postgres._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_saas_normalization, aq_saas_integration")
    try:
        yield postgres
    finally:
        await cast(_Closable, postgres).close()


def _object(object_id: str, index: int) -> NormalizedSaaSObject:
    return NormalizedSaaSObject(
        object_id=object_id,
        tenant_id=TENANT,
        object_type="saas_app",
        provider="google_workspace",
        tenant=f"ecr0097-{index}.example",
        native_facts={"mfa_enabled": True},
        field_provenance={"mfa_enabled": "/mfa_enabled"},
        evidence_id=new_id("evd"),
    )


async def _assert_walk(store: SaaSNormalizationStore, expected: list[str]) -> None:
    held, held_cursor = await store.query(tenant_id=TENANT, limit=len(expected))
    assert len(held) == len(expected), "SSPM fixture did not retain its full population"
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
            raise AssertionError("SSPM single-column ordering walk did not terminate")
        assert seen == expected
        assert len(seen) == len(set(seen))


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_sspm_single_column_ordering_witness(
    kind: str,
    forced_keyset_plan: Callable[[object], AbstractAsyncContextManager[None]],
) -> None:
    async with _store(kind) as store:
        expected = sorted(new_id("obj") for _ in range(ROW_COUNT))
        for index, object_id in enumerate(reversed(expected)):
            await store.put(_object(object_id, index))

        if kind == "postgres":
            async with forced_keyset_plan(store):
                await _assert_walk(store, expected)
        else:
            await _assert_walk(store, expected)
