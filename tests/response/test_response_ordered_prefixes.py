"""ECR-0098 ordered-prefix witnesses for response campaign reads."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.response import (
    CampaignStore,
    InMemoryCampaignStore,
    Phase,
    PostgresCampaignStore,
    ResponseCampaign,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
BASE = datetime(2026, 8, 4, 11, 0, tzinfo=UTC)
ACTOR = ActorRef(actor_type="system", actor_id="ecr0098-response")
ROW_COUNT = 6


def _campaign(*, campaign_id: str, updated_at: datetime) -> ResponseCampaign:
    return ResponseCampaign(
        id=campaign_id,
        phases=[Phase(name="contain", order=1)],
        created_by=ACTOR,
        created_at=BASE,
        updated_at=updated_at,
    )


async def _stores(kind: str) -> AsyncIterator[CampaignStore]:
    if kind == "inmemory":
        yield InMemoryCampaignStore()
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresCampaignStore.connect(PG_URL)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_response_campaign")
    try:
        yield store
    finally:
        await store.close()


async def _assert_prefixes(store: CampaignStore, expected: list[str]) -> None:
    held = await store.query(tenant_id=None, limit=len(expected))
    assert len(held) == len(expected), "campaign fixture lost rows"
    for limit in range(1, len(expected) + 1):
        rows = await store.query(tenant_id=None, limit=limit)
        assert [row.id for row in rows] == expected[:limit]


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_campaign_query_ordered_prefixes(
    kind: str,
    forced_keyset_plan: Callable[[object], AbstractAsyncContextManager[None]],
) -> None:
    ids = sorted(new_id("rsp") for _ in range(ROW_COUNT))
    records = [
        _campaign(campaign_id=row_id, updated_at=BASE + timedelta(minutes=index // 2))
        for index, row_id in enumerate(ids)
    ]
    ordered = sorted(records, key=lambda row: (-row.updated_at.timestamp(), row.id))
    expected = [row.id for row in ordered]
    async for store in _stores(kind):
        for record in reversed(ordered):
            await store.upsert(record)
        if kind == "postgres":
            async with forced_keyset_plan(store):
                await _assert_prefixes(store, expected)
        else:
            await _assert_prefixes(store, expected)
