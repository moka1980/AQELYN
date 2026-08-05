"""ECR-0098 ordered-prefix witnesses for vulnerability reads."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta

import pytest

from aqelyn.conventions import new_id
from aqelyn.exposure import AssetRef
from aqelyn.vuln import (
    InMemoryVulnerabilityStore,
    PostgresVulnerabilityStore,
    VulnBasis,
    VulnerabilityRecord,
    VulnerabilityStore,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
BASE = datetime(2026, 8, 4, 15, 0, tzinfo=UTC)
ROW_COUNT = 6


def _record(*, vulnerability_id: str, discovered_at: datetime, index: int) -> VulnerabilityRecord:
    return VulnerabilityRecord(
        id=vulnerability_id,
        cve_id=f"CVE-2026-{5000 + index}",
        scanner="ecr0098",
        asset_ref=AssetRef(kind="asset", ref_id=f"asset:{vulnerability_id}"),
        severity="unknown",
        confidence=0.8,
        basis=[VulnBasis(kind="scanner", ref="scanner:ecr0098", as_of=discovered_at)],
        discovered_at=discovered_at,
    )


async def _stores(kind: str) -> AsyncIterator[VulnerabilityStore]:
    if kind == "inmemory":
        yield InMemoryVulnerabilityStore()
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresVulnerabilityStore.connect(PG_URL)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_vuln_history, aq_vuln_record")
    try:
        yield store
    finally:
        await store.close()


async def _assert_prefixes(store: VulnerabilityStore, expected: list[str]) -> None:
    held = await store.query(tenant_id=None, limit=len(expected))
    assert len(held) == len(expected), "vulnerability fixture lost rows"
    for limit in range(1, len(expected) + 1):
        rows = await store.query(tenant_id=None, limit=limit)
        assert [row.id for row in rows] == expected[:limit]


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_vulnerability_query_ordered_prefixes(
    kind: str,
    forced_keyset_plan: Callable[[object], AbstractAsyncContextManager[None]],
) -> None:
    ids = sorted(new_id("vln") for _ in range(ROW_COUNT))
    # Leading-key groups descend across ascending IDs; IDs still decide each tie.
    records = [
        _record(
            vulnerability_id=row_id,
            discovered_at=BASE + timedelta(minutes=((ROW_COUNT // 2) - 1) - (index // 2)),
            index=index,
        )
        for index, row_id in enumerate(ids)
    ]
    ordered = sorted(records, key=lambda row: (row.discovered_at, row.id))
    expected = [row.id for row in ordered]
    async for store in _stores(kind):
        for record in reversed(ordered):
            await store.put(record)
        if kind == "postgres":
            async with forced_keyset_plan(store):
                await _assert_prefixes(store, expected)
        else:
            await _assert_prefixes(store, expected)
