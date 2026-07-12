"""Fixtures: evidence_store parametrized over in-memory and Postgres."""

import os
from collections.abc import AsyncIterator

import pytest

from aqelyn.evidence import InMemoryEvidenceStore

PG_URL = os.getenv("AQELYN_DATABASE_URL")


@pytest.fixture(params=["inmemory", "postgres"])
async def evidence_store(request: pytest.FixtureRequest) -> AsyncIterator[object]:
    if request.param == "inmemory":
        yield InMemoryEvidenceStore(mode="local")
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    from aqelyn.evidence.postgres import PostgresEvidenceStore

    store = await PostgresEvidenceStore.connect(PG_URL, mode="local")
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_evidence, aq_evidence_custody, aq_evidence_package")
    try:
        yield store
    finally:
        await store.close()
