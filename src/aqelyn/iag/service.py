"""Identity & Access Governance AQService wrapper and events (EA-0011 I5)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import (
    EvidenceNotFound,
    IAGConfigInvalid,
    ObjectNotFound,
    StoreUnavailable,
)
from aqelyn.events.registry import EventTypeRegistry
from aqelyn.iag.engine import IdentityAccessGovernanceEngine
from aqelyn.iag.models import IAGConfig
from aqelyn.iag.store import CertificationStore
from aqelyn.kernel.service import HealthStatus
from aqelyn.policy.models import ComplianceResult
from aqelyn.policy.store import PolicyStore

IAG_EVENTS: dict[str, int] = {
    "aqelyn.iag.risk_detected": 1,
    "aqelyn.iag.certification_opened": 1,
    "aqelyn.iag.item_decided": 1,
    "aqelyn.iag.certification_completed": 1,
}


def register_iag_events(registry: EventTypeRegistry) -> None:
    for event_type, schema_version in IAG_EVENTS.items():
        registry.register(event_type, schema_version, None)


class IdentityAccessGovernanceService:
    def __init__(
        self,
        engine: IdentityAccessGovernanceEngine,
        *,
        certification_store: CertificationStore,
        close_certification_store: Callable[[], Awaitable[None]] | None = None,
        dependencies: Sequence[str] = (
            "object_store",
            "knowledge_graph",
            "policy_engine",
            "mission_engine",
            "workflow_engine",
        ),
        critical: bool = True,
    ) -> None:
        self.engine = engine
        self._certification_store = certification_store
        self._close_certification_store = close_certification_store
        self._dependencies = tuple(dependencies)
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return "iag_engine"

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
            if self._close_certification_store is not None:
                await self._close_certification_store()
        finally:
            self._started = False

    async def health(self) -> HealthStatus:
        dependencies: dict[str, str] = {}
        try:
            self._check_config()
            await self._check_object_store()
            dependencies["object_store"] = "healthy"
            await self._check_knowledge_graph()
            dependencies["knowledge_graph"] = "healthy"
            await self._check_policy_engine()
            dependencies["policy_engine"] = "healthy"
            await self._check_certification_store()
            dependencies["certification_store"] = "healthy"
            await self._check_evidence_store()
            dependencies["evidence_store"] = "healthy"
            await self._check_finding_store()
            dependencies["finding_store"] = "healthy"
            self._check_workflow_engine()
            dependencies["workflow_engine"] = "healthy"
        except IAGConfigInvalid as exc:
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
        await self._check_knowledge_graph()
        await self._check_policy_engine()
        await self._check_certification_store()
        await self._check_evidence_store()
        await self._check_finding_store()
        self._check_workflow_engine()

    def _check_config(self) -> None:
        IAGConfig.model_validate(self.engine.config.model_dump(mode="json"))

    async def _check_object_store(self) -> None:
        try:
            await self.engine.object_store.get(new_id("obj"), resolve_merged=False)
        except Exception as exc:
            raise StoreUnavailable(f"iag object store unavailable: {exc}") from exc

    async def _check_knowledge_graph(self) -> None:
        try:
            await self.engine.knowledge_graph.impact(new_id("obj"), max_depth=1, max_nodes=1)
        except ObjectNotFound:
            return
        except StoreUnavailable:
            raise
        except Exception as exc:
            raise StoreUnavailable(f"iag knowledge graph unavailable: {exc}") from exc

    async def _check_policy_engine(self) -> None:
        try:
            result = await self.engine.policy_engine.evaluate_compliance(
                {
                    "id": new_id("obj"),
                    "type": "identity",
                    "object_type": "identity",
                    "tenant_id": None,
                    "attributes": {},
                    "labels": {},
                    "confidence": 1.0,
                    "lifecycle_state": "active",
                },
                tenant_id=None,
                policy_ids=set(),
            )
            ComplianceResult.model_validate(result.model_dump(mode="json"))
        except Exception as exc:
            raise StoreUnavailable(f"iag policy engine unavailable: {exc}") from exc

    async def _check_certification_store(self) -> None:
        try:
            await self._certification_store.get(new_id("cert"))
        except Exception as exc:
            raise StoreUnavailable(f"iag certification store unavailable: {exc}") from exc

    async def _check_evidence_store(self) -> None:
        try:
            await self.engine.evidence_store.verify(new_id("evd"))
        except EvidenceNotFound:
            return
        except Exception as exc:
            raise StoreUnavailable(f"iag evidence store unavailable: {exc}") from exc

    async def _check_finding_store(self) -> None:
        if self.engine.finding_store is None:
            raise StoreUnavailable("iag finding store unavailable")
        try:
            await self.engine.finding_store.get(new_id("fnd"))
        except Exception as exc:
            raise StoreUnavailable(f"iag finding store unavailable: {exc}") from exc

    def _check_workflow_engine(self) -> None:
        if self.engine.workflow_engine is None:
            raise StoreUnavailable("iag workflow engine unavailable")


class StoreBackedIAGPolicyEvaluator:
    """Loads tenant-visible policies before delegating SoD evaluation."""

    def __init__(self, store: PolicyStore) -> None:
        self._store = store

    async def evaluate_compliance(
        self,
        resource: dict[str, object],
        *,
        tenant_id: str | None,
        policy_ids: set[str] | None = None,
    ) -> ComplianceResult:
        from aqelyn.policy import PolicyEngine

        policies = await self._store.list(tenant_id=tenant_id)
        return await PolicyEngine(policies).evaluate_compliance(
            resource,
            tenant_id=tenant_id,
            policy_ids=policy_ids,
        )
