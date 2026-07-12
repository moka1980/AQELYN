"""Evidence & Integrity (T4). Implements EA-0004-evidence-and-integrity.spec.md:
EvidenceRecord, hash-chain, packages, EvidenceStore + BlobStore."""

from aqelyn.evidence.memory import InMemoryBlobStore, InMemoryEvidenceStore
from aqelyn.evidence.models import (
    BlobRef,
    EvidencePackage,
    EvidenceRecord,
    VerifyResult,
)
from aqelyn.evidence.store import BlobStore, EvidenceStore

__all__ = [
    "BlobRef",
    "BlobStore",
    "EvidencePackage",
    "EvidenceRecord",
    "EvidenceStore",
    "InMemoryBlobStore",
    "InMemoryEvidenceStore",
    "VerifyResult",
    "register_evidence_events",
]


from aqelyn.events.registry import EventTypeRegistry

EVIDENCE_EVENTS: dict[str, int] = {"aqelyn.evidence.recorded": 1}


def register_evidence_events(registry: EventTypeRegistry) -> None:
    """Register the event types owned by EA-0004 (EA-0003 §7 extensibility)."""
    for name, ver in EVIDENCE_EVENTS.items():
        registry.register(name, ver, None)
