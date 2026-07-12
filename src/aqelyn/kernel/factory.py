"""Kernel construction + dependency injection (EA-0001 §7, D3)."""

from __future__ import annotations

from dataclasses import dataclass

from aqelyn.events import EventTypeRegistry, InMemoryEventBus
from aqelyn.evidence import InMemoryBlobStore, InMemoryEvidenceStore, register_evidence_events
from aqelyn.findings import InMemoryFindingStore, register_finding_events
from aqelyn.kernel.config import AQELYNConfig
from aqelyn.kernel.kernel import AQKernel
from aqelyn.kernel.wiring import BusObjectEventSink
from aqelyn.objects import InMemoryObjectStore, ObjectTypeRegistry


@dataclass
class Runtime:
    """The wired kernel plus the shared infrastructure it injects."""

    kernel: AQKernel
    event_bus: InMemoryEventBus
    object_store: InMemoryObjectStore
    evidence_store: InMemoryEvidenceStore
    finding_store: InMemoryFindingStore
    blob_store: InMemoryBlobStore


def create_inmemory_runtime(config: AQELYNConfig | None = None) -> Runtime:
    """Build a fully wired in-memory runtime (used by C-001 and unit tests)."""
    cfg = config or AQELYNConfig(backend="memory")
    registry = EventTypeRegistry()
    register_evidence_events(registry)
    register_finding_events(registry)
    bus = InMemoryEventBus(registry=registry)

    sink = BusObjectEventSink(bus)
    object_store = InMemoryObjectStore(
        registry=ObjectTypeRegistry(), mode=cfg.tenant_mode, event_sink=sink
    )
    evidence_store = InMemoryEvidenceStore(mode=cfg.tenant_mode, event_bus=bus)
    finding_store = InMemoryFindingStore(
        mode=cfg.tenant_mode, event_bus=bus, evidence_exists=evidence_store.exists
    )
    kernel = AQKernel(cfg, event_bus=bus)
    return Runtime(
        kernel=kernel,
        event_bus=bus,
        object_store=object_store,
        evidence_store=evidence_store,
        finding_store=finding_store,
        blob_store=InMemoryBlobStore(),
    )
