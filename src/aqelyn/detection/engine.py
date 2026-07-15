"""Threat Detection reference engine (EA-0017 D3/D4)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast

from aqelyn.conventions import ActorRef, is_valid, new_id, utc_now
from aqelyn.conventions.errors import (
    DetectionConfigInvalid,
    DetectionRuleNotFound,
    ProfileNotFound,
    StoreUnavailable,
)
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
    Projection,
    SignalRef,
    ThreatDetection,
)
from aqelyn.detection.rules import rule_matches
from aqelyn.detection.scoring import MissionImpactProvider, score_detection
from aqelyn.detection.store import ProfileStore, RuleStore, validate_tenant
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord
from aqelyn.evidence.store import EvidenceStore
from aqelyn.findings import Automation, Finding, FindingStore, Remediation
from aqelyn.findings.models import Severity
from aqelyn.mission.models import MissionConfig
from aqelyn.threat.models import ThreatIndicator
from aqelyn.trust import TrustEngine

_ACTOR = ActorRef(actor_type="system", actor_id="detection_engine")
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
        evidence_store: EvidenceStore | None = None,
        finding_store: FindingStore | None = None,
        threat_indicators: Mapping[str, ThreatIndicator] | None = None,
        actor: ActorRef | None = None,
        source_id: str | None = None,
        config: DetectionConfig | None = None,
    ) -> None:
        self.rule_store = rule_store
        self.profile_store = profile_store
        self.trust_engine = trust_engine or TrustEngine()
        self.mission_engine = mission_engine
        self.mission_config = mission_config or MissionConfig()
        self.evidence_store = evidence_store
        self.finding_store = finding_store
        self.threat_indicators = dict(threat_indicators or {})
        self.actor = actor or _ACTOR
        self.source_id = source_id or new_id("src")
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

    async def correlate_signals(
        self,
        detections: Sequence[ThreatDetection],
        *,
        tenant_id: str | None = None,
    ) -> list[ThreatDetection]:
        selected_tenant = validate_tenant(tenant_id)
        selected = [
            detection
            for detection in detections[: self.config.batch_size]
            if selected_tenant is None or detection.tenant_id == selected_tenant
        ]
        groups: dict[tuple[str | None, str, tuple[str, ...]], list[ThreatDetection]] = {}
        for detection in selected:
            key = (
                detection.tenant_id,
                detection.subject_ref,
                tuple(await self.map_techniques(detection)),
            )
            groups.setdefault(key, []).append(detection)

        correlated: list[ThreatDetection] = []
        for group in groups.values():
            ordered = sorted(group, key=lambda item: (item.detected_at, item.id))
            if len(ordered) == 1:
                correlated.append(ordered[0].model_copy(deep=True))
                continue
            correlated.append(self._merge_detections(ordered))
        return _stable_detections(correlated)

    async def map_techniques(self, detection: ThreatDetection) -> list[str]:
        techniques = list(detection.technique_ids)
        for signal in detection.signal_refs:
            indicator = self.threat_indicators.get(signal.source_id)
            if indicator is not None:
                techniques.extend(indicator.ttps)
        return sorted(dict.fromkeys(technique for technique in techniques if technique.strip()))

    async def detections_to_findings(
        self,
        detections: Sequence[ThreatDetection],
        *,
        by: ActorRef,
        prioritize: bool = True,
    ) -> list[str]:
        if self.evidence_store is None:
            raise StoreUnavailable("detections_to_findings requires an EvidenceStore")
        if self.finding_store is None:
            raise StoreUnavailable("detections_to_findings requires a FindingStore")

        ordered = list(detections[: self.config.batch_size])
        if prioritize:
            ordered.sort(key=lambda item: (-item.severity_score, item.id))
        finding_ids: list[str] = []
        for detection in ordered:
            evidence = await self._record_detection_evidence(detection, by=by)
            finding = await self.finding_store.raise_finding(
                _finding_for_detection(detection, evidence=evidence)
            )
            finding_ids.append(finding.id)
        return finding_ids

    async def project(
        self,
        *,
        subject_ref: str,
        horizon_days: int,
        basis: Mapping[str, object] | None = None,
        tenant_id: str | None = None,
        confidence: float = 0.0,
    ) -> Projection:
        return Projection(
            tenant_id=tenant_id,
            subject_ref=subject_ref,
            statement=(
                f"Advisory projection for {subject_ref} over {horizon_days} days; "
                "not a finding and not evidence."
            ),
            basis=dict(basis or {}),
            horizon_days=horizon_days,
            confidence=confidence,
            advisory=True,
        )

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

    def _merge_detections(self, detections: Sequence[ThreatDetection]) -> ThreatDetection:
        base = sorted(
            detections, key=lambda item: (-item.confidence, -item.severity_score, item.id)
        )[0]
        signals: list[SignalRef] = []
        for detection in detections:
            for signal in detection.signal_refs:
                if signal.model_dump(mode="json") not in [
                    existing.model_dump(mode="json") for existing in signals
                ]:
                    signals.append(signal.model_copy(deep=True))
        return base.model_copy(
            update={
                "id": new_id("det"),
                "signal_refs": signals,
                "confidence": max(detection.confidence for detection in detections),
                "severity_score": max(detection.severity_score for detection in detections),
                "technique_ids": sorted(
                    dict.fromkeys(
                        technique
                        for detection in detections
                        for technique in detection.technique_ids
                    )
                ),
                "reason": (
                    f"Correlated {len(detections)} detections for {base.subject_ref}; "
                    "SOC owns incident correlation."
                ),
            },
            deep=True,
        )

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

    async def _record_detection_evidence(
        self, detection: ThreatDetection, *, by: ActorRef
    ) -> EvidenceRecord:
        assert self.evidence_store is not None
        now = utc_now()
        record = EvidenceRecord(
            id="",
            tenant_id=detection.tenant_id,
            evidence_type="detection.threat",
            schema_version=1,
            subject=Subject(
                object_ids=_subject_objects(detection), evidence_id=detection.evidence_id
            ),
            collected_at=detection.detected_at,
            recorded_at=now,
            collector=by,
            source_id=self.source_id,
            method="detection.detections_to_findings/v1",
            content={
                "detection": detection.model_dump(mode="json"),
                "explain": self.explain(detection),
                "pinned": {
                    "rule_id": detection.rule_id,
                    "rule_version": detection.rule_version,
                    "profile_version": detection.profile_version,
                },
            },
            content_hash="",
            confidence=detection.confidence,
            labels={"module": "EA-0017", "kind": "threat_detection"},
            seq=0,
            prev_hash=None,
            record_hash="",
        )
        return await self.evidence_store.add(record)


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


def _finding_for_detection(detection: ThreatDetection, *, evidence: EvidenceRecord) -> Finding:
    return Finding(
        id="",
        tenant_id=detection.tenant_id,
        finding_type="detection.threat",
        schema_version=1,
        dedup_key=_dedup_key(detection),
        title=f"Threat detection on {detection.subject_ref}",
        severity=_severity(detection.severity),
        severity_score=detection.severity_score,
        status="open",
        what_happened=detection.reason,
        why_it_matters=(
            "The Threat Detection Engine raised an evidence-backed detection that may indicate "
            "malicious or risky behavior."
        ),
        how_determined=(
            "The engine evaluated declarative rules and/or pinned behavioral baselines, recorded "
            "the detection as evidence, and preserved the rule/profile versions used."
        ),
        risk_of_inaction=(
            "If this detection is not triaged, the related suspicious activity may remain "
            "uninvestigated."
        ),
        evidence_ids=[evidence.id],
        affected_object_ids=_subject_objects(detection),
        expert_details={
            "detection": detection.model_dump(mode="json"),
            "pinned": {
                "rule_id": detection.rule_id,
                "rule_version": detection.rule_version,
                "profile_version": detection.profile_version,
            },
            "no_action": True,
        },
        remediation=Remediation(
            summary="Triage the detection and hand off any response through SOC/Workflow.",
            steps=[
                "Review the detection evidence and pinned rule/profile versions.",
                "Confirm whether the activity represents a true positive.",
                "Use SOC and Workflow for any response proposal.",
            ],
            difficulty="medium",
            estimated_effort=None,
            expected_outcome="The detection is triaged without executing any response action.",
            references=["EA-0017 §0", "EA-0015", "EA-0008"],
        ),
        automation=Automation(
            eligibility="none",
            action_ref=None,
            requires_approval=True,
            risk_note="Threat Detection never acts directly; response belongs to SOC/Workflow.",
        ),
        confidence=detection.confidence,
        source_engine="detection_engine",
        correlation_id=_dedup_key(detection),
        first_detected_at=detection.detected_at,
        last_detected_at=detection.detected_at,
    )


def _dedup_key(detection: ThreatDetection) -> str:
    return (
        f"detection:{detection.rule_id}:v{detection.rule_version}:"
        f"{detection.subject_ref}:{detection.profile_version or 'none'}"
    )


def _subject_objects(detection: ThreatDetection) -> list[str]:
    if is_valid(detection.subject_ref, "obj"):
        return [detection.subject_ref]
    return []
