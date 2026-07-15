"""Threat Detection & Analytics Engine (EA-0017)."""

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
from aqelyn.detection.store import ProfileStore, RuleStore

__all__ = [
    "AnomalyMeasure",
    "BehaviorProfile",
    "DetectionConfig",
    "DetectionRule",
    "InMemoryProfileStore",
    "InMemoryRuleStore",
    "PostgresProfileStore",
    "PostgresRuleStore",
    "ProfileStore",
    "Projection",
    "RuleStore",
    "SignalRef",
    "ThreatDetection",
    "build_profile",
    "rule_matches",
]
