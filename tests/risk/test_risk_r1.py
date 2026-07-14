"""R1 acceptance tests for Risk Intelligence models and scoring."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import ALL_ERROR_CODES, RiskConfigInvalid
from aqelyn.risk import AppetiteConfig, Risk, RiskConfig, SignalRef, band_for_score, score_risk


def _now() -> datetime:
    return datetime.now(UTC)


def _risk(
    *,
    impact: float = 0.4,
    signals: list[SignalRef] | None = None,
) -> Risk:
    now = _now()
    selected_signals = (
        [
            SignalRef(kind="finding", ref_id=new_id("fnd"), weight=0.8),
            SignalRef(kind="config", ref_id="drift-snapshot-1", weight=0.5),
        ]
        if signals is None
        else signals
    )
    return Risk(
        id="risk-test",
        correlation_key="finding:asset",
        title="Credential risk on a critical asset",
        category="access",
        likelihood=0.0,
        impact=impact,
        score=0.0,
        band="within_appetite",
        signals=selected_signals,
        affected_object_ids=[new_id("obj")],
        reason="Unscored test risk.",
        first_seen_at=now,
        last_scored_at=now,
    )


def test_risk_score_bounded() -> None:
    config = RiskConfig(
        likelihood_weights={
            "finding": 1.0,
            "config": 1.0,
            "compliance": 1.0,
            "identity": 1.0,
            "threat_intel": 1.0,
        }
    )
    risk = _risk(
        impact=1.0,
        signals=[
            SignalRef(kind="finding", ref_id=new_id("fnd"), weight=1.0),
            SignalRef(kind="config", ref_id="drift-snapshot-1", weight=1.0),
        ],
    )

    first = score_risk(risk, config=config)
    second = score_risk(risk, config=config)

    assert first.score == 100.0
    assert first.score == second.score
    assert 0.0 <= first.likelihood <= 1.0
    assert 0.0 <= first.impact <= 1.0
    assert first.band == "over_tolerance"
    assert first.factors["likelihood"] == 1.0
    assert first.factors["impact"] == 1.0
    assert "mission_weighted/v1" in first.reason


def test_risk_mission_weighted() -> None:
    config = RiskConfig(w_likelihood=0.4, w_impact=0.6)
    risk = _risk(impact=0.2, signals=[SignalRef(kind="finding", ref_id=new_id("fnd"), weight=0.7)])
    high_mission = new_id("obj")

    low = score_risk(risk, config=config, mission_factor=0.2)
    high = score_risk(
        risk,
        config=config,
        mission_factor=1.0,
        top_mission_id=high_mission,
    )

    assert high.score >= low.score
    assert high.impact == 1.0
    assert high.top_mission_id == high_mission
    assert high.factors["mission_factor"] == 1.0


def test_risk_appetite_band() -> None:
    config = RiskConfig(appetite=AppetiteConfig(elevated=40.0, over=70.0))

    assert band_for_score(0.0, config) == "within_appetite"
    assert band_for_score(39.9, config) == "within_appetite"
    assert band_for_score(40.0, config) == "elevated"
    assert band_for_score(69.9, config) == "elevated"
    assert band_for_score(70.0, config) == "over_tolerance"

    elevated = score_risk(
        _risk(impact=0.0, signals=[SignalRef(kind="finding", ref_id=new_id("fnd"), weight=0.8)]),
        config=config,
    )
    assert elevated.score == 40.0
    assert elevated.band == "elevated"


def test_risk_config_invalid() -> None:
    with pytest.raises(RiskConfigInvalid, match="sum to 1"):
        RiskConfig(w_likelihood=0.7, w_impact=0.4)
    with pytest.raises(RiskConfigInvalid, match=r"appetite\.elevated"):
        RiskConfig(appetite=AppetiteConfig(elevated=80.0, over=70.0))
    with pytest.raises(RiskConfigInvalid, match="appetite threshold"):
        AppetiteConfig(elevated=-1.0, over=70.0)
    with pytest.raises(RiskConfigInvalid, match="unknown risk combiner"):
        RiskConfig(combiner="opaque-ml/v9")
    with pytest.raises(RiskConfigInvalid, match="unknown signal kind"):
        RiskConfig.model_validate({"likelihood_weights": {"unknown": 1.0}})
    with pytest.raises(RiskConfigInvalid, match="risk requires at least one signal"):
        _risk(signals=[])
    with pytest.raises(RiskConfigInvalid, match="mission_factor"):
        score_risk(_risk(), mission_factor=1.2)

    assert "RiskConfigInvalid" in ALL_ERROR_CODES
    assert "RiskNotFound" in ALL_ERROR_CODES
    assert "RiskSnapshotNotFound" in ALL_ERROR_CODES
