"""Security Operations AQService wrapper and events (EA-0015 S5)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import EvidenceNotFound, ObjectNotFound, StoreUnavailable
from aqelyn.events.registry import EventTypeRegistry
from aqelyn.kernel.service import HealthStatus
from aqelyn.soc.engine import SecurityOperationsEngine
from aqelyn.soc.models import SOCConfig
from aqelyn.soc.store import SOCStore

SOC_EVENTS: dict[str, int] = {
    "aqelyn.soc.alert_raised": 1,
    "aqelyn.soc.incident_created": 1,
    "aqelyn.soc.incident_status_changed": 1,
    "aqelyn.soc.response_proposed": 1,
}


def register_soc_events(registry: EventTypeRegistry) -> None:
    for event_type, schema_version in SOC_EVENTS.items():
        registry.register(event_type, schema_version, None)


class SecurityOperationsService:
    def __init__(
        self,
        engine: SecurityOperationsEngine,
        *,
        store: SOCStore,
        close_store: Callable[[], Awaitable[None]] | None = None,
        dependencies: Sequence[str] = (
            "object_store",
            "knowledge_graph",
            "mission_engine",
            "workflow_engine",
            "risk_engine",
            "threat_fusion_engine",
        ),
        critical: bool = True,
    ) -> None:
        self.engine = engine
        self._store = store
        self._close_store = close_store
        self._dependencies = tuple(dependencies)
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return "soc_engine"

    @property
    def dependencies(self) -> Sequence[str]:
        return self._dependencies

    @property
    def critical(self) -> bool:
        return self._critical

    async def start(self) -> None:
        await self._check_available()
        self._started = True

    async def stop(self) -> None:
        try:
            if self._close_store is not None:
                await self._close_store()
        finally:
            self._started = False

    async def health(self) -> HealthStatus:
        dependencies: dict[str, str] = {}
        try:
            self._check_config()
            await self._check_store()
            dependencies["soc_store"] = "healthy"
            await self._check_evidence_store()
            dependencies["evidence_store"] = "healthy"
            await self._check_object_store()
            dependencies["object_store"] = "healthy"
            await self._check_knowledge_graph()
            dependencies["knowledge_graph"] = "healthy"
            await self._check_mission_engine()
            dependencies["mission_engine"] = "healthy"
            self._check_workflow_engine()
            dependencies["workflow_engine"] = "healthy"
        except StoreUnavailable as exc:
            return HealthStatus(
                status="unavailable",
                ready=False,
                detail=exc.message,
                dependencies=dependencies,
            )
        except Exception as exc:
            return HealthStatus(
                status="unavailable",
                ready=False,
                detail=str(exc),
                dependencies=dependencies,
            )

        if not self._started:
            return HealthStatus(
                status="degraded",
                ready=False,
                detail="service not started",
                dependencies=dependencies,
            )
        return HealthStatus(status="healthy", ready=True, dependencies=dependencies)

    async def _check_available(self) -> None:
        self._check_config()
        await self._check_store()
        await self._check_evidence_store()
        await self._check_object_store()
        await self._check_knowledge_graph()
        await self._check_mission_engine()
        self._check_workflow_engine()

    def _check_config(self) -> None:
        SOCConfig.model_validate(self.engine.config.model_dump(mode="json"))

    async def _check_store(self) -> None:
        try:
            await self._store.get_incident(new_id("inc"))
        except Exception as exc:
            raise StoreUnavailable(f"soc store unavailable: {exc}") from exc

    async def _check_evidence_store(self) -> None:
        try:
            await self.engine.evidence_store.verify(new_id("evd"))
        except EvidenceNotFound:
            return
        except Exception as exc:
            raise StoreUnavailable(f"soc evidence store unavailable: {exc}") from exc

    async def _check_object_store(self) -> None:
        if self.engine.object_store is None:
            raise StoreUnavailable("soc object store unavailable")
        try:
            await self.engine.object_store.get(new_id("obj"), resolve_merged=False)
        except Exception as exc:
            raise StoreUnavailable(f"soc object store unavailable: {exc}") from exc

    async def _check_knowledge_graph(self) -> None:
        if self.engine.graph is None:
            raise StoreUnavailable("soc knowledge graph unavailable")
        try:
            await self.engine.graph.correlate([new_id("obj")], within_hops=1, max_nodes=1)
        except ObjectNotFound:
            return
        except StoreUnavailable:
            raise
        except Exception as exc:
            raise StoreUnavailable(f"soc knowledge graph unavailable: {exc}") from exc

    async def _check_mission_engine(self) -> None:
        if self.engine.mission_engine is None:
            raise StoreUnavailable("soc mission engine unavailable")
        try:
            await self.engine.mission_engine.mission_impact(new_id("obj"))
        except ObjectNotFound:
            return
        except StoreUnavailable:
            raise
        except Exception as exc:
            raise StoreUnavailable(f"soc mission engine unavailable: {exc}") from exc

    def _check_workflow_engine(self) -> None:
        if self.engine.workflow_engine is None:
            raise StoreUnavailable("soc workflow engine unavailable")
