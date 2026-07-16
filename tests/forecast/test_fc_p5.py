"""P5 acceptance tests for scenario sandboxing and no-precrime refusal."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import ResponseConfigInvalid
from aqelyn.decision import ClaimRef, Derivation, DerivationStep, replay
from aqelyn.evidence import EvidenceRecord
from aqelyn.forecast import (
    BasisRef,
    Forecast,
    ForecastingEngine,
    InMemoryForecastStore,
    InMemoryPredictionModelStore,
    Interval,
    MetricObservation,
    Scenario,
    scenario_operation_registry,
    simulate_scenario,
)
from aqelyn.response import reject_forecast_trigger_input

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000000621"
ACTOR = ActorRef(actor_type="user", actor_id="forecast-p5@example.com")


class EmptyHistory:
    async def history(
        self, *, metric: str, window_days: int, tenant_id: str | None
    ) -> list[MetricObservation]:
        _ = (metric, window_days, tenant_id)
        return []


class EmptyEvidence:
    async def get(self, evidence_id: str, *, actor: ActorRef) -> EvidenceRecord:
        _ = (evidence_id, actor)
        raise AssertionError("simulation should not read evidence")


def _scenario() -> Scenario:
    return Scenario(
        tenant_id=TENANT,
        name="Phishing surge",
        assumptions={"base_value": 40.0, "percent_delta": 0.25, "absolute_delta": 3.0},
        base_metric="phishing_volume",
        result={"base_value": 40.0, "projected": 40.0, "hypothetical": True},
        derivation=_placeholder_derivation(),
        created_by=ACTOR,
    )


def _placeholder_derivation() -> Derivation:
    output = {"point": 40.0, "interval": {"low": 39.0, "high": 41.0, "level": 0.8}}
    return Derivation(
        inputs=[ClaimRef(kind="trust", ref_id="scenario:placeholder")],
        steps=[
            DerivationStep(
                seq=1,
                op="forecast_result",
                input_refs=["scenario:placeholder"],
                params={
                    "point": 40.0,
                    "interval": {"low": 39.0, "high": 41.0, "level": 0.8},
                },
                output=output,
                note="Placeholder derivation before simulation.",
            )
        ],
        result=output,
        model_version=1,
        engine_version="forecast-p5-test/v1",
    )


def _forecast() -> Forecast:
    interval = Interval(low=35.0, high=45.0, level=0.8)
    output = {"point": 40.0, "interval": interval.model_dump(mode="json")}
    return Forecast(
        tenant_id=TENANT,
        metric="phishing_volume",
        subject_ref="aggregate:phishing_volume",
        method="moving_average",
        model_version=1,
        horizon_days=14,
        issued_at=NOW,
        resolves_at=NOW + timedelta(days=14),
        point=40.0,
        interval=interval,
        confidence=0.7,
        basis=[
            BasisRef(
                kind="metric",
                ref="metric:phishing_volume",
                window={"days": 30},
                evidence_id=new_id("evd"),
            )
        ],
        derivation=Derivation(
            inputs=[
                ClaimRef(kind="risk", ref_id="metric:phishing_volume", evidence_id=new_id("evd"))
            ],
            steps=[
                DerivationStep(
                    seq=1,
                    op="forecast_result",
                    input_refs=["metric:phishing_volume"],
                    params=output,
                    output=output,
                    note="Replay forecast.",
                )
            ],
            result=output,
            model_version=1,
            engine_version="forecast-p5-test/v1",
        ),
        statement="Given the cited basis, moving_average projects 40.0.",
    )


async def test_fc_scenario_sandboxed() -> None:
    original = _scenario()
    before = original.model_dump(mode="json")
    engine = ForecastingEngine(
        InMemoryForecastStore(),
        InMemoryPredictionModelStore(),
        history_source=EmptyHistory(),
        evidence_store=EmptyEvidence(),
        clock=lambda: NOW,
    )

    simulated = await engine.simulate(scenario=original)
    direct = simulate_scenario(original)

    assert original.model_dump(mode="json") == before
    assert simulated is not original
    assert simulated.hypothetical is True
    assert simulated.result == {
        "base_value": 40.0,
        "projected": 53.0,
        "assumptions": {"base_value": 40.0, "percent_delta": 0.25, "absolute_delta": 3.0},
        "hypothetical": True,
    }
    assert simulated.derivation.result == simulated.result
    assert replay(simulated.derivation, registry=scenario_operation_registry()) == simulated.result
    assert direct.result == simulated.result


def test_fc_no_automation_trigger() -> None:
    forecast = _forecast()

    with pytest.raises(ResponseConfigInvalid, match="forecasts cannot"):
        reject_forecast_trigger_input(forecast)

    reject_forecast_trigger_input({"kind": "finding", "id": new_id("fnd")})
