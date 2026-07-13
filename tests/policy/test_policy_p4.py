"""P4 acceptance tests for PolicyEngineService and Workflow integration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from aqelyn.conventions import ActorRef
from aqelyn.conventions.errors import ApprovalRequired, UnauthorizedAction
from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime, create_runtime
from aqelyn.policy import (
    Condition,
    InMemoryPolicyStore,
    Policy,
    PostgresPolicyStore,
    Rule,
    Target,
)
from aqelyn.policy.service import PolicyEngineService, PolicyWorkflowAdapter
from aqelyn.workflow import ActionEffect, ActionSpec, Approval, Playbook, Step

PG_URL = os.getenv("AQELYN_DATABASE_URL")
SYS = ActorRef(actor_type="system", actor_id="policy-p4-test")


@dataclass
class _Handler:
    spec: ActionSpec
    executed: int = 0
    outcomes: list[dict[str, Any]] = field(default_factory=list)

    async def simulate(self, inputs: dict[str, Any], *, tenant_id: str | None) -> dict[str, Any]:
        return {"inputs": dict(inputs), "tenant_id": tenant_id}

    async def execute(
        self,
        inputs: dict[str, Any],
        *,
        tenant_id: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.executed += 1
        outcome = {
            "inputs": dict(inputs),
            "tenant_id": tenant_id,
            "idempotency_key": idempotency_key,
        }
        self.outcomes.append(outcome)
        return outcome

    async def rollback(self, rollback_ref: str, *, tenant_id: str | None) -> None:
        return None


def _condition(payload: dict[str, object]) -> Condition:
    return Condition.model_validate(payload)


def _policy(
    policy_id: str,
    *,
    action: str,
    resource_type: str,
    effect: str,
    priority: int = 0,
) -> Policy:
    return Policy(
        id=policy_id,
        version=1,
        name=f"Policy {policy_id}",
        description="P4 workflow adapter policy",
        tenant_id=None,
        rules=[
            Rule(
                id=f"{policy_id}-rule",
                kind="authorization",
                description=f"{effect} {action}",
                target=Target(actions=[action], resource_types=[resource_type]),
                condition=_condition({"op": "eq", "attr": "resource.type", "value": resource_type}),
                effect=effect,
                obligations=[],
                priority=priority,
            )
        ],
        standard=None,
        set_by=SYS,
        set_at=datetime.now(UTC),
    )


def _handler(
    action_type: str,
    capability: str,
    effect: ActionEffect = "read_only",
    *,
    reversible: bool = False,
) -> _Handler:
    return _Handler(
        ActionSpec(
            action_type=action_type,
            capability=capability,
            effect=effect,
            reversible=reversible,
            description=f"{effect} P4 workflow action",
        )
    )


def _playbook(action_type: str, *, step_id: str) -> Playbook:
    return Playbook(
        id=f"pb-{step_id}",
        version=1,
        name=f"P4 playbook {step_id}",
        description="Exercise policy workflow adapter.",
        steps=[
            Step(
                id=step_id,
                action_type=action_type,
                inputs={"target": step_id},
                idempotency_key=f"{step_id}:once",
            )
        ],
    )


def _approval(step_id: str) -> Approval:
    return Approval(
        step_ids=[step_id],
        approver=SYS,
        reason="Approved by policy P4 test",
        at=datetime.now(UTC),
    )


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_policy_service_health(backend: str) -> None:
    if backend == "postgres" and not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    if backend == "memory":
        runtime = create_inmemory_runtime()
        assert isinstance(runtime.policy_store, InMemoryPolicyStore)
    else:
        assert PG_URL is not None
        runtime = await create_runtime(AQELYNConfig(backend="postgres", database_url=PG_URL))
        assert isinstance(runtime.policy_store, PostgresPolicyStore)
        async with runtime.policy_store._pool.acquire() as conn:
            await conn.execute("TRUNCATE aq_policy RESTART IDENTITY")

    service = runtime.kernel.get_service("policy_engine")
    workflow_service = runtime.kernel.get_service("workflow_engine")

    assert service.name == "policy_engine"
    assert tuple(service.dependencies) == ()
    assert isinstance(runtime.policy_engine_service, PolicyEngineService)
    assert isinstance(runtime.workflow_policy_adapter, PolicyWorkflowAdapter)
    assert tuple(workflow_service.dependencies) == ("event_bus", "policy_engine")
    assert runtime.event_bus.registry.is_registered("aqelyn.policy.updated")
    assert runtime.event_bus.registry.is_registered("aqelyn.policy.decision_denied")

    pre_start = await service.health()
    assert pre_start.status == "degraded"
    assert pre_start.ready is False

    await runtime.kernel.start()
    try:
        state = await runtime.kernel.health()
        policy_health = state.services["policy_engine"]

        assert policy_health.status == "healthy"
        assert policy_health.ready is True
        assert state.services["workflow_engine"].ready is True
        assert state.services["_kernel"].ready is True
    finally:
        await runtime.kernel.stop()


async def test_policy_workflow_adapter() -> None:
    runtime = create_inmemory_runtime()
    deny = _handler("workflow.policy.deny", "cap.policy.deny")
    approval = _handler("workflow.policy.approval", "cap.policy.approval")
    reversible = _handler(
        "workflow.policy.reversible",
        "cap.policy.reversible",
        "reversible",
        reversible=True,
    )
    runtime.workflow_action_registry.register(deny)
    runtime.workflow_action_registry.register(approval)
    runtime.workflow_action_registry.register(reversible)

    await runtime.policy_store.put(
        _policy(
            "policy-deny",
            action=deny.spec.capability,
            resource_type=deny.spec.action_type,
            effect="deny",
            priority=10,
        )
    )
    await runtime.policy_store.put(
        _policy(
            "policy-approval",
            action=approval.spec.capability,
            resource_type=approval.spec.action_type,
            effect="require_approval",
        )
    )
    await runtime.policy_store.put(
        _policy(
            "policy-permit-reversible",
            action=reversible.spec.capability,
            resource_type=reversible.spec.action_type,
            effect="permit",
        )
    )

    denied_run = await runtime.workflow_engine.propose(
        _playbook(deny.spec.action_type, step_id="deny-step"),
        by=SYS,
    )
    with pytest.raises(UnauthorizedAction):
        await runtime.workflow_engine.execute(denied_run.id, by=SYS)
    assert deny.executed == 0

    approval_run = await runtime.workflow_engine.propose(
        _playbook(approval.spec.action_type, step_id="approval-step"),
        by=SYS,
    )
    with pytest.raises(ApprovalRequired):
        await runtime.workflow_engine.execute(approval_run.id, by=SYS)
    approved = await runtime.workflow_engine.approve(
        approval_run.id,
        _approval("approval-step"),
    )
    completed = await runtime.workflow_engine.execute(approved.id, by=SYS)
    assert completed.status == "completed"
    assert approval.executed == 1

    reversible_run = await runtime.workflow_engine.propose(
        _playbook(reversible.spec.action_type, step_id="reversible-step"),
        by=SYS,
    )
    with pytest.raises(ApprovalRequired):
        await runtime.workflow_engine.execute(reversible_run.id, by=SYS)
    approved_reversible = await runtime.workflow_engine.approve(
        reversible_run.id,
        _approval("reversible-step"),
    )
    completed_reversible = await runtime.workflow_engine.execute(
        approved_reversible.id,
        by=SYS,
    )
    assert completed_reversible.status == "completed"
    assert reversible.executed == 1
