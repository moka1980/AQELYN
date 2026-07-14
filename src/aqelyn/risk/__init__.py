"""Risk Intelligence Engine (EA-0013)."""

from aqelyn.risk.correlate import RiskCorrelator, correlate, explain
from aqelyn.risk.models import (
    AppetiteConfig,
    CorrelationSignal,
    Risk,
    RiskBand,
    RiskConfig,
    RiskLifecycle,
    RiskSnapshot,
    RiskTreatment,
    SignalKind,
    SignalRef,
)
from aqelyn.risk.scoring import band_for_score, score_risk

__all__ = [
    "AppetiteConfig",
    "CorrelationSignal",
    "Risk",
    "RiskBand",
    "RiskConfig",
    "RiskCorrelator",
    "RiskLifecycle",
    "RiskSnapshot",
    "RiskTreatment",
    "SignalKind",
    "SignalRef",
    "band_for_score",
    "correlate",
    "explain",
    "score_risk",
]
