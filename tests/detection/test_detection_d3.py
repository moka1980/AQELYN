"""D3 acceptance tests for explainable, reproducible detection analytics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.detection import (
    BehaviorProfile,
    DetectionConfig,
    DetectionRule,
    InMemoryProfileStore,
    InMemoryRuleStore,
    ObservedMetric,
    RuleSignal,
    ThreatDetectionEngine,
    anomaly_measure,
    is_anomalous,
)
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord
from aqelyn.graph import Path as KGPath
from aqelyn.mission import MissionConfig
from aqelyn.mission.models import MissionImpact, MissionImpactResult, MissionView
from aqelyn.trust import TrustConfig, TrustEngine

TENANT = "018f0000-0000-7000-8000-000000001701"
NOW = datetime(2026, 7, 15, 17, 0, tzinfo=UTC)
ACTOR = ActorRef(actor_type="system", actor_id="detection-test")
SUBJECT_OBJ = new_id("obj")


class FakeMissionEngine:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def mission_impact(self, object_id: str) -> MissionImpactResult:
        self.calls.append(object_id)
        mission = MissionView(
            id=new_id("obj"),
            display_name="Payments",
            criticality_tier=1,
            criticality_weight=1.0,
            reason="test mission tier",
        )
        return MissionImpactResult(
            impacts=[
                MissionImpact(
                    mission=mission,
                    impact_score=1.0,
                    via=KGPath(node_ids=[object_id, mission.id], edges=[], length=1),
                    source_object_id=object_id,
                    reason="Payments depends on the observed object.",
                )
            ],
            truncated=False,
        )


def test_det_anomaly_measure() -> None:
    profile = _profile(version=3, mean=5.0, stddev=2.0, p95=9.0)

    z_score = anomaly_measure(profile, observed=15.0, measure="z_score", threshold=3.0)
    percentile = anomaly_measure(profile, observed=18.0, measure="percentile", threshold=1.5)
    rate = anomaly_measure(profile, observed=11.0, measure="rate_change", threshold=1.0)

    assert z_score.profile_version == 3
    assert z_score.baseline_value == 5.0
    assert z_score.value == pytest.approx(5.0)
    assert is_anomalous(z_score)
    assert percentile.baseline_value == 9.0
    assert percentile.value == pytest.approx(2.0)
    assert is_anomalous(percentile)
    assert rate.baseline_value == 5.0
    assert rate.value == pytest.approx(1.2)
    assert is_anomalous(rate)


async def test_det_pins_versions() -> None:
    engine, rules, profiles, _mission = await _engine()
    rule = await rules.put(_rule(rule_id="rule-login-spike", version=2))
    profile = await profiles.put(_profile(version=1))
    observation = _observation(value=47.0)

    detections = await engine.detect_anomalies(
        tenant_id=TENANT,
        observations=[observation],
        detected_at=NOW,
    )

    assert len(detections) == 1
    detection = detections[0]
    assert detection.rule_id == rule.id
    assert detection.rule_version == 2
    assert detection.profile_version == profile.version
    assert detection.anomaly is not None
    assert detection.anomaly.profile_version == profile.version
    assert detection.anomaly.observed == 47.0
    assert detection.anomaly.threshold == 3.0


async def test_det_reproduce() -> None:
    engine, rules, profiles, _mission = await _engine()
    rule = await rules.put(_rule(rule_id="rule-login-spike", version=1, severity="high"))
    profile = await profiles.put(_profile(version=1, mean=5.0, stddev=2.0))
    observation = _observation(value=47.0, collected_at=NOW - timedelta(days=4))
    original = (
        await engine.detect_anomalies(
            tenant_id=TENANT,
            observations=[observation],
            detected_at=NOW,
        )
    )[0]

    await rules.put(_rule(rule_id=rule.id, version=2, severity="critical"))
    await profiles.put(
        profile.model_copy(
            update={
                "baseline": {
                    "n": 8,
                    "mean": 47.0,
                    "stddev": 1.0,
                    "p95": 48.0,
                    "insufficient_data": False,
                },
                "version": 1,
            },
            deep=True,
        )
    )

    reproduced = await engine.reproduce(original.id)
    latest_rule = await rules.get(rule.id)
    latest_profile = await profiles.get(profile.id)

    assert reproduced.model_dump(mode="json") == original.model_dump(mode="json")
    assert reproduced.confidence == pytest.approx(0.25)
    assert latest_rule is not None
    assert latest_rule.version == 2
    assert latest_profile is not None
    assert latest_profile.version == 2


async def test_det_explainable() -> None:
    engine, rules, profiles, _mission = await _engine()
    await rules.put(_rule(rule_id="rule-login-spike"))
    await profiles.put(_profile(mean=3.0, stddev=1.0))

    detection = (
        await engine.detect_anomalies(
            tenant_id=TENANT,
            observations=[_observation(value=12.0)],
            detected_at=NOW,
        )
    )[0]
    explanation = engine.explain(detection)

    assert "baseline was 3.000" in detection.reason
    assert "observed 12.000" in detection.reason
    assert "threshold 3.000" in detection.reason
    assert explanation["rule"] == {"id": "rule-login-spike", "version": 1}
    assert explanation["profile_version"] == 1
    assert explanation["anomaly"] is not None
    assert explanation["signal_refs"]


async def test_det_scoring_composed() -> None:
    engine, rules, profiles, mission = await _engine()
    await rules.put(_rule(rule_id="rule-login-spike", severity="high"))
    await profiles.put(_profile(subject_ref=SUBJECT_OBJ, mean=1.0, stddev=1.0))

    detection = (
        await engine.detect_anomalies(
            tenant_id=TENANT,
            observations=[_observation(subject_ref=SUBJECT_OBJ, value=8.0)],
            detected_at=NOW,
        )
    )[0]

    assert detection.confidence == pytest.approx(1.0)
    assert detection.severity_score == pytest.approx(75.0)
    assert mission.calls == [SUBJECT_OBJ]

    source = (
        Path(__file__).resolve().parents[2] / "src" / "aqelyn" / "detection" / "scoring.py"
    ).read_text(encoding="utf-8")
    assert "TrustEngine" in source
    assert "MissionImpactProvider" in source
    assert "MissionConfig" in source


async def test_det_evaluate_rules_uses_latest_enabled_state() -> None:
    engine, rules, _profiles, _mission = await _engine()
    await rules.put(_rule(rule_id="rule-disabled-latest", kind="rule", version=1, enabled=True))
    await rules.put(_rule(rule_id="rule-disabled-latest", kind="rule", version=2, enabled=False))
    signal = RuleSignal(
        subject_ref="acct:alice",
        subject_type="identity",
        data={"id": "signal-login-alice", "type": "login", "count": 47},
        evidence=_evidence(),
        observed_at=NOW,
    )

    detections = await engine.evaluate_rules(
        tenant_id=TENANT,
        signals=[signal],
        detected_at=NOW,
    )

    assert detections == []


async def _engine() -> tuple[
    ThreatDetectionEngine,
    InMemoryRuleStore,
    InMemoryProfileStore,
    FakeMissionEngine,
]:
    rules = InMemoryRuleStore()
    profiles = InMemoryProfileStore()
    mission = FakeMissionEngine()
    engine = ThreatDetectionEngine(
        rule_store=rules,
        profile_store=profiles,
        trust_engine=TrustEngine(
            config=TrustConfig(
                type_weights={"detection.observation/v1": 1.0},
                half_life_days=2.0,
                recency_floor=0.0,
                default_reliability=1.0,
            )
        ),
        mission_engine=mission,
        mission_config=MissionConfig(),
        config=DetectionConfig(
            thresholds={"z_score": 3.0, "percentile": 1.5, "rate_change": 1.0},
            min_samples=3,
        ),
    )
    return engine, rules, profiles, mission


def _rule(
    *,
    rule_id: str,
    version: int = 1,
    kind: str = "behavioral",
    severity: str = "high",
    enabled: bool = True,
) -> DetectionRule:
    return DetectionRule(
        id=rule_id,
        name="Login spike",
        description="Detects anomalous login volume.",
        kind=kind,
        condition={
            "all": [
                {"op": "eq", "attr": "signal.metric", "value": "logins_per_day"},
                {"op": "eq", "attr": "signal.measure", "value": "z_score"},
            ]
        }
        if kind == "behavioral"
        else {"op": "eq", "attr": "signal.type", "value": "login"},
        subject_type="identity",
        technique_ids=["T1078"],
        severity=severity,
        enabled=enabled,
        version=version,
        tenant_id=TENANT,
    )


def _profile(
    *,
    subject_ref: str = "acct:alice",
    version: int = 1,
    mean: float = 5.0,
    stddev: float = 2.0,
    p95: float = 9.0,
) -> BehaviorProfile:
    return BehaviorProfile(
        tenant_id=TENANT,
        subject_ref=subject_ref,
        metric="logins_per_day",
        window_days=30,
        baseline={
            "n": 10,
            "mean": mean,
            "stddev": stddev,
            "p95": p95,
            "insufficient_data": False,
        },
        computed_at=NOW,
        version=version,
        insufficient_data=False,
    )


def _observation(
    *,
    subject_ref: str = "acct:alice",
    value: float,
    collected_at: datetime | None = None,
) -> ObservedMetric:
    observed_at = collected_at or NOW
    return ObservedMetric(
        subject_ref=subject_ref,
        subject_type="identity",
        metric="logins_per_day",
        value=value,
        observed_at=observed_at,
        evidence=_evidence(subject_ref=subject_ref, collected_at=observed_at),
        measure="z_score",
    )


def _evidence(
    *,
    subject_ref: str = "acct:alice",
    collected_at: datetime = NOW,
) -> EvidenceRecord:
    object_ids = [subject_ref] if subject_ref.startswith("obj_") else []
    return EvidenceRecord(
        id=new_id("evd"),
        tenant_id=TENANT,
        evidence_type="detection.observation/v1",
        schema_version=1,
        subject=Subject(object_ids=object_ids),
        collected_at=collected_at,
        recorded_at=NOW,
        collector=ACTOR,
        source_id=new_id("src"),
        method="detection.observation/v1",
        content={"subject_ref": subject_ref, "metric": "logins_per_day"},
        content_hash="synthetic-detection-test-input",
        confidence=1.0,
        labels={"module": "EA-0017", "kind": "detection_observation"},
        seq=0,
        prev_hash=None,
        record_hash="synthetic-detection-test-input",
    )
