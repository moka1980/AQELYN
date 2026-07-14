"""Threat Intelligence Fusion Engine (EA-0014)."""

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
)
from aqelyn.threat.normalize import (
    indicator_to_object,
    normalize_record,
    object_to_indicator,
    register_threat_object_types,
)

__all__ = [
    "FeedRecord",
    "FusionConfig",
    "IndicatorType",
    "MatchReport",
    "MatchVia",
    "QuarantinedFeedRecord",
    "ThreatFusionEngine",
    "ThreatIndicator",
    "ThreatMatch",
    "indicator_to_object",
    "normalize_record",
    "object_to_indicator",
    "register_threat_object_types",
]
