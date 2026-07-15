"""R4 acceptance tests for trigger bounds and approval routing."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.evidence import InMemoryEvidenceStore
from aqelyn.findings import Automation, Finding, Remediation
from aqelyn.policy import Decision, DecisionRequest
from aqelyn.response import (
    AutomationTrigger,
    CampaignStore,
    InMemoryCampaignStore,
    InMemoryTriggerStore,
    PostgresCampaignStore,
    PostgresTriggerStore,
    ResponseOrchestrationEngine,
    TriggerStore,
)
from aqelyn.workflow import (
    ActionEffect,
    ActionSpec,
    InMemoryActionRegistry,
    InMemoryRunStore,
    Playbook,
    PostgresRunStore,
    Run,
    RunStore,
    Step,
    WorkflowEngine,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
SYS = ActorRef(actor_type="system", actor_id="response-r4-test")
NOW = datetime(2026, 7, 15, 20, 0, tzinfo=UTC)


@dataclass
class _ActionHandler:
    spec: ActionSpec
    executed: int = 0
    rolled_back: int = 0

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
        return {"inputs": dict(inputs), "tenant_id": tenant_id, "key": idempotency_key}

    async def rollback(self, rollback_ref: str, *, tenant_id: str | None) -> None:
        self.rolled_back += 1


class _WorkflowSpy:
    def __init__(self, inner: WorkflowEngine) -> None:
        self._inner = inner
        self.propose_calls: list[str] = []
        self.execute_calls: list[str] = []
        self.approve_calls = 0

    async def propose(
        self,
        playbook: Playbook,
        *,
        by: ActorRef,
        source_finding: Finding | None = None,
    ) -> Run:
        self.propose_calls.append(playbook.id)
        return await self._inner.propose(playbook, by=by, source_finding=source_finding)

    async def execute(self, run_id: str, *, by: ActorRef) -> Run:
        self.execute_calls.append(run_id)
        return await self._inner.execute(run_id, by=by)

    async def halt(self, run_id: str, *, by: ActorRef, reason: str) -> Run:
        return await self._inner.halt(run_id, by=by, reason=reason)


class _Resolver:
    def __init__(self, playbooks: dict[str, Playbook]) -> None:
        self._playbooks = playbooks

    async def resolve_playbook(self, playbook_id: str, *, tenant_id: str | None) -> Playbook:
        playbook = self._playbooks[playbook_id]
        return playbook.model_copy(update={"tenant_id": tenant_id}, deep=True)


class _PolicyStub:
    def __init__(self, effect: str) -> None:
        self.effect = effect
        self.requests: list[DecisionRequest] = []

    async def authorize(self, request: DecisionRequest) -> Decision:
        self.requests.append(request)
        return Decision(effect=self.effect, matched_rules=["pol-auto"], reason=self.effect)


@dataclass
class _Harness:
    campaign_store: CampaignStore
    trigger_store: TriggerStore
    run_store: RunStore
    workflow: _WorkflowSpy
    engine: ResponseOrchestrationEngine
    handler: _ActionHandler
    policy: _PolicyStub


def _handler(action_type: str, effect: ActionEffect = "read_only") -> _ActionHandler:
    return _ActionHandler(
        ActionSpec(
            action_type=action_type,
            capability=f"capability:{action_type}",
            effect=effect,
            reversible=effect == "reversible",
            description=f"{effect} response trigger action",
        )
    )


def _playbook(playbook_id: str, action_type: str) -> Playbook:
    return Playbook(
        id=playbook_id,
        version=1,
        name=f"Playbook {playbook_id}",
        description="R4 trigger playbook.",
        steps=[
            Step(
                id=f"{playbook_id}-step",
                action_type=action_type,
                inputs={"target": "asset-1"},
                idempotency_key=f"{playbook_id}:once",
            )
        ],
    )


def _trigger(*, condition: dict[str, object] | None = None) -> AutomationTrigger:
    return AutomationTrigger(
        tenant_id=None,
        name="Auto-start response",
        condition=condition or {"op": "eq", "attr": "finding.severity", "value": "high"},
        playbook_id="pb-triggered",
        max_effect="read_only",
        enabled=True,
    )


def _finding(
    *,
    eligibility: str = "automatic",
    requires_approval: bool = False,
    severity: str = "high",
) -> Finding:
    return Finding(
        id=new_id("fnd"),
        tenant_id=None,
        finding_type="response-r4",
        schema_version=1,
        dedup_key=new_id("fnd"),
        title="R4 finding",
        severity=severity,
        severity_score=8.0,
        what_happened="A triggerable condition was observed.",
        why_it_matters="It may require response orchestration.",
        how_determined="Synthetic R4 fixture.",
        risk_of_inaction="The response could be delayed.",
        evidence_ids=[new_id("evd")],
        affected_object_ids=[new_id("obj")],
        remediation=Remediation(
            summary="Review response.",
            steps=["Run approved playbook"],
            difficulty="low",
            expected_outcome="Response is coordinated safely.",
        ),
        automation=Automation(
            eligibility=eligibility,
            action_ref="response.auto_start",
            requires_approval=requires_approval,
            risk_note="R4 test gate.",
        ),
        confidence=0.9,
        source_engine="response-r4-test",
        first_detected_at=NOW,
        last_detected_at=NOW,
    )


async def _postgres_campaign_store() -> PostgresCampaignStore:
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresCampaignStore.connect(PG_URL, mode="local")
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_response_campaign RESTART IDENTITY")
    return store


async def _postgres_trigger_store() -> PostgresTriggerStore:
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresTriggerStore.connect(PG_URL, mode="local")
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_response_trigger RESTART IDENTITY")
    return store


async def _postgres_run_store() -> PostgresRunStore:
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresRunStore.connect(PG_URL, mode="local")
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_workflow_run RESTART IDENTITY")
    return store


async def _harness(
    kind: str,
    *,
    policy_effect: str = "permit",
) -> AsyncIterator[_Harness]:
    if kind == "inmemory":
        campaign_store: CampaignStore = InMemoryCampaignStore()
        trigger_store: TriggerStore = InMemoryTriggerStore()
        run_store: RunStore = InMemoryRunStore()
        close_campaign = close_trigger = close_run = False
    else:
        campaign_store = await _postgres_campaign_store()
        trigger_store = await _postgres_trigger_store()
        run_store = await _postgres_run_store()
        close_campaign = close_trigger = close_run = True

    handler = _handler("response.collect-context")
    registry = InMemoryActionRegistry()
    registry.register(handler)
    workflow = _WorkflowSpy(
        WorkflowEngine(
            store=run_store,
            registry=registry,
            evidence_store=InMemoryEvidenceStore(),
            granted_capabilities={handler.spec.capability},
        )
    )
    playbook = _playbook("pb-triggered", handler.spec.action_type)
    policy = _PolicyStub(policy_effect)
    try:
        yield _Harness(
            campaign_store=campaign_store,
            trigger_store=trigger_store,
            run_store=run_store,
            workflow=workflow,
            engine=ResponseOrchestrationEngine(
                campaign_store=campaign_store,
                workflow=workflow,
                run_store=run_store,
                trigger_store=trigger_store,
                playbook_resolver=_Resolver({playbook.id: playbook}),
                policy_authorizer=policy,
                default_approval_route="response-duty-manager",
            ),
            handler=handler,
            policy=policy,
        )
    finally:
        if close_campaign and isinstance(campaign_store, PostgresCampaignStore):
            await campaign_store.close()
        if close_trigger and isinstance(trigger_store, PostgresTriggerStore):
            await trigger_store.close()
        if close_run and isinstance(run_store, PostgresRunStore):
            await run_store.close()


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_resp_trigger_bounded(kind: str) -> None:
    async for harness in _harness(kind):
        await harness.trigger_store.put(_trigger())

        started = await harness.engine.evaluate_triggers(
            tenant_id=None,
            findings=[_finding()],
            by=SYS,
        )

        assert len(started) == 1
        assert harness.workflow.propose_calls == ["pb-triggered"]
        assert len(harness.workflow.execute_calls) == 1
        assert harness.handler.executed == 1
        assert harness.engine.list_approval_requests() == []
        assert harness.policy.requests[0].action == "response.auto_start"


@pytest.mark.parametrize(
    ("eligibility", "requires_approval", "policy_effect"),
    [
        ("assisted", False, "permit"),
        ("automatic", True, "permit"),
        ("automatic", False, "deny"),
        ("automatic", False, "require_approval"),
    ],
)
async def test_resp_trigger_and_gate_routes_when_any_bound_fails(
    eligibility: str,
    requires_approval: bool,
    policy_effect: str,
) -> None:
    async for harness in _harness("inmemory", policy_effect=policy_effect):
        await harness.trigger_store.put(_trigger())

        started = await harness.engine.evaluate_triggers(
            tenant_id=None,
            findings=[
                _finding(eligibility=eligibility, requires_approval=requires_approval),
            ],
            by=SYS,
        )

        assert started == []
        assert harness.workflow.propose_calls == ["pb-triggered"]
        assert harness.workflow.execute_calls == []
        assert harness.handler.executed == 0
        requests = harness.engine.list_approval_requests()
        assert len(requests) == 1
        assert requests[0].status == "open"


def test_resp_routing_not_granting() -> None:
    handler = _handler("response.inspect")
    registry = InMemoryActionRegistry()
    registry.register(handler)
    workflow = _WorkflowSpy(
        WorkflowEngine(
            store=InMemoryRunStore(),
            registry=registry,
            evidence_store=InMemoryEvidenceStore(),
        )
    )
    engine = ResponseOrchestrationEngine(
        campaign_store=InMemoryCampaignStore(),
        workflow=workflow,
    )
    request = engine.route_approval(
        new_id("run"),
        step_ids=["step-1"],
        routed_to="tier-1",
        sla_seconds=60,
        escalate_to="tier-2",
        requested_at=NOW - timedelta(seconds=120),
    )

    assert request.status == "open"
    overdue = engine.escalate_overdue(now=NOW)
    assert [item.status for item in overdue] == ["escalated"]
    assert engine.list_approval_requests()[0].status == "escalated"
    assert workflow.approve_calls == 0
    assert all(item.status != "granted" for item in engine.list_approval_requests())


def test_resp_trigger_no_eval() -> None:
    response_root = Path("src/aqelyn/response")
    source = "\n".join(path.read_text() for path in response_root.glob("*.py"))
    banned = ("eval(", "exec(", "importlib", "__import__", "socket", "requests.", "httpx.")

    assert not any(token in source for token in banned)
