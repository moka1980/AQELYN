"""Identity Threat AQService wrapper and owned events (EA-0027 I5)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol, cast

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import (
    EvidenceNotFound,
    IdThreatConfigInvalid,
    StoreUnavailable,
)
from aqelyn.events.registry import EventTypeRegistry
from aqelyn.findings import Finding
from aqelyn.idthreat.engine import IdentityThreatEngine
from aqelyn.idthreat.models import (
    IdentityDetection,
    IdentityObservation,
    IdThreatConfig,
    assert_dignity_floors,
)
from aqelyn.idthreat.store import IdentityDetectionStore
from aqelyn.kernel.service import HealthStatus
from aqelyn.objects import ObjectQuery
from aqelyn.trust import SourceReliabilityRegistry, TrustConfig

IDTHREAT_EVENTS: dict[str, int] = {
    "aqelyn.idthreat.detected": 1,
    "aqelyn.idthreat.reviewed": 1,
    "aqelyn.idthreat.credential_anomaly": 1,
    "aqelyn.idthreat.privilege_use": 1,
}


class _TrustHealthSource(Protocol):
    config: TrustConfig
    registry: SourceReliabilityRegistry


def register_idthreat_events(registry: EventTypeRegistry) -> None:
    for event_type, schema_version in IDTHREAT_EVENTS.items():
        registry.register(event_type, schema_version, None)


class IdentityThreatService:
    def __init__(
        self,
        engine: IdentityThreatEngine,
        *,
        store: IdentityDetectionStore,
        close_store: Callable[[], Awaitable[None]] | None = None,
        dependencies: Sequence[str] = (
            "detection_engine",
            "iag_engine",
            "trust_engine",
        ),
        critical: bool = True,
    ) -> None:
        self.engine = engine
        self.store = store
        self._close_store = close_store
        self._dependencies = tuple(dependencies)
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return "idthreat_engine"

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
            dependencies["dignity_gate"] = "healthy"
            await self._check_store()
            dependencies["identity_detection_store"] = "healthy"
            await self._check_profile_store()
            dependencies["detection_engine"] = "healthy"
            await self._check_entitlement_analyzer()
            dependencies["iag_engine"] = "healthy"
            await self._check_trust_engine()
            dependencies["trust_engine"] = "healthy"
            await self._check_evidence_store()
            dependencies["evidence_store"] = "healthy"
            await self._check_finding_store()
            dependencies["finding_store"] = "healthy"
        except (IdThreatConfigInvalid, StoreUnavailable) as exc:
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

    async def detect(
        self,
        *,
        observation: IdentityObservation,
        tenant_id: str | None,
    ) -> IdentityDetection | None:
        return await self.engine.detect(observation=observation, tenant_id=tenant_id)

    async def raise_detection(
        self,
        detection: IdentityDetection,
        *,
        by: ActorRef,
    ) -> Finding:
        return await self.engine.raise_detection(detection, by=by)

    async def review(
        self,
        detection_id: str,
        *,
        by: ActorRef,
        outcome: str,
        tenant_id: str | None,
    ) -> IdentityDetection:
        return await self.engine.review(
            detection_id,
            by=by,
            outcome=outcome,
            tenant_id=tenant_id,
        )

    async def _check_available(self) -> None:
        self._check_config()
        await self._check_store()
        await self._check_profile_store()
        await self._check_entitlement_analyzer()
        await self._check_trust_engine()
        await self._check_evidence_store()
        await self._check_finding_store()

    def _check_config(self) -> None:
        try:
            selected = IdThreatConfig.model_validate(self.engine.config.model_dump(mode="json"))
            assert_dignity_floors(selected)
        except IdThreatConfigInvalid:
            raise
        except Exception as exc:
            raise IdThreatConfigInvalid(f"identity threat config invalid: {exc}") from exc

    async def _check_store(self) -> None:
        try:
            await self.store.get(new_id("idt"), tenant_id=None)
        except Exception as exc:
            raise StoreUnavailable(f"identity detection store unavailable: {exc}") from exc

    async def _check_profile_store(self) -> None:
        try:
            await self.engine.profile_store.get(new_id("prf"), version=1)
        except Exception as exc:
            raise StoreUnavailable(f"identity profile source unavailable: {exc}") from exc

    async def _check_entitlement_analyzer(self) -> None:
        try:
            await self.engine.entitlement_analyzer.access_paths(
                new_id("obj"),
                tenant_id=None,
            )
            await self.engine.entitlement_analyzer.analyze_risk(
                tenant_id=None,
                scope=ObjectQuery(limit=1),
            )
        except Exception as exc:
            raise StoreUnavailable(f"identity entitlement source unavailable: {exc}") from exc

    async def _check_trust_engine(self) -> None:
        try:
            trust_engine = cast(_TrustHealthSource, self.engine.trust_engine)
            TrustConfig.model_validate(trust_engine.config.model_dump(mode="json"))
            await trust_engine.registry.get()
        except Exception as exc:
            raise StoreUnavailable(f"identity trust engine unavailable: {exc}") from exc

    async def _check_evidence_store(self) -> None:
        try:
            await self.engine.evidence_store.get(
                new_id("evd"),
                actor=ActorRef(actor_type="system", actor_id="idthreat-health"),
            )
        except EvidenceNotFound:
            return
        except Exception as exc:
            raise StoreUnavailable(f"identity evidence store unavailable: {exc}") from exc

    async def _check_finding_store(self) -> None:
        if self.engine.finding_store is None:
            raise StoreUnavailable("identity finding store unavailable")
        try:
            await self.engine.finding_store.get(new_id("fnd"))
        except Exception as exc:
            raise StoreUnavailable(f"identity finding store unavailable: {exc}") from exc
