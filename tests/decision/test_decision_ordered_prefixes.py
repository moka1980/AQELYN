"""ECR-0098 ordered-prefix witnesses for recommendation reads."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta

import pytest

from aqelyn.conventions import new_id
from aqelyn.decision import (
    ClaimRef,
    DerivationStep,
    InMemoryRecommendationStore,
    Recommendation,
    RecommendationStore,
    build_derivation,
)
from aqelyn.decision.postgres import PostgresRecommendationStore

PG_URL = os.getenv("AQELYN_DATABASE_URL")
BASE = datetime(2026, 8, 4, 8, 0, tzinfo=UTC)
ROW_COUNT = 6


def _recommendation(*, recommendation_id: str, created_at: datetime) -> Recommendation:
    claim = ClaimRef(kind="finding", ref_id=f"finding:{recommendation_id}")
    output = {"claims": [claim.model_dump(mode="json")], "count": 1}
    return Recommendation(
        id=recommendation_id,
        subject_ref=f"case:{recommendation_id}",
        statement="Review the cited finding before taking action.",
        confidence=0.8,
        derivation=build_derivation(
            inputs=[claim],
            steps=[
                DerivationStep(
                    seq=1,
                    op="select_claims",
                    input_refs=[claim.ref_id],
                    params={"kinds": ["finding"]},
                    output=output,
                    note="Select the cited finding.",
                )
            ],
            model_version=1,
            engine_version="ecr0098/v1",
        ),
        created_at=created_at,
    )


async def _stores(kind: str) -> AsyncIterator[RecommendationStore]:
    if kind == "inmemory":
        yield InMemoryRecommendationStore()
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresRecommendationStore.connect(PG_URL)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_decision_recommendation")
    try:
        yield store
    finally:
        await store.close()


async def _assert_prefixes(store: RecommendationStore, expected: list[str]) -> None:
    held = await store.query(limit=len(expected))
    assert len(held) == len(expected), "recommendation fixture lost rows"
    for limit in range(1, len(expected) + 1):
        rows = await store.query(limit=limit)
        assert [row.id for row in rows] == expected[:limit]


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_recommendation_query_ordered_prefixes(
    kind: str,
    forced_keyset_plan: Callable[[object], AbstractAsyncContextManager[None]],
) -> None:
    expected = sorted(new_id("rec") for _ in range(ROW_COUNT))
    records = [
        _recommendation(recommendation_id=row_id, created_at=BASE + timedelta(minutes=index))
        for index, row_id in enumerate(expected)
    ]
    async for store in _stores(kind):
        for record in reversed(records):
            await store.put(record)
        if kind == "postgres":
            async with forced_keyset_plan(store):
                await _assert_prefixes(store, expected)
        else:
            await _assert_prefixes(store, expected)
