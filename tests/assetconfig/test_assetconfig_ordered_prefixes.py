"""ECR-0098 ordered-prefix witnesses for drift snapshot history."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta

import pytest

from aqelyn.assetconfig import (
    ASSET_OBJECT_TYPE,
    AssetDrift,
    DriftSnapshot,
    DriftSnapshotStore,
    InMemoryDriftSnapshotStore,
    ObjectTypeAssessmentCoverage,
    PostgresDriftSnapshotStore,
)
from aqelyn.conventions import new_id

PG_URL = os.getenv("AQELYN_DATABASE_URL")
BASE = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
ROW_COUNT = 6


def _snapshot(*, snapshot_id: str, run_at: datetime) -> DriftSnapshot:
    asset_id = new_id("obj")
    return DriftSnapshot(
        id=snapshot_id,
        run_at=run_at,
        scope={"object_type": ASSET_OBJECT_TYPE},
        baseline_ids=["ecr0098-baseline"],
        overall_score=1.0,
        asset_drifts=[
            AssetDrift(
                asset_id=asset_id,
                baseline_id="ecr0098-baseline",
                evaluated=1,
                passed=1,
                failed=0,
                score=1.0,
            )
        ],
        coverage_complete=True,
        objects_in_scope=1,
        objects_assessed=1,
        coverage_by_object_type=[
            ObjectTypeAssessmentCoverage(
                object_type=ASSET_OBJECT_TYPE,
                objects_in_scope=1,
                objects_assessed=1,
            )
        ],
    )


async def _stores(kind: str) -> AsyncIterator[DriftSnapshotStore]:
    if kind == "inmemory":
        yield InMemoryDriftSnapshotStore()
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresDriftSnapshotStore.connect(PG_URL)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_acg_drift_snapshot")
    try:
        yield store
    finally:
        await store.close()


async def _assert_prefixes(store: DriftSnapshotStore, expected: list[str]) -> None:
    held = await store.history(tenant_id=None, limit=len(expected))
    assert len(held) == len(expected), "drift snapshot fixture lost rows"
    for limit in range(1, len(expected) + 1):
        rows = await store.history(tenant_id=None, limit=limit)
        assert [row.id for row in rows] == expected[:limit]


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_drift_snapshot_history_ordered_prefixes(
    kind: str,
    forced_keyset_plan: Callable[[object], AbstractAsyncContextManager[None]],
) -> None:
    ids = [f"ecr0098-drift-{index}" for index in range(ROW_COUNT)]
    # Leading-key groups descend across ascending IDs; IDs still decide each tie.
    records = [
        _snapshot(
            snapshot_id=row_id,
            run_at=BASE + timedelta(minutes=((ROW_COUNT // 2) - 1) - (index // 2)),
        )
        for index, row_id in enumerate(ids)
    ]
    ordered = sorted(records, key=lambda row: (row.run_at, row.id))
    expected = [row.id for row in ordered]
    async for store in _stores(kind):
        for record in reversed(ordered):
            await store.put(record)
        if kind == "postgres":
            async with forced_keyset_plan(store):
                await _assert_prefixes(store, expected)
        else:
            await _assert_prefixes(store, expected)
