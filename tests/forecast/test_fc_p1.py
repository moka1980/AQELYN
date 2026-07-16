"""P1 acceptance tests for forecast types, methods, and config validation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from aqelyn.conventions import ALL_ERROR_CODES, PREFIXES, ActorRef, is_valid, new_id
from aqelyn.conventions.errors import ForecastConfigInvalid, UnknownMethod
from aqelyn.decision import ClaimRef, Derivation, DerivationStep
from aqelyn.forecast import (
    VALID_METHODS,
    AccuracyRecord,
    BasisRef,
    Forecast,
    ForecastConfig,
    Interval,
    Method,
    PredictionModel,
    Scenario,
    TrendRecord,
    default_method_registry,
)

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000000221"
ACTOR = ActorRef(actor_type="user", actor_id="forecast-admin@example.com")


def _basis() -> BasisRef:
    return BasisRef(
        kind="telemetry",
        ref="dataset:security_daily",
        window={"days": 30, "until": NOW.isoformat()},
        evidence_id=new_id("evd"),
    )


def _derivation() -> Derivation:
    return Derivation(
        inputs=[ClaimRef(kind="risk", ref_id="risk:aggregate", evidence_id=new_id("evd"))],
        steps=[
            DerivationStep(
                seq=1,
                op="moving_average",
                input_refs=["risk:aggregate"],
                params={"window": 3, "horizon_days": 14, "level": 0.8},
                output={
                    "point": 12.0,
                    "interval": {"low": 9.0, "high": 15.0, "level": 0.8},
                },
                note="Project the aggregate metric from cited history.",
            )
        ],
        result={"point": 12.0, "interval": {"low": 9.0, "high": 15.0, "level": 0.8}},
        model_version=1,
        engine_version="forecast-p1/v1",
    )


def test_fc_method_registry() -> None:
    registry = default_method_registry()
    history = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 24.0]

    assert set(registry.names()) == set(VALID_METHODS)
    for name in VALID_METHODS:
        before = list(history)
        fn = registry.get(cast(Method, name))
        result = fn(history, horizon_days=7, level=0.8)
        result_again = fn(history, horizon_days=7, level=0.8)

        assert history == before
        assert result.point == pytest.approx(result_again.point)
        assert result.interval == result_again.interval
        assert result.interval.low <= result.point <= result.interval.high
        assert result.interval.level == pytest.approx(0.8)
        assert result.as_dict()["point"] == result.point

    with pytest.raises(UnknownMethod):
        registry.get(cast(Method, "opaque_model"))
    with pytest.raises(ForecastConfigInvalid):
        registry.register("moving_average", registry.get("moving_average"))


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ForecastConfig(methods_allowed=[]),
        lambda: ForecastConfig(methods_allowed=["moving_average", "moving_average"]),
        lambda: ForecastConfig(methods_allowed=["opaque_model"]),
        lambda: ForecastConfig(max_horizon_days=0),
        lambda: ForecastConfig(min_history_points=1),
        lambda: ForecastConfig(default_level=0.0),
        lambda: ForecastConfig(default_level=1.0),
        lambda: ForecastConfig(batch_size=0),
        lambda: Interval(low=10.0, high=9.0, level=0.8),
        lambda: Interval(low=9.0, high=10.0, level=1.0),
        lambda: BasisRef(kind="person", ref="alice", window={"days": 7}),
        lambda: BasisRef(kind="metric", ref="", window={"days": 7}),
        lambda: BasisRef(kind="metric", ref="risk", window={}),
        lambda: TrendRecord(
            tenant_id=TENANT,
            metric="risk_score",
            window_days=30,
            slope=0.1,
            r_squared=1.2,
            direction="up",
            basis=[_basis()],
            reason="Invalid fit.",
        ),
        lambda: Forecast(
            tenant_id=TENANT,
            metric="risk_score",
            subject_ref="aggregate:risk",
            method="moving_average",
            model_version=1,
            horizon_days=14,
            issued_at=NOW,
            resolves_at=NOW + timedelta(days=14),
            point=12.0,
            interval=Interval(low=9.0, high=15.0, level=0.8),
            confidence=0.7,
            basis=[_basis()],
            derivation=_derivation(),
            advisory=False,
            statement="Invalid non-advisory forecast.",
        ),
        lambda: Forecast(
            tenant_id=TENANT,
            metric="risk_score",
            subject_ref="aggregate:risk",
            method="moving_average",
            model_version=1,
            horizon_days=14,
            issued_at=NOW,
            resolves_at=NOW,
            point=12.0,
            interval=Interval(low=9.0, high=15.0, level=0.8),
            confidence=0.7,
            basis=[_basis()],
            derivation=_derivation(),
            statement="Invalid time order.",
        ),
        lambda: PredictionModel(
            tenant_id=TENANT,
            method="moving_average",
            params={"window": 7},
            version=1,
            active=True,
        ),
        lambda: Scenario(
            tenant_id=TENANT,
            name="capacity stress",
            assumptions={"risk_delta": 0.1},
            base_metric="risk_score",
            result={"projected": 12.0},
            hypothetical=False,
            derivation=_derivation(),
            created_by=ACTOR,
        ),
    ],
)
def test_fc_config_invalid(factory: Callable[[], object]) -> None:
    with pytest.raises(ForecastConfigInvalid):
        factory()


def test_fc_p1_model_shapes_and_taxonomy() -> None:
    interval = Interval(low=9.0, high=15.0, level=0.8)
    trend = TrendRecord(
        tenant_id=TENANT,
        metric="risk_score",
        window_days=30,
        slope=0.2,
        r_squared=0.82,
        direction="up",
        basis=[_basis()],
        reason="Slope 0.2 over 30 days indicates an upward trend.",
    )
    forecast = Forecast(
        tenant_id=TENANT,
        metric="risk_score",
        subject_ref="aggregate:risk",
        method="moving_average",
        model_version=1,
        horizon_days=14,
        issued_at=NOW,
        resolves_at=NOW + timedelta(days=14),
        point=12.0,
        interval=interval,
        confidence=0.7,
        basis=[_basis()],
        derivation=_derivation(),
        statement="Given the cited history, moving_average projects 12.0 +/- 3.0.",
    )
    accuracy = AccuracyRecord(
        method="moving_average",
        metric="risk_score",
        n=0,
        mae=0.0,
        within_interval_pct=0.0,
        updated_at=NOW,
    )
    inactive_model = PredictionModel(
        tenant_id=TENANT,
        method="moving_average",
        params={"window": 7},
        version=1,
    )
    active_model = PredictionModel(
        tenant_id=TENANT,
        method="moving_average",
        params={"window": 7},
        version=2,
        promoted_by=ACTOR,
        promoted_at=NOW,
        active=True,
        evidence_id=new_id("evd"),
    )
    scenario = Scenario(
        tenant_id=TENANT,
        name="capacity stress",
        assumptions={"risk_delta": 0.1},
        base_metric="risk_score",
        result={"projected": 12.0},
        derivation=_derivation(),
        created_by=ACTOR,
    )

    assert is_valid(trend.id, "trn")
    assert is_valid(forecast.id, "fct")
    assert is_valid(inactive_model.id, "pdm")
    assert is_valid(active_model.id, "pdm")
    assert is_valid(scenario.id, "scn")
    assert forecast.interval == interval
    assert forecast.advisory is True
    assert forecast.outcome is None
    assert accuracy.n == 0
    assert inactive_model.active is False
    assert active_model.active is True
    assert scenario.hypothetical is True

    assert PREFIXES["fct"] == "forecast"
    assert PREFIXES["trn"] == "forecast_trend"
    assert PREFIXES["pdm"] == "prediction_model"
    assert PREFIXES["scn"] == "forecast_scenario"
    assert "ForecastConfigInvalid" in ALL_ERROR_CODES
    assert "UnknownMethod" in ALL_ERROR_CODES
    assert "InsufficientHistory" in ALL_ERROR_CODES
    assert "ForecastNotFound" in ALL_ERROR_CODES
    assert "ForecastNotReplayable" in ALL_ERROR_CODES
