"""W3 acceptance tests for Workflow Engine propose/simulate/approve."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from aqelyn.conventions import ActorRef
from aqelyn.conventions.errors import ConfirmationRequired, SchemaValidationError
from aqelyn.events import InMemoryEventBus
from aqelyn.events.registry import EventTypeRegistry
from aqelyn.evidence import InMemoryEvidenceStore
from aqelyn.workflow import (
    ActionEffect,
    ActionSpec,
    Approval,
    InMemoryActionRegistry,
    InMemoryRunStore,
    Playbook,
    PostgresRunStore,
    RunStore,
    Step,
    WorkflowEngine,
    register_workflow_events,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
SYS = ActorRef(actor_type="system", actor_id="workflow-w3-test")
HUMAN = ActorRef(actor_type="user", actor_id="workflow-w3-reviewer")


@dataclass
class _TrackingHandler:
    spec: ActionSpec
    simulated: list[dict[str, Any]] = field(default_factory=list)
    executed: int = 0

    async def simulate(self, inputs: dict[str, Any], *, tenant_id: str | None) -> dict[str, Any]:
        prediction = {"inputs": dict(inputs), "tenant_id": tenant_id, "effect": self.spec.effect}
        self.simulated.append(prediction)
        return prediction

    async def execute(
        self,
        inputs: dict[str, Any],
        *,
        tenant_id: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.executed += 1
        raise AssertionError("W3 simulate/propose/approve must not execute actions")

    async def rollback(self, rollback_ref: str, *, tenant_id: str | None) -> None:
        raise AssertionError("W3 must not rollback actions")


@dataclass
class _Harness:
    store: RunStore
    registry: InMemoryActionRegistry
    bus: InMemoryEventBus
    engine: WorkflowEngine


def _now() -> datetime:
    return datetime.now(UTC)


def _handler(
    action_type: str,
    effect: ActionEffect = "read_only",
    *,
    reversible: bool = False,
) -> _TrackingHandler:
    return _TrackingHandler(
        ActionSpec(
            action_type=action_type,
            capability=f"capability:{action_type}",
            effect=effect,
            reversible=reversible,
            description=f"{effect} workflow test action",
        )
    )


def _step(action_type: str, *, step_id: str) -> Step:
    return Step(
        id=step_id,
        action_type=action_type,
        inputs={"target": step_id},
        idempotency_key=f"{step_id}:once",
    )


def _playbook(*steps: Step) -> Playbook:
    return Playbook(
        id="pb-w3",
        version=1,
        name="W3 test playbook",
        description="Exercise propose, simulate, and approve.",
        steps=list(steps),
    )


def _approval(
    *step_ids: str, reason: str = "Approved", confirm_token: str | None = None
) -> Approval:
    return Approval(
        step_ids=list(step_ids),
        approver=HUMAN,
        reason=reason,
        confirm_token=confirm_token,
        at=_now(),
    )


async def _postgres_store() -> PostgresRunStore:
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresRunStore.connect(PG_URL, mode="local")
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_workflow_run RESTART IDENTITY")
    return store


async def _harness(kind: str) -> AsyncIterator[_Harness]:
    if kind == "inmemory":
        store: RunStore = InMemoryRunStore()
        close_store = False
    else:
        store = await _postgres_store()
        close_store = True

    registry = InMemoryActionRegistry()
    event_registry = EventTypeRegistry()
    register_workflow_events(event_registry)
    bus = InMemoryEventBus(registry=event_registry)
    try:
        yield _Harness(
            store=store,
            registry=registry,
            bus=bus,
            engine=WorkflowEngine(
                store=store,
                registry=registry,
                evidence_store=InMemoryEvidenceStore(),
                event_bus=bus,
            ),
        )
    finally:
        if close_store and isinstance(store, PostgresRunStore):
            await store.close()


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_wf_simulate_no_effect(kind: str) -> None:
    async for harness in _harness(kind):
        handler = _handler("workflow.read")
        harness.registry.register(handler)
        run = await harness.engine.propose(
            _playbook(_step("workflow.read", step_id="step-1")), by=SYS
        )

        result = await harness.engine.simulate(run.id)

        loaded = await harness.store.get(run.id)
        assert loaded is not None
        assert loaded.status == "simulated"
        assert result.safe_to_execute is True
        assert [action.step_id for action in result.planned] == ["step-1"]
        assert result.planned[0].predicted["inputs"] == {"target": "step-1"}
        assert handler.simulated == [
            {"inputs": {"target": "step-1"}, "tenant_id": None, "effect": "read_only"}
        ]
        assert handler.executed == 0
        assert loaded.results == []
        assert [event.event_type for event in harness.bus.log] == [
            "aqelyn.workflow.run_proposed",
            "aqelyn.workflow.run_simulated",
        ]


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_wf_approval_recorded(kind: str) -> None:
    async for harness in _harness(kind):
        handler = _handler("workflow.reversible", "reversible", reversible=True)
        harness.registry.register(handler)
        run = await harness.engine.propose(
            _playbook(_step("workflow.reversible", step_id="step-1")),
            by=SYS,
        )

        simulated = await harness.engine.simulate(run.id)
        assert simulated.safe_to_execute is False
        pending = await harness.store.get(run.id)
        assert pending is not None
        assert pending.status == "awaiting_approval"

        approval = _approval("step-1", reason="Reviewed blast radius")
        approved = await harness.engine.approve(run.id, approval)

        assert approved.status == "approved"
        assert len(approved.approvals) == 1
        assert approved.approvals[0].approver == HUMAN
        assert approved.approvals[0].step_ids == ["step-1"]
        assert approved.approvals[0].reason == "Reviewed blast radius"
        assert [event.event_type for event in harness.bus.log] == [
            "aqelyn.workflow.run_proposed",
            "aqelyn.workflow.run_simulated",
            "aqelyn.workflow.approval_granted",
        ]
        assert harness.bus.log[-1].payload["step_ids"] == ["step-1"]


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_wf_approval_scope(kind: str) -> None:
    async for harness in _harness(kind):
        first = _handler("workflow.first", "reversible", reversible=True)
        second = _handler("workflow.second", "destructive", reversible=False)
        harness.registry.register(first)
        harness.registry.register(second)
        run = await harness.engine.propose(
            _playbook(
                _step("workflow.first", step_id="step-1"),
                _step("workflow.second", step_id="step-2"),
            ),
            by=SYS,
        )

        partial = await harness.engine.approve(run.id, _approval("step-1"))

        assert partial.status == "awaiting_approval"
        assert [approval.step_ids for approval in partial.approvals] == [["step-1"]]
        simulated = await harness.engine.simulate(run.id)
        assert simulated.safe_to_execute is False

        with pytest.raises(SchemaValidationError):
            await harness.engine.approve(run.id, _approval("step-3"))

        with pytest.raises(ConfirmationRequired):
            await harness.engine.approve(run.id, _approval("step-2"))

        complete = await harness.engine.approve(
            run.id,
            _approval("step-2", confirm_token="CONFIRM-step-2"),
        )

        assert complete.status == "approved"
        assert [approval.step_ids for approval in complete.approvals] == [
            ["step-1"],
            ["step-2"],
        ]
