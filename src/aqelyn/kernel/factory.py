"""Kernel construction + dependency injection (EA-0001 §7, D3)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import ConfigError, StoreUnavailable
from aqelyn.events import EventTypeRegistry, InMemoryEventBus
from aqelyn.evidence import InMemoryBlobStore, InMemoryEvidenceStore, register_evidence_events
from aqelyn.findings import InMemoryFindingStore, register_finding_events
from aqelyn.graph import InMemoryKnowledgeGraph, KnowledgeGraph
from aqelyn.graph.postgres import PostgresKnowledgeGraph
from aqelyn.graph.service import KnowledgeGraphService
from aqelyn.kernel.config import AQELYNConfig
from aqelyn.kernel.kernel import AQKernel
from aqelyn.kernel.service import HealthStatus
from aqelyn.kernel.wiring import BusObjectEventSink
from aqelyn.objects import InMemoryObjectStore, ObjectStore, ObjectTypeRegistry
from aqelyn.objects.postgres import PostgresObjectStore


@dataclass
class Runtime:
    """The wired kernel plus the shared infrastructure it injects."""

    kernel: AQKernel
    event_bus: InMemoryEventBus
    object_store: ObjectStore
    evidence_store: InMemoryEvidenceStore
    finding_store: InMemoryFindingStore
    blob_store: InMemoryBlobStore
    knowledge_graph: KnowledgeGraph
    knowledge_graph_service: KnowledgeGraphService


class _RuntimeService:
    def __init__(
        self,
        name: str,
        *,
        dependencies: Sequence[str] = (),
        health_check: Callable[[], Awaitable[None]] | None = None,
        close: Callable[[], Awaitable[None]] | None = None,
        critical: bool = True,
    ) -> None:
        self._name = name
        self._dependencies = tuple(dependencies)
        self._health_check = health_check
        self._close = close
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def dependencies(self) -> Sequence[str]:
        return self._dependencies

    @property
    def critical(self) -> bool:
        return self._critical

    async def start(self) -> None:
        await self._check()
        self._started = True

    async def stop(self) -> None:
        try:
            if self._close is not None:
                await self._close()
        finally:
            self._started = False

    async def health(self) -> HealthStatus:
        try:
            await self._check()
        except StoreUnavailable as exc:
            return HealthStatus(status="unavailable", ready=False, detail=exc.message)
        if not self._started:
            return HealthStatus(status="degraded", ready=False, detail="service not started")
        return HealthStatus(status="healthy", ready=True)

    async def _check(self) -> None:
        if self._health_check is None:
            return
        try:
            await self._health_check()
        except StoreUnavailable:
            raise
        except Exception as exc:
            raise StoreUnavailable(str(exc)) from exc


async def _check_object_store(object_store: ObjectStore) -> None:
    await object_store.get(new_id("obj"), resolve_merged=False)


def _register_runtime_services(
    kernel: AQKernel,
    *,
    object_store: ObjectStore,
    knowledge_graph: KnowledgeGraph,
    close_object_store: Callable[[], Awaitable[None]] | None = None,
) -> KnowledgeGraphService:
    kernel.register(_RuntimeService("event_bus"))
    kernel.register(
        _RuntimeService(
            "object_store",
            dependencies=("event_bus",),
            health_check=lambda: _check_object_store(object_store),
            close=close_object_store,
        )
    )
    service = KnowledgeGraphService(knowledge_graph, object_store)
    kernel.register(service)
    return service


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
    knowledge_graph = InMemoryKnowledgeGraph(object_store)
    kernel = AQKernel(cfg, event_bus=bus)
    knowledge_graph_service = _register_runtime_services(
        kernel,
        object_store=object_store,
        knowledge_graph=knowledge_graph,
    )
    return Runtime(
        kernel=kernel,
        event_bus=bus,
        object_store=object_store,
        evidence_store=evidence_store,
        finding_store=finding_store,
        blob_store=InMemoryBlobStore(),
        knowledge_graph=knowledge_graph,
        knowledge_graph_service=knowledge_graph_service,
    )


async def create_runtime(config: AQELYNConfig | None = None) -> Runtime:
    """Build the runtime selected by AQELYN_BACKEND."""
    cfg = config or AQELYNConfig.load()
    if cfg.backend == "memory":
        return create_inmemory_runtime(cfg)
    if cfg.database_url is None:
        raise ConfigError("backend=postgres requires AQELYN_DATABASE_URL")

    registry = EventTypeRegistry()
    register_evidence_events(registry)
    register_finding_events(registry)
    bus = InMemoryEventBus(registry=registry)
    sink = BusObjectEventSink(bus)
    object_store = await PostgresObjectStore.connect(
        cfg.database_url,
        registry=ObjectTypeRegistry(),
        mode=cfg.tenant_mode,
        event_sink=sink,
    )
    evidence_store = InMemoryEvidenceStore(mode=cfg.tenant_mode, event_bus=bus)
    finding_store = InMemoryFindingStore(
        mode=cfg.tenant_mode, event_bus=bus, evidence_exists=evidence_store.exists
    )
    knowledge_graph = PostgresKnowledgeGraph(object_store._pool)
    kernel = AQKernel(cfg, event_bus=bus)
    knowledge_graph_service = _register_runtime_services(
        kernel,
        object_store=object_store,
        knowledge_graph=knowledge_graph,
        close_object_store=object_store.close,
    )
    return Runtime(
        kernel=kernel,
        event_bus=bus,
        object_store=object_store,
        evidence_store=evidence_store,
        finding_store=finding_store,
        blob_store=InMemoryBlobStore(),
        knowledge_graph=knowledge_graph,
        knowledge_graph_service=knowledge_graph_service,
    )
