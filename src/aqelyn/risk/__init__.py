"""Risk Intelligence Engine (EA-0013)."""

from aqelyn.risk.correlate import RiskCorrelator, correlate, explain
from aqelyn.risk.engine import RiskIntelligenceEngine
from aqelyn.risk.memory import InMemoryRiskSnapshotStore, InMemoryRiskStore
from aqelyn.risk.models import (
    AppetiteConfig,
    CorrelationSignal,
    Risk,
    RiskBand,
    RiskConfig,
    RiskLifecycle,
    RiskMissionContext,
    RiskMissionStatus,
    RiskMissionUnknownCause,
    RiskSnapshot,
    RiskTreatment,
    SignalKind,
    SignalRef,
)
from aqelyn.risk.scoring import band_for_score, mission_context_from_results, score_risk
from aqelyn.risk.service import RISK_EVENTS, RiskIntelligenceService, register_risk_events
from aqelyn.risk.store import RiskSnapshotStore, RiskStore, new_risk_snapshot_id

__all__ = [
    "RISK_EVENTS",
    "AppetiteConfig",
    "CorrelationSignal",
    "InMemoryRiskSnapshotStore",
    "InMemoryRiskStore",
    "Risk",
    "RiskBand",
    "RiskConfig",
    "RiskCorrelator",
    "RiskIntelligenceEngine",
    "RiskIntelligenceService",
    "RiskLifecycle",
    "RiskMissionContext",
    "RiskMissionStatus",
    "RiskMissionUnknownCause",
    "RiskSnapshot",
    "RiskSnapshotStore",
    "RiskStore",
    "RiskTreatment",
    "SignalKind",
    "SignalRef",
    "band_for_score",
    "correlate",
    "explain",
    "mission_context_from_results",
    "new_risk_snapshot_id",
    "register_risk_events",
    "score_risk",
]
