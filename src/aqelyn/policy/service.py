"""PolicyEngine AQService wrapper and Workflow adapter (EA-0009 P4)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from aqelyn.conventions import ActorRef
from aqelyn.conventions.errors import PolicyConfigInvalid, StoreUnavailable, UnauthorizedAction
from aqelyn.events.registry import EventTypeRegistry
from aqelyn.findings import Finding
from aqelyn.kernel.service import HealthStatus
from aqelyn.policy.engine import PolicyEngine
from aqelyn.policy.models import (
    ComplianceResult,
    Decision,
    DecisionRequest,
    DecisionResource,
    Policy,
)
from aqelyn.policy.store import PolicyStore
from aqelyn.workflow.engine import StepAuthorization
from aqelyn.workflow.models import ActionSpec, Run, Step

POLICY_EVENTS: dict[str, int] = {
    "aqelyn.policy.updated": 1,
    "aqelyn.policy.decision_denied": 1,
}


def register_policy_events(registry: EventTypeRegistry) -> None:
    for event_type, schema_version in POLICY_EVENTS.items():
        registry.register(event_type, schema_version, None)


class PolicyEngineService:
    def __init__(
        self,
        store: PolicyStore,
        *,
        close_store: Callable[[], Awaitable[None]] | None = None,
        critical: bool = True,
    ) -> None:
        self.store = store
        self._close_store = close_store
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return "policy_engine"

    @property
    def dependencies(self) -> Sequence[str]:
        return ()

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
        try:
            await self._check_available()
        except PolicyConfigInvalid as exc:
            return HealthStatus(status="unavailable", ready=False, detail=exc.message)
        except StoreUnavailable as exc:
            return HealthStatus(status="unavailable", ready=False, detail=exc.message)
        except Exception as exc:
            return HealthStatus(
                status="unavailable", ready=False, detail=f"policy store unavailable: {exc}"
            )
        if not self._started:
            return HealthStatus(status="degraded", ready=False, detail="service not started")
        return HealthStatus(status="healthy", ready=True)

    async def authorize(self, request: DecisionRequest) -> Decision:
        engine = await self._engine_for(request.resource.tenant_id)
        return await engine.authorize(request)

    async def evaluate_compliance(
        self, resource: dict[str, Any], *, tenant_id: str | None
    ) -> ComplianceResult:
        engine = await self._engine_for(tenant_id)
        return await engine.evaluate_compliance(resource, tenant_id=tenant_id)

    def explain(self, decision: Decision) -> dict[str, object]:
        return PolicyEngine().explain(decision)

    async def _engine_for(self, tenant_id: str | None) -> PolicyEngine:
        policies = await self.store.list(tenant_id=tenant_id)
        return PolicyEngine(policies)

    async def _check_available(self) -> None:
        policies = await self.store.list(tenant_id=None)
        for policy in policies:
            Policy.model_validate(policy.model_dump(mode="json"))


class PolicyWorkflowAdapter:
    def __init__(self, policy_engine: PolicyEngineService) -> None:
        self._policy_engine = policy_engine

    async def authorize_step(
        self,
        *,
        step: Step,
        spec: ActionSpec,
        run: Run,
        actor: ActorRef,
        source_finding: Finding | None = None,
    ) -> StepAuthorization:
        request = DecisionRequest(
            subject=actor,
            action=spec.capability,
            resource=DecisionResource(
                id=run.source_finding_id or run.playbook_id,
                type=spec.action_type,
                tenant_id=run.tenant_id,
                attributes={
                    "run_id": run.id,
                    "playbook_id": run.playbook_id,
                    "playbook_version": run.playbook_version,
                    "step_id": step.id,
                    "action_type": step.action_type,
                    "capability": spec.capability,
                    "effect": spec.effect,
                    "reversible": spec.reversible,
                    "inputs": step.inputs,
                    "source_finding_id": run.source_finding_id,
                    "has_source_finding": source_finding is not None,
                },
            ),
            context={"workflow": "execute"},
        )
        decision = await self._policy_engine.authorize(request)
        if decision.effect == "deny":
            raise UnauthorizedAction(decision.reason)
        return StepAuthorization(
            granted_capabilities=frozenset({spec.capability}),
            requires_approval=_decision_requires_approval(decision),
            reason=decision.reason,
        )


def _decision_requires_approval(decision: Decision) -> bool:
    return decision.effect == "require_approval" or any(
        obligation.type == "require_approval" for obligation in decision.obligations
    )
