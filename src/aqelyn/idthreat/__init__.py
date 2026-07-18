"""Identity Threat Detection & Behavioral Analytics (EA-0027)."""

from aqelyn.idthreat.dignity import dignity_gate
from aqelyn.idthreat.models import (
    VALID_BASIS_KINDS,
    VALID_DETECTION_STATUS,
    VALID_DETECTION_TYPES,
    DetectionType,
    IdentityBasis,
    IdentityBasisKind,
    IdentityDetection,
    IdentityDetectionStatus,
    IdThreatConfig,
    SignalRef,
)

__all__ = [
    "VALID_BASIS_KINDS",
    "VALID_DETECTION_STATUS",
    "VALID_DETECTION_TYPES",
    "DetectionType",
    "IdThreatConfig",
    "IdentityBasis",
    "IdentityBasisKind",
    "IdentityDetection",
    "IdentityDetectionStatus",
    "SignalRef",
    "dignity_gate",
]
