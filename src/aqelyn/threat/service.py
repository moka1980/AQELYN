"""Threat Intelligence Fusion AQService wrapper and events (EA-0014 T5)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import EvidenceNotFound, ObjectNotFound, StoreUnavailable
from aqelyn.events.registry import EventTypeRegistry
from aqelyn.kernel.service import HealthStatus
from aqelyn.threat.engine import ThreatFusionEngine
from aqelyn.threat.models import FusionConfig
from aqelyn.threat.registry import ThreatSourceRegistry
from aqelyn.trust.engine import TrustEngine
from aqelyn.trust.models import TrustConfig

THREAT_EVENTS: dict[str, int] = {
    "aqelyn.threat.indicator_ingested": 1,
    "aqelyn.threat.match_detected": 1,
    "aqelyn.threat.updated": 1,
}


def register_threat_events(registry: EventTypeRegistry) -> None:
    for event_type, schema_version in THREAT_EVENTS.items():
        registry.register(event_type, schema_version, None)


class ThreatFusionService:
    def __init__(
        self,
        engine: ThreatFusionEngine,
        *,
        source_registry: ThreatSourceRegistry,
        trust_engine: TrustEngine | None = None,
        close_source_registry: Callable[[], Awaitable[None]] | None = None,
        dependencies: Sequence[str] = (
            "object_store",
            "knowledge_graph",
            "trust_engine",
            "mission_engine",
            "workflow_engine",
        ),
        critical: bool = True,
    ) -> None:
        self.engine = engine
        self._source_registry = source_registry
        self._trust_engine = trust_engine
        self._close_source_registry = close_source_registry
        self._dependencies = tuple(dependencies)
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return "threat_fusion_engine"

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
            if self._close_source_registry is not None:
                await self._close_source_registry()
        finally:
            self._started = False

    async def health(self) -> HealthStatus:
        dependencies: dict[str, str] = {}
        try:
            self._check_config()
            await self._check_object_store()
            dependencies["object_store"] = "healthy"
            await self._check_knowledge_graph()
            dependencies["knowledge_graph"] = "healthy"
            await self._check_source_registry()
            dependencies["source_registry"] = "healthy"
            await self._check_trust_engine()
            dependencies["trust_engine"] = "healthy"
            await self._check_evidence_store()
            dependencies["evidence_store"] = "healthy"
            await self._check_finding_store()
            dependencies["finding_store"] = "healthy"
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
            return HealthStatus(status="unavailable", ready=False, detail=str(exc))

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
        await self._check_object_store()
        await self._check_knowledge_graph()
        await self._check_source_registry()
        await self._check_trust_engine()
        await self._check_evidence_store()
        await self._check_finding_store()
        await self._check_mission_engine()
        self._check_workflow_engine()

    def _check_config(self) -> None:
        FusionConfig.model_validate(self.engine.config.model_dump(mode="json"))

    async def _check_object_store(self) -> None:
        try:
            await self.engine.object_store.get(new_id("obj"), resolve_merged=False)
        except Exception as exc:
            raise StoreUnavailable(f"threat object store unavailable: {exc}") from exc

    async def _check_knowledge_graph(self) -> None:
        try:
            await self.engine.graph.correlate([new_id("obj")], within_hops=1, max_nodes=1)
        except ObjectNotFound:
            return
        except StoreUnavailable:
            raise
        except Exception as exc:
            raise StoreUnavailable(f"threat knowledge graph unavailable: {exc}") from exc

    async def _check_source_registry(self) -> None:
        try:
            await self._source_registry.get(new_id("src"))
        except Exception as exc:
            raise StoreUnavailable(f"threat source registry unavailable: {exc}") from exc

    async def _check_trust_engine(self) -> None:
        if self._trust_engine is None:
            raise StoreUnavailable("threat trust engine unavailable")
        try:
            TrustConfig.model_validate(self._trust_engine.config.model_dump(mode="json"))
            await self._trust_engine.registry.get()
        except Exception as exc:
            raise StoreUnavailable(f"threat trust engine unavailable: {exc}") from exc

    async def _check_evidence_store(self) -> None:
        if self.engine.evidence_store is None:
            raise StoreUnavailable("threat evidence store unavailable")
        try:
            await self.engine.evidence_store.verify(new_id("evd"))
        except EvidenceNotFound:
            return
        except Exception as exc:
            raise StoreUnavailable(f"threat evidence store unavailable: {exc}") from exc

    async def _check_finding_store(self) -> None:
        if self.engine.finding_store is None:
            raise StoreUnavailable("threat finding store unavailable")
        try:
            await self.engine.finding_store.get(new_id("fnd"))
        except Exception as exc:
            raise StoreUnavailable(f"threat finding store unavailable: {exc}") from exc

    async def _check_mission_engine(self) -> None:
        if self.engine.mission_engine is None:
            raise StoreUnavailable("threat mission engine unavailable")
        try:
            await self.engine.mission_engine.mission_impact(new_id("obj"))
        except ObjectNotFound:
            return
        except StoreUnavailable:
            raise
        except Exception as exc:
            raise StoreUnavailable(f"threat mission engine unavailable: {exc}") from exc

    def _check_workflow_engine(self) -> None:
        if self.engine.workflow_engine is None:
            raise StoreUnavailable("threat workflow engine unavailable")
