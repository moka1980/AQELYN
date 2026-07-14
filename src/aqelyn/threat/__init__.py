"""Threat Intelligence Fusion Engine (EA-0014)."""

from aqelyn.threat.confidence import score_confidence
from aqelyn.threat.correlate import correlate
from aqelyn.threat.engine import THREAT_RESPONSE_ACTION, ThreatFusionEngine
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
from aqelyn.threat.service import THREAT_EVENTS, ThreatFusionService, register_threat_events

__all__ = [
    "THREAT_EVENTS",
    "THREAT_RESPONSE_ACTION",
    "FeedRecord",
    "FusionConfig",
    "InMemoryThreatSourceRegistry",
    "IndicatorType",
    "MatchReport",
    "MatchVia",
    "QuarantinedFeedRecord",
    "ThreatFusionEngine",
    "ThreatFusionService",
    "ThreatIndicator",
    "ThreatMatch",
    "ThreatSource",
    "ThreatSourceRegistry",
    "correlate",
    "indicator_to_object",
    "normalize_record",
    "object_to_indicator",
    "register_threat_events",
    "register_threat_object_types",
    "score_confidence",
]
