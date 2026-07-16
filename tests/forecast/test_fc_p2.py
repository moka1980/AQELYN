"""P2 acceptance tests for forecast stores and replay gates."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import (
    ForecastConfigInvalid,
    ForecastNotReplayable,
    OptimisticConcurrencyConflict,
)
from aqelyn.decision import ClaimRef, Derivation, DerivationStep
from aqelyn.forecast import (
    BasisRef,
    Forecast,
    ForecastStore,
    InMemoryForecastStore,
    InMemoryPredictionModelStore,
    Interval,
    Outcome,
    PostgresForecastStore,
    PostgresPredictionModelStore,
    PredictionModel,
    PredictionModelStore,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
TENANT = "018f0000-0000-7000-8000-000000000321"
OTHER_TENANT = "018f0000-0000-7000-8000-000000000322"
NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
ACTOR = ActorRef(actor_type="user", actor_id="forecast-reviewer@example.com")


class _Closable(Protocol):
    async def close(self) -> None: ...


def _interval(*, low: float = 9.0, high: float = 15.0) -> Interval:
    return Interval(low=low, high=high, level=0.8)


def _basis() -> BasisRef:
    return BasisRef(
        kind="metric",
        ref="metric:phishing_volume",
        window={"days": 30, "until": NOW.isoformat()},
        evidence_id=new_id("evd"),
    )


def _derivation(*, point: float = 12.0, interval: Interval | None = None) -> Derivation:
    selected_interval = interval or _interval()
    output = {
        "point": point,
        "interval": selected_interval.model_dump(mode="json"),
    }
    return Derivation(
        inputs=[
            ClaimRef(
                kind="risk",
                ref_id="metric:phishing_volume",
                evidence_id=new_id("evd"),
            )
        ],
        steps=[
            DerivationStep(
                seq=1,
                op="forecast_result",
                input_refs=["metric:phishing_volume"],
                params=output,
                output=output,
                note="Return the replayable forecast point and interval.",
            )
        ],
        result=output,
        model_version=1,
        engine_version="forecast-p2/v1",
    )


def _forecast(
    *,
    forecast_id: str | None = None,
    tenant_id: str | None = TENANT,
    metric: str = "phishing_volume",
    point: float = 12.0,
    interval: Interval | None = None,
    derivation: Derivation | None = None,
    issued_at: datetime = NOW,
    resolves_at: datetime | None = None,
    outcome: Outcome | None = None,
) -> Forecast:
    selected_interval = interval or _interval()
    data: dict[str, object] = {
        "tenant_id": tenant_id,
        "metric": metric,
        "subject_ref": f"aggregate:{metric}",
        "method": "moving_average",
        "model_version": 1,
        "horizon_days": 14,
        "issued_at": issued_at,
        "resolves_at": resolves_at or issued_at + timedelta(days=14),
        "point": point,
        "interval": selected_interval,
        "confidence": 0.7,
        "basis": [_basis()],
        "derivation": derivation or _derivation(point=point, interval=selected_interval),
        "statement": "Given the cited history, moving_average projects 12.0 +/- 3.0.",
        "outcome": outcome,
    }
    if forecast_id is not None:
        data["id"] = forecast_id
    return Forecast.model_validate(data)


def _model(
    *,
    model_id: str | None = None,
    tenant_id: str | None = TENANT,
    method: str = "moving_average",
    version: int = 1,
) -> PredictionModel:
    data: dict[str, object] = {
        "tenant_id": tenant_id,
        "method": method,
        "params": {"window": 7},
        "version": version,
    }
    if model_id is not None:
        data["id"] = model_id
    return PredictionModel.model_validate(data)


async def _postgres_forecast_store() -> PostgresForecastStore:
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresForecastStore.connect(PG_URL, mode="enterprise")
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_forecast")
    return store


async def _postgres_model_store() -> PostgresPredictionModelStore:
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresPredictionModelStore.connect(PG_URL, mode="enterprise")
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_prediction_model")
    return store


async def _forecast_store(kind: str) -> AsyncIterator[ForecastStore]:
    if kind == "inmemory":
        yield InMemoryForecastStore(mode="enterprise")
        return
    store = await _postgres_forecast_store()
    try:
        yield store
    finally:
        await cast(_Closable, store).close()


async def _model_store(kind: str) -> AsyncIterator[PredictionModelStore]:
    if kind == "inmemory":
        yield InMemoryPredictionModelStore(mode="enterprise")
        return
    store = await _postgres_model_store()
    try:
        yield store
    finally:
        await cast(_Closable, store).close()


def test_fc_interval_required() -> None:
    data = _forecast().model_dump(mode="json")
    data.pop("interval")

    with pytest.raises(ForecastConfigInvalid):
        Forecast.model_validate(data)


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_fc_replay_equals_result(kind: str) -> None:
    async for store in _forecast_store(kind):
        forecast = _forecast()

        stored = await store.put(forecast)
        fetched = await store.get(stored.id, tenant_id=TENANT)

        assert fetched == stored
        assert stored.derivation.result == {
            "point": stored.point,
            "interval": stored.interval.model_dump(mode="json"),
        }


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_fc_replay_mismatch_rejected(kind: str) -> None:
    async for store in _forecast_store(kind):
        forecast = _forecast(point=12.0, derivation=_derivation(point=13.0))

        with pytest.raises(ForecastNotReplayable):
            await store.put(forecast)

        assert await store.query(tenant_id=TENANT) == []


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_fc_store_contract(kind: str) -> None:
    async for store in _forecast_store(kind):
        due = _forecast(
            issued_at=NOW - timedelta(days=20),
            resolves_at=NOW - timedelta(days=1),
        )
        future = _forecast(
            forecast_id=new_id("fct"),
            resolves_at=NOW + timedelta(days=1),
        )
        scored = _forecast(
            forecast_id=new_id("fct"),
            issued_at=NOW - timedelta(days=19),
            resolves_at=NOW - timedelta(days=2),
            outcome=Outcome(
                actual=11.0,
                error=1.0,
                within_interval=True,
                scored_at=NOW,
                evidence_id=new_id("evd"),
            ),
        )
        other_tenant = _forecast(
            forecast_id=new_id("fct"),
            tenant_id=OTHER_TENANT,
            issued_at=NOW - timedelta(days=20),
            resolves_at=NOW - timedelta(days=1),
        )

        stored_due = await store.put(due)
        await store.put(future)
        await store.put(scored)
        await store.put(other_tenant)

        with pytest.raises(OptimisticConcurrencyConflict):
            await store.put(due)

        assert await store.get(stored_due.id, tenant_id=OTHER_TENANT) is None
        queried = await store.query(tenant_id=TENANT, metric="phishing_volume")
        assert [row.id for row in queried] == [stored_due.id, scored.id, future.id]

        due_rows = await store.due_for_scoring(tenant_id=TENANT, now=NOW)
        assert [row.id for row in due_rows] == [stored_due.id]


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_fc_model_contract(kind: str) -> None:
    async for store in _model_store(kind):
        model_v1 = await store.put(_model(version=1))
        model_v2 = await store.put(_model(model_id=new_id("pdm"), version=2))
        await store.put(_model(model_id=new_id("pdm"), tenant_id=OTHER_TENANT, version=1))

        with pytest.raises(OptimisticConcurrencyConflict):
            await store.put(_model(model_id=new_id("pdm"), version=1))

        promoted_v1 = await store.promote(
            model_v1.id,
            by=ACTOR,
            reason="Initial forecast method approved.",
            evidence_id=new_id("evd"),
            tenant_id=TENANT,
        )
        promoted_v2 = await store.promote(
            model_v2.id,
            by=ACTOR,
            reason="Updated forecast window approved.",
            evidence_id=new_id("evd"),
            tenant_id=TENANT,
        )

        assert promoted_v1.active is True
        assert promoted_v2.active is True
        active = await store.active("moving_average", tenant_id=TENANT)
        assert active.id == model_v2.id
        fetched_v1 = await store.get(model_v1.id, tenant_id=TENANT)
        assert fetched_v1 is not None
        assert fetched_v1.active is False

        queried = await store.query(tenant_id=TENANT, method="moving_average")
        assert [row.version for row in queried] == [1, 2]
        assert await store.get(model_v1.id, tenant_id=OTHER_TENANT) is None
