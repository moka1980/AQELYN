"""R2 acceptance tests for response stores and campaign planning."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from aqelyn.conventions import ActorRef, is_valid, new_id
from aqelyn.conventions.errors import (
    OptimisticConcurrencyConflict,
    ResponseConfigInvalid,
    TenantScopeRequired,
)
from aqelyn.evidence import InMemoryEvidenceStore
from aqelyn.policy import Condition
from aqelyn.response import (
    AutomationTrigger,
    CampaignStore,
    InMemoryCampaignStore,
    InMemoryTriggerStore,
    Phase,
    PostgresCampaignStore,
    PostgresTriggerStore,
    ResponseCampaign,
    ResponseOrchestrationEngine,
    RunRef,
    TriggerStore,
    derive_campaign_status,
)
from aqelyn.workflow import (
    ActionEffect,
    ActionSpec,
    InMemoryActionRegistry,
    InMemoryRunStore,
    Playbook,
    PostgresRunStore,
    Run,
    RunStatus,
    RunStore,
    Step,
    WorkflowEngine,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
TENANT_A = "018f0000-0000-7000-8000-000000000181"
TENANT_B = "018f0000-0000-7000-8000-000000000182"
SYS = ActorRef(actor_type="system", actor_id="response-r2-test")
NOW = datetime(2026, 7, 15, 19, 0, tzinfo=UTC)


@dataclass
class _TrackingHandler:
    spec: ActionSpec
    simulated: int = 0
    executed: int = 0
    rolled_back: int = 0

    async def simulate(self, inputs: dict[str, Any], *, tenant_id: str | None) -> dict[str, Any]:
        self.simulated += 1
        return {"inputs": dict(inputs), "tenant_id": tenant_id}

    async def execute(
        self,
        inputs: dict[str, Any],
        *,
        tenant_id: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.executed += 1
        raise AssertionError("R2 planning must not execute workflow actions")

    async def rollback(self, rollback_ref: str, *, tenant_id: str | None) -> None:
        self.rolled_back += 1
        raise AssertionError("R2 planning must not rollback workflow actions")


@dataclass
class _PlanHarness:
    campaign_store: CampaignStore
    run_store: RunStore
    registry: InMemoryActionRegistry
    engine: ResponseOrchestrationEngine
    handlers: list[_TrackingHandler] = field(default_factory=list)


def _campaign(
    *,
    campaign_id: str = "",
    tenant_id: str | None = None,
    status: str = "planned",
    updated_at: datetime = NOW,
) -> ResponseCampaign:
    return ResponseCampaign.model_validate(
        {
            "id": campaign_id,
            "tenant_id": tenant_id,
            "incident_id": None,
            "source_finding_id": None,
            "phases": [
                Phase(
                    name="contain",
                    order=1,
                    run_refs=[
                        RunRef(
                            workflow_run_id=new_id("run"),
                            action_type="response.contain",
                            effect="read_only",
                            status="proposed",
                        )
                    ],
                )
            ],
            "status": status,
            "created_by": SYS,
            "created_at": NOW,
            "updated_at": updated_at,
            "evidence_ids": [new_id("evd")],
            "version": 1,
        }
    )


def _trigger(
    *,
    trigger_id: str = "",
    tenant_id: str | None = None,
    enabled: bool = True,
    max_effect: str = "read_only",
) -> AutomationTrigger:
    return AutomationTrigger(
        id=trigger_id,
        tenant_id=tenant_id,
        name="Start safe response",
        condition={"op": "exists", "attr": "finding.id"},
        playbook_id="pb-response-safe",
        max_effect=max_effect,
        enabled=enabled,
        version=1,
    )


def _playbook(playbook_id: str, action_type: str) -> Playbook:
    return Playbook(
        id=playbook_id,
        version=1,
        name=f"Playbook {playbook_id}",
        description="R2 planning test playbook.",
        steps=[
            Step(
                id=f"{playbook_id}-step",
                action_type=action_type,
                inputs={"target": "asset-1"},
                idempotency_key=f"{playbook_id}:once",
            )
        ],
    )


def _run(run_id: str, *, status: RunStatus = "proposed") -> Run:
    return Run(
        id=run_id,
        playbook_id="pb-status",
        playbook_version=1,
        tenant_id=None,
        status=status,
        created_by=SYS,
        created_at=NOW,
        updated_at=NOW,
        version=1,
    )


def _handler(action_type: str, effect: ActionEffect) -> _TrackingHandler:
    return _TrackingHandler(
        ActionSpec(
            action_type=action_type,
            capability=f"capability:{action_type}",
            effect=effect,
            reversible=effect == "reversible",
            description=f"{effect} response planning action",
        )
    )


async def _postgres_campaign_store(*, mode: str = "local") -> PostgresCampaignStore:
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresCampaignStore.connect(PG_URL, mode=mode)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_response_campaign RESTART IDENTITY")
    return store


async def _postgres_trigger_store(*, mode: str = "local") -> PostgresTriggerStore:
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresTriggerStore.connect(PG_URL, mode=mode)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_response_trigger RESTART IDENTITY")
    return store


async def _postgres_run_store(*, mode: str = "local") -> PostgresRunStore:
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresRunStore.connect(PG_URL, mode=mode)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_workflow_run RESTART IDENTITY")
    return store


async def _campaign_store(kind: str, *, mode: str = "local") -> AsyncIterator[CampaignStore]:
    if kind == "inmemory":
        yield InMemoryCampaignStore(mode=mode)
        return
    store = await _postgres_campaign_store(mode=mode)
    try:
        yield store
    finally:
        await store.close()


async def _trigger_store(kind: str, *, mode: str = "local") -> AsyncIterator[TriggerStore]:
    if kind == "inmemory":
        yield InMemoryTriggerStore(mode=mode)
        return
    store = await _postgres_trigger_store(mode=mode)
    try:
        yield store
    finally:
        await store.close()


async def _campaign_trigger_stores(
    kind: str,
    *,
    mode: str = "local",
) -> AsyncIterator[tuple[CampaignStore, TriggerStore]]:
    if kind == "inmemory":
        yield InMemoryCampaignStore(mode=mode), InMemoryTriggerStore(mode=mode)
        return
    campaign_store = await _postgres_campaign_store(mode=mode)
    trigger_store = await _postgres_trigger_store(mode=mode)
    try:
        yield campaign_store, trigger_store
    finally:
        await campaign_store.close()
        await trigger_store.close()


async def _run_store(kind: str) -> AsyncIterator[RunStore]:
    if kind == "inmemory":
        yield InMemoryRunStore()
        return
    store = await _postgres_run_store()
    try:
        yield store
    finally:
        await store.close()


async def _plan_harness(kind: str) -> AsyncIterator[_PlanHarness]:
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
    workflow = WorkflowEngine(
        store=run_store,
        registry=registry,
        evidence_store=InMemoryEvidenceStore(),
    )
    try:
        yield _PlanHarness(
            campaign_store=campaign_store,
            run_store=run_store,
            registry=registry,
            engine=ResponseOrchestrationEngine(
                campaign_store=campaign_store,
                workflow=workflow,
            ),
        )
    finally:
        if close_campaign and isinstance(campaign_store, PostgresCampaignStore):
            await campaign_store.close()
        if close_run and isinstance(run_store, PostgresRunStore):
            await run_store.close()


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_resp_campaign_contract(kind: str) -> None:
    async for store in _campaign_store(kind):
        created = await store.upsert(_campaign())

        assert is_valid(created.id, "rsp")
        assert created.version == 1

        loaded = await store.get(created.id)
        assert loaded is not None
        assert loaded.model_dump(mode="json") == created.model_dump(mode="json")
        assert loaded is not created
        loaded.phases[0].run_refs[0].status = "failed"
        reloaded = await store.get(created.id)
        assert reloaded is not None
        assert reloaded.model_dump(mode="json") == created.model_dump(mode="json")

        changed = created.model_copy(
            update={"status": "running", "updated_at": NOW + timedelta(minutes=1)},
            deep=True,
        )
        updated = await store.upsert(changed)
        assert updated.version == 2
        assert updated.created_at == created.created_at
        assert updated.updated_at >= changed.updated_at
        assert updated.status == "running"

        with pytest.raises(OptimisticConcurrencyConflict):
            await store.upsert(changed)

        await store.upsert(_campaign(status="completed", updated_at=NOW + timedelta(minutes=2)))
        rows = await store.query(tenant_id=None, status=["running"])
        assert [campaign.id for campaign in rows] == [updated.id]
        assert await store.get(new_id("rsp")) is None


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_resp_trigger_contract(kind: str) -> None:
    async for store in _trigger_store(kind):
        created = await store.put(_trigger())

        assert is_valid(created.id, "trg")
        assert created.version == 1

        disabled = await store.put(created.model_copy(update={"enabled": False}, deep=True))
        assert disabled.version == 2
        assert await store.list(tenant_id=None) == []
        all_rows = await store.list(tenant_id=None, enabled_only=False)
        assert [trigger.id for trigger in all_rows] == [disabled.id]

        with pytest.raises(OptimisticConcurrencyConflict):
            await store.put(created)

        bad_data: dict[str, Any] = {
            "id": "",
            "tenant_id": None,
            "name": "Bad destructive trigger",
            "condition": Condition.model_validate({"op": "exists", "attr": "finding.id"}),
            "playbook_id": "pb-destroy",
            "max_effect": "destructive",
            "enabled": True,
            "version": 1,
        }
        bad = AutomationTrigger.model_construct(**bad_data)
        with pytest.raises(ResponseConfigInvalid, match="max_effect"):
            await store.put(bad)


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_resp_tenant_isolation(kind: str) -> None:
    async for campaign_store, trigger_store in _campaign_trigger_stores(kind, mode="enterprise"):
        campaign_a = await campaign_store.upsert(_campaign(tenant_id=TENANT_A))
        campaign_b = await campaign_store.upsert(_campaign(tenant_id=TENANT_B))
        trigger_a = await trigger_store.put(_trigger(tenant_id=TENANT_A))
        trigger_b = await trigger_store.put(_trigger(tenant_id=TENANT_B))

        assert await campaign_store.get(campaign_a.id, tenant_id=TENANT_A) is not None
        assert await campaign_store.get(campaign_b.id, tenant_id=TENANT_A) is None
        rows_a = await campaign_store.query(tenant_id=TENANT_A)
        assert [campaign.id for campaign in rows_a] == [campaign_a.id]

        triggers_a = await trigger_store.list(tenant_id=TENANT_A)
        assert [trigger.id for trigger in triggers_a] == [trigger_a.id]
        assert trigger_b.id not in [trigger.id for trigger in triggers_a]

        with pytest.raises(TenantScopeRequired):
            await campaign_store.query(tenant_id=None)
        with pytest.raises(TenantScopeRequired):
            await trigger_store.list(tenant_id=None)


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_resp_plan_no_execution(kind: str) -> None:
    async for harness in _plan_harness(kind):
        contain = _handler("response.contain", "read_only")
        remediate = _handler("response.remediate", "reversible")
        harness.registry.register(contain)
        harness.registry.register(remediate)
        harness.handlers.extend([contain, remediate])

        campaign = await harness.engine.plan_campaign(
            incident_id=new_id("inc"),
            tenant_id=None,
            playbooks=[
                {
                    "playbook": _playbook("pb-contain", "response.contain"),
                    "phase": "contain",
                    "effect": "read_only",
                },
                {
                    "playbook": _playbook("pb-remediate", "response.remediate"),
                    "phase": "remediate",
                    "effect": "reversible",
                },
            ],
            by=SYS,
        )

        assert is_valid(campaign.id, "rsp")
        assert campaign.status == "planned"
        assert [phase.name for phase in campaign.phases] == ["contain", "remediate"]
        assert campaign.phases[1].depends_on == ["contain"]
        assert all(handler.executed == 0 for handler in harness.handlers)
        assert all(handler.rolled_back == 0 for handler in harness.handlers)

        runs = await harness.run_store.list()
        assert len(runs) == 2
        assert all(run.status == "proposed" for run in runs)
        assert sorted(
            ref.workflow_run_id for phase in campaign.phases for ref in phase.run_refs
        ) == sorted(run.id for run in runs)
        persisted = await harness.campaign_store.get(campaign.id)
        assert persisted is not None
        assert persisted.model_dump(mode="json") == campaign.model_dump(mode="json")


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_resp_status_derived(kind: str) -> None:
    async for run_store in _run_store(kind):
        first = await run_store.create(_run(new_id("run"), status="proposed"))
        second = await run_store.create(_run(new_id("run"), status="proposed"))
        stale = ResponseCampaign(
            id="",
            tenant_id=None,
            incident_id=None,
            source_finding_id=None,
            phases=[
                Phase(
                    name="contain",
                    order=1,
                    run_refs=[
                        RunRef(
                            workflow_run_id=first.id,
                            action_type="response.contain",
                            effect="read_only",
                            status="failed",
                        ),
                        RunRef(
                            workflow_run_id=second.id,
                            action_type="response.contain",
                            effect="read_only",
                            status="failed",
                        ),
                    ],
                    status="failed",
                )
            ],
            status="failed",
            created_by=SYS,
            created_at=NOW,
            updated_at=NOW,
        )

        planned = await derive_campaign_status(stale, run_store)
        assert planned.status == "planned"
        assert planned.phases[0].status == "pending"
        assert {ref.status for ref in planned.phases[0].run_refs} == {"proposed"}

        await run_store.update(
            first.model_copy(update={"status": "awaiting_approval"}, deep=True),
            expected_version=first.version,
        )
        awaiting = await derive_campaign_status(stale, run_store)
        assert awaiting.status == "awaiting_approval"
        assert awaiting.phases[0].status == "blocked"

        refreshed_first = await run_store.get(first.id)
        refreshed_second = await run_store.get(second.id)
        assert refreshed_first is not None
        assert refreshed_second is not None
        await run_store.update(
            refreshed_first.model_copy(update={"status": "completed"}, deep=True),
            expected_version=refreshed_first.version,
        )
        await run_store.update(
            refreshed_second.model_copy(update={"status": "completed"}, deep=True),
            expected_version=refreshed_second.version,
        )
        completed = await derive_campaign_status(stale, run_store)
        assert completed.status == "completed"
        assert completed.phases[0].status == "completed"
