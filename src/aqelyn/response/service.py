"""Response Orchestration AQService wrapper and events (EA-0018 R6)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import EvidenceNotFound, ResponseConfigInvalid, StoreUnavailable
from aqelyn.events.registry import EventTypeRegistry
from aqelyn.evidence import EvidenceStore
from aqelyn.findings.store import FindingStore
from aqelyn.kernel.service import HealthStatus
from aqelyn.response.campaign import ResponseOrchestrationEngine, WorkflowController
from aqelyn.response.metrics import IncidentReader
from aqelyn.response.models import ResponseConfig
from aqelyn.response.store import CampaignStore, TriggerStore
from aqelyn.response.triggers import PolicyAuthorizer

RESPONSE_EVENTS: dict[str, int] = {
    "aqelyn.response.campaign_planned": 1,
    "aqelyn.response.started": 1,
    "aqelyn.response.phase_completed": 1,
    "aqelyn.response.approval_routed": 1,
    "aqelyn.response.campaign_completed": 1,
}


def register_response_events(registry: EventTypeRegistry) -> None:
    for event_type, schema_version in RESPONSE_EVENTS.items():
        registry.register(event_type, schema_version, None)


class ResponseOrchestrationService:
    def __init__(
        self,
        engine: ResponseOrchestrationEngine,
        *,
        campaign_store: CampaignStore,
        trigger_store: TriggerStore,
        evidence_store: EvidenceStore,
        finding_store: FindingStore,
        workflow_engine: WorkflowController,
        policy_authorizer: PolicyAuthorizer,
        incident_reader: IncidentReader | None = None,
        close_campaign_store: Callable[[], Awaitable[None]] | None = None,
        close_trigger_store: Callable[[], Awaitable[None]] | None = None,
        dependencies: Sequence[str] = ("workflow_engine", "policy_engine", "soc_engine"),
        critical: bool = True,
    ) -> None:
        self.engine = engine
        self.campaign_store = campaign_store
        self.trigger_store = trigger_store
        self.evidence_store = evidence_store
        self.finding_store = finding_store
        self.workflow_engine = workflow_engine
        self.policy_authorizer = policy_authorizer
        self.incident_reader = incident_reader
        self._close_campaign_store = close_campaign_store
        self._close_trigger_store = close_trigger_store
        self._dependencies = tuple(dependencies)
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return "response_engine"

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
            if self._close_trigger_store is not None:
                await self._close_trigger_store()
            if self._close_campaign_store is not None:
                await self._close_campaign_store()
        finally:
            self._started = False

    async def health(self) -> HealthStatus:
        dependencies: dict[str, str] = {}
        try:
            self._check_config()
            await self._check_campaign_store()
            dependencies["campaign_store"] = "healthy"
            await self._check_trigger_store()
            dependencies["trigger_store"] = "healthy"
            await self._check_evidence_store()
            dependencies["evidence_store"] = "healthy"
            await self._check_finding_store()
            dependencies["finding_store"] = "healthy"
            self._check_workflow_engine()
            dependencies["workflow_engine"] = "healthy"
            self._check_policy_engine()
            dependencies["policy_engine"] = "healthy"
            self._check_soc_engine()
            dependencies["soc_engine"] = "healthy"
        except ResponseConfigInvalid as exc:
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
        await self._check_campaign_store()
        await self._check_trigger_store()
        await self._check_evidence_store()
        await self._check_finding_store()
        self._check_workflow_engine()
        self._check_policy_engine()
        self._check_soc_engine()

    def _check_config(self) -> None:
        ResponseConfig.model_validate(self.engine.config.model_dump(mode="json"))

    async def _check_campaign_store(self) -> None:
        try:
            await self.campaign_store.get(new_id("rsp"))
        except Exception as exc:
            raise StoreUnavailable(f"response campaign store unavailable: {exc}") from exc

    async def _check_trigger_store(self) -> None:
        try:
            await self.trigger_store.list(tenant_id=None, enabled_only=True)
        except Exception as exc:
            raise StoreUnavailable(f"response trigger store unavailable: {exc}") from exc

    async def _check_evidence_store(self) -> None:
        try:
            await self.evidence_store.verify(new_id("evd"))
        except EvidenceNotFound:
            return
        except Exception as exc:
            raise StoreUnavailable(f"response evidence store unavailable: {exc}") from exc

    async def _check_finding_store(self) -> None:
        try:
            await self.finding_store.get(new_id("fnd"))
        except Exception as exc:
            raise StoreUnavailable(f"response finding store unavailable: {exc}") from exc

    def _check_workflow_engine(self) -> None:
        if self.workflow_engine is None:
            raise StoreUnavailable("response workflow engine unavailable")

    def _check_policy_engine(self) -> None:
        if self.policy_authorizer is None:
            raise StoreUnavailable("response policy engine unavailable")

    def _check_soc_engine(self) -> None:
        if self.incident_reader is None:
            raise StoreUnavailable("response SOC incident reader unavailable")
