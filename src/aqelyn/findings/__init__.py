"""Finding model (T5). Implements Finding-model.spec.md:
Finding, FindingStore, dedup/reopen, transitions."""

from aqelyn.events.registry import EventTypeRegistry
from aqelyn.findings.memory import InMemoryFindingStore
from aqelyn.findings.models import (
    AuditEntry,
    Automation,
    Finding,
    FindingQuery,
    Remediation,
)
from aqelyn.findings.store import FindingStore

FINDING_EVENTS: dict[str, int] = {
    "aqelyn.finding.raised": 1,
    "aqelyn.finding.status_changed": 1,
    "aqelyn.finding.regressed": 1,
}


def register_finding_events(registry: EventTypeRegistry) -> None:
    """Register the event types owned by the Finding model (EA-0003 §7)."""
    for name, ver in FINDING_EVENTS.items():
        registry.register(name, ver, None)


__all__ = [
    "FINDING_EVENTS",
    "AuditEntry",
    "Automation",
    "Finding",
    "FindingQuery",
    "FindingStore",
    "InMemoryFindingStore",
    "Remediation",
    "register_finding_events",
]
