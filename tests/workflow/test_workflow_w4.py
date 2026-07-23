"""W4 acceptance tests for Workflow Engine execution, evidence, failure, rollback."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from aqelyn.conventions import ActorRef
from aqelyn.conventions.errors import ActionFailed
from aqelyn.events import InMemoryEventBus
from aqelyn.events.registry import EventTypeRegistry
from aqelyn.evidence import EvidenceStore, InMemoryEvidenceStore
from aqelyn.evidence.postgres import PostgresEvidenceStore
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
SYS = ActorRef(actor_type="system", actor_id="workflow-w4-test")
HUMAN = ActorRef(actor_type="user", actor_id="workflow-w4-reviewer")


@dataclass
class _ActionHandler:
    spec: ActionSpec
    outcome: dict[str, Any] = field(default_factory=dict)
    delay_seconds: float = 0.0
    fail_message: str | None = None
    executed: int = 0
    rolled_back: list[str] = field(default_factory=list)

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
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.fail_message is not None:
            raise ActionFailed(self.fail_message)
        return {
            "inputs": dict(inputs),
            "tenant_id": tenant_id,
            "idempotency_key": idempotency_key,
            **self.outcome,
        }

    async def rollback(self, rollback_ref: str, *, tenant_id: str | None) -> None:
        self.rolled_back.append(rollback_ref)


@dataclass
class _Harness:
    run_store: RunStore
    evidence_store: EvidenceStore
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
    outcome: dict[str, Any] | None = None,
    delay_seconds: float = 0.0,
    fail_message: str | None = None,
) -> _ActionHandler:
    return _ActionHandler(
        spec=ActionSpec(
            action_type=action_type,
            capability=f"capability:{action_type}",
            effect=effect,
            reversible=reversible,
            description=f"{effect} workflow W4 test action",
        ),
        outcome=outcome or {},
        delay_seconds=delay_seconds,
        fail_message=fail_message,
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
        id="pb-w4",
        version=1,
        name="W4 test playbook",
        description="Exercise workflow execution.",
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


async def _postgres_run_store() -> PostgresRunStore:
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresRunStore.connect(PG_URL, mode="local")
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_workflow_run RESTART IDENTITY")
    return store


async def _postgres_evidence_store() -> PostgresEvidenceStore:
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresEvidenceStore.connect(PG_URL, mode="local")
    async with store._pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE aq_evidence_custody, aq_evidence_package, aq_evidence RESTART IDENTITY"
        )
    return store


async def _harness(
    kind: str,
    *,
    handlers: list[_ActionHandler],
    timeout_seconds: float = 30.0,
) -> AsyncIterator[_Harness]:
    if kind == "inmemory":
        run_store: RunStore = InMemoryRunStore()
        evidence_store: EvidenceStore = InMemoryEvidenceStore()
        close_run_store = False
        close_evidence_store = False
    else:
        run_store = await _postgres_run_store()
        evidence_store = await _postgres_evidence_store()
        close_run_store = True
        close_evidence_store = True

    registry = InMemoryActionRegistry()
    for handler in handlers:
        registry.register(handler)
    event_registry = EventTypeRegistry()
    register_workflow_events(event_registry)
    bus = InMemoryEventBus(registry=event_registry)
    capabilities = frozenset(handler.spec.capability for handler in handlers)
    try:
        yield _Harness(
            run_store=run_store,
            evidence_store=evidence_store,
            registry=registry,
            bus=bus,
            engine=WorkflowEngine(
                store=run_store,
                registry=registry,
                evidence_store=evidence_store,
                event_bus=bus,
                granted_capabilities=capabilities,
                step_timeout_seconds=timeout_seconds,
            ),
        )
    finally:
        if close_run_store and isinstance(run_store, PostgresRunStore):
            await run_store.close()
        if close_evidence_store and isinstance(evidence_store, PostgresEvidenceStore):
            await evidence_store.close()


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_wf_idempotent_step(kind: str) -> None:
    handler = _handler("workflow.read")
    async for harness in _harness(kind, handlers=[handler]):
        run = await harness.engine.propose(
            _playbook(_step("workflow.read", step_id="step-1")),
            by=SYS,
        )

        first = await harness.engine.execute(run.id, by=SYS)
        second = await harness.engine.execute(run.id, by=SYS)

        assert first.status == "completed"
        assert second.model_dump(mode="json") == first.model_dump(mode="json")
        assert handler.executed == 1
        assert [result.status for result in second.results] == ["succeeded"]


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_wf_action_evidenced(kind: str) -> None:
    handler = _handler("workflow.read", outcome={"changed": False})
    async for harness in _harness(kind, handlers=[handler]):
        run = await harness.engine.propose(
            _playbook(_step("workflow.read", step_id="step-1")),
            by=SYS,
        )

        completed = await harness.engine.execute(run.id, by=SYS)

        assert completed.status == "completed"
        assert len(completed.results) == 1
        evidence = await harness.evidence_store.get(completed.results[0].evidence_id, actor=SYS)
        assert evidence.evidence_type == "workflow.action"
        assert evidence.method == "workflow.execute/v1"
        assert evidence.content is not None
        assert evidence.content["run_id"] == run.id
        assert evidence.content["step_id"] == "step-1"
        assert evidence.content["status"] == "succeeded"
        assert [event.event_type for event in harness.bus.log] == [
            "aqelyn.workflow.run_proposed",
            "aqelyn.workflow.step_executed",
            "aqelyn.workflow.run_completed",
        ]
        assert harness.bus.log[1].payload["evidence_id"] == completed.results[0].evidence_id


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_wf_failure_stops(kind: str) -> None:
    first = _handler("workflow.first")
    second = _handler("workflow.second", fail_message="second step failed")
    third = _handler("workflow.third")
    async for harness in _harness(kind, handlers=[first, second, third]):
        run = await harness.engine.propose(
            _playbook(
                _step("workflow.first", step_id="step-1"),
                _step("workflow.second", step_id="step-2"),
                _step("workflow.third", step_id="step-3"),
            ),
            by=SYS,
        )

        failed = await harness.engine.execute(run.id, by=SYS)

        assert failed.status == "failed"
        assert [result.step_id for result in failed.results] == ["step-1", "step-2"]
        assert [result.status for result in failed.results] == ["succeeded", "failed"]
        assert failed.results[-1].error == "second step failed"
        assert first.executed == 1
        assert second.executed == 1
        assert third.executed == 0
        assert harness.bus.log[-1].event_type == "aqelyn.workflow.run_failed"
        evidence = await harness.evidence_store.get(failed.results[-1].evidence_id, actor=SYS)
        assert evidence.content is not None
        assert evidence.content["status"] == "failed"
        assert evidence.content["error"] == "second step failed"


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_wf_rollback(kind: str) -> None:
    reversible = _handler(
        "workflow.reversible",
        "reversible",
        reversible=True,
        outcome={"rollback_ref": "rollback:step-1"},
    )
    destructive = _handler("workflow.destructive", "destructive", reversible=False)
    async for harness in _harness(kind, handlers=[reversible, destructive]):
        run = await harness.engine.propose(
            _playbook(
                _step("workflow.reversible", step_id="step-1"),
                _step("workflow.destructive", step_id="step-2"),
            ),
            by=SYS,
        )
        await harness.engine.approve(run.id, _approval("step-1"))
        await harness.engine.approve(run.id, _approval("step-2", confirm_token="CONFIRM-step-2"))
        completed = await harness.engine.execute(run.id, by=SYS)

        rolled_back = await harness.engine.rollback(
            completed.id,
            by=SYS,
            approval=_approval("step-1", reason="Human approved the rollback."),
        )

        assert rolled_back.status == "halted"
        assert reversible.rolled_back == ["rollback:step-1"]
        assert destructive.rolled_back == []
        assert [result.status for result in rolled_back.results] == [
            "succeeded",
            "succeeded",
            "rollback_skipped",
            "rolled_back",
        ]
        rollback_evidence = await harness.evidence_store.get(
            rolled_back.results[-1].evidence_id, actor=SYS
        )
        assert rollback_evidence.method == "workflow.rollback/v1"
        assert rollback_evidence.content is not None
        assert rollback_evidence.content["status"] == "rolled_back"
        assert harness.bus.log[-1].event_type == "aqelyn.workflow.run_halted"


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_wf_step_timeout(kind: str) -> None:
    slow = _handler("workflow.slow", delay_seconds=0.05)
    after = _handler("workflow.after")
    async for harness in _harness(kind, handlers=[slow, after], timeout_seconds=0.01):
        run = await harness.engine.propose(
            _playbook(
                _step("workflow.slow", step_id="step-1"),
                _step("workflow.after", step_id="step-2"),
            ),
            by=SYS,
        )

        failed = await harness.engine.execute(run.id, by=SYS)

        assert failed.status == "failed"
        assert [result.step_id for result in failed.results] == ["step-1"]
        assert failed.results[0].status == "failed"
        assert "timed out" in (failed.results[0].error or "")
        assert slow.executed == 1
        assert after.executed == 0
        assert harness.bus.log[-1].event_type == "aqelyn.workflow.run_failed"


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_wf_halt(kind: str) -> None:
    handler = _handler("workflow.read")
    async for harness in _harness(kind, handlers=[handler]):
        run = await harness.engine.propose(
            _playbook(_step("workflow.read", step_id="step-1")),
            by=SYS,
        )

        halted = await harness.engine.halt(run.id, by=SYS, reason="operator requested halt")

        assert halted.status == "halted"
        assert handler.executed == 0
        assert harness.bus.log[-1].event_type == "aqelyn.workflow.run_halted"
        assert harness.bus.log[-1].payload["reason"] == "operator requested halt"
