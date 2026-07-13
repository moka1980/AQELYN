"""W2 acceptance tests for Workflow Engine run persistence."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from aqelyn.conventions import ActorRef, new_id, parse_id
from aqelyn.conventions.errors import OptimisticConcurrencyConflict, TenantScopeRequired
from aqelyn.workflow import (
    Approval,
    InMemoryRunStore,
    PostgresRunStore,
    Run,
    RunStatus,
    RunStore,
    StepResult,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
SYS = ActorRef(actor_type="system", actor_id="workflow-store-test")
TENANT_A = "018f0000-0000-7000-8000-000000000001"
TENANT_B = "018f0000-0000-7000-8000-000000000002"


def _now() -> datetime:
    return datetime.now(UTC)


def _run(
    *,
    run_id: str = "",
    status: RunStatus = "proposed",
    tenant_id: str | None = None,
    source_finding_id: str | None = None,
    approvals: list[Approval] | None = None,
    results: list[StepResult] | None = None,
) -> Run:
    now = _now()
    return Run(
        id=run_id,
        playbook_id="pb-remediate",
        playbook_version=1,
        tenant_id=tenant_id,
        status=status,
        source_finding_id=source_finding_id,
        results=results or [],
        approvals=approvals or [],
        created_by=SYS,
        created_at=now,
        updated_at=now,
        version=1,
    )


def _approval(*step_ids: str) -> Approval:
    return Approval(
        step_ids=list(step_ids),
        approver=SYS,
        reason="Approved for W2 persistence test",
        confirm_token=None,
        at=_now(),
    )


def _result(step_id: str, *, status: str = "succeeded") -> StepResult:
    return StepResult(
        step_id=step_id,
        status=status,
        outcome={"ok": True, "step": step_id},
        evidence_id=new_id("evd"),
        rollback_ref=f"rollback:{step_id}",
    )


async def _postgres_store(*, mode: str = "local") -> PostgresRunStore:
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresRunStore.connect(PG_URL, mode=mode)
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_workflow_run RESTART IDENTITY")
    return store


async def _store(kind: str, *, mode: str = "local") -> AsyncIterator[RunStore]:
    if kind == "inmemory":
        yield InMemoryRunStore(mode=mode)
        return
    store = await _postgres_store(mode=mode)
    try:
        yield store
    finally:
        await store.close()


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_wf_runstore_contract(kind: str) -> None:
    async for store in _store(kind):
        created = await store.create(
            _run(
                source_finding_id=new_id("fnd"),
                approvals=[_approval("step-1")],
                results=[_result("step-1")],
            )
        )

        assert parse_id(created.id)[0] == "run"
        assert created.version == 1
        assert created.status == "proposed"

        loaded = await store.get(created.id)
        assert loaded is not None
        assert loaded.model_dump(mode="json") == created.model_dump(mode="json")
        assert loaded is not created
        loaded.results[0].outcome["mutated"] = True
        reloaded = await store.get(created.id)
        assert reloaded is not None
        assert reloaded.model_dump(mode="json") == created.model_dump(mode="json")

        changed = created.model_copy(
            update={
                "status": "simulated",
                "results": [*created.results, _result("step-2")],
            },
            deep=True,
        )
        updated = await store.update(changed, expected_version=created.version)

        assert updated.version == 2
        assert updated.status == "simulated"
        assert updated.created_at == created.created_at
        assert updated.updated_at >= created.updated_at
        assert [result.step_id for result in updated.results] == ["step-1", "step-2"]

        second = await store.create(_run(status="awaiting_approval"))
        rows = await store.list()
        assert [run.id for run in rows] == sorted([updated.id, second.id])
        assert await store.get(new_id("run")) is None


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_wf_optimistic_conflict(kind: str) -> None:
    async for store in _store(kind):
        created = await store.create(_run())
        first_update = created.model_copy(
            update={"status": "simulated"},
            deep=True,
        )
        await store.update(first_update, expected_version=created.version)

        stale_update = created.model_copy(update={"status": "failed"}, deep=True)
        with pytest.raises(OptimisticConcurrencyConflict):
            await store.update(stale_update, expected_version=created.version)


@pytest.mark.parametrize("kind", ["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def test_wf_tenant_isolation(kind: str) -> None:
    async for store in _store(kind, mode="enterprise"):
        run_a = await store.create(_run(tenant_id=TENANT_A))
        run_b = await store.create(_run(tenant_id=TENANT_B))

        assert await store.get(run_a.id, tenant_id=TENANT_A) is not None
        assert await store.get(run_b.id, tenant_id=TENANT_A) is None

        rows_a = await store.list(tenant_id=TENANT_A)
        assert [run.id for run in rows_a] == [run_a.id]
        assert run_b.id not in [run.id for run in rows_a]

        with pytest.raises(TenantScopeRequired):
            await store.list()
