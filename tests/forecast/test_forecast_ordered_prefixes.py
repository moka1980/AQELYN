"""ECR-0098 ordered-prefix witnesses for forecast reads."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta

import pytest

from aqelyn.conventions import new_id
from aqelyn.decision import ClaimRef, Derivation, DerivationStep
from aqelyn.forecast import (
    BasisRef,
    Forecast,
    ForecastStore,
    InMemoryForecastStore,
    InMemoryPredictionModelStore,
    Interval,
    PostgresForecastStore,
    PostgresPredictionModelStore,
    PredictionModel,
    PredictionModelStore,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
BASE = datetime(2026, 8, 4, 17, 0, tzinfo=UTC)
ROW_COUNT = 6


def _forecast(*, forecast_id: str, issued_at: datetime) -> Forecast:
    interval = Interval(low=9.0, high=15.0, level=0.8)
    output = {"point": 12.0, "interval": interval.model_dump(mode="json")}
    return Forecast(
        id=forecast_id,
        metric="phishing_volume",
        subject_ref="aggregate:phishing_volume",
        method="moving_average",
        model_version=1,
        horizon_days=14,
        issued_at=issued_at,
        resolves_at=issued_at + timedelta(days=14),
        point=12.0,
        interval=interval,
        confidence=0.7,
        basis=[BasisRef(kind="metric", ref="metric:phishing_volume", window={"days": 30})],
        derivation=Derivation(
            inputs=[ClaimRef(kind="risk", ref_id="metric:phishing_volume")],
            steps=[
                DerivationStep(
                    seq=1,
                    op="forecast_result",
                    input_refs=["metric:phishing_volume"],
                    params=output,
                    output=output,
                    note="Return the forecast result.",
                )
            ],
            result=output,
            model_version=1,
            engine_version="forecast-p2/v1",
        ),
        statement="The cited history projects 12.0.",
    )


async def _forecast_stores(kind: str) -> AsyncIterator[ForecastStore]:
    if kind == "inmemory":
        yield InMemoryForecastStore()
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresForecastStore.connect(PG_URL)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_forecast")
    try:
        yield store
    finally:
        await store.close()


async def _model_stores(kind: str) -> AsyncIterator[PredictionModelStore]:
    if kind == "inmemory":
        yield InMemoryPredictionModelStore()
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresPredictionModelStore.connect(PG_URL)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_prediction_model")
    try:
        yield store
    finally:
        await store.close()


async def _assert_forecast_prefixes(store: ForecastStore, expected: list[str]) -> None:
    held = await store.query(tenant_id=None, limit=len(expected))
    assert len(held) == len(expected), "forecast fixture lost rows"
    for limit in range(1, len(expected) + 1):
        rows = await store.query(tenant_id=None, limit=limit)
        assert [row.id for row in rows] == expected[:limit]


async def _assert_model_prefixes(store: PredictionModelStore, expected: list[str]) -> None:
    held = await store.query(tenant_id=None, limit=len(expected))
    assert len(held) == len(expected), "prediction model fixture lost rows"
    for limit in range(1, len(expected) + 1):
        rows = await store.query(tenant_id=None, limit=limit)
        assert [row.id for row in rows] == expected[:limit]


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_forecast_query_ordered_prefixes(
    kind: str,
    forced_keyset_plan: Callable[[object], AbstractAsyncContextManager[None]],
) -> None:
    ids = sorted(new_id("fct") for _ in range(ROW_COUNT))
    # This is forecast query's owned leading-key witness; FC-P2 remains defence in depth.
    records = [
        _forecast(
            forecast_id=row_id,
            issued_at=BASE + timedelta(minutes=((ROW_COUNT // 2) - 1) - (index // 2)),
        )
        for index, row_id in enumerate(ids)
    ]
    ordered = sorted(records, key=lambda row: (row.issued_at, row.id))
    expected = [row.id for row in ordered]
    async for store in _forecast_stores(kind):
        for record in reversed(ordered):
            await store.put(record)
        if kind == "postgres":
            async with forced_keyset_plan(store):
                await _assert_forecast_prefixes(store, expected)
        else:
            await _assert_forecast_prefixes(store, expected)


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_prediction_model_query_ordered_prefixes(
    kind: str,
    forced_keyset_plan: Callable[[object], AbstractAsyncContextManager[None]],
) -> None:
    ids = sorted(new_id("pdm") for _ in range(ROW_COUNT))
    methods = ["holt_winters", "linear_trend", "moving_average"]
    # Lower versions receive larger IDs so removing `version` reverses each pair.
    records = [
        PredictionModel(
            id=ids[(index * 2) + (1 - version_index)],
            method=method,
            params={"window": index + 1},
            version=version_index + 1,
        )
        for index, method in enumerate(methods)
        for version_index in range(2)
    ]
    ordered = sorted(records, key=lambda row: (row.method, row.version, row.id))
    expected = [row.id for row in ordered]
    async for store in _model_stores(kind):
        for record in reversed(ordered):
            await store.put(record)
        if kind == "postgres":
            async with forced_keyset_plan(store):
                await _assert_model_prefixes(store, expected)
        else:
            await _assert_model_prefixes(store, expected)
