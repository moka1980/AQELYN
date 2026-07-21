"""Secrets Intelligence AQService wrapper and owned events (EA-0032 W5)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Protocol

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import CryptoConfigInvalid, EvidenceNotFound, StoreUnavailable
from aqelyn.events.registry import EventTypeRegistry
from aqelyn.exposure import KnownSurfaceSource
from aqelyn.findings import FindingQuery
from aqelyn.governance import ComplianceSnapshot
from aqelyn.kernel.service import HealthStatus
from aqelyn.objects import ObjectQuery
from aqelyn.secrets.engine import SecretsIntelligenceEngine
from aqelyn.secrets.models import (
    CertificateAsset,
    CertificateDescriptor,
    CryptoAssessment,
    CryptoAsset,
    CryptoConfig,
    CryptographicExposure,
    CryptographicKey,
    CryptographicKeyDescriptor,
    CryptoQuery,
    CryptoScope,
    SecretAsset,
    SecretScanDescriptor,
    _reject_value_keys,
)
from aqelyn.secrets.store import CryptoStore
from aqelyn.workflow import Run

CRYPTO_EVENTS: dict[str, int] = {
    "aqelyn.crypto.secret_detected": 1,
    "aqelyn.crypto.certificate_expiring": 1,
    "aqelyn.crypto.weak_key_detected": 1,
    "aqelyn.crypto.lifecycle_unknown": 1,
}

_OWNER_SERVICES = frozenset(
    (
        "inventory_engine",
        "exposure_engine",
        "compliance_engine",
        "trust_engine",
        "workflow_engine",
    )
)


def register_crypto_events(registry: EventTypeRegistry) -> None:
    for event_type, schema_version in CRYPTO_EVENTS.items():
        registry.register(event_type, schema_version, _validate_crypto_event_payload)


def _validate_crypto_event_payload(payload: dict[str, object]) -> None:
    _reject_value_keys(payload, path="crypto_event")


class _HealthSource(Protocol):
    async def health(self) -> HealthStatus: ...


class SecretsIntelligenceService:
    def __init__(
        self,
        engine: SecretsIntelligenceEngine,
        *,
        store: CryptoStore,
        known_surface_source: KnownSurfaceSource,
        owner_services: Mapping[str, _HealthSource],
        close_store: Callable[[], Awaitable[None]] | None = None,
        dependencies: Sequence[str] = (
            "object_store",
            "inventory_engine",
            "exposure_engine",
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
        return "secrets_engine"

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
            dependencies["crypto_store"] = "healthy"
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
            if self.engine.authenticity_verifier is None:
                dependencies["authenticity_verifier"] = "unconfigured"
                degraded.append("authenticity_verifier")
            else:
                dependencies["authenticity_verifier"] = "configured"
        except (CryptoConfigInvalid, StoreUnavailable) as exc:
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

    async def ingest_secrets(
        self,
        descriptors: Sequence[SecretScanDescriptor],
        *,
        tenant_id: str | None,
    ) -> list[SecretAsset]:
        return await self.engine.ingest_secrets(descriptors, tenant_id=tenant_id)

    async def ingest_crypto_assets(
        self,
        keys: Sequence[CryptographicKeyDescriptor],
        certificates: Sequence[CertificateDescriptor],
        *,
        tenant_id: str | None,
    ) -> list[CryptoAsset]:
        return await self.engine.ingest_crypto_assets(
            keys,
            certificates,
            tenant_id=tenant_id,
        )

    async def assess_certificate(
        self,
        certificate_id: str,
        *,
        tenant_id: str | None,
    ) -> CertificateAsset:
        return await self.engine.assess_certificate(certificate_id, tenant_id=tenant_id)

    async def assess_key(
        self,
        key_id: str,
        *,
        tenant_id: str | None,
    ) -> CryptographicKey:
        return await self.engine.assess_key(key_id, tenant_id=tenant_id)

    async def analyze_exposure(
        self,
        *,
        tenant_id: str | None,
        scope: CryptoScope | None = None,
    ) -> list[CryptographicExposure]:
        return await self.engine.analyze_exposure(tenant_id=tenant_id, scope=scope)

    async def exposures_to_findings(
        self,
        exposures: Sequence[CryptographicExposure],
        *,
        tenant_id: str | None,
        by: ActorRef,
    ) -> list[str]:
        return await self.engine.exposures_to_findings(
            exposures,
            tenant_id=tenant_id,
            by=by,
        )

    async def crypto_compliance(
        self,
        *,
        tenant_id: str | None,
        scope: ObjectQuery,
    ) -> ComplianceSnapshot:
        return await self.engine.crypto_compliance(tenant_id=tenant_id, scope=scope)

    async def assess(
        self,
        *,
        tenant_id: str | None,
        scope: CryptoScope | None = None,
    ) -> CryptoAssessment:
        return await self.engine.assess(tenant_id=tenant_id, scope=scope)

    async def propose_rotation(
        self,
        finding_id: str,
        *,
        tenant_id: str | None,
        by: ActorRef,
        reason: str,
    ) -> Run:
        return await self.engine.propose_rotation(
            finding_id,
            tenant_id=tenant_id,
            by=by,
            reason=reason,
        )

    def explain(self, asset: CryptoAsset) -> dict[str, object]:
        return self.engine.explain(asset)

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
        CryptoConfig.model_validate(self.engine.config.model_dump(mode="json"))

    async def _check_store(self) -> None:
        try:
            await self.store.query_assets(
                query=self._health_query(),
            )
        except Exception as exc:
            raise StoreUnavailable(f"crypto store unavailable: {exc}") from exc

    async def _check_object_store(self) -> None:
        try:
            await self.engine.object_store.get(new_id("obj"), resolve_merged=False)
        except Exception as exc:
            raise StoreUnavailable(f"crypto object store unavailable: {exc}") from exc

    async def _check_evidence_store(self) -> None:
        try:
            await self.engine.evidence_store.verify(new_id("evd"))
        except EvidenceNotFound:
            return
        except Exception as exc:
            raise StoreUnavailable(f"crypto evidence store unavailable: {exc}") from exc

    async def _check_known_surface_source(self) -> None:
        try:
            await self.known_surface_source.list_known_surface(tenant_id=self._health_tenant())
        except Exception as exc:
            raise StoreUnavailable(f"crypto known surface unavailable: {exc}") from exc

    async def _check_finding_store(self) -> None:
        if self.engine.finding_store is None:
            raise StoreUnavailable("crypto finding store unavailable")
        try:
            await self.engine.finding_store.query(
                FindingQuery(tenant_id=self._health_tenant(), limit=1)
            )
        except Exception as exc:
            raise StoreUnavailable(f"crypto finding store unavailable: {exc}") from exc

    def _check_adapters(self) -> None:
        if self.engine.exposure_owner is None:
            raise StoreUnavailable("EA-0023 crypto exposure owner unavailable")
        if self.engine.compliance_owner is None:
            raise StoreUnavailable("EA-0010 crypto compliance owner unavailable")
        if self.engine.workflow_engine is None:
            raise StoreUnavailable("EA-0008 crypto workflow owner unavailable")

    async def _owner_status(self, service_name: str) -> str:
        service = self.owner_services.get(service_name)
        if service is None:
            raise StoreUnavailable(f"required crypto owner unavailable: {service_name}")
        status = await service.health()
        if status.status == "unavailable":
            raise StoreUnavailable(
                f"required crypto owner unavailable: {service_name}: {status.detail or 'unknown'}"
            )
        return status.status

    def _health_query(self) -> CryptoQuery:
        return CryptoQuery(tenant_id=self._health_tenant(), limit=1)

    def _health_tenant(self) -> str | None:
        if getattr(self.store, "mode", "local") == "enterprise":
            return "018f0000-0000-7000-8000-000000320500"
        return None
