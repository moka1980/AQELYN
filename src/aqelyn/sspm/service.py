"""SSPM AQService wrapper and normalization-owned events (EA-0029 Z4)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Protocol

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import (
    EvidenceNotFound,
    ObjectNotFound,
    SaaSConfigInvalid,
    StoreUnavailable,
)
from aqelyn.events.registry import EventTypeRegistry
from aqelyn.kernel.service import HealthStatus
from aqelyn.sspm.engine import SaaSPostureEngine
from aqelyn.sspm.models import (
    BlastRadius,
    IntegrationDescriptor,
    NormalizedSaaSObject,
    SaaSAppDescriptor,
    SaaSConfig,
    SaaSIntegration,
    SaaSRoutingResult,
)
from aqelyn.sspm.store import SaaSNormalizationStore
from aqelyn.workflow import Run

SAAS_EVENTS: dict[str, int] = {
    "aqelyn.saas.app_normalized": 1,
    "aqelyn.saas.integration_detected": 1,
    "aqelyn.saas.app_unclassified": 1,
}

_ROUTE_OWNERS = frozenset(("inventory", "assetconfig", "compliance", "iag"))


def register_saas_events(registry: EventTypeRegistry) -> None:
    for event_type, schema_version in SAAS_EVENTS.items():
        registry.register(event_type, schema_version, None)


class _HealthSource(Protocol):
    async def health(self) -> HealthStatus: ...


class SaaSPostureService:
    def __init__(
        self,
        engine: SaaSPostureEngine,
        *,
        store: SaaSNormalizationStore,
        owner_services: Mapping[str, _HealthSource],
        close_store: Callable[[], Awaitable[None]] | None = None,
        dependencies: Sequence[str] = (
            "object_store",
            "knowledge_graph",
            "inventory_engine",
            "acg_engine",
            "compliance_engine",
            "iag_engine",
            "exposure_engine",
            "risk_engine",
            "trust_engine",
            "workflow_engine",
        ),
        critical: bool = True,
    ) -> None:
        self.engine = engine
        self.store = store
        self.owner_services = dict(owner_services)
        self._close_store = close_store
        self._dependencies = tuple(dependencies)
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return "sspm_engine"

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
            dependencies["saas_normalization_store"] = "healthy"
            await self._check_object_store()
            dependencies["object_store"] = "healthy"
            await self._check_evidence_store()
            dependencies["evidence_store"] = "healthy"
            await self._check_trust_registry()
            dependencies["trust_engine"] = "healthy"
            await self._check_graph()
            dependencies["knowledge_graph"] = "healthy"
            for service_name in sorted(self.owner_services):
                await self._check_owner_service(service_name)
                dependencies[service_name] = "healthy"
            self._check_adapters()
        except (SaaSConfigInvalid, StoreUnavailable) as exc:
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

    async def normalize(
        self,
        descriptors: Sequence[SaaSAppDescriptor],
        *,
        tenant_id: str | None,
    ) -> list[NormalizedSaaSObject]:
        return await self.engine.normalize(descriptors, tenant_id=tenant_id)

    async def route(
        self,
        object_ids: Sequence[str],
        *,
        tenant_id: str | None,
    ) -> list[SaaSRoutingResult]:
        return await self.engine.route(object_ids, tenant_id=tenant_id)

    async def map_integration(
        self,
        descriptors: Sequence[IntegrationDescriptor],
        *,
        tenant_id: str | None,
    ) -> list[SaaSIntegration]:
        return await self.engine.map_integration(descriptors, tenant_id=tenant_id)

    async def integration_blast_radius(
        self,
        integration_id: str,
        *,
        tenant_id: str | None,
    ) -> BlastRadius:
        return await self.engine.integration_blast_radius(
            integration_id,
            tenant_id=tenant_id,
        )

    async def apply_saas_baselines(
        self,
        *,
        tenant_id: str | None,
        scope: Mapping[str, object] | None = None,
    ) -> str:
        return await self.engine.apply_saas_baselines(tenant_id=tenant_id, scope=scope)

    async def mark_app_unreported(
        self,
        object_id: str,
        *,
        tenant_id: str | None,
    ) -> str:
        return await self.engine.mark_app_unreported(object_id, tenant_id=tenant_id)

    async def propose_revocation(
        self,
        integration_id: str,
        *,
        tenant_id: str | None,
        by: ActorRef,
        reason: str,
    ) -> Run:
        return await self.engine.propose_revocation(
            integration_id,
            tenant_id=tenant_id,
            by=by,
            reason=reason,
        )

    def explain(self, obj: NormalizedSaaSObject) -> dict[str, object]:
        return self.engine.explain(obj)

    async def _check_available(self) -> None:
        health = await self.health()
        if health.status == "unavailable":
            raise StoreUnavailable(health.detail or "sspm service unavailable")

    def _check_config(self) -> None:
        SaaSConfig.model_validate(self.engine.config.model_dump(mode="json"))
        if set(self.engine.owner_routers) != _ROUTE_OWNERS:
            raise SaaSConfigInvalid("all four SSPM owner routers must be configured")

    async def _check_store(self) -> None:
        tenant_id = self._health_tenant()
        try:
            await self.store.query(tenant_id=tenant_id, limit=1)
            await self.store.query_integrations(tenant_id=tenant_id, limit=1)
        except Exception as exc:
            raise StoreUnavailable(f"SaaS normalization store unavailable: {exc}") from exc

    async def _check_object_store(self) -> None:
        try:
            await self.engine.object_store.get(new_id("obj"), resolve_merged=False)
        except Exception as exc:
            raise StoreUnavailable(f"sspm object store unavailable: {exc}") from exc

    async def _check_evidence_store(self) -> None:
        try:
            await self.engine.evidence_store.verify(new_id("evd"))
        except EvidenceNotFound:
            return
        except Exception as exc:
            raise StoreUnavailable(f"sspm evidence store unavailable: {exc}") from exc

    async def _check_trust_registry(self) -> None:
        try:
            await self.engine.source_registry.get()
        except Exception as exc:
            raise StoreUnavailable(f"sspm trust registry unavailable: {exc}") from exc

    async def _check_graph(self) -> None:
        if self.engine.integration_graph is None:
            raise StoreUnavailable("sspm knowledge graph unavailable")
        try:
            await self.engine.integration_graph.subgraph(new_id("obj"), max_nodes=1)
        except ObjectNotFound:
            return
        except StoreUnavailable:
            raise
        except Exception as exc:
            raise StoreUnavailable(f"sspm knowledge graph unavailable: {exc}") from exc

    async def _check_owner_service(self, service_name: str) -> None:
        service = self.owner_services.get(service_name)
        if service is None:
            raise StoreUnavailable(f"{service_name} unavailable")
        status = await service.health()
        if status.status == "unavailable":
            raise StoreUnavailable(status.detail or f"{service_name} unavailable")

    def _check_adapters(self) -> None:
        if self.engine.trust_engine is None:
            raise StoreUnavailable("sspm trust engine unavailable")
        if self.engine.workflow_engine is None:
            raise StoreUnavailable("sspm workflow engine unavailable")
        if self.engine.absence_router is None:
            raise StoreUnavailable("sspm inventory lifecycle adapter unavailable")
        if self.engine.config.baseline_ids and self.engine.baseline_router is None:
            raise StoreUnavailable("EA-0012 SaaS baseline router unavailable")

    def _health_tenant(self) -> str | None:
        if getattr(self.store, "mode", "local") == "enterprise":
            return "018f0000-0000-7000-8000-000000290504"
        return None
