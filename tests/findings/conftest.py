"""Fixtures: finding_store parametrized over in-memory and Postgres."""

import os
from collections.abc import AsyncIterator

import pytest

from aqelyn.findings import InMemoryFindingStore

PG_URL = os.getenv("AQELYN_DATABASE_URL")


async def _yes(_eid: str) -> bool:
    return True


@pytest.fixture(params=["inmemory", "postgres"])
async def finding_store(request: pytest.FixtureRequest) -> AsyncIterator[object]:
    if request.param == "inmemory":
        yield InMemoryFindingStore(mode="local", evidence_exists=_yes)
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    from aqelyn.findings.postgres import PostgresFindingStore

    store = await PostgresFindingStore.connect(PG_URL, mode="local", evidence_exists=_yes)
    async with store._pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE aq_finding_audit, aq_finding_evidence, aq_finding_asset, aq_finding "
            "RESTART IDENTITY"
        )
    try:
        yield store
    finally:
        await store.close()
