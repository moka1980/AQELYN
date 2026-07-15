"""D1 acceptance tests for Threat Detection models and declarative rules."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import ALL_ERROR_CODES, DetectionConfigInvalid
from aqelyn.detection import (
    AnomalyMeasure,
    DetectionConfig,
    DetectionRule,
    Projection,
    SignalRef,
    ThreatDetection,
    rule_matches,
)

NOW = datetime(2026, 7, 15, 15, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000000017"


def test_det_rules_no_eval() -> None:
    rule = _rule(
        {
            "all": [
                {"op": "eq", "attr": "signal.type", "value": "login"},
                {"op": "gt", "attr": "signal.count", "value": 10},
                {"op": "contains", "attr": "signal.tags", "value": "privileged"},
                {"not": {"op": "eq", "attr": "scope.suppressed", "value": True}},
            ]
        }
    )

    assert rule_matches(
        rule,
        {"type": "login", "count": 47, "tags": ["privileged", "remote"]},
        scope={"suppressed": False},
    )
    assert not rule_matches(
        rule,
        {"type": "login", "count": 4, "tags": ["privileged"]},
        scope={"suppressed": False},
    )
    assert not rule_matches(
        _rule({"op": "exists", "attr": "signal.__class__"}),
        {"__class__": "secret"},
    )

    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (Path(__file__).resolve().parents[2] / "src" / "aqelyn" / "detection").glob(
            "*.py"
        )
    )
    for forbidden in (
        "eval(",
        "exec(",
        "compile(",
        "__import__(",
        "importlib",
        "pickle.loads",
        "cloudpickle",
        "sklearn",
        "torch",
        "tensorflow",
    ):
        assert forbidden not in source


@pytest.mark.parametrize(
    "factory",
    [
        lambda: DetectionConfig(window_days=0),
        lambda: DetectionConfig(batch_size=0),
        lambda: DetectionConfig(min_samples=0),
        lambda: DetectionConfig(min_confidence=1.1),
        lambda: DetectionConfig(thresholds={"z_score": -1}),
        lambda: _rule({"op": "matches", "attr": "signal.type", "value": "login"}),
        lambda: _rule({"script": "return true"}),
        lambda: _rule({"op": "eq", "attr": "signal.type", "value": "login"}, kind="ml"),
        lambda: _rule({"op": "eq", "attr": "signal.type", "value": "login"}, version=0),
        lambda: _rule({"op": "eq", "attr": "signal.type", "value": "login"}, severity="info"),
        lambda: Projection(
            subject_ref="acct:alice",
            statement="privilege use may increase",
            basis={"samples": 10},
            horizon_days=7,
            confidence=0.5,
            advisory=False,
        ),
    ],
)
def test_det_config_invalid(factory: Callable[[], object]) -> None:
    with pytest.raises(DetectionConfigInvalid):
        factory()


def test_det_config_invalid_taxonomy_registered() -> None:
    assert "DetectionConfigInvalid" in ALL_ERROR_CODES
    assert "DetectionRuleNotFound" in ALL_ERROR_CODES
    assert "ProfileNotFound" in ALL_ERROR_CODES


def test_det_d1_model_shapes() -> None:
    anomaly = AnomalyMeasure(
        metric="login_count",
        observed=47.0,
        baseline_value=3.0,
        measure="z_score",
        value=8.8,
        threshold=3.0,
        profile_version=2,
    )
    detection = ThreatDetection(
        tenant_id=TENANT,
        rule_id="rule-login-spike",
        rule_version=3,
        subject_ref="acct:alice",
        kind="behavioral",
        signal_refs=[
            SignalRef(
                source_type="observation",
                source_id="login-count:alice:2026-07-15",
                evidence_id=new_id("evd"),
                observed_at=NOW,
            )
        ],
        anomaly=anomaly,
        confidence=0.82,
        severity="high",
        severity_score=76.0,
        technique_ids=["T1078"],
        evidence_id=new_id("evd"),
        profile_version=2,
        reason="Account alice averaged 3 logins/day; observed 47.",
        detected_at=NOW,
    )

    assert detection.id.startswith("det_")
    assert detection.anomaly is not None
    assert detection.profile_version == detection.anomaly.profile_version


def _rule(
    condition: dict[str, object],
    *,
    kind: str = "rule",
    version: int = 1,
    severity: str = "high",
) -> DetectionRule:
    return DetectionRule(
        id="rule-login-spike",
        name="Login spike",
        description="Detects an unusual login count.",
        kind=kind,
        condition=condition,
        subject_type="identity",
        technique_ids=["T1078"],
        severity=severity,
        enabled=True,
        version=version,
        tenant_id=TENANT,
    )
