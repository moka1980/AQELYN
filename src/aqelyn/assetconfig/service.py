"""Asset & Configuration Governance AQService wrapper and events (EA-0012 A5)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from aqelyn.assetconfig.drift import AssetConfigAnalyzer
from aqelyn.assetconfig.models import ACGConfig
from aqelyn.assetconfig.store import BaselineStore, DriftSnapshotStore
from aqelyn.conventions import new_id
from aqelyn.conventions.errors import BaselineConfigInvalid, EvidenceNotFound, StoreUnavailable
from aqelyn.events.registry import EventTypeRegistry
from aqelyn.kernel.service import HealthStatus

ACG_EVENTS: dict[str, int] = {
    "aqelyn.config.drift_detected": 1,
    "aqelyn.config.assessment_completed": 1,
}


def register_acg_events(registry: EventTypeRegistry) -> None:
    for event_type, schema_version in ACG_EVENTS.items():
        registry.register(event_type, schema_version, None)


class AssetConfigGovernanceService:
    def __init__(
        self,
        engine: AssetConfigAnalyzer,
        *,
        baseline_store: BaselineStore,
        snapshot_store: DriftSnapshotStore,
        close_baseline_store: Callable[[], Awaitable[None]] | None = None,
        close_snapshot_store: Callable[[], Awaitable[None]] | None = None,
        dependencies: Sequence[str] = (
            "object_store",
            "mission_engine",
            "workflow_engine",
        ),
        critical: bool = True,
    ) -> None:
        self.engine = engine
        self._baseline_store = baseline_store
        self._snapshot_store = snapshot_store
        self._close_baseline_store = close_baseline_store
        self._close_snapshot_store = close_snapshot_store
        self._dependencies = tuple(dependencies)
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return "acg_engine"

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
            if self._close_snapshot_store is not None:
                await self._close_snapshot_store()
            if self._close_baseline_store is not None:
                await self._close_baseline_store()
        finally:
            self._started = False

    async def health(self) -> HealthStatus:
        dependencies: dict[str, str] = {}
        try:
            self._check_config()
            await self._check_object_store()
            dependencies["object_store"] = "healthy"
            await self._check_baseline_store()
            dependencies["baseline_store"] = "healthy"
            await self._check_snapshot_store()
            dependencies["snapshot_store"] = "healthy"
            await self._check_evidence_store()
            dependencies["evidence_store"] = "healthy"
            await self._check_finding_store()
            dependencies["finding_store"] = "healthy"
            self._check_mission_engine()
            dependencies["mission_engine"] = "healthy"
            self._check_workflow_engine()
            dependencies["workflow_engine"] = "healthy"
        except BaselineConfigInvalid as exc:
            return HealthStatus(status="unavailable", ready=False, detail=exc.message)
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
        self._check_config()
        await self._check_object_store()
        await self._check_baseline_store()
        await self._check_snapshot_store()
        await self._check_evidence_store()
        await self._check_finding_store()
        self._check_mission_engine()
        self._check_workflow_engine()

    def _check_config(self) -> None:
        ACGConfig.model_validate(self.engine.config.model_dump(mode="json"))

    async def _check_object_store(self) -> None:
        try:
            await self.engine.object_store.get(new_id("obj"), resolve_merged=False)
        except Exception as exc:
            raise StoreUnavailable(f"acg object store unavailable: {exc}") from exc

    async def _check_baseline_store(self) -> None:
        try:
            await self._baseline_store.get("healthcheck-baseline")
        except Exception as exc:
            raise StoreUnavailable(f"acg baseline store unavailable: {exc}") from exc

    async def _check_snapshot_store(self) -> None:
        try:
            await self._snapshot_store.get("healthcheck-snapshot")
        except Exception as exc:
            raise StoreUnavailable(f"acg snapshot store unavailable: {exc}") from exc

    async def _check_evidence_store(self) -> None:
        if self.engine.evidence_store is None:
            raise StoreUnavailable("acg evidence store unavailable")
        try:
            await self.engine.evidence_store.verify(new_id("evd"))
        except EvidenceNotFound:
            return
        except Exception as exc:
            raise StoreUnavailable(f"acg evidence store unavailable: {exc}") from exc

    async def _check_finding_store(self) -> None:
        if self.engine.finding_store is None:
            raise StoreUnavailable("acg finding store unavailable")
        try:
            await self.engine.finding_store.get(new_id("fnd"))
        except Exception as exc:
            raise StoreUnavailable(f"acg finding store unavailable: {exc}") from exc

    def _check_mission_engine(self) -> None:
        if self.engine.mission_engine is None:
            raise StoreUnavailable("acg mission engine unavailable")

    def _check_workflow_engine(self) -> None:
        if self.engine.workflow_engine is None:
            raise StoreUnavailable("acg workflow engine unavailable")
