"""CSPM AQService wrapper and normalization-owned events (EA-0028 Y4)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Protocol

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import CloudConfigInvalid, EvidenceNotFound, StoreUnavailable
from aqelyn.cspm.engine import CloudPostureEngine
from aqelyn.cspm.models import (
    ROUTE_OWNERS,
    CloudNormalizationConfig,
    CloudResourceDescriptor,
    CloudRoutingResult,
    NormalizedCloudObject,
)
from aqelyn.cspm.store import CloudNormalizationStore
from aqelyn.events.registry import EventTypeRegistry
from aqelyn.kernel.service import HealthStatus

CLOUD_EVENTS: dict[str, int] = {
    "aqelyn.cloud.resource_normalized": 1,
    "aqelyn.cloud.resource_unclassified": 1,
}


def register_cloud_events(registry: EventTypeRegistry) -> None:
    for event_type, schema_version in CLOUD_EVENTS.items():
        registry.register(event_type, schema_version, None)


class _HealthSource(Protocol):
    async def health(self) -> HealthStatus: ...


class CloudPostureService:
    def __init__(
        self,
        engine: CloudPostureEngine,
        *,
        store: CloudNormalizationStore,
        owner_services: Mapping[str, _HealthSource],
        close_store: Callable[[], Awaitable[None]] | None = None,
        dependencies: Sequence[str] = (
            "object_store",
            "inventory_engine",
            "acg_engine",
            "compliance_engine",
            "exposure_engine",
            "iag_engine",
            "risk_engine",
            "trust_engine",
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
        return "cspm_engine"

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
            dependencies["cloud_normalization_store"] = "healthy"
            await self._check_object_store()
            dependencies["object_store"] = "healthy"
            await self._check_evidence_store()
            dependencies["evidence_store"] = "healthy"
            await self._check_trust_registry()
            dependencies["trust_engine"] = "healthy"
            for owner in sorted(ROUTE_OWNERS):
                service_name = _owner_service_name(owner)
                await self._check_owner_service(service_name)
                dependencies[service_name] = "healthy"
            if self.engine.config.baseline_ids and self.engine.baseline_router is None:
                raise StoreUnavailable("EA-0012 cloud baseline router unavailable")
        except (CloudConfigInvalid, StoreUnavailable) as exc:
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
        descriptors: Sequence[CloudResourceDescriptor],
        *,
        tenant_id: str | None,
    ) -> list[NormalizedCloudObject]:
        return await self.engine.normalize(descriptors, tenant_id=tenant_id)

    async def route(
        self,
        object_ids: Sequence[str],
        *,
        tenant_id: str | None,
    ) -> list[CloudRoutingResult]:
        return await self.engine.route(object_ids, tenant_id=tenant_id)

    async def apply_cloud_baselines(
        self,
        *,
        tenant_id: str | None,
        scope: Mapping[str, object] | None = None,
    ) -> str:
        return await self.engine.apply_cloud_baselines(tenant_id=tenant_id, scope=scope)

    def explain(self, obj: NormalizedCloudObject) -> dict[str, object]:
        return self.engine.explain(obj)

    async def _check_available(self) -> None:
        health = await self.health()
        if health.status == "unavailable":
            raise StoreUnavailable(health.detail or "cspm service unavailable")

    def _check_config(self) -> None:
        CloudNormalizationConfig.model_validate(self.engine.config.model_dump(mode="json"))
        if set(self.engine.owner_routers) != ROUTE_OWNERS:
            raise CloudConfigInvalid("all six CSPM owner routers must be configured")

    async def _check_store(self) -> None:
        try:
            await self.store.query(tenant_id=self._health_tenant(), limit=1)
        except Exception as exc:
            raise StoreUnavailable(f"cloud normalization store unavailable: {exc}") from exc

    async def _check_object_store(self) -> None:
        try:
            await self.engine.object_store.get(new_id("obj"), resolve_merged=False)
        except Exception as exc:
            raise StoreUnavailable(f"cspm object store unavailable: {exc}") from exc

    async def _check_evidence_store(self) -> None:
        try:
            await self.engine.evidence_store.verify(new_id("evd"))
        except EvidenceNotFound:
            return
        except Exception as exc:
            raise StoreUnavailable(f"cspm evidence store unavailable: {exc}") from exc

    async def _check_trust_registry(self) -> None:
        try:
            await self.engine.source_registry.get()
        except Exception as exc:
            raise StoreUnavailable(f"cspm trust registry unavailable: {exc}") from exc

    async def _check_owner_service(self, service_name: str) -> None:
        service = self.owner_services.get(service_name)
        if service is None:
            raise StoreUnavailable(f"{service_name} unavailable")
        status = await service.health()
        if status.status == "unavailable":
            raise StoreUnavailable(status.detail or f"{service_name} unavailable")

    def _health_tenant(self) -> str | None:
        if getattr(self.store, "mode", "local") == "enterprise":
            return "018f0000-0000-7000-8000-000000280504"
        return None


def _owner_service_name(owner: str) -> str:
    if owner == "inventory":
        return "inventory_engine"
    if owner == "assetconfig":
        return "acg_engine"
    return f"{owner}_engine"
