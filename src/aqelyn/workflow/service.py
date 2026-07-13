"""Workflow Engine AQService wrapper (EA-0008 W5)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import EvidenceNotFound, StoreUnavailable
from aqelyn.evidence import EvidenceStore
from aqelyn.kernel.service import HealthStatus
from aqelyn.workflow.engine import WorkflowEngine
from aqelyn.workflow.registry import InMemoryActionRegistry
from aqelyn.workflow.store import RunStore


class WorkflowEngineService:
    def __init__(
        self,
        engine: WorkflowEngine,
        *,
        run_store: RunStore,
        registry: InMemoryActionRegistry,
        evidence_store: EvidenceStore,
        close_run_store: Callable[[], Awaitable[None]] | None = None,
        dependencies: Sequence[str] = ("event_bus",),
        critical: bool = True,
    ) -> None:
        self.engine = engine
        self._run_store = run_store
        self._registry = registry
        self._evidence_store = evidence_store
        self._close_run_store = close_run_store
        self._dependencies = tuple(dependencies)
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return "workflow_engine"

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
            if self._close_run_store is not None:
                await self._close_run_store()
        finally:
            self._started = False

    async def health(self) -> HealthStatus:
        dependencies: dict[str, str] = {}
        try:
            self._check_registry()
            dependencies["registry"] = "healthy"
            await self._check_run_store()
            dependencies["run_store"] = "healthy"
            await self._check_evidence_store()
            dependencies["evidence_store"] = "healthy"
        except StoreUnavailable as exc:
            return HealthStatus(
                status="unavailable",
                ready=False,
                detail=exc.message,
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
        self._check_registry()
        await self._check_run_store()
        await self._check_evidence_store()

    def _check_registry(self) -> None:
        try:
            self._registry.list()
        except Exception as exc:
            raise StoreUnavailable(f"workflow registry unavailable: {exc}") from exc

    async def _check_run_store(self) -> None:
        try:
            await self._run_store.get(new_id("run"))
        except Exception as exc:
            raise StoreUnavailable(f"workflow run store unavailable: {exc}") from exc

    async def _check_evidence_store(self) -> None:
        try:
            await self._evidence_store.verify(new_id("evd"))
        except EvidenceNotFound:
            return
        except Exception as exc:
            raise StoreUnavailable(f"workflow evidence store unavailable: {exc}") from exc
