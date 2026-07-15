"""Threat Detection reference engine (EA-0017 D3)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast

from aqelyn.conventions import new_id, utc_now
from aqelyn.conventions.errors import DetectionConfigInvalid, DetectionRuleNotFound, ProfileNotFound
from aqelyn.detection.anomaly import (
    ObservedMetric,
    anomaly_measure,
    anomaly_reason,
    is_anomalous,
)
from aqelyn.detection.models import (
    AnomalyMeasure,
    BehaviorProfile,
    DetectionConfig,
    DetectionRule,
    SignalRef,
    ThreatDetection,
)
from aqelyn.detection.rules import rule_matches
from aqelyn.detection.scoring import MissionImpactProvider, score_detection
from aqelyn.detection.store import ProfileStore, RuleStore, validate_tenant
from aqelyn.evidence import EvidenceRecord
from aqelyn.findings.models import Severity
from aqelyn.mission.models import MissionConfig
from aqelyn.trust import TrustEngine

_ACTOR_ID = "detection_engine"
_DEFAULT_THRESHOLDS: dict[str, float] = {
    "z_score": 3.0,
    "percentile": 1.0,
    "rate_change": 1.0,
}


@dataclass(frozen=True)
class RuleSignal:
    subject_ref: str
    subject_type: str
    data: Mapping[str, Any]
    evidence: EvidenceRecord
    observed_at: datetime | None = None


@dataclass(frozen=True)
class _ReproductionInput:
    kind: Literal["rule", "anomaly"]
    detection: ThreatDetection
    rule_id: str
    rule_version: int
    evidence: EvidenceRecord
    signal: RuleSignal | None = None
    observation: ObservedMetric | None = None
    profile_id: str | None = None
    profile_version: int | None = None


class ThreatDetectionEngine:
    def __init__(
        self,
        *,
        rule_store: RuleStore,
        profile_store: ProfileStore,
        trust_engine: TrustEngine | None = None,
        mission_engine: MissionImpactProvider | None = None,
        mission_config: MissionConfig | None = None,
        config: DetectionConfig | None = None,
    ) -> None:
        self.rule_store = rule_store
        self.profile_store = profile_store
        self.trust_engine = trust_engine or TrustEngine()
        self.mission_engine = mission_engine
        self.mission_config = mission_config or MissionConfig()
        self.config = config or DetectionConfig()
        self._reproduction_inputs: dict[str, _ReproductionInput] = {}

    async def evaluate_rules(
        self,
        *,
        tenant_id: str | None,
        signals: Sequence[RuleSignal],
        scope: Mapping[str, Any] | None = None,
        detected_at: datetime | None = None,
    ) -> list[ThreatDetection]:
        selected_tenant = validate_tenant(tenant_id)
        selected_at = detected_at or utc_now()
        detections: list[ThreatDetection] = []
        rules = await self._active_rules(tenant_id=selected_tenant, kind="rule")
        for rule in rules:
            for signal in signals[: self.config.batch_size]:
                if signal.subject_type != rule.subject_type:
                    continue
                if rule_matches(rule, dict(signal.data), scope=dict(scope or {})):
                    detection = await self._rule_detection(
                        rule,
                        signal,
                        detected_at=selected_at,
                    )
                    if detection.confidence >= self.config.min_confidence:
                        self._remember_rule(detection, rule=rule, signal=signal)
                        detections.append(detection)
        return _stable_detections(detections)

    async def detect_anomalies(
        self,
        *,
        tenant_id: str | None,
        observations: Sequence[ObservedMetric],
        scope: Mapping[str, Any] | None = None,
        detected_at: datetime | None = None,
    ) -> list[ThreatDetection]:
        selected_tenant = validate_tenant(tenant_id)
        selected_at = detected_at or utc_now()
        detections: list[ThreatDetection] = []
        rules = await self._active_rules(tenant_id=selected_tenant, kind="behavioral")
        for observation in observations[: self.config.batch_size]:
            profile = await self.profile_store.latest(
                subject_ref=observation.subject_ref,
                metric=observation.metric,
                tenant_id=selected_tenant,
            )
            if profile is None or profile.insufficient_data:
                continue
            for rule in rules:
                if observation.subject_type != rule.subject_type:
                    continue
                threshold = self._threshold(observation.measure)
                anomaly = anomaly_measure(
                    profile,
                    observed=observation.value,
                    measure=observation.measure,
                    threshold=threshold,
                )
                signal = _anomaly_signal(
                    observation,
                    profile=profile,
                    anomaly=anomaly,
                    scope=scope,
                )
                matches_rule = rule_matches(rule, signal, scope=dict(scope or {}))
                if not is_anomalous(anomaly) or not matches_rule:
                    continue
                detection = await self._anomaly_detection(
                    rule,
                    profile,
                    observation,
                    anomaly,
                    detected_at=selected_at,
                )
                if detection.confidence >= self.config.min_confidence:
                    self._remember_anomaly(
                        detection,
                        rule=rule,
                        profile=profile,
                        observation=observation,
                    )
                    detections.append(detection)
        return _stable_detections(detections)

    async def reproduce(self, detection_id: str) -> ThreatDetection:
        remembered = self._reproduction_inputs.get(detection_id)
        if remembered is None:
            raise DetectionRuleNotFound(f"detection not found: {detection_id}")
        rule = await self.rule_store.get(remembered.rule_id, version=remembered.rule_version)
        if rule is None:
            raise DetectionRuleNotFound(
                f"detection rule not found: {remembered.rule_id} v{remembered.rule_version}"
            )
        if remembered.kind == "rule":
            assert remembered.signal is not None
            reproduced = await self._rule_detection(
                rule,
                remembered.signal,
                detected_at=remembered.detection.detected_at,
                detection_id=remembered.detection.id,
            )
        else:
            assert remembered.profile_id is not None
            assert remembered.profile_version is not None
            assert remembered.observation is not None
            profile = await self.profile_store.get(
                remembered.profile_id,
                version=remembered.profile_version,
            )
            if profile is None:
                raise ProfileNotFound(
                    f"profile not found: {remembered.profile_id} v{remembered.profile_version}"
                )
            anomaly = anomaly_measure(
                profile,
                observed=remembered.observation.value,
                measure=remembered.observation.measure,
                threshold=remembered.detection.anomaly.threshold
                if remembered.detection.anomaly is not None
                else self._threshold(remembered.observation.measure),
            )
            reproduced = await self._anomaly_detection(
                rule,
                profile,
                remembered.observation,
                anomaly,
                detected_at=remembered.detection.detected_at,
                detection_id=remembered.detection.id,
            )
        return reproduced

    def explain(self, detection: ThreatDetection) -> dict[str, object]:
        return {
            "detection_id": detection.id,
            "rule": {"id": detection.rule_id, "version": detection.rule_version},
            "profile_version": detection.profile_version,
            "anomaly": (
                None if detection.anomaly is None else detection.anomaly.model_dump(mode="json")
            ),
            "signal_refs": [signal.model_dump(mode="json") for signal in detection.signal_refs],
            "confidence": detection.confidence,
            "severity": detection.severity,
            "severity_score": detection.severity_score,
            "technique_ids": list(detection.technique_ids),
            "reason": detection.reason,
            "detected_at": detection.detected_at.isoformat(),
        }

    async def _active_rules(self, *, tenant_id: str | None, kind: str) -> list[DetectionRule]:
        latest = await self.rule_store.list(tenant_id=tenant_id, enabled_only=False)
        return [rule for rule in latest if rule.enabled and rule.kind == kind]

    async def _rule_detection(
        self,
        rule: DetectionRule,
        signal: RuleSignal,
        *,
        detected_at: datetime,
        detection_id: str | None = None,
    ) -> ThreatDetection:
        score = await score_detection(
            subject_ref=signal.subject_ref,
            severity=_severity(rule.severity),
            evidence=[signal.evidence],
            trust_engine=self.trust_engine,
            detected_at=detected_at,
            mission_engine=self.mission_engine,
            mission_config=self.mission_config,
        )
        return ThreatDetection(
            id=detection_id or new_id("det"),
            tenant_id=signal.evidence.tenant_id,
            rule_id=rule.id,
            rule_version=rule.version,
            subject_ref=signal.subject_ref,
            kind=rule.kind,
            signal_refs=[
                SignalRef(
                    source_type="signal",
                    source_id=str(signal.data.get("id", signal.subject_ref)),
                    evidence_id=signal.evidence.id,
                    observed_at=signal.observed_at or signal.evidence.collected_at,
                )
            ],
            anomaly=None,
            confidence=score.confidence,
            severity=rule.severity,
            severity_score=score.severity_score,
            technique_ids=list(rule.technique_ids),
            evidence_id=signal.evidence.id,
            profile_version=None,
            reason=(
                f"Rule {rule.name} matched {signal.subject_ref} using cited evidence "
                f"{signal.evidence.id}; confidence came from Trust {score.trust_method}."
            ),
            detected_at=detected_at,
        )

    async def _anomaly_detection(
        self,
        rule: DetectionRule,
        profile: BehaviorProfile,
        observation: ObservedMetric,
        anomaly: AnomalyMeasure,
        *,
        detected_at: datetime,
        detection_id: str | None = None,
    ) -> ThreatDetection:
        score = await score_detection(
            subject_ref=observation.subject_ref,
            severity=_severity(rule.severity),
            evidence=[observation.evidence],
            trust_engine=self.trust_engine,
            detected_at=detected_at,
            mission_engine=self.mission_engine,
            mission_config=self.mission_config,
        )
        return ThreatDetection(
            id=detection_id or new_id("det"),
            tenant_id=profile.tenant_id,
            rule_id=rule.id,
            rule_version=rule.version,
            subject_ref=observation.subject_ref,
            kind=rule.kind,
            signal_refs=[
                SignalRef(
                    source_type="observation",
                    source_id=_observation_source_id(observation),
                    evidence_id=observation.evidence.id,
                    observed_at=observation.observed_at,
                )
            ],
            anomaly=anomaly,
            confidence=score.confidence,
            severity=rule.severity,
            severity_score=score.severity_score,
            technique_ids=list(rule.technique_ids),
            evidence_id=observation.evidence.id,
            profile_version=profile.version,
            reason=anomaly_reason(
                subject_ref=observation.subject_ref,
                anomaly=anomaly,
                rule_version=rule.version,
            ),
            detected_at=detected_at,
        )

    def _threshold(self, measure: str) -> float:
        return self.config.thresholds.get(measure, _DEFAULT_THRESHOLDS[measure])

    def _remember_rule(
        self, detection: ThreatDetection, *, rule: DetectionRule, signal: RuleSignal
    ) -> None:
        self._reproduction_inputs[detection.id] = _ReproductionInput(
            kind="rule",
            detection=detection.model_copy(deep=True),
            rule_id=rule.id,
            rule_version=rule.version,
            evidence=signal.evidence.model_copy(deep=True),
            signal=signal,
        )

    def _remember_anomaly(
        self,
        detection: ThreatDetection,
        *,
        rule: DetectionRule,
        profile: BehaviorProfile,
        observation: ObservedMetric,
    ) -> None:
        self._reproduction_inputs[detection.id] = _ReproductionInput(
            kind="anomaly",
            detection=detection.model_copy(deep=True),
            rule_id=rule.id,
            rule_version=rule.version,
            profile_id=profile.id,
            profile_version=profile.version,
            evidence=observation.evidence.model_copy(deep=True),
            observation=observation,
        )


def _anomaly_signal(
    observation: ObservedMetric,
    *,
    profile: BehaviorProfile,
    anomaly: AnomalyMeasure,
    scope: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "subject_ref": observation.subject_ref,
        "subject_type": observation.subject_type,
        "metric": observation.metric,
        "observed": observation.value,
        "measure": anomaly.measure,
        "anomaly_value": anomaly.value,
        "threshold": anomaly.threshold,
        "profile_version": profile.version,
        "profile": dict(profile.baseline),
        "scope": dict(scope or {}),
    }


def _observation_source_id(observation: ObservedMetric) -> str:
    return f"{observation.subject_ref}:{observation.metric}:{observation.observed_at.isoformat()}"


def _stable_detections(detections: Sequence[ThreatDetection]) -> list[ThreatDetection]:
    return sorted(
        detections,
        key=lambda detection: (
            detection.detected_at.isoformat(),
            detection.rule_id,
            detection.rule_version,
            detection.subject_ref,
            detection.evidence_id,
        ),
    )


def _severity(value: str) -> Severity:
    if value not in {"low", "medium", "high", "critical"}:
        raise DetectionConfigInvalid(f"unknown severity: {value!r}")
    return cast(Severity, value)
