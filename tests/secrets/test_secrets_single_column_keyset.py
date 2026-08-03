"""ECR-0096 ordering witnesses for the secrets single-column keyset."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from typing import Protocol, cast

import pytest

from aqelyn.conventions import new_id
from aqelyn.secrets import (
    CryptoQuery,
    CryptoStore,
    InMemoryCryptoStore,
    PostgresCryptoStore,
    SecretAsset,
    SecretLocation,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000960201"
ROW_COUNT = 6


class _Closable(Protocol):
    async def close(self) -> None: ...


@asynccontextmanager
async def _store(kind: str) -> AsyncIterator[CryptoStore]:
    if kind == "inmemory":
        yield InMemoryCryptoStore(mode="enterprise")
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    postgres = await PostgresCryptoStore.connect(PG_URL, mode="enterprise")
    async with postgres._pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE aq_crypto_asset_revision, aq_crypto_asset_identity, "
            "aq_crypto_assessment RESTART IDENTITY CASCADE"
        )
    try:
        yield postgres
    finally:
        await cast(_Closable, postgres).close()


def _asset(asset_id: str, index: int) -> SecretAsset:
    return SecretAsset(
        id=asset_id,
        tenant_id=TENANT,
        object_id=new_id("obj"),
        inventory_ref=new_id("ast"),
        kind="api_key",
        fingerprint=f"hmac-sha256:{index + 9600:064x}",
        location=SecretLocation(
            kind="configuration",
            resource_ref=f"app://ecr0096/{index}",
        ),
        rotation={"reason": "Not assessed by this ordering witness."},
        claim_confidence=1.0,
        source_id=new_id("src"),
        detected_at=NOW,
        evidence_id=new_id("evd"),
    )


async def _assert_walk(store: CryptoStore, expected: list[str]) -> None:
    held, held_cursor = await store.query_assets(CryptoQuery(tenant_id=TENANT, limit=len(expected)))
    assert len(held) == len(expected), "secrets fixture did not retain its full population"
    assert held_cursor is None

    for limit in range(1, len(expected) + 1):
        cursor: str | None = None
        seen: list[str] = []
        for _page_number in range(len(expected) + 2):
            page, cursor = await store.query_assets(
                CryptoQuery(tenant_id=TENANT, limit=limit, cursor=cursor)
            )
            seen.extend(row.id for row in page)
            if cursor is None:
                break
        else:
            raise AssertionError("secrets single-column keyset walk did not terminate")
        assert seen == expected
        assert len(seen) == len(set(seen))


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_secrets_single_column_keyset_ordering_witness(
    kind: str,
    forced_keyset_plan: Callable[[object], AbstractAsyncContextManager[None]],
) -> None:
    async with _store(kind) as store:
        expected = sorted(new_id("sct") for _ in range(ROW_COUNT))
        for index, asset_id in enumerate(reversed(expected)):
            await store.put_asset(_asset(asset_id, index))

        if kind == "postgres":
            # DISTINCT ON already orders the CTE by id. The behavioral output
            # cannot distinguish deletion of the identical outer order clause;
            # the executed SQL is pinned by the central ECR-0096 AST guard.
            async with forced_keyset_plan(store):
                await _assert_walk(store, expected)
        else:
            await _assert_walk(store, expected)
