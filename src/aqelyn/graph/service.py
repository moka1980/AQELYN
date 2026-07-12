"""Knowledge Graph AQService wrapper (EA-0005 G5)."""

from __future__ import annotations

from collections.abc import Sequence

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import StoreUnavailable
from aqelyn.graph.graph import KnowledgeGraph
from aqelyn.kernel.service import HealthStatus
from aqelyn.objects.store import ObjectStore


class KnowledgeGraphService:
    def __init__(
        self,
        graph: KnowledgeGraph,
        object_store: ObjectStore,
        *,
        critical: bool = True,
    ) -> None:
        self.graph = graph
        self._object_store = object_store
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return "knowledge_graph"

    @property
    def dependencies(self) -> Sequence[str]:
        return ("object_store",)

    @property
    def critical(self) -> bool:
        return self._critical

    async def start(self) -> None:
        await self._check_object_store()
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def health(self) -> HealthStatus:
        try:
            await self._check_object_store()
        except StoreUnavailable as exc:
            return HealthStatus(
                status="unavailable",
                ready=False,
                detail=exc.message,
                dependencies={"object_store": "unavailable"},
            )
        if not self._started:
            return HealthStatus(
                status="degraded",
                ready=False,
                detail="service not started",
                dependencies={"object_store": "healthy"},
            )
        return HealthStatus(
            status="healthy",
            ready=True,
            dependencies={"object_store": "healthy"},
        )

    async def _check_object_store(self) -> None:
        try:
            await self._object_store.get(new_id("obj"), resolve_merged=False)
        except Exception as exc:
            raise StoreUnavailable(str(exc)) from exc
