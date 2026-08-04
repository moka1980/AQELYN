"""ECR-0097 ordering witnesses for the Workflow bounded list read."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from typing import Protocol, cast

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.workflow import InMemoryRunStore, PostgresRunStore, Run, RunStore

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000970401"
ACTOR = ActorRef(actor_type="system", actor_id="ecr0097-workflow-ordering")
ROW_COUNT = 6


class _Closable(Protocol):
    async def close(self) -> None: ...


@asynccontextmanager
async def _store(kind: str) -> AsyncIterator[RunStore]:
    if kind == "inmemory":
        yield InMemoryRunStore(mode="enterprise")
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    postgres = await PostgresRunStore.connect(PG_URL, mode="enterprise")
    async with postgres._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_workflow_run")
    try:
        yield postgres
    finally:
        await cast(_Closable, postgres).close()


def _run(run_id: str, index: int) -> Run:
    # RunStore.create rejects duplicate IDs and has no secondary natural key.
    # Distinct playbooks make the fixture's six independent runs explicit.
    return Run(
        id=run_id,
        playbook_id=f"ecr0097-playbook-{index}",
        playbook_version=1,
        tenant_id=TENANT,
        status="proposed",
        source_finding_id=new_id("fnd"),
        created_by=ACTOR,
        created_at=NOW,
        updated_at=NOW,
    )


async def _assert_ordered_prefixes(store: RunStore, expected: list[str]) -> None:
    held = await store.list(tenant_id=TENANT, limit=len(expected))
    assert len(held) == len(expected), "workflow fixture did not retain its full population"

    # RunStore.list is bounded but has no cursor. Its truthful analogue to a
    # keyset walk is to prove every allowed prefix length.
    for limit in range(1, len(expected) + 1):
        page = await store.list(tenant_id=TENANT, limit=limit)
        assert [run.id for run in page] == expected[:limit]


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_workflow_single_column_ordering_witness(
    kind: str,
    forced_keyset_plan: Callable[[object], AbstractAsyncContextManager[None]],
) -> None:
    async with _store(kind) as store:
        expected = sorted(new_id("run") for _ in range(ROW_COUNT))
        for index, run_id in enumerate(reversed(expected)):
            await store.create(_run(run_id, index))

        if kind == "postgres":
            async with forced_keyset_plan(store):
                await _assert_ordered_prefixes(store, expected)
        else:
            await _assert_ordered_prefixes(store, expected)
