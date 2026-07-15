"""R3 acceptance tests for response advance/halt through Workflow only."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import ActionFailed, PhaseBlocked
from aqelyn.evidence import InMemoryEvidenceStore
from aqelyn.findings import Finding
from aqelyn.response import (
    CampaignStore,
    InMemoryCampaignStore,
    PostgresCampaignStore,
    ResponseOrchestrationEngine,
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
SYS = ActorRef(actor_type="system", actor_id="response-r3-test")


@dataclass
class _ActionHandler:
    spec: ActionSpec
    fail_message: str | None = None
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
        if self.fail_message is not None:
            raise ActionFailed(self.fail_message)
        return {"inputs": dict(inputs), "tenant_id": tenant_id, "idempotency_key": idempotency_key}

    async def rollback(self, rollback_ref: str, *, tenant_id: str | None) -> None:
        self.rolled_back += 1


class _WorkflowSpy:
    def __init__(self, inner: WorkflowEngine) -> None:
        self._inner = inner
        self.propose_calls: list[str] = []
        self.execute_calls: list[str] = []
        self.halt_calls: list[str] = []

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
        self.halt_calls.append(run_id)
        return await self._inner.halt(run_id, by=by, reason=reason)


@dataclass
class _Harness:
    campaign_store: CampaignStore
    run_store: RunStore
    registry: InMemoryActionRegistry
    workflow: _WorkflowSpy
    engine: ResponseOrchestrationEngine
    handlers: dict[str, _ActionHandler] = field(default_factory=dict)


def _handler(
    action_type: str,
    effect: ActionEffect = "read_only",
    *,
    fail_message: str | None = None,
) -> _ActionHandler:
    return _ActionHandler(
        spec=ActionSpec(
            action_type=action_type,
            capability=f"capability:{action_type}",
            effect=effect,
            reversible=effect == "reversible",
            description=f"{effect} response R3 action",
        ),
        fail_message=fail_message,
    )


def _playbook(playbook_id: str, action_type: str) -> Playbook:
    return Playbook(
        id=playbook_id,
        version=1,
        name=f"Playbook {playbook_id}",
        description="R3 response orchestration playbook.",
        steps=[
            Step(
                id=f"{playbook_id}-step",
                action_type=action_type,
                inputs={"target": "asset-1"},
                idempotency_key=f"{playbook_id}:once",
            )
        ],
    )


async def _postgres_campaign_store() -> PostgresCampaignStore:
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresCampaignStore.connect(PG_URL, mode="local")
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_response_campaign RESTART IDENTITY")
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
    handlers: list[_ActionHandler],
) -> AsyncIterator[_Harness]:
    if kind == "inmemory":
        campaign_store: CampaignStore = InMemoryCampaignStore()
        run_store: RunStore = InMemoryRunStore()
        close_campaign = False
        close_run = False
    else:
        campaign_store = await _postgres_campaign_store()
        run_store = await _postgres_run_store()
        close_campaign = True
        close_run = True

    registry = InMemoryActionRegistry()
    for handler in handlers:
        registry.register(handler)
    workflow = _WorkflowSpy(
        WorkflowEngine(
            store=run_store,
            registry=registry,
            evidence_store=InMemoryEvidenceStore(),
            granted_capabilities=frozenset(handler.spec.capability for handler in handlers),
        )
    )
    try:
        yield _Harness(
            campaign_store=campaign_store,
            run_store=run_store,
            registry=registry,
            workflow=workflow,
            engine=ResponseOrchestrationEngine(
                campaign_store=campaign_store,
                workflow=workflow,
                run_store=run_store,
            ),
            handlers={handler.spec.action_type: handler for handler in handlers},
        )
    finally:
        if close_campaign and isinstance(campaign_store, PostgresCampaignStore):
            await campaign_store.close()
        if close_run and isinstance(run_store, PostgresRunStore):
            await run_store.close()


async def _planned_campaign(
    harness: _Harness,
    playbooks: list[dict[str, object]],
) -> str:
    campaign = await harness.engine.plan_campaign(
        incident_id=new_id("inc"),
        tenant_id=None,
        playbooks=playbooks,
        by=SYS,
    )
    return campaign.id


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_resp_advance_via_workflow(kind: str) -> None:
    handler = _handler("response.contain")
    async for harness in _harness(kind, handlers=[handler]):
        campaign_id = await _planned_campaign(
            harness,
            [
                {
                    "playbook": _playbook("pb-contain", "response.contain"),
                    "phase": "contain",
                    "effect": "read_only",
                }
            ],
        )
        campaign = await harness.campaign_store.get(campaign_id)
        assert campaign is not None

        advanced = await harness.engine.advance(
            campaign.id,
            by=SYS,
            expected_version=campaign.version,
        )

        assert advanced.status == "completed"
        assert advanced.phases[0].status == "completed"
        assert harness.workflow.execute_calls == [advanced.phases[0].run_refs[0].workflow_run_id]
        assert handler.executed == 1
        loaded_run = await harness.run_store.get(advanced.phases[0].run_refs[0].workflow_run_id)
        assert loaded_run is not None
        assert loaded_run.status == "completed"


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_resp_refusal_blocks(kind: str) -> None:
    handler = _handler("response.remediate", "reversible")
    async for harness in _harness(kind, handlers=[handler]):
        campaign_id = await _planned_campaign(
            harness,
            [
                {
                    "playbook": _playbook("pb-remediate", "response.remediate"),
                    "phase": "remediate",
                    "effect": "reversible",
                }
            ],
        )
        campaign = await harness.campaign_store.get(campaign_id)
        assert campaign is not None

        with pytest.raises(PhaseBlocked) as caught:
            await harness.engine.advance(campaign.id, by=SYS, expected_version=campaign.version)

        assert caught.value.details["error_code"] == "ApprovalRequired"
        assert harness.workflow.execute_calls == [campaign.phases[0].run_refs[0].workflow_run_id]
        assert handler.executed == 0
        blocked = await harness.campaign_store.get(campaign.id)
        assert blocked is not None
        assert blocked.status == "awaiting_approval"
        assert blocked.phases[0].status == "blocked"
        run = await harness.run_store.get(campaign.phases[0].run_refs[0].workflow_run_id)
        assert run is not None
        assert run.status == "proposed"


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_resp_no_privileged_path(kind: str) -> None:
    handler = _handler("response.read")
    async for harness in _harness(kind, handlers=[handler]):
        campaign_id = await _planned_campaign(
            harness,
            [
                {
                    "playbook": _playbook("pb-read", "response.read"),
                    "phase": "contain",
                    "effect": "read_only",
                }
            ],
        )
        campaign = await harness.campaign_store.get(campaign_id)
        assert campaign is not None

        await harness.engine.advance(campaign.id, by=SYS, expected_version=campaign.version)

        assert harness.workflow.execute_calls == [campaign.phases[0].run_refs[0].workflow_run_id]
        source = (Path(__file__).resolve().parents[2] / "src" / "aqelyn" / "response").glob("*.py")
        response_source = "\n".join(path.read_text(encoding="utf-8") for path in source)
        assert "ActionHandler" not in response_source
        assert "registry.get" not in response_source
        assert "handler.execute" not in response_source
        assert "Approval(" not in response_source
        assert "Run(" not in response_source


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_resp_phase_ordering(kind: str) -> None:
    contain = _handler("response.contain")
    remediate = _handler("response.remediate")
    async for harness in _harness(kind, handlers=[contain, remediate]):
        campaign_id = await _planned_campaign(
            harness,
            [
                {
                    "playbook": _playbook("pb-contain", "response.contain"),
                    "phase": "contain",
                    "effect": "read_only",
                },
                {
                    "playbook": _playbook("pb-remediate", "response.remediate"),
                    "phase": "remediate",
                    "effect": "read_only",
                },
            ],
        )
        campaign = await harness.campaign_store.get(campaign_id)
        assert campaign is not None

        after_contain = await harness.engine.advance(
            campaign.id,
            by=SYS,
            expected_version=campaign.version,
        )

        assert after_contain.status == "running"
        assert [phase.status for phase in after_contain.phases] == ["completed", "pending"]
        assert contain.executed == 1
        assert remediate.executed == 0

        completed = await harness.engine.advance(
            after_contain.id,
            by=SYS,
            expected_version=after_contain.version,
        )

        assert completed.status == "completed"
        assert [phase.status for phase in completed.phases] == ["completed", "completed"]
        assert remediate.executed == 1


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_resp_failed_phase_blocks_dependents(kind: str) -> None:
    contain = _handler("response.contain", fail_message="containment failed")
    remediate = _handler("response.remediate")
    async for harness in _harness(kind, handlers=[contain, remediate]):
        campaign_id = await _planned_campaign(
            harness,
            [
                {
                    "playbook": _playbook("pb-contain", "response.contain"),
                    "phase": "contain",
                    "effect": "read_only",
                },
                {
                    "playbook": _playbook("pb-remediate", "response.remediate"),
                    "phase": "remediate",
                    "effect": "read_only",
                },
            ],
        )
        campaign = await harness.campaign_store.get(campaign_id)
        assert campaign is not None

        failed = await harness.engine.advance(
            campaign.id,
            by=SYS,
            expected_version=campaign.version,
        )

        assert failed.status == "failed"
        assert [phase.status for phase in failed.phases] == ["failed", "blocked"]
        assert contain.executed == 1
        assert remediate.executed == 0
        second_attempt = await harness.engine.advance(
            failed.id,
            by=SYS,
            expected_version=failed.version,
        )
        assert second_attempt.model_dump(mode="json") == failed.model_dump(mode="json")


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_resp_halt(kind: str) -> None:
    contain = _handler("response.contain")
    remediate = _handler("response.remediate")
    async for harness in _harness(kind, handlers=[contain, remediate]):
        campaign_id = await _planned_campaign(
            harness,
            [
                {
                    "playbook": _playbook("pb-contain", "response.contain"),
                    "phase": "contain",
                    "effect": "read_only",
                },
                {
                    "playbook": _playbook("pb-remediate", "response.remediate"),
                    "phase": "remediate",
                    "effect": "read_only",
                },
            ],
        )
        campaign = await harness.campaign_store.get(campaign_id)
        assert campaign is not None

        halted = await harness.engine.halt_campaign(
            campaign.id,
            by=SYS,
            reason="Operator stopped the response campaign.",
            expected_version=campaign.version,
        )

        run_ids = [ref.workflow_run_id for phase in campaign.phases for ref in phase.run_refs]
        assert halted.status == "halted"
        assert sorted(harness.workflow.halt_calls) == sorted(run_ids)
        assert contain.executed == 0
        assert remediate.executed == 0
        runs = [await harness.run_store.get(run_id) for run_id in run_ids]
        assert all(run is not None and run.status == "halted" for run in runs)
