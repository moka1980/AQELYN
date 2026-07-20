"""DSPM AQService wrapper and owned events (EA-0031 P5)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Protocol

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import DSPMConfigInvalid, EvidenceNotFound, StoreUnavailable
from aqelyn.dspm.engine import DSPMEngine
from aqelyn.dspm.models import (
    DataAccessContext,
    DataAsset,
    DataExposure,
    DataPostureAssessment,
    DataStoreDescriptor,
    DSPMConfig,
    DSPMScope,
    FieldClassification,
)
from aqelyn.dspm.store import DSPMStore
from aqelyn.dspm.surface import DataStoreKnownSurfaceSource
from aqelyn.events.registry import EventTypeRegistry
from aqelyn.findings import FindingQuery
from aqelyn.governance import ComplianceSnapshot
from aqelyn.kernel.service import HealthStatus
from aqelyn.objects import ObjectQuery

DSPM_EVENTS: dict[str, int] = {
    "aqelyn.data.store_classified": 1,
    "aqelyn.data.exposure_detected": 1,
    "aqelyn.data.classification_conflict": 1,
}

_OWNER_SERVICES = frozenset(
    (
        "inventory_engine",
        "exposure_engine",
        "iag_engine",
        "compliance_engine",
        "trust_engine",
        "workflow_engine",
    )
)


def register_dspm_events(registry: EventTypeRegistry) -> None:
    for event_type, schema_version in DSPM_EVENTS.items():
        registry.register(event_type, schema_version, None)


class _HealthSource(Protocol):
    async def health(self) -> HealthStatus: ...


class DSPMService:
    def __init__(
        self,
        engine: DSPMEngine,
        *,
        store: DSPMStore,
        known_surface_source: DataStoreKnownSurfaceSource,
        owner_services: Mapping[str, _HealthSource],
        close_store: Callable[[], Awaitable[None]] | None = None,
        dependencies: Sequence[str] = (
            "object_store",
            "inventory_engine",
            "exposure_engine",
            "iag_engine",
            "compliance_engine",
            "trust_engine",
            "workflow_engine",
        ),
        critical: bool = True,
    ) -> None:
        self.engine = engine
        self.store = store
        self.known_surface_source = known_surface_source
        self.owner_services = dict(owner_services)
        self._close_store = close_store
        self._dependencies = tuple(dependencies)
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return "dspm_engine"

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
        degraded: list[str] = []
        try:
            self._check_config()
            await self._check_store()
            dependencies["dspm_store"] = "healthy"
            await self._check_object_store()
            dependencies["object_store"] = "healthy"
            await self._check_evidence_store()
            dependencies["evidence_store"] = "healthy"
            await self._check_known_surface_source()
            dependencies["known_surface_source"] = "healthy"
            await self._check_finding_store()
            dependencies["finding_store"] = "healthy"
            self._check_adapters()
            for service_name in sorted(_OWNER_SERVICES):
                status = await self._owner_status(service_name)
                dependencies[service_name] = status
                if status != "healthy":
                    degraded.append(service_name)
        except (DSPMConfigInvalid, StoreUnavailable) as exc:
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
        if degraded:
            return HealthStatus(
                status="degraded",
                ready=True,
                detail=f"degraded dependencies: {', '.join(sorted(degraded))}",
                dependencies=dependencies,
            )
        return HealthStatus(status="healthy", ready=True, dependencies=dependencies)

    async def ingest_store(
        self,
        descriptors: Sequence[DataStoreDescriptor],
        *,
        tenant_id: str | None,
    ) -> list[DataAsset]:
        return await self.engine.ingest_store(descriptors, tenant_id=tenant_id)

    async def classify(
        self,
        asset_id: str,
        *,
        tenant_id: str | None,
    ) -> list[FieldClassification]:
        return await self.engine.classify(asset_id, tenant_id=tenant_id)

    async def analyze_exposure(
        self,
        *,
        tenant_id: str | None,
        scope: DSPMScope | None = None,
    ) -> list[DataExposure]:
        return await self.engine.analyze_exposure(tenant_id=tenant_id, scope=scope)

    async def access_context(
        self,
        asset_id: str,
        *,
        tenant_id: str | None,
    ) -> DataAccessContext:
        return await self.engine.access_context(asset_id, tenant_id=tenant_id)

    async def data_compliance(
        self,
        *,
        tenant_id: str | None,
        scope: ObjectQuery,
    ) -> ComplianceSnapshot:
        return await self.engine.data_compliance(tenant_id=tenant_id, scope=scope)

    async def assess(
        self,
        *,
        tenant_id: str | None,
        scope: DSPMScope | None = None,
    ) -> DataPostureAssessment:
        return await self.engine.assess(tenant_id=tenant_id, scope=scope)

    async def exposures_to_findings(
        self,
        assessment_id: str,
        *,
        tenant_id: str | None,
        by: ActorRef,
        propose_remediation: bool = True,
    ) -> list[str]:
        return await self.engine.exposures_to_findings(
            assessment_id,
            tenant_id=tenant_id,
            by=by,
            propose_remediation=propose_remediation,
        )

    def explain(self, exposure: DataExposure) -> dict[str, object]:
        return self.engine.explain(exposure)

    async def _check_available(self) -> None:
        self._check_config()
        await self._check_store()
        await self._check_object_store()
        await self._check_evidence_store()
        await self._check_known_surface_source()
        await self._check_finding_store()
        self._check_adapters()
        for service_name in sorted(_OWNER_SERVICES):
            await self._owner_status(service_name)

    def _check_config(self) -> None:
        DSPMConfig.model_validate(self.engine.config.model_dump(mode="json"))

    async def _check_store(self) -> None:
        try:
            await self.store.query_assets(tenant_id=self._health_tenant(), limit=1)
        except Exception as exc:
            raise StoreUnavailable(f"DSPM store unavailable: {exc}") from exc

    async def _check_object_store(self) -> None:
        try:
            await self.engine.object_store.get(new_id("obj"), resolve_merged=False)
        except Exception as exc:
            raise StoreUnavailable(f"DSPM object store unavailable: {exc}") from exc

    async def _check_evidence_store(self) -> None:
        try:
            await self.engine.evidence_store.verify(new_id("evd"))
        except EvidenceNotFound:
            return
        except Exception as exc:
            raise StoreUnavailable(f"DSPM classifier evidence unavailable: {exc}") from exc

    async def _check_known_surface_source(self) -> None:
        try:
            await self.known_surface_source.list_known_surface(tenant_id=self._health_tenant())
        except Exception as exc:
            raise StoreUnavailable(f"DSPM known surface unavailable: {exc}") from exc

    async def _check_finding_store(self) -> None:
        if self.engine.finding_store is None:
            raise StoreUnavailable("DSPM finding store unavailable")
        try:
            await self.engine.finding_store.query(
                FindingQuery(tenant_id=self._health_tenant(), limit=1)
            )
        except Exception as exc:
            raise StoreUnavailable(f"DSPM finding store unavailable: {exc}") from exc

    def _check_adapters(self) -> None:
        if self.engine.exposure_owner is None:
            raise StoreUnavailable("DSPM exposure owner unavailable")
        if self.engine.iag_owner is None:
            raise StoreUnavailable("DSPM IAG owner unavailable")
        if self.engine.compliance_owner is None:
            raise StoreUnavailable("DSPM governance owner unavailable")
        if self.engine.workflow_engine is None:
            raise StoreUnavailable("DSPM Workflow owner unavailable")

    async def _owner_status(self, service_name: str) -> str:
        service = self.owner_services.get(service_name)
        if service is None:
            raise StoreUnavailable(f"required DSPM owner unavailable: {service_name}")
        status = await service.health()
        if status.status == "unavailable":
            raise StoreUnavailable(
                f"required DSPM owner unavailable: {service_name}: {status.detail or 'unknown'}"
            )
        return status.status

    def _health_tenant(self) -> str | None:
        if getattr(self.store, "mode", "local") == "enterprise":
            return "018f0000-0000-7000-8000-000000310500"
        return None
