"""Threat Intelligence Fusion Engine (EA-0014)."""

from aqelyn.threat.confidence import score_confidence
from aqelyn.threat.engine import ThreatFusionEngine
from aqelyn.threat.models import (
    FeedRecord,
    FusionConfig,
    IndicatorType,
    MatchReport,
    MatchVia,
    QuarantinedFeedRecord,
    ThreatIndicator,
    ThreatMatch,
    ThreatSource,
)
from aqelyn.threat.normalize import (
    indicator_to_object,
    normalize_record,
    object_to_indicator,
    register_threat_object_types,
)
from aqelyn.threat.registry import InMemoryThreatSourceRegistry, ThreatSourceRegistry

__all__ = [
    "FeedRecord",
    "FusionConfig",
    "InMemoryThreatSourceRegistry",
    "IndicatorType",
    "MatchReport",
    "MatchVia",
    "QuarantinedFeedRecord",
    "ThreatFusionEngine",
    "ThreatIndicator",
    "ThreatMatch",
    "ThreatSource",
    "ThreatSourceRegistry",
    "indicator_to_object",
    "normalize_record",
    "object_to_indicator",
    "register_threat_object_types",
    "score_confidence",
]
