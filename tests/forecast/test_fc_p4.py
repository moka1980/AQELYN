"""P4 acceptance tests for outcome scoring and published accuracy."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.decision import ClaimRef, Derivation, DerivationStep
from aqelyn.evidence import InMemoryEvidenceStore
from aqelyn.forecast import (
    AccuracyRecord,
    BasisRef,
    Forecast,
    ForecastConfig,
    ForecastingEngine,
    ForecastPublication,
    ForecastStore,
    InMemoryForecastStore,
    InMemoryPredictionModelStore,
    Interval,
    MetricObservation,
    PostgresForecastStore,
    PredictionModelStore,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
TENANT = "018f0000-0000-7000-8000-000000000521"
NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
ACTOR = ActorRef(actor_type="user", actor_id="forecast-p4@example.com")


class _Closable(Protocol):
    async def close(self) -> None: ...


class EmptyHistory:
    async def history(
        self,
        *,
        metric: str,
        window_days: int,
        tenant_id: str | None,
    ) -> list[MetricObservation]:
        _ = (metric, window_days, tenant_id)
        return []


class Actuals:
    def __init__(self, values: dict[str, MetricObservation]) -> None:
        self.values = values
        self.calls: list[tuple[str, datetime, str | None]] = []

    async def actual(
        self,
        *,
        metric: str,
        at: datetime,
        tenant_id: str | None,
    ) -> MetricObservation | None:
        self.calls.append((metric, at, tenant_id))
        return self.values.get(metric)


async def _postgres_forecast_store() -> PostgresForecastStore:
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresForecastStore.connect(PG_URL, mode="enterprise")
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_forecast")
    return store


async def _stores(kind: str) -> AsyncIterator[tuple[ForecastStore, PredictionModelStore]]:
    if kind == "inmemory":
        yield (
            InMemoryForecastStore(mode="enterprise"),
            InMemoryPredictionModelStore(mode="enterprise"),
        )
        return
    forecast_store = await _postgres_forecast_store()
    try:
        yield forecast_store, InMemoryPredictionModelStore(mode="enterprise")
    finally:
        await cast(_Closable, forecast_store).close()


def _basis(metric: str, *, evidence_id: str | None = None) -> BasisRef:
    return BasisRef(
        kind="metric",
        ref=f"metric:{metric}",
        window={"days": 30, "until": NOW.isoformat()},
        evidence_id=evidence_id or new_id("evd"),
    )


def _derivation(*, point: float, interval: Interval, metric: str) -> Derivation:
    output = {"point": point, "interval": interval.model_dump(mode="json")}
    return Derivation(
        inputs=[
            ClaimRef(
                kind="risk",
                ref_id=f"metric:{metric}",
                evidence_id=new_id("evd"),
            )
        ],
        steps=[
            DerivationStep(
                seq=1,
                op="forecast_result",
                input_refs=[f"metric:{metric}"],
                params={
                    **output,
                    "method": "moving_average",
                    "horizon_days": 7,
                    "model_version": 1,
                },
                output=output,
                note="Replay the scored forecast point and interval.",
            )
        ],
        result=output,
        model_version=1,
        engine_version="forecast-p4-test/v1",
    )


def _forecast(
    *,
    metric: str,
    point: float,
    interval: Interval,
    resolves_at: datetime,
    forecast_id: str | None = None,
) -> Forecast:
    return Forecast(
        id=forecast_id or new_id("fct"),
        tenant_id=TENANT,
        metric=metric,
        subject_ref=f"aggregate:{metric}",
        method="moving_average",
        model_version=1,
        horizon_days=7,
        issued_at=resolves_at - timedelta(days=7),
        resolves_at=resolves_at,
        point=point,
        interval=interval,
        confidence=0.7,
        basis=[_basis(metric)],
        derivation=_derivation(point=point, interval=interval, metric=metric),
        statement="Given the cited basis, moving_average projects a test value.",
    )


def _actual(metric: str, value: float) -> MetricObservation:
    return MetricObservation(
        observed_at=NOW,
        value=value,
        basis=_basis(metric, evidence_id=new_id("evd")),
    )


def _engine(
    forecast_store: ForecastStore,
    model_store: PredictionModelStore,
    actuals: Actuals,
    evidence_store: InMemoryEvidenceStore,
) -> ForecastingEngine:
    return ForecastingEngine(
        forecast_store,
        model_store,
        history_source=EmptyHistory(),
        evidence_store=evidence_store,
        actual_source=actuals,
        evidence_recorder=evidence_store,
        config=ForecastConfig(batch_size=20),
        clock=lambda: NOW,
    )


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_fc_score_all_due(kind: str) -> None:
    async for forecast_store, model_store in _stores(kind):
        first = await forecast_store.put(
            _forecast(
                metric="phishing_volume",
                point=10.0,
                interval=Interval(low=8.0, high=13.0, level=0.8),
                resolves_at=NOW - timedelta(days=1),
            )
        )
        second = await forecast_store.put(
            _forecast(
                metric="phishing_volume",
                point=14.0,
                interval=Interval(low=13.0, high=15.0, level=0.8),
                resolves_at=NOW - timedelta(days=1),
            )
        )
        unscoreable = await forecast_store.put(
            _forecast(
                metric="malware_volume",
                point=5.0,
                interval=Interval(low=4.0, high=6.0, level=0.8),
                resolves_at=NOW - timedelta(days=1),
            )
        )
        future = await forecast_store.put(
            _forecast(
                metric="phishing_volume",
                point=99.0,
                interval=Interval(low=90.0, high=110.0, level=0.8),
                resolves_at=NOW + timedelta(days=1),
            )
        )
        actuals = Actuals({"phishing_volume": _actual("phishing_volume", 12.0)})
        evidence_store = InMemoryEvidenceStore(mode="enterprise")
        engine = _engine(forecast_store, model_store, actuals, evidence_store)

        outcomes = await engine.score_due(tenant_id=TENANT)

        assert len(outcomes) == 3
        assert len(actuals.calls) == 3
        assert sorted(call[0] for call in actuals.calls) == [
            "malware_volume",
            "phishing_volume",
            "phishing_volume",
        ]
        scored_first = await forecast_store.get(first.id, tenant_id=TENANT)
        scored_second = await forecast_store.get(second.id, tenant_id=TENANT)
        flagged = await forecast_store.get(unscoreable.id, tenant_id=TENANT)
        still_future = await forecast_store.get(future.id, tenant_id=TENANT)
        assert scored_first is not None
        assert scored_first.outcome is not None
        assert scored_second is not None
        assert scored_second.outcome is not None
        assert flagged is not None
        assert flagged.outcome is not None
        assert still_future is not None
        assert still_future.outcome is None
        assert scored_first.outcome.actual == pytest.approx(12.0)
        assert scored_first.outcome.error == pytest.approx(2.0)
        assert scored_first.outcome.within_interval is True
        assert scored_second.outcome.error == pytest.approx(2.0)
        assert scored_second.outcome.within_interval is False
        assert flagged.outcome.unscoreable is True
        assert flagged.outcome.reason == "actual value unavailable for forecast resolution"
        assert await forecast_store.due_for_scoring(tenant_id=TENANT, now=NOW) == []
        assert len(await evidence_store.custody_of(scored_first.outcome.evidence_id)) == 1
        assert len(await evidence_store.custody_of(flagged.outcome.evidence_id)) == 1


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_fc_accuracy_published(kind: str) -> None:
    async for forecast_store, model_store in _stores(kind):
        await forecast_store.put(
            _forecast(
                metric="phishing_volume",
                point=10.0,
                interval=Interval(low=8.0, high=13.0, level=0.8),
                resolves_at=NOW - timedelta(days=1),
            )
        )
        await forecast_store.put(
            _forecast(
                metric="phishing_volume",
                point=14.0,
                interval=Interval(low=13.0, high=15.0, level=0.8),
                resolves_at=NOW - timedelta(days=1),
            )
        )
        await forecast_store.put(
            _forecast(
                metric="malware_volume",
                point=5.0,
                interval=Interval(low=4.0, high=6.0, level=0.8),
                resolves_at=NOW - timedelta(days=1),
            )
        )
        await forecast_store.put(
            _forecast(
                metric="phishing_volume",
                point=99.0,
                interval=Interval(low=90.0, high=110.0, level=0.8),
                resolves_at=NOW + timedelta(days=1),
            )
        )
        evidence_store = InMemoryEvidenceStore(mode="enterprise")
        engine = _engine(
            forecast_store,
            model_store,
            Actuals({"phishing_volume": _actual("phishing_volume", 12.0)}),
            evidence_store,
        )

        await engine.score_due(tenant_id=TENANT)
        records = await engine.accuracy(tenant_id=TENANT)
        published = await engine.published_forecasts(tenant_id=TENANT, limit=10)

        by_metric = {record.metric: record for record in records}
        assert by_metric["phishing_volume"] == AccuracyRecord(
            method="moving_average",
            metric="phishing_volume",
            n=2,
            mae=2.0,
            within_interval_pct=0.5,
            updated_at=NOW,
        )
        assert by_metric["malware_volume"].n == 0
        assert by_metric["malware_volume"].mae == 0.0
        assert len(published) == 4
        assert all(isinstance(row, ForecastPublication) for row in published)
        phishing_publications = [
            row for row in published if row.forecast.metric == "phishing_volume"
        ]
        assert len(phishing_publications) == 3
        assert {row.accuracy.n for row in phishing_publications} == {2}
