"""Identity Security Posture Management AQService and events (EA-0033 G5)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Protocol

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import EvidenceNotFound, ISPMConfigInvalid, StoreUnavailable
from aqelyn.events.registry import EventTypeRegistry
from aqelyn.exposure import ExposureRecord, KnownSurfaceSource
from aqelyn.findings import FindingQuery
from aqelyn.iag import AccessPath, AccessRiskReport, Certification
from aqelyn.ispm.engine import ISPMEngine
from aqelyn.ispm.models import (
    ISPM_EVENTS,
    IdentityDescriptor,
    IdentityDriftSnapshot,
    IdentityPostureScore,
    ISPMAssessment,
    ISPMConfig,
    NormalizedIdentity,
)
from aqelyn.ispm.store import ISPMStore
from aqelyn.kernel.service import HealthStatus
from aqelyn.objects import ObjectQuery

_OWNER_SERVICES = frozenset(
    (
        "iag_engine",
        "inventory_engine",
        "exposure_engine",
        "risk_engine",
        "mission_engine",
        "trust_engine",
        "decision_engine",
        "acg_engine",
        "compliance_engine",
        "workflow_engine",
    )
)


def register_ispm_events(registry: EventTypeRegistry) -> None:
    for event_type, schema_version in ISPM_EVENTS.items():
        registry.register(event_type, schema_version, None)


class _HealthSource(Protocol):
    async def health(self) -> HealthStatus: ...


class ISPMService:
    def __init__(
        self,
        engine: ISPMEngine,
        *,
        store: ISPMStore,
        known_surface_source: KnownSurfaceSource,
        owner_services: Mapping[str, _HealthSource],
        close_store: Callable[[], Awaitable[None]] | None = None,
        dependencies: Sequence[str] = (
            "object_store",
            "iag_engine",
            "inventory_engine",
            "exposure_engine",
            "risk_engine",
            "mission_engine",
            "trust_engine",
            "decision_engine",
            "acg_engine",
            "compliance_engine",
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
        return "ispm_engine"

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
            dependencies["ispm_store"] = "healthy"
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
        except (ISPMConfigInvalid, StoreUnavailable) as exc:
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
                detail=f"optional/degraded dependencies: {', '.join(sorted(degraded))}",
                dependencies=dependencies,
            )
        return HealthStatus(status="healthy", ready=True, dependencies=dependencies)

    async def ingest_identities(
        self,
        descriptors: Sequence[IdentityDescriptor],
        *,
        tenant_id: str | None,
    ) -> list[NormalizedIdentity]:
        return await self.engine.ingest_identities(descriptors, tenant_id=tenant_id)

    async def score_identity(
        self,
        account_object_id: str,
        *,
        tenant_id: str | None,
    ) -> IdentityPostureScore:
        return await self.engine.score_identity(account_object_id, tenant_id=tenant_id)

    async def detect_drift(
        self,
        *,
        baseline_id: str,
        tenant_id: str | None,
        scope: dict[str, object] | None = None,
    ) -> IdentityDriftSnapshot:
        return await self.engine.detect_drift(
            baseline_id=baseline_id,
            tenant_id=tenant_id,
            scope=scope,
        )

    async def governance_context(
        self,
        object_id: str,
        *,
        tenant_id: str | None,
    ) -> AccessRiskReport:
        return await self.engine.governance_context(object_id, tenant_id=tenant_id)

    async def access_paths(
        self,
        identity_id: str,
        *,
        tenant_id: str | None,
    ) -> list[AccessPath]:
        return await self.engine.access_paths(identity_id, tenant_id=tenant_id)

    async def open_certification(
        self,
        *,
        tenant_id: str | None,
        name: str,
        scope: ObjectQuery,
        by: ActorRef,
        due_days: int | None = None,
    ) -> Certification:
        return await self.engine.open_certification(
            tenant_id=tenant_id,
            name=name,
            scope=scope,
            by=by,
            due_days=due_days,
        )

    async def assess(
        self,
        *,
        tenant_id: str | None,
        scope: dict[str, object] | None = None,
    ) -> ISPMAssessment:
        return await self.engine.assess(tenant_id=tenant_id, scope=scope)

    async def posture_to_findings(
        self,
        assessment_id: str,
        *,
        tenant_id: str | None,
        by: ActorRef,
        propose_remediation: bool = True,
    ) -> list[str]:
        return await self.engine.posture_to_findings(
            assessment_id,
            tenant_id=tenant_id,
            by=by,
            propose_remediation=propose_remediation,
        )

    async def analyze_identity_exposure(
        self,
        score_id: str,
        *,
        tenant_id: str | None,
    ) -> ExposureRecord:
        return await self.engine.analyze_identity_exposure(score_id, tenant_id=tenant_id)

    def explain(self, score: IdentityPostureScore) -> dict[str, object]:
        return self.engine.explain(score)

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
        ISPMConfig.model_validate(self.engine.config.model_dump(mode="json"))

    async def _check_store(self) -> None:
        try:
            await self.store.query_identities(
                tenant_id=self._health_tenant(),
                limit=1,
            )
        except Exception as exc:
            raise StoreUnavailable(f"ISPM store unavailable: {exc}") from exc

    async def _check_object_store(self) -> None:
        try:
            await self.engine.object_store.get(new_id("obj"), resolve_merged=False)
        except Exception as exc:
            raise StoreUnavailable(f"ISPM object store unavailable: {exc}") from exc

    async def _check_evidence_store(self) -> None:
        try:
            await self.engine.evidence_store.verify(new_id("evd"))
        except EvidenceNotFound:
            return
        except Exception as exc:
            raise StoreUnavailable(f"ISPM evidence store unavailable: {exc}") from exc

    async def _check_known_surface_source(self) -> None:
        try:
            await self.known_surface_source.list_known_surface(tenant_id=self._health_tenant())
        except Exception as exc:
            raise StoreUnavailable(f"ISPM known surface unavailable: {exc}") from exc

    async def _check_finding_store(self) -> None:
        if self.engine.finding_store is None:
            raise StoreUnavailable("ISPM finding store unavailable")
        try:
            await self.engine.finding_store.query(
                FindingQuery(tenant_id=self._health_tenant(), limit=1)
            )
        except Exception as exc:
            raise StoreUnavailable(f"ISPM finding store unavailable: {exc}") from exc

    def _check_adapters(self) -> None:
        if self.engine.governance_owner is None:
            raise StoreUnavailable("EA-0011 ISPM governance owner unavailable")
        if self.engine.mission_owner is None:
            raise StoreUnavailable("EA-0007 ISPM mission owner unavailable")
        if self.engine.exposure_owner is None:
            raise StoreUnavailable("EA-0023 ISPM exposure owner unavailable")
        if self.engine.workflow_engine is None:
            raise StoreUnavailable("EA-0008 ISPM workflow owner unavailable")

    async def _owner_status(self, service_name: str) -> str:
        service = self.owner_services.get(service_name)
        if service is None:
            raise StoreUnavailable(f"required ISPM owner unavailable: {service_name}")
        status = await service.health()
        if status.status == "unavailable":
            raise StoreUnavailable(
                f"required ISPM owner unavailable: {service_name}: {status.detail or 'unknown'}"
            )
        return status.status

    def _health_tenant(self) -> str | None:
        if getattr(self.store, "mode", "local") == "enterprise":
            return "018f0000-0000-7000-8000-000000330500"
        return None
