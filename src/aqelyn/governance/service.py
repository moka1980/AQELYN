"""Compliance & Governance AQService wrapper and events (EA-0010 G5)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import EvidenceNotFound, GovernanceConfigInvalid, StoreUnavailable
from aqelyn.events.registry import EventTypeRegistry
from aqelyn.evidence import EvidenceStore
from aqelyn.findings import FindingStore
from aqelyn.governance.engine import ComplianceEngine
from aqelyn.governance.models import GovernanceConfig
from aqelyn.governance.store import SnapshotStore
from aqelyn.kernel.service import HealthStatus
from aqelyn.policy import PolicyEngine
from aqelyn.policy.models import ComplianceResult
from aqelyn.policy.store import PolicyStore

COMPLIANCE_EVENTS: dict[str, int] = {
    "aqelyn.compliance.assessment_completed": 1,
    "aqelyn.compliance.posture_changed": 1,
}


def register_compliance_events(registry: EventTypeRegistry) -> None:
    for event_type, schema_version in COMPLIANCE_EVENTS.items():
        registry.register(event_type, schema_version, None)


class StoreBackedCompliancePolicyEngine:
    """Loads tenant-visible policies before delegating compliance evaluation."""

    def __init__(self, store: PolicyStore) -> None:
        self._store = store

    async def evaluate_compliance(
        self,
        resource: dict[str, Any],
        *,
        tenant_id: str | None,
        policy_ids: set[str] | None = None,
    ) -> ComplianceResult:
        policies = await self._store.list(tenant_id=tenant_id)
        return await PolicyEngine(policies).evaluate_compliance(
            resource,
            tenant_id=tenant_id,
            policy_ids=policy_ids,
        )


class ComplianceGovernanceService:
    def __init__(
        self,
        engine: ComplianceEngine,
        *,
        snapshot_store: SnapshotStore,
        evidence_store: EvidenceStore,
        finding_store: FindingStore,
        close_snapshot_store: Callable[[], Awaitable[None]] | None = None,
        dependencies: Sequence[str] = ("object_store", "policy_engine", "mission_engine"),
        critical: bool = True,
    ) -> None:
        self.engine = engine
        self._snapshot_store = snapshot_store
        self._evidence_store = evidence_store
        self._finding_store = finding_store
        self._close_snapshot_store = close_snapshot_store
        self._dependencies = tuple(dependencies)
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return "compliance_engine"

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
        finally:
            self._started = False

    async def health(self) -> HealthStatus:
        dependencies: dict[str, str] = {}
        try:
            self._check_config()
            await self._check_object_store()
            dependencies["object_store"] = "healthy"
            await self._check_policy_engine()
            dependencies["policy_engine"] = "healthy"
            await self._check_snapshot_store()
            dependencies["snapshot_store"] = "healthy"
            await self._check_evidence_store()
            dependencies["evidence_store"] = "healthy"
            await self._check_finding_store()
            dependencies["finding_store"] = "healthy"
        except GovernanceConfigInvalid as exc:
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
        await self._check_policy_engine()
        await self._check_snapshot_store()
        await self._check_evidence_store()
        await self._check_finding_store()

    def _check_config(self) -> None:
        GovernanceConfig.model_validate(self.engine.config.model_dump(mode="json"))

    async def _check_object_store(self) -> None:
        try:
            await self.engine.object_store.get(new_id("obj"), resolve_merged=False)
        except Exception as exc:
            raise StoreUnavailable(f"governance object store unavailable: {exc}") from exc

    async def _check_policy_engine(self) -> None:
        try:
            await self.engine.policy_engine.evaluate_compliance(
                {
                    "id": new_id("obj"),
                    "type": "generic",
                    "object_type": "generic",
                    "tenant_id": None,
                    "attributes": {},
                    "labels": {},
                    "confidence": 1.0,
                    "lifecycle_state": "active",
                },
                tenant_id=None,
                policy_ids=set(),
            )
        except Exception as exc:
            raise StoreUnavailable(f"governance policy engine unavailable: {exc}") from exc

    async def _check_snapshot_store(self) -> None:
        try:
            await self._snapshot_store.get(new_id("snap"))
        except Exception as exc:
            raise StoreUnavailable(f"governance snapshot store unavailable: {exc}") from exc

    async def _check_evidence_store(self) -> None:
        try:
            await self._evidence_store.verify(new_id("evd"))
        except EvidenceNotFound:
            return
        except Exception as exc:
            raise StoreUnavailable(f"governance evidence store unavailable: {exc}") from exc

    async def _check_finding_store(self) -> None:
        try:
            await self._finding_store.get(new_id("fnd"))
        except Exception as exc:
            raise StoreUnavailable(f"governance finding store unavailable: {exc}") from exc
