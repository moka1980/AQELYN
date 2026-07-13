"""W5 acceptance tests for WorkflowEngineService lifecycle wiring."""

from __future__ import annotations

import os

import pytest

from aqelyn.conventions import ActorRef
from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime, create_runtime
from aqelyn.workflow import (
    InMemoryRunStore,
    Playbook,
    PostgresRunStore,
    ReadOnlyEchoHandler,
    Step,
    WorkflowEngine,
)
from aqelyn.workflow.service import WorkflowEngineService

PG_URL = os.getenv("AQELYN_DATABASE_URL")
SYS = ActorRef(actor_type="system", actor_id="workflow-w5-test")


def _playbook() -> Playbook:
    return Playbook(
        id="pb-w5",
        version=1,
        name="W5 service playbook",
        description="Exercise workflow service wiring.",
        steps=[
            Step(
                id="step-1",
                action_type="workflow.w5.echo",
                inputs={"target": "service"},
                idempotency_key="workflow-w5-once",
            )
        ],
    )


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_wf_service_health(backend: str) -> None:
    if backend == "postgres" and not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    if backend == "memory":
        runtime = create_inmemory_runtime()
        assert isinstance(runtime.workflow_run_store, InMemoryRunStore)
    else:
        assert PG_URL is not None
        runtime = await create_runtime(AQELYNConfig(backend="postgres", database_url=PG_URL))
        assert isinstance(runtime.workflow_run_store, PostgresRunStore)
        async with runtime.workflow_run_store._pool.acquire() as conn:
            await conn.execute("TRUNCATE aq_workflow_run RESTART IDENTITY")

    runtime.workflow_action_registry.register(ReadOnlyEchoHandler(action_type="workflow.w5.echo"))
    service = runtime.kernel.get_service("workflow_engine")
    assert service.name == "workflow_engine"
    assert tuple(service.dependencies) == ("event_bus",)
    assert isinstance(runtime.workflow_engine, WorkflowEngine)
    assert isinstance(runtime.workflow_engine_service, WorkflowEngineService)
    assert runtime.workflow_engine_service.engine is runtime.workflow_engine

    pre_start = await service.health()
    assert pre_start.status == "degraded"
    assert pre_start.ready is False
    assert pre_start.dependencies["registry"] == "healthy"
    assert pre_start.dependencies["run_store"] == "healthy"
    assert pre_start.dependencies["evidence_store"] == "healthy"

    await runtime.kernel.start()
    try:
        state = await runtime.kernel.health()
        workflow_health = state.services["workflow_engine"]

        assert workflow_health.status == "healthy"
        assert workflow_health.ready is True
        assert workflow_health.dependencies["registry"] == "healthy"
        assert workflow_health.dependencies["run_store"] == "healthy"
        assert workflow_health.dependencies["evidence_store"] == "healthy"
        assert state.services["_kernel"].ready is True

        run = await runtime.workflow_engine.propose(_playbook(), by=SYS)
        simulated = await runtime.workflow_engine.simulate(run.id)
        loaded = await runtime.workflow_run_store.get(run.id)

        assert simulated.safe_to_execute is True
        assert [planned.step_id for planned in simulated.planned] == ["step-1"]
        assert loaded is not None
        assert loaded.status == "simulated"
        assert any(
            event.event_type == "aqelyn.workflow.run_simulated" for event in runtime.event_bus.log
        )
        evidence_events = [
            event
            for event in runtime.event_bus.log
            if event.event_type == "aqelyn.evidence.recorded"
        ]
        assert len(evidence_events) == 1
        assert evidence_events[0].payload["evidence_type"] == "workflow.action"
    finally:
        await runtime.kernel.stop()
