"""Mission Engine AQService wrapper (EA-0007 M4)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, cast

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import MissionConfigInvalid, ObjectNotFound, StoreUnavailable
from aqelyn.kernel.service import HealthStatus
from aqelyn.mission.engine import MissionEngine
from aqelyn.mission.models import MISSION_OBJECT_TYPE, MissionConfig
from aqelyn.objects.registry import ObjectTypeRegistry


class _ObjectStoreRegistry(Protocol):
    registry: ObjectTypeRegistry


class MissionEngineService:
    def __init__(self, engine: MissionEngine, *, critical: bool = True) -> None:
        self.engine = engine
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return "mission_engine"

    @property
    def dependencies(self) -> Sequence[str]:
        return ("object_store", "knowledge_graph")

    @property
    def critical(self) -> bool:
        return self._critical

    async def start(self) -> None:
        await self._check_available()
        self._register_mission_type()
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def health(self) -> HealthStatus:
        try:
            self._check_config()
        except MissionConfigInvalid as exc:
            return HealthStatus(status="unavailable", ready=False, detail=exc.message)

        dependencies: dict[str, str] = {}
        try:
            await self._check_object_store()
            dependencies["object_store"] = "healthy"
        except StoreUnavailable as exc:
            return HealthStatus(
                status="unavailable",
                ready=False,
                detail=exc.message,
                dependencies={"object_store": "unavailable", "knowledge_graph": "unknown"},
            )

        try:
            await self._check_knowledge_graph()
            dependencies["knowledge_graph"] = "healthy"
        except StoreUnavailable as exc:
            return HealthStatus(
                status="unavailable",
                ready=False,
                detail=exc.message,
                dependencies={"object_store": "healthy", "knowledge_graph": "unavailable"},
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
        await self._check_object_store()
        await self._check_knowledge_graph()

    def _check_config(self) -> None:
        MissionConfig.model_validate(self.engine.config.model_dump())

    async def _check_object_store(self) -> None:
        try:
            await self.engine.object_store.get(new_id("obj"), resolve_merged=False)
        except Exception as exc:
            raise StoreUnavailable(f"object store unavailable: {exc}") from exc

    async def _check_knowledge_graph(self) -> None:
        if self.engine.knowledge_graph is None:
            raise StoreUnavailable("knowledge graph unavailable")
        try:
            await self.engine.knowledge_graph.impact(new_id("obj"), max_depth=1, max_nodes=1)
        except ObjectNotFound:
            return
        except StoreUnavailable:
            raise
        except Exception as exc:
            raise StoreUnavailable(f"knowledge graph unavailable: {exc}") from exc

    def _register_mission_type(self) -> None:
        registry = cast(_ObjectStoreRegistry, self.engine.object_store).registry
        registry.register(MISSION_OBJECT_TYPE, 1, None)
