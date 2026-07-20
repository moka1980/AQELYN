"""Threat Exposure AQService wrapper and events (EA-0023 E5)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import (
    EvidenceNotFound,
    ExposureConfigInvalid,
    ObjectNotFound,
    StoreUnavailable,
)
from aqelyn.events.registry import EventTypeRegistry
from aqelyn.exposure.engine import KnownDataExposureEngine
from aqelyn.exposure.models import (
    AssetRef,
    ExposureConfig,
    ExposureImpactContext,
    ExposureRecord,
)
from aqelyn.exposure.store import ExposureStore
from aqelyn.kernel.service import HealthStatus
from aqelyn.trust.models import TrustConfig

EXPOSURE_EVENTS: dict[str, int] = {
    "aqelyn.exposure.asset_discovered": 1,
    "aqelyn.exposure.detected": 1,
    "aqelyn.exposure.attack_surface_updated": 1,
    "aqelyn.exposure.score_updated": 1,
    "aqelyn.exposure.closed": 1,
}


def register_exposure_events(registry: EventTypeRegistry) -> None:
    for event_type, schema_version in EXPOSURE_EVENTS.items():
        registry.register(event_type, schema_version, None)


class ExposureManagementService:
    def __init__(
        self,
        engine: KnownDataExposureEngine,
        *,
        store: ExposureStore,
        risk_engine: object | None = None,
        close_store: Callable[[], Awaitable[None]] | None = None,
        close_source_store: Callable[[], Awaitable[None]] | None = None,
        dependencies: Sequence[str] = (
            "inventory_engine",
            "acg_engine",
            "knowledge_graph",
            "iag_engine",
            "mission_engine",
            "trust_engine",
            "risk_engine",
            "forecast_engine",
        ),
        critical: bool = True,
    ) -> None:
        self.engine = engine
        self.store = store
        self.risk_engine = risk_engine
        self._close_store = close_store
        self._close_source_store = close_source_store
        self._dependencies = tuple(dependencies)
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return "exposure_engine"

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
            try:
                if self._close_source_store is not None:
                    await self._close_source_store()
            finally:
                self._started = False

    async def health(self) -> HealthStatus:
        dependencies: dict[str, str] = {}
        try:
            self._check_config()
            await self._check_store()
            dependencies["exposure_store"] = "healthy"
            await self._check_known_surface_source()
            dependencies["known_surface_source"] = "healthy"
            await self._check_graph()
            dependencies["knowledge_graph"] = "healthy"
            await self._check_identity_provider()
            dependencies["iag_engine"] = "healthy"
            await self._check_trend_provider()
            dependencies["forecast_engine"] = "healthy"
            await self._check_evidence_lookup()
            dependencies["evidence_store"] = "healthy"
            await self._check_trust_provider()
            dependencies["trust_engine"] = "healthy"
            await self._check_mission_provider()
            dependencies["mission_engine"] = "healthy"
            await self._check_finding_store()
            dependencies["finding_store"] = "healthy"
            self._check_risk_engine()
            dependencies["risk_engine"] = "healthy"
        except ExposureConfigInvalid as exc:
            return HealthStatus(
                status="unavailable",
                ready=False,
                detail=exc.message,
                dependencies=dependencies,
            )
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

    async def derive_surface(self, *, tenant_id: str | None) -> object:
        return await self.engine.derive_surface(tenant_id=tenant_id)

    async def analyze_exposure(
        self, *, asset_ref: AssetRef, tenant_id: str | None
    ) -> ExposureRecord:
        return await self.engine.analyze_exposure(asset_ref=asset_ref, tenant_id=tenant_id)

    async def score_exposure(
        self,
        exposure: ExposureRecord,
        *,
        impact_context: ExposureImpactContext | None = None,
    ) -> ExposureRecord:
        return await self.engine.score_exposure(exposure, impact_context=impact_context)

    async def raise_exposure_finding(self, exposure: ExposureRecord) -> object:
        return await self.engine.raise_exposure_finding(exposure)

    async def _check_available(self) -> None:
        self._check_config()
        await self._check_store()
        await self._check_known_surface_source()
        await self._check_graph()
        await self._check_identity_provider()
        await self._check_trend_provider()
        await self._check_evidence_lookup()
        await self._check_trust_provider()
        await self._check_mission_provider()
        await self._check_finding_store()
        self._check_risk_engine()

    def _check_config(self) -> None:
        ExposureConfig.model_validate(self.engine.config.model_dump(mode="json"))

    async def _check_store(self) -> None:
        try:
            await self.store.get(new_id("exp"), tenant_id=self._health_tenant())
        except Exception as exc:
            raise StoreUnavailable(f"exposure store unavailable: {exc}") from exc

    async def _check_known_surface_source(self) -> None:
        try:
            await self.engine.source.list_known_surface(tenant_id=self._health_tenant())
        except Exception as exc:
            raise StoreUnavailable(f"exposure source unavailable: {exc}") from exc

    async def _check_graph(self) -> None:
        if self.engine.graph is None:
            raise StoreUnavailable("exposure knowledge graph unavailable")
        try:
            await self.engine.graph.paths(
                new_id("obj"),
                new_id("obj"),
                direction="out",
                max_paths=1,
                max_work=1,
            )
        except ObjectNotFound:
            return
        except StoreUnavailable:
            raise
        except Exception as exc:
            raise StoreUnavailable(f"exposure knowledge graph unavailable: {exc}") from exc

    async def _check_identity_provider(self) -> None:
        if self.engine.identity_provider is None:
            raise StoreUnavailable("exposure identity provider unavailable")
        try:
            await self.engine.identity_provider.analyze_risk(
                tenant_id=self._health_tenant(), scope=None
            )
        except StoreUnavailable:
            raise
        except Exception as exc:
            raise StoreUnavailable(f"exposure identity provider unavailable: {exc}") from exc

    async def _check_trend_provider(self) -> None:
        if self.engine.trend_provider is None:
            raise StoreUnavailable("exposure forecast provider unavailable")
        if not hasattr(self.engine.trend_provider, "analyze_trend"):
            raise StoreUnavailable("exposure forecast provider unavailable")

    async def _check_evidence_lookup(self) -> None:
        if self.engine.evidence_lookup is None:
            raise StoreUnavailable("exposure evidence lookup unavailable")
        actor = ActorRef(actor_type="system", actor_id="exposure_engine")
        try:
            await self.engine.evidence_lookup.get(new_id("evd"), actor=actor)
        except EvidenceNotFound:
            return
        except KeyError:
            return
        except Exception as exc:
            raise StoreUnavailable(f"exposure evidence lookup unavailable: {exc}") from exc

    async def _check_trust_provider(self) -> None:
        if self.engine.trust_provider is None:
            raise StoreUnavailable("exposure trust provider unavailable")
        config = getattr(self.engine.trust_provider, "config", None)
        registry = getattr(self.engine.trust_provider, "registry", None)
        try:
            if config is not None:
                TrustConfig.model_validate(config.model_dump(mode="json"))
            if registry is not None:
                await registry.get()
        except Exception as exc:
            raise StoreUnavailable(f"exposure trust provider unavailable: {exc}") from exc

    async def _check_mission_provider(self) -> None:
        if self.engine.mission_provider is None:
            raise StoreUnavailable("exposure mission provider unavailable")
        try:
            await self.engine.mission_provider.mission_impact(new_id("obj"))
        except ObjectNotFound:
            return
        except StoreUnavailable:
            raise
        except Exception as exc:
            raise StoreUnavailable(f"exposure mission provider unavailable: {exc}") from exc

    async def _check_finding_store(self) -> None:
        if self.engine.finding_store is None:
            raise StoreUnavailable("exposure finding store unavailable")
        try:
            await self.engine.finding_store.get(new_id("fnd"))
        except Exception as exc:
            raise StoreUnavailable(f"exposure finding store unavailable: {exc}") from exc

    def _check_risk_engine(self) -> None:
        if self.risk_engine is None:
            raise StoreUnavailable("exposure risk engine unavailable")

    def _health_tenant(self) -> str | None:
        if getattr(self.store, "mode", "local") == "enterprise":
            return "018f0000-0000-7000-8000-000000230500"
        return None
