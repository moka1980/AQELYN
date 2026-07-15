"""Threat Detection & Analytics Engine (EA-0017)."""

from aqelyn.detection.anomaly import ObservedMetric, anomaly_measure, is_anomalous
from aqelyn.detection.engine import RuleSignal, ThreatDetectionEngine
from aqelyn.detection.memory import InMemoryProfileStore, InMemoryRuleStore
from aqelyn.detection.models import (
    AnomalyMeasure,
    BehaviorProfile,
    DetectionConfig,
    DetectionRule,
    Projection,
    SignalRef,
    ThreatDetection,
)
from aqelyn.detection.postgres import PostgresProfileStore, PostgresRuleStore
from aqelyn.detection.profiles import build_profile
from aqelyn.detection.rules import rule_matches
from aqelyn.detection.scoring import DetectionScore, MissionImpactProvider, score_detection
from aqelyn.detection.service import (
    DETECTION_EVENTS,
    ThreatDetectionService,
    register_detection_events,
)
from aqelyn.detection.store import ProfileStore, RuleStore

__all__ = [
    "DETECTION_EVENTS",
    "AnomalyMeasure",
    "BehaviorProfile",
    "DetectionConfig",
    "DetectionRule",
    "DetectionScore",
    "InMemoryProfileStore",
    "InMemoryRuleStore",
    "MissionImpactProvider",
    "ObservedMetric",
    "PostgresProfileStore",
    "PostgresRuleStore",
    "ProfileStore",
    "Projection",
    "RuleSignal",
    "RuleStore",
    "SignalRef",
    "ThreatDetection",
    "ThreatDetectionEngine",
    "ThreatDetectionService",
    "anomaly_measure",
    "build_profile",
    "is_anomalous",
    "register_detection_events",
    "rule_matches",
    "score_detection",
]
