"""ECR-0098 ordered-prefix witnesses for risk reads."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta

import pytest

from aqelyn.conventions import new_id
from aqelyn.risk import (
    InMemoryRiskSnapshotStore,
    InMemoryRiskStore,
    Risk,
    RiskSnapshot,
    RiskSnapshotStore,
    RiskStore,
    new_risk_snapshot_id,
)
from aqelyn.risk.postgres import PostgresRiskSnapshotStore, PostgresRiskStore

PG_URL = os.getenv("AQELYN_DATABASE_URL")
BASE = datetime(2026, 8, 4, 18, 0, tzinfo=UTC)
ROW_COUNT = 6


def _risk(*, risk_id: str, score: float, index: int) -> Risk:
    return Risk.model_validate(
        {
            "id": risk_id,
            "correlation_key": f"ecr0098:{index}",
            "title": f"ECR-0098 risk {index}",
            "category": "governance",
            "likelihood": 0.4,
            "impact": 0.2,
            "score": score,
            "band": "elevated",
            "signals": [
                {
                    "kind": "finding",
                    "ref_id": new_id("fnd"),
                    "weight": 0.5,
                    "evidence_id": new_id("evd"),
                }
            ],
            "affected_object_ids": [new_id("obj")],
            "lifecycle": "identified",
            "treatment": "none",
            "reason": "ECR-0098 ordering witness.",
            "factors": {"likelihood": 0.4, "impact": 0.2},
            "first_seen_at": BASE,
            "last_scored_at": BASE,
            "version": 1,
        }
    )


async def _risk_stores(kind: str) -> AsyncIterator[RiskStore]:
    if kind == "inmemory":
        yield InMemoryRiskStore()
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresRiskStore.connect(PG_URL)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_risk_snapshot, aq_risk")
    try:
        yield store
    finally:
        await store.close()


async def _snapshot_stores(kind: str) -> AsyncIterator[RiskSnapshotStore]:
    if kind == "inmemory":
        yield InMemoryRiskSnapshotStore()
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresRiskSnapshotStore.connect(PG_URL)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_risk_snapshot, aq_risk")
    try:
        yield store
    finally:
        await store.close()


async def _assert_risk_prefixes(store: RiskStore, expected: list[str]) -> None:
    held = await store.query(tenant_id=None, limit=len(expected))
    assert len(held) == len(expected), "risk fixture lost rows"
    for limit in range(1, len(expected) + 1):
        rows = await store.query(tenant_id=None, limit=limit)
        assert [row.id for row in rows] == expected[:limit]


async def _assert_snapshot_prefixes(store: RiskSnapshotStore, expected: list[str]) -> None:
    held = await store.history(tenant_id=None, limit=len(expected))
    assert len(held) == len(expected), "risk snapshot fixture lost rows"
    for limit in range(1, len(expected) + 1):
        rows = await store.history(tenant_id=None, limit=limit)
        assert [row.id for row in rows] == expected[:limit]


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_risk_query_ordered_prefixes(
    kind: str,
    forced_keyset_plan: Callable[[object], AbstractAsyncContextManager[None]],
) -> None:
    records = [
        _risk(risk_id=f"risk:ecr0098:{index}", score=10.0 + index, index=index)
        for index in range(ROW_COUNT)
    ]
    ordered = sorted(records, key=lambda row: (-row.score, row.id))
    expected = [row.id for row in ordered]
    async for store in _risk_stores(kind):
        for record in reversed(ordered):
            await store.upsert(record)
        if kind == "postgres":
            async with forced_keyset_plan(store):
                await _assert_risk_prefixes(store, expected)
        else:
            await _assert_risk_prefixes(store, expected)


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_risk_snapshot_history_ordered_prefixes(
    kind: str,
    forced_keyset_plan: Callable[[object], AbstractAsyncContextManager[None]],
) -> None:
    records = [
        RiskSnapshot(
            id=new_risk_snapshot_id(),
            run_at=BASE + timedelta(minutes=index),
            total=0,
            overall_exposure=0.0,
        )
        for index in range(ROW_COUNT)
    ]
    expected = [row.id for row in records]
    async for store in _snapshot_stores(kind):
        for record in reversed(records):
            await store.put(record)
        if kind == "postgres":
            async with forced_keyset_plan(store):
                await _assert_snapshot_prefixes(store, expected)
        else:
            await _assert_snapshot_prefixes(store, expected)
