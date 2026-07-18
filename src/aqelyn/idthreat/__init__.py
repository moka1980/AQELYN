"""Identity Threat Detection & Behavioral Analytics (EA-0027)."""

from aqelyn.idthreat.dignity import dignity_gate
from aqelyn.idthreat.engine import (
    IdentityEvidenceLookup,
    IdentityThreatEngine,
    IdentityTrustAssessor,
)
from aqelyn.idthreat.memory import InMemoryIdentityDetectionStore
from aqelyn.idthreat.models import (
    VALID_BASIS_KINDS,
    VALID_DETECTION_STATUS,
    VALID_DETECTION_TYPES,
    DetectionType,
    IdentityBasis,
    IdentityBasisKind,
    IdentityDetection,
    IdentityDetectionStatus,
    IdentityObservation,
    IdThreatConfig,
    SignalRef,
    independent_signal_count,
)
from aqelyn.idthreat.postgres import PostgresIdentityDetectionStore
from aqelyn.idthreat.store import (
    IdentityDetectionStore,
    validate_replayable_detection,
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
    "IdentityDetectionStore",
    "IdentityEvidenceLookup",
    "IdentityObservation",
    "IdentityThreatEngine",
    "IdentityTrustAssessor",
    "InMemoryIdentityDetectionStore",
    "PostgresIdentityDetectionStore",
    "SignalRef",
    "dignity_gate",
    "independent_signal_count",
    "validate_replayable_detection",
]
