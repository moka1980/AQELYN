"""C-033 K1 real-engine conformance tests for IS-036."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.conventions.errors import (
    ApprovalRequired,
    PhaseBlocked,
    UnauthorizedAction,
)
from aqelyn.evidence import InMemoryEvidenceStore
from aqelyn.findings import Automation, Finding, Remediation
from aqelyn.response import (
    InMemoryCampaignStore,
    PostgresCampaignStore,
    ResponseOrchestrationEngine,
)
from aqelyn.response.store import CampaignStore
from aqelyn.workflow import (
    ActionSpec,
    Approval,
    InMemoryActionRegistry,
    InMemoryRunStore,
    Playbook,
    PostgresRunStore,
    Run,
    RunStore,
    Step,
    StepAuthorization,
    WorkflowEngine,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
ROOT = Path(__file__).resolve().parents[2]
TENANT = "018f0000-0000-7000-8000-000000230600"
SYSTEM = ActorRef(actor_type="system", actor_id="is036-conformance")
HUMAN = ActorRef(actor_type="user", actor_id="is036-reviewer")


@dataclass
class _TrackingHandler:
    spec: ActionSpec
    simulated: int = 0
    executed: int = 0
    rolled_back: list[str] = field(default_factory=list)

    async def simulate(
        self,
        inputs: dict[str, Any],
        *,
        tenant_id: str | None,
    ) -> dict[str, Any]:
        self.simulated += 1
        return {"would_change": True, "tenant_id": tenant_id, "inputs": dict(inputs)}

    async def execute(
        self,
        inputs: dict[str, Any],
        *,
        tenant_id: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self.executed += 1
        return {
            "changed": True,
            "rollback_ref": f"rollback:{idempotency_key}",
            "tenant_id": tenant_id,
            "inputs": dict(inputs),
        }

    async def rollback(self, rollback_ref: str, *, tenant_id: str | None) -> None:
        self.rolled_back.append(rollback_ref)


class _DenyCompletedRunAuthorizer:
    async def authorize_step(
        self,
        *,
        step: Step,
        spec: ActionSpec,
        run: Run,
        actor: ActorRef,
        source_finding: Finding | None = None,
    ) -> StepAuthorization:
        granted = frozenset() if run.status == "completed" else frozenset({spec.capability})
        return StepAuthorization(granted_capabilities=granted)


@dataclass
class _Harness:
    workflow: WorkflowEngine
    response: ResponseOrchestrationEngine
    run_store: RunStore
    campaign_store: CampaignStore
    handler: _TrackingHandler
    tenant_id: str | None


def _playbook(tenant_id: str | None) -> Playbook:
    return Playbook(
        id="pb-is036-conformance",
        version=1,
        name="IS-036 conformance action",
        description="Exercise the shipped EA-0008 approval boundary.",
        tenant_id=tenant_id,
        steps=[
            Step(
                id="remediate",
                action_type="is036.remediate",
                inputs={"target_ref": "conformance-target"},
                idempotency_key="is036-remediate-once",
            )
        ],
    )


def _finding(tenant_id: str | None, *, eligibility: str) -> Finding:
    now = utc_now()
    return Finding(
        id=new_id("fnd"),
        tenant_id=tenant_id,
        finding_type="aqelyn.finding.is036.conformance",
        schema_version=1,
        dedup_key=new_id("fnd"),
        title="IS-036 conformance finding",
        severity="high",
        severity_score=80.0,
        what_happened="A remediation action was proposed.",
        why_it_matters="Execution must remain inside the EA-0008 human gate.",
        how_determined="C-033 K1 real-engine conformance exercise.",
        risk_of_inaction="An unsafe state remains until a human decides.",
        evidence_ids=[new_id("evd")],
        remediation=Remediation(
            summary="Review the proposed action.",
            steps=["Inspect the evidence and decide whether to approve this run."],
            difficulty="medium",
            expected_outcome="The action remains gated until a human decision.",
        ),
        automation=Automation(
            eligibility=eligibility,
            requires_approval=True,
            risk_note="IS-036 must not bypass the shipped workflow gate.",
        ),
        confidence=1.0,
        source_engine="is036-conformance",
        first_detected_at=now,
        last_detected_at=now,
    )


def _approval(*, approver: ActorRef = HUMAN, reason: str = "Human review complete") -> Approval:
    return Approval(
        step_ids=["remediate"],
        approver=approver,
        reason=reason,
        at=utc_now(),
    )


@asynccontextmanager
async def _harness(
    backend: str,
    tenant_mode: str,
    *,
    deny_completed_run: bool = False,
) -> AsyncIterator[_Harness]:
    tenant_id = None if tenant_mode == "local" else TENANT
    if backend == "memory":
        run_store: RunStore = InMemoryRunStore(mode=tenant_mode)
        campaign_store: CampaignStore = InMemoryCampaignStore(mode=tenant_mode)
        closeables: list[PostgresRunStore | PostgresCampaignStore] = []
    else:
        if not PG_URL:
            pytest.skip("AQELYN_DATABASE_URL not set")
        run_pg = await PostgresRunStore.connect(PG_URL, mode=tenant_mode)
        campaign_pg = await PostgresCampaignStore.connect(PG_URL, mode=tenant_mode)
        async with run_pg._pool.acquire() as conn:
            await conn.execute("TRUNCATE aq_workflow_run RESTART IDENTITY")
        async with campaign_pg._pool.acquire() as conn:
            await conn.execute("TRUNCATE aq_response_campaign RESTART IDENTITY")
        run_store = run_pg
        campaign_store = campaign_pg
        closeables = [campaign_pg, run_pg]

    handler = _TrackingHandler(
        spec=ActionSpec(
            action_type="is036.remediate",
            capability="cap:is036.remediate",
            effect="reversible",
            reversible=True,
            description="Reversible conformance action.",
        )
    )
    registry = InMemoryActionRegistry()
    registry.register(handler)
    workflow = WorkflowEngine(
        store=run_store,
        registry=registry,
        evidence_store=InMemoryEvidenceStore(mode=tenant_mode),
        granted_capabilities=frozenset({handler.spec.capability}),
        policy_authorizer=_DenyCompletedRunAuthorizer() if deny_completed_run else None,
    )
    response = ResponseOrchestrationEngine(
        campaign_store=campaign_store,
        workflow=workflow,
        run_store=run_store,
    )
    try:
        yield _Harness(
            workflow=workflow,
            response=response,
            run_store=run_store,
            campaign_store=campaign_store,
            handler=handler,
            tenant_id=tenant_id,
        )
    finally:
        for closeable in closeables:
            await closeable.close()


MATRIX = [
    pytest.param("memory", "local", id="memory-local"),
    pytest.param("memory", "enterprise", id="memory-enterprise"),
    pytest.param("postgres", "local", id="postgres-local"),
    pytest.param("postgres", "enterprise", id="postgres-enterprise"),
]


@pytest.mark.parametrize(("backend", "tenant_mode"), MATRIX)
async def test_is036_conformance_campaign_sequences_not_executes(
    backend: str,
    tenant_mode: str,
) -> None:
    async with _harness(backend, tenant_mode) as harness:
        finding = _finding(harness.tenant_id, eligibility="assisted")
        campaign = await harness.response.plan_campaign(
            incident_id=None,
            tenant_id=harness.tenant_id,
            playbooks=[
                {
                    "playbook": _playbook(harness.tenant_id),
                    "phase": "contain",
                    "effect": "reversible",
                }
            ],
            by=SYSTEM,
            source_finding=finding,
        )
        run_id = campaign.phases[0].run_refs[0].workflow_run_id

        assert harness.handler.executed == 0
        with pytest.raises(PhaseBlocked, match="blocked by Workflow refusal"):
            await harness.response.advance(
                campaign.id,
                by=SYSTEM,
                expected_version=campaign.version,
            )
        assert harness.handler.executed == 0

        blocked = await harness.campaign_store.get(
            campaign.id,
            tenant_id=harness.tenant_id,
        )
        assert blocked is not None
        assert blocked.status == "awaiting_approval"

        await harness.workflow.approve(run_id, _approval())
        completed = await harness.response.advance(
            campaign.id,
            by=SYSTEM,
            expected_version=blocked.version,
        )

        assert completed.status == "completed"
        assert harness.handler.executed == 1


@pytest.mark.parametrize(("backend", "tenant_mode"), MATRIX)
async def test_is036_conformance_gated_execution_after_approval(
    backend: str,
    tenant_mode: str,
) -> None:
    async with _harness(backend, tenant_mode) as harness:
        run = await harness.workflow.propose(_playbook(harness.tenant_id), by=SYSTEM)

        with pytest.raises(ApprovalRequired):
            await harness.workflow.execute(run.id, by=SYSTEM)
        assert harness.handler.executed == 0

        with pytest.raises(UnauthorizedAction, match="human user"):
            await harness.workflow.approve(run.id, _approval(approver=SYSTEM))
        assert harness.handler.executed == 0

        approved = await harness.workflow.approve(run.id, _approval())
        assert approved.status == "approved"
        completed = await harness.workflow.execute(run.id, by=SYSTEM)

        assert completed.status == "completed"
        assert completed.approvals[-1].approver == HUMAN
        assert harness.handler.executed == 1


@pytest.mark.parametrize(("backend", "tenant_mode"), MATRIX)
async def test_is036_conformance_eligibility_none_refused(
    backend: str,
    tenant_mode: str,
) -> None:
    async with _harness(backend, tenant_mode) as harness:
        finding = _finding(harness.tenant_id, eligibility="none")
        run = await harness.workflow.propose(
            _playbook(harness.tenant_id),
            by=SYSTEM,
            source_finding=finding,
        )
        approved = await harness.workflow.approve(run.id, _approval())

        assert approved.source_finding_id == finding.id
        with pytest.raises(UnauthorizedAction, match="eligibility 'none'"):
            await harness.workflow.execute(run.id, by=SYSTEM)
        assert harness.handler.executed == 0


@pytest.mark.parametrize(("backend", "tenant_mode"), MATRIX)
async def test_is036_conformance_source_finding_bound(
    backend: str,
    tenant_mode: str,
) -> None:
    async with _harness(backend, tenant_mode) as harness:
        finding = _finding(harness.tenant_id, eligibility="assisted")
        campaign = await harness.response.plan_campaign(
            incident_id=None,
            tenant_id=harness.tenant_id,
            playbooks=[_playbook(harness.tenant_id)],
            by=SYSTEM,
            source_finding=finding,
        )
        run_id = campaign.phases[0].run_refs[0].workflow_run_id
        run = await harness.run_store.get(run_id, tenant_id=harness.tenant_id)
        simulation = await harness.workflow.simulate(run_id)

        assert campaign.source_finding_id == finding.id
        assert run is not None
        assert run.source_finding_id == finding.id
        assert simulation.safe_to_execute is False
        assert simulation.planned[0].requires_approval is True
        assert harness.handler.executed == 0


@pytest.mark.parametrize(("backend", "tenant_mode"), MATRIX)
async def test_is036_conformance_rollback_requires_fresh_human_gate(
    backend: str,
    tenant_mode: str,
) -> None:
    async with _harness(backend, tenant_mode) as harness:
        run = await harness.workflow.propose(_playbook(harness.tenant_id), by=SYSTEM)
        execution_approval = _approval(reason="Human approved execution.")
        await harness.workflow.approve(run.id, execution_approval)
        completed = await harness.workflow.execute(run.id, by=SYSTEM)

        with pytest.raises(ApprovalRequired, match="fresh human approval"):
            await harness.workflow.rollback(completed.id, by=SYSTEM)
        with pytest.raises(UnauthorizedAction, match="human user"):
            await harness.workflow.rollback(
                completed.id,
                by=SYSTEM,
                approval=_approval(
                    approver=SYSTEM,
                    reason="A service attempted to approve rollback.",
                ),
            )
        with pytest.raises(ApprovalRequired, match="latest action result"):
            await harness.workflow.rollback(
                completed.id,
                by=SYSTEM,
                approval=execution_approval,
            )
        assert harness.handler.rolled_back == []

        rolled_back = await harness.workflow.rollback(
            completed.id,
            by=SYSTEM,
            approval=_approval(reason="Human approved this rollback."),
        )
        assert rolled_back.status == "halted"
        assert harness.handler.rolled_back == ["rollback:is036-remediate-once"]


@pytest.mark.parametrize(("backend", "tenant_mode"), MATRIX)
async def test_is036_conformance_rollback_rechecks_capability(
    backend: str,
    tenant_mode: str,
) -> None:
    async with _harness(backend, tenant_mode, deny_completed_run=True) as harness:
        run = await harness.workflow.propose(_playbook(harness.tenant_id), by=SYSTEM)
        await harness.workflow.approve(run.id, _approval(reason="Human approved execution."))
        completed = await harness.workflow.execute(run.id, by=SYSTEM)

        with pytest.raises(UnauthorizedAction, match="capability not granted"):
            await harness.workflow.rollback(
                completed.id,
                by=SYSTEM,
                approval=_approval(reason="Human approved this rollback."),
            )
        assert harness.handler.rolled_back == []


@pytest.mark.parametrize(("backend", "tenant_mode"), MATRIX)
def test_is036_conformance_eligibility_none_refused_dash_o(
    backend: str,
    tenant_mode: str,
) -> None:
    if backend == "postgres" and not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    env = os.environ.copy()
    src = str(ROOT / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [
            sys.executable,
            "-O",
            str(Path(__file__).resolve()),
            "--dash-o-probe",
            backend,
            tenant_mode,
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


async def _dash_o_probe(backend: str, tenant_mode: str) -> None:
    async with _harness(backend, tenant_mode) as harness:
        finding = _finding(harness.tenant_id, eligibility="none")
        run = await harness.workflow.propose(
            _playbook(harness.tenant_id),
            by=SYSTEM,
            source_finding=finding,
        )
        await harness.workflow.approve(run.id, _approval())
        try:
            await harness.workflow.execute(run.id, by=SYSTEM)
        except UnauthorizedAction as exc:
            if "eligibility 'none'" not in exc.message:
                raise RuntimeError(f"unexpected refusal: {exc.message}") from exc
        else:
            raise RuntimeError("eligibility-none execution was not refused")
        if harness.handler.executed != 0:
            raise RuntimeError("handler executed under assertion-stripped Python")


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "--dash-o-probe":
        raise SystemExit("usage: test_response_k1_conformance.py --dash-o-probe BACKEND MODE")
    asyncio.run(_dash_o_probe(sys.argv[2], sys.argv[3]))
