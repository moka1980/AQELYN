"""P3 acceptance tests for trend and advisory forecasts."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import ForecastConfigInvalid, InsufficientHistory
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord
from aqelyn.forecast import (
    BasisRef,
    ForecastConfig,
    ForecastingEngine,
    ForecastStore,
    InMemoryForecastStore,
    InMemoryPredictionModelStore,
    MetricObservation,
    PostgresForecastStore,
    PostgresPredictionModelStore,
    PredictionModel,
    PredictionModelStore,
    statement_from_derivation,
)
from aqelyn.trust import TrustAssessment

PG_URL = os.getenv("AQELYN_DATABASE_URL")
TENANT = "018f0000-0000-7000-8000-000000000421"
NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
ACTOR = ActorRef(actor_type="user", actor_id="forecast-p3@example.com")


class _Closable(Protocol):
    async def close(self) -> None: ...


class StaticHistory:
    def __init__(self, observations: Sequence[MetricObservation]) -> None:
        self.observations = list(observations)
        self.calls: list[tuple[str, int, str | None]] = []

    async def history(
        self,
        *,
        metric: str,
        window_days: int,
        tenant_id: str | None,
    ) -> Sequence[MetricObservation]:
        self.calls.append((metric, window_days, tenant_id))
        return list(self.observations)


class EvidenceLookup:
    def __init__(self, records: Sequence[EvidenceRecord]) -> None:
        self.records = {record.id: record for record in records}
        self.reads: list[str] = []

    async def get(self, evidence_id: str, *, actor: ActorRef) -> EvidenceRecord:
        _ = actor
        self.reads.append(evidence_id)
        return self.records[evidence_id]


class SpyTrust:
    def __init__(self, score: float) -> None:
        self.score = score
        self.calls: list[tuple[str, list[str], datetime | None]] = []

    async def assess(
        self,
        subject_ref: str,
        evidence: Sequence[EvidenceRecord],
        *,
        now: datetime | None = None,
    ) -> TrustAssessment:
        self.calls.append((subject_ref, [record.id for record in evidence], now))
        return TrustAssessment(
            subject_ref=subject_ref,
            score=self.score,
            level="medium",
            method="spy_trust/v1",
            contributions=[],
            reason="confidence supplied by EA-0006 Trust test double.",
            no_evidence=False,
            computed_at=now or NOW,
        )


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


async def _stores(
    kind: str,
) -> AsyncIterator[tuple[ForecastStore, PredictionModelStore]]:
    if kind == "inmemory":
        yield (
            InMemoryForecastStore(mode="enterprise"),
            InMemoryPredictionModelStore(mode="enterprise"),
        )
        return
    forecast_store = await _postgres_forecast_store()
    model_store = await _postgres_model_store()
    try:
        yield forecast_store, model_store
    finally:
        await cast(_Closable, forecast_store).close()
        await cast(_Closable, model_store).close()


async def _seed_model(store: PredictionModelStore, *, version: int = 1) -> PredictionModel:
    model = await store.put(
        PredictionModel(
            tenant_id=TENANT,
            method="moving_average",
            params={"window": 7},
            version=version,
        )
    )
    return await store.promote(
        model.id,
        by=ACTOR,
        reason=f"Promote moving average v{version}.",
        evidence_id=new_id("evd"),
        tenant_id=TENANT,
    )


def _observations(count: int = 7) -> tuple[list[MetricObservation], list[EvidenceRecord]]:
    observations: list[MetricObservation] = []
    evidence: list[EvidenceRecord] = []
    for index in range(count):
        evidence_id = new_id("evd")
        collected_at = NOW - timedelta(days=count - index)
        basis = BasisRef(
            kind="telemetry" if index % 2 == 0 else "risk",
            ref=f"metric:phishing_volume:{index}",
            window={"days": 30, "index": index},
            evidence_id=evidence_id,
        )
        observations.append(
            MetricObservation(
                observed_at=collected_at,
                value=10.0 + float(index),
                basis=basis,
            )
        )
        evidence.append(
            EvidenceRecord(
                id=evidence_id,
                tenant_id=TENANT,
                evidence_type="forecast.basis",
                schema_version=1,
                subject=Subject(),
                collected_at=collected_at,
                recorded_at=collected_at,
                collector=ACTOR,
                source_id=new_id("src"),
                method="forecast-test/v1",
                content={"metric": "phishing_volume", "value": 10.0 + float(index)},
                content_hash="basis",
                confidence=0.9,
                labels={"module": "EA-0021", "kind": "basis"},
                seq=index + 1,
                prev_hash=None,
                record_hash=f"hash-{index}",
            )
        )
    return observations, evidence


def _engine(
    forecast_store: ForecastStore,
    model_store: PredictionModelStore,
    observations: Sequence[MetricObservation],
    evidence: Sequence[EvidenceRecord],
    *,
    trust_score: float = 0.73,
) -> tuple[ForecastingEngine, SpyTrust, EvidenceLookup, StaticHistory]:
    history = StaticHistory(observations)
    evidence_lookup = EvidenceLookup(evidence)
    trust = SpyTrust(trust_score)
    return (
        ForecastingEngine(
            forecast_store,
            model_store,
            history_source=history,
            evidence_store=evidence_lookup,
            trust_engine=trust,
            config=ForecastConfig(min_history_points=7, default_level=0.8),
            clock=lambda: NOW,
        ),
        trust,
        evidence_lookup,
        history,
    )


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_fc_statement_from_derivation(kind: str) -> None:
    async for forecast_store, model_store in _stores(kind):
        observations, evidence = _observations()
        await _seed_model(model_store)
        engine, _, _, _ = _engine(forecast_store, model_store, observations, evidence)

        forecast = await engine.forecast(
            metric="phishing_volume",
            horizon_days=14,
            method="moving_average",
            tenant_id=TENANT,
        )

        assert forecast.statement == statement_from_derivation(forecast.derivation)
        assert engine.explain(forecast)["statement"] == forecast.statement
        assert "moving_average projects" in forecast.statement


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_fc_advisory_only(kind: str) -> None:
    async for forecast_store, model_store in _stores(kind):
        observations, evidence = _observations()
        await _seed_model(model_store)
        engine, _, _, _ = _engine(forecast_store, model_store, observations, evidence)

        forecast = await engine.forecast(
            metric="phishing_volume",
            horizon_days=7,
            method="moving_average",
            tenant_id=TENANT,
        )

        assert forecast.advisory is True
        assert forecast.outcome is None
        assert "finding_id" not in forecast.model_dump(mode="json")


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_fc_basis_not_outcome_evidence(kind: str) -> None:
    async for forecast_store, model_store in _stores(kind):
        observations, evidence = _observations()
        await _seed_model(model_store)
        engine, _, evidence_lookup, _ = _engine(forecast_store, model_store, observations, evidence)

        forecast = await engine.forecast(
            metric="phishing_volume",
            horizon_days=7,
            method="moving_average",
            tenant_id=TENANT,
        )

        basis_evidence = [ref.evidence_id for ref in forecast.basis]
        input_evidence = [claim.evidence_id for claim in forecast.derivation.inputs]
        assert basis_evidence == input_evidence
        assert evidence_lookup.reads == basis_evidence
        assert forecast.outcome is None


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_fc_insufficient_history(kind: str) -> None:
    async for forecast_store, model_store in _stores(kind):
        observations, evidence = _observations(count=3)
        await _seed_model(model_store)
        engine, _, _, _ = _engine(forecast_store, model_store, observations, evidence)

        with pytest.raises(InsufficientHistory):
            await engine.forecast(
                metric="phishing_volume",
                horizon_days=7,
                method="moving_average",
                tenant_id=TENANT,
            )

        assert await forecast_store.query(tenant_id=TENANT) == []


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_fc_no_individual_prediction(kind: str) -> None:
    async for forecast_store, model_store in _stores(kind):
        observations, evidence = _observations()
        await _seed_model(model_store)
        engine, _, _, _ = _engine(forecast_store, model_store, observations, evidence)

        with pytest.raises(ForecastConfigInvalid):
            await engine.forecast(
                metric="phishing_volume",
                horizon_days=7,
                method="moving_average",
                tenant_id=TENANT,
                subject_ref="acct:alice",
            )

        assert await forecast_store.query(tenant_id=TENANT) == []


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_fc_confidence_from_trust(kind: str) -> None:
    async for forecast_store, model_store in _stores(kind):
        observations, evidence = _observations()
        await _seed_model(model_store)
        engine, trust, _, _ = _engine(
            forecast_store, model_store, observations, evidence, trust_score=0.42
        )

        forecast = await engine.forecast(
            metric="phishing_volume",
            horizon_days=7,
            method="moving_average",
            tenant_id=TENANT,
        )

        assert forecast.confidence == pytest.approx(0.42)
        assert trust.calls == [
            ("aggregate:phishing_volume", sorted(record.id for record in evidence), NOW)
        ]


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_fc_model_version_pinned(kind: str) -> None:
    async for forecast_store, model_store in _stores(kind):
        observations, evidence = _observations()
        await _seed_model(model_store, version=1)
        active_v2 = await _seed_model(model_store, version=2)
        engine, _, _, _ = _engine(forecast_store, model_store, observations, evidence)

        forecast = await engine.forecast(
            metric="phishing_volume",
            horizon_days=7,
            method="moving_average",
            tenant_id=TENANT,
        )

        assert forecast.model_version == active_v2.version
        assert forecast.derivation.model_version == active_v2.version


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_fc_analyze_trend(kind: str) -> None:
    async for forecast_store, model_store in _stores(kind):
        observations, evidence = _observations()
        engine, _, _, history = _engine(forecast_store, model_store, observations, evidence)

        trend = await engine.analyze_trend(
            metric="phishing_volume",
            window_days=30,
            tenant_id=TENANT,
        )

        assert trend.direction == "up"
        assert trend.slope == pytest.approx(1.0)
        assert trend.r_squared == pytest.approx(1.0)
        assert len(trend.basis) == 7
        assert history.calls == [("phishing_volume", 30, TENANT)]
