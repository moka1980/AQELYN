"""C-038/R3: orderings on a non-unique key are deterministic and agree across backends.

The EA-0013 backlog item was *equal timestamps produce nondeterministic ordering*. The
audit found the item **already satisfied**: every SQL ordering in `src/` terminates in a
unique column (`id`, `object_id`, `evidence_id`, `seq`, `source_id` PK, or the lake's
unique `(tenant_id, name)`), and every Python sort key ends in a unique component. No
ordering was left un-tie-broken.

So this pins the property rather than fixing a defect. Which makes the fixtures the
whole point:

> **The rows must carry identical timestamps.** A suite whose timestamps are all
> distinct passes against an un-tie-broken implementation, so it would confirm nothing —
> C-037's inert-control lesson (rule 24) in its next instance. The tie-breaker is
> removed by mutation to prove the fixtures can see it.

The concrete risk this guards is **backend divergence**: Python's `sort` is stable, so
an in-memory store returns insertion order on ties while Postgres returns whatever the
plan yields. The one-contract-suite guarantee exists to catch exactly that, and cannot
if there are no ties to disagree about.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest

from aqelyn.conventions import new_id
from aqelyn.exposure import AssetRef
from aqelyn.vuln import (
    CarriedScore,
    InMemoryVulnerabilityStore,
    PostgresVulnerabilityStore,
    VulnBasis,
    VulnerabilityRecord,
    VulnerabilityStore,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
TIED_AT = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000380101"

BACKENDS = [
    pytest.param("inmemory", id="inmemory"),
    pytest.param("postgres", id="postgres"),
]


def _record(*, vulnerability_id: str, discovered_at: datetime) -> VulnerabilityRecord:
    return VulnerabilityRecord(
        id=vulnerability_id,
        tenant_id=TENANT,
        cve_id="CVE-2026-4242",
        scanner="nessus",
        asset_ref=AssetRef(kind="asset", ref_id="asset:web-1"),
        severity="high",
        cvss=CarriedScore(
            source="nvd:cve-2026-4242",
            value=9.8,
            vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
            as_of=discovered_at,
        ),
        epss=CarriedScore(source="first:epss:2026-07-20", value=0.73, as_of=discovered_at),
        confidence=0.84,
        basis=[
            VulnBasis(
                kind="scanner",
                ref=f"scanner:nessus:{vulnerability_id}",
                as_of=discovered_at,
            )
        ],
        discovered_at=discovered_at,
    )


@asynccontextmanager
async def _store(backend: str) -> AsyncIterator[VulnerabilityStore]:
    if backend == "inmemory":
        yield InMemoryVulnerabilityStore(mode="enterprise")
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    pg = await PostgresVulnerabilityStore.connect(PG_URL, mode="enterprise")
    async with pg._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_vulnerability RESTART IDENTITY CASCADE")
    try:
        yield pg
    finally:
        await pg.close()


async def _write_tied(store: VulnerabilityStore) -> list[str]:
    """Five records sharing one `discovered_at`, inserted in reverse id order.

    Reverse insertion matters for the same reason it did in C-037: `new_id` is
    monotonic, so inserting in id order would let a store that merely preserves
    insertion order satisfy every assertion below.
    """
    ids = sorted(new_id("vln") for _ in range(5))
    for vulnerability_id in reversed(ids):
        await store.put(_record(vulnerability_id=vulnerability_id, discovered_at=TIED_AT))
    return ids


@pytest.mark.parametrize("backend", BACKENDS)
async def test_vuln_order_deterministic_on_ties(backend: str) -> None:
    """Identical timestamps still produce one stable order, repeated reads agreeing."""
    async with _store(backend) as store:
        expected = await _write_tied(store)

        first = [row.id for row in await store.query(tenant_id=TENANT, limit=10)]
        second = [row.id for row in await store.query(tenant_id=TENANT, limit=10)]

        assert first == expected, "tied rows are not ordered by the unique secondary key"
        assert first == second, "repeated reads disagreed on tied rows"


@pytest.mark.parametrize("backend", BACKENDS)
async def test_vuln_order_ties_are_actually_tied(backend: str) -> None:
    """Guard the guard: if the fixtures stop tying, the tests above prove nothing."""
    async with _store(backend) as store:
        await _write_tied(store)

        rows = await store.query(tenant_id=TENANT, limit=10)

        assert len({row.discovered_at for row in rows}) == 1, (
            "fixtures no longer share a timestamp -- these tests can no longer see a "
            "missing tie-breaker (rule 24)"
        )
        assert len(rows) == 5


async def test_vuln_order_backends_agree_on_ties() -> None:
    """Both backends return the same order for the same tied input.

    This is the divergence the one-contract-suite guarantee exists to catch: stable
    Python sort versus whatever the query plan yields.
    """
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    async with _store("inmemory") as memory_store:
        memory_ids = await _write_tied(memory_store)
        memory_order = [row.id for row in await memory_store.query(tenant_id=TENANT, limit=10)]

    async with _store("postgres") as pg_store:
        for vulnerability_id in reversed(memory_ids):
            await pg_store.put(_record(vulnerability_id=vulnerability_id, discovered_at=TIED_AT))
        pg_order = [row.id for row in await pg_store.query(tenant_id=TENANT, limit=10)]

    assert memory_order == pg_order
