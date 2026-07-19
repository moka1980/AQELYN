"""Software Supply Chain AQService wrapper and events (EA-0030 Q5)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Protocol

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import EvidenceNotFound, StoreUnavailable, SupplyChainConfigInvalid
from aqelyn.events.registry import EventTypeRegistry
from aqelyn.kernel.service import HealthStatus
from aqelyn.supplychain.engine import SupplyChainEngine
from aqelyn.supplychain.models import (
    ProvenanceAttestation,
    ProvenanceResult,
    ReachabilitySignal,
    SBOMDocument,
    SoftwareComponent,
    SupplyChainAssessment,
    SupplyChainConfig,
)
from aqelyn.supplychain.store import SBOMStore

SUPPLYCHAIN_EVENTS: dict[str, int] = {
    "aqelyn.supplychain.sbom_ingested": 1,
    "aqelyn.supplychain.dependency_risk_detected": 1,
    "aqelyn.supplychain.provenance_failed": 1,
}


def register_supplychain_events(registry: EventTypeRegistry) -> None:
    for event_type, schema_version in SUPPLYCHAIN_EVENTS.items():
        registry.register(event_type, schema_version, None)


class _HealthSource(Protocol):
    async def health(self) -> HealthStatus: ...


class SupplyChainService:
    def __init__(
        self,
        engine: SupplyChainEngine,
        *,
        store: SBOMStore,
        owner_services: Mapping[str, _HealthSource],
        close_store: Callable[[], Awaitable[None]] | None = None,
        dependencies: Sequence[str] = (
            "object_store",
            "knowledge_graph",
            "inventory_engine",
            "vuln_engine",
            "compliance_engine",
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
        return "supplychain_engine"

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
            dependencies["sbom_store"] = "healthy"
            await self._check_evidence_store()
            dependencies["evidence_store"] = "healthy"
            for service_name in sorted(self.owner_services):
                status = await self._owner_status(service_name)
                dependencies[service_name] = status
                if status != "healthy":
                    degraded.append(service_name)
            if self.engine.provenance_verifier is None:
                dependencies["provenance_verifier"] = "unconfigured"
                degraded.append("provenance_verifier")
            else:
                dependencies["provenance_verifier"] = "configured"
        except (SupplyChainConfigInvalid, StoreUnavailable) as exc:
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

    async def ingest_sbom(
        self,
        doc: SBOMDocument,
        *,
        tenant_id: str | None,
    ) -> list[SoftwareComponent]:
        return await self.engine.ingest_sbom(doc, tenant_id=tenant_id)

    async def reachability(
        self,
        component_purl: str,
        cve_id: str,
        *,
        tenant_id: str | None,
    ) -> ReachabilitySignal:
        return await self.engine.reachability(
            component_purl,
            cve_id,
            tenant_id=tenant_id,
        )

    async def verify_provenance(
        self,
        attestations: Sequence[ProvenanceAttestation],
        *,
        tenant_id: str | None,
    ) -> list[ProvenanceResult]:
        return await self.engine.verify_provenance(attestations, tenant_id=tenant_id)

    async def component_vulns_to_prioritization(
        self,
        purls: Sequence[str],
        *,
        tenant_id: str | None,
        by: ActorRef,
    ) -> list[str]:
        return await self.engine.component_vulns_to_prioritization(
            purls,
            tenant_id=tenant_id,
            by=by,
        )

    async def license_findings(
        self,
        *,
        tenant_id: str | None,
        by: ActorRef,
    ) -> list[str]:
        return await self.engine.license_findings(tenant_id=tenant_id, by=by)

    async def aggregate_risk(self, *, tenant_id: str | None) -> str:
        return await self.engine.aggregate_risk(tenant_id=tenant_id)

    async def propose_remediation(
        self,
        component_purl: str,
        *,
        action: str,
        tenant_id: str | None,
        by: ActorRef,
    ) -> str:
        return await self.engine.propose_remediation(
            component_purl,
            action=action,
            tenant_id=tenant_id,
            by=by,
        )

    async def assess(
        self,
        *,
        subject_ref: str,
        tenant_id: str | None,
    ) -> SupplyChainAssessment:
        return await self.engine.assess(subject_ref=subject_ref, tenant_id=tenant_id)

    def explain(self, signal: ReachabilitySignal) -> dict[str, object]:
        return self.engine.explain(signal)

    async def _check_available(self) -> None:
        self._check_config()
        await self._check_store()
        await self._check_evidence_store()
        for service_name in sorted(self.owner_services):
            await self._owner_status(service_name)

    def _check_config(self) -> None:
        SupplyChainConfig.model_validate(self.engine.config.model_dump(mode="json"))

    async def _check_store(self) -> None:
        try:
            await self.store.query(tenant_id=self._health_tenant(), limit=1)
        except Exception as exc:
            raise StoreUnavailable(f"SBOM store unavailable: {exc}") from exc

    async def _check_evidence_store(self) -> None:
        try:
            await self.engine.evidence_store.verify(new_id("evd"))
        except EvidenceNotFound:
            return
        except Exception as exc:
            raise StoreUnavailable(f"evidence store unavailable: {exc}") from exc

    async def _owner_status(self, service_name: str) -> str:
        service = self.owner_services.get(service_name)
        if service is None:
            raise StoreUnavailable(f"required owner service unavailable: {service_name}")
        status = await service.health()
        if status.status == "unavailable":
            raise StoreUnavailable(
                f"required owner service unavailable: {service_name}: {status.detail or 'unknown'}"
            )
        return status.status

    def _health_tenant(self) -> str | None:
        if getattr(self.store, "mode", "local") == "enterprise":
            return "018f0000-0000-7000-8000-000000300500"
        return None
