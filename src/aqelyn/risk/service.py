"""Risk Intelligence AQService wrapper and events (EA-0013 R5)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import (
    EvidenceNotFound,
    ObjectNotFound,
    RiskConfigInvalid,
    StoreUnavailable,
)
from aqelyn.events.registry import EventTypeRegistry
from aqelyn.kernel.service import HealthStatus
from aqelyn.risk.engine import RiskIntelligenceEngine
from aqelyn.risk.models import RiskConfig
from aqelyn.risk.store import RiskSnapshotStore, RiskStore

RISK_EVENTS: dict[str, int] = {
    "aqelyn.risk.identified": 1,
    "aqelyn.risk.score_changed": 1,
    "aqelyn.risk.treated": 1,
}


def register_risk_events(registry: EventTypeRegistry) -> None:
    for event_type, schema_version in RISK_EVENTS.items():
        registry.register(event_type, schema_version, None)


class RiskIntelligenceService:
    def __init__(
        self,
        engine: RiskIntelligenceEngine,
        *,
        risk_store: RiskStore,
        snapshot_store: RiskSnapshotStore,
        close_risk_store: Callable[[], Awaitable[None]] | None = None,
        close_snapshot_store: Callable[[], Awaitable[None]] | None = None,
        dependencies: Sequence[str] = (
            "mission_engine",
            "workflow_engine",
            "compliance_engine",
            "iag_engine",
            "acg_engine",
        ),
        critical: bool = True,
    ) -> None:
        self.engine = engine
        self._risk_store = risk_store
        self._snapshot_store = snapshot_store
        self._close_risk_store = close_risk_store
        self._close_snapshot_store = close_snapshot_store
        self._dependencies = tuple(dependencies)
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return "risk_engine"

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
            if self._close_risk_store is not None:
                await self._close_risk_store()
        finally:
            self._started = False

    async def health(self) -> HealthStatus:
        dependencies: dict[str, str] = {}
        try:
            self._check_config()
            await self._check_risk_store()
            dependencies["risk_store"] = "healthy"
            await self._check_snapshot_store()
            dependencies["snapshot_store"] = "healthy"
            await self._check_evidence_store()
            dependencies["evidence_store"] = "healthy"
            await self._check_finding_store()
            dependencies["finding_store"] = "healthy"
            await self._check_mission_engine()
            dependencies["mission_engine"] = "healthy"
            self._check_workflow_engine()
            dependencies["workflow_engine"] = "healthy"
        except RiskConfigInvalid as exc:
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
        await self._check_risk_store()
        await self._check_snapshot_store()
        await self._check_evidence_store()
        await self._check_finding_store()
        await self._check_mission_engine()
        self._check_workflow_engine()

    def _check_config(self) -> None:
        RiskConfig.model_validate(self.engine.config.model_dump(mode="json"))

    async def _check_risk_store(self) -> None:
        try:
            await self._risk_store.get("healthcheck-risk")
        except Exception as exc:
            raise StoreUnavailable(f"risk store unavailable: {exc}") from exc

    async def _check_snapshot_store(self) -> None:
        try:
            await self._snapshot_store.get("healthcheck-risk-snapshot")
        except Exception as exc:
            raise StoreUnavailable(f"risk snapshot store unavailable: {exc}") from exc

    async def _check_evidence_store(self) -> None:
        if self.engine.evidence_store is None:
            raise StoreUnavailable("risk evidence store unavailable")
        try:
            await self.engine.evidence_store.verify(new_id("evd"))
        except EvidenceNotFound:
            return
        except Exception as exc:
            raise StoreUnavailable(f"risk evidence store unavailable: {exc}") from exc

    async def _check_finding_store(self) -> None:
        try:
            await self.engine.finding_store.get(new_id("fnd"))
        except Exception as exc:
            raise StoreUnavailable(f"risk finding store unavailable: {exc}") from exc

    async def _check_mission_engine(self) -> None:
        if self.engine.mission_engine is None:
            raise StoreUnavailable("risk mission engine unavailable")
        try:
            await self.engine.mission_engine.mission_impact(new_id("obj"))
        except ObjectNotFound:
            return
        except StoreUnavailable:
            raise
        except Exception as exc:
            raise StoreUnavailable(f"risk mission engine unavailable: {exc}") from exc

    def _check_workflow_engine(self) -> None:
        if self.engine.workflow_engine is None:
            raise StoreUnavailable("risk workflow engine unavailable")
