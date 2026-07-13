"""WorkflowEngine W3 orchestration: propose, simulate, approve."""

from __future__ import annotations

from typing import Any

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.conventions.errors import (
    ConfirmationRequired,
    CrossTenantReference,
    RunNotFound,
    SchemaValidationError,
)
from aqelyn.events import Event, EventBus, Subject
from aqelyn.events.registry import EventTypeRegistry
from aqelyn.findings import Finding
from aqelyn.workflow.gating import gate_playbook
from aqelyn.workflow.models import (
    Approval,
    PlannedAction,
    Playbook,
    Run,
    RunStatus,
    SimulationResult,
    Step,
)
from aqelyn.workflow.registry import ActionRegistry
from aqelyn.workflow.store import RunStore

WORKFLOW_EVENTS: dict[str, int] = {
    "aqelyn.workflow.run_proposed": 1,
    "aqelyn.workflow.run_simulated": 1,
    "aqelyn.workflow.approval_granted": 1,
    "aqelyn.workflow.step_executed": 1,
    "aqelyn.workflow.run_completed": 1,
    "aqelyn.workflow.run_failed": 1,
    "aqelyn.workflow.run_halted": 1,
}

SYSTEM_ACTOR = ActorRef(actor_type="system", actor_id="workflow_engine")


def register_workflow_events(registry: EventTypeRegistry) -> None:
    for event_type, schema_version in WORKFLOW_EVENTS.items():
        registry.register(event_type, schema_version, None)


class WorkflowEngine:
    def __init__(
        self,
        *,
        store: RunStore,
        registry: ActionRegistry,
        event_bus: EventBus | None = None,
    ) -> None:
        self._store = store
        self._registry = registry
        self._bus = event_bus
        self._playbooks: dict[str, Playbook] = {}

    async def propose(
        self,
        playbook: Playbook,
        *,
        by: ActorRef,
        source_finding: Finding | None = None,
    ) -> Run:
        tenant_id = _run_tenant(playbook, source_finding)
        scoped_playbook = playbook.model_copy(update={"tenant_id": tenant_id}, deep=True)
        gated = gate_playbook(scoped_playbook, self._registry, source_finding=source_finding)
        now = utc_now()
        created = await self._store.create(
            Run(
                id="",
                playbook_id=gated.id,
                playbook_version=gated.version,
                tenant_id=tenant_id,
                status="proposed",
                source_finding_id=source_finding.id if source_finding is not None else None,
                created_by=by,
                created_at=now,
                updated_at=now,
                version=1,
            )
        )
        self._playbooks[created.id] = gated
        await self._emit(
            "aqelyn.workflow.run_proposed",
            created,
            by,
            {
                "playbook_id": created.playbook_id,
                "playbook_version": created.playbook_version,
                "requires_approval": any(step.requires_approval for step in gated.steps),
            },
        )
        return created

    async def simulate(self, run_id: str) -> SimulationResult:
        run = await self._require_run(run_id)
        playbook = self._require_playbook(run.id)
        planned: list[PlannedAction] = []
        for step in playbook.steps:
            handler = self._registry.get(step.action_type)
            predicted = await handler.simulate(step.inputs, tenant_id=run.tenant_id)
            planned.append(
                PlannedAction(
                    step_id=step.id,
                    action_type=step.action_type,
                    effect=handler.spec.effect,
                    requires_approval=step.requires_approval,
                    predicted=predicted,
                )
            )

        safe_to_execute = self._approvals_cover_required_steps(playbook, run.approvals)
        updated = await self._store.update(
            run.model_copy(
                update={"status": _simulated_status(playbook, safe_to_execute, run.approvals)},
                deep=True,
            ),
            expected_version=run.version,
        )
        await self._emit(
            "aqelyn.workflow.run_simulated",
            updated,
            SYSTEM_ACTOR,
            {
                "planned_count": len(planned),
                "safe_to_execute": safe_to_execute,
                "status": updated.status,
            },
        )
        return SimulationResult(
            run_id=updated.id,
            planned=planned,
            safe_to_execute=safe_to_execute,
        )

    async def approve(self, run_id: str, approval: Approval) -> Run:
        run = await self._require_run(run_id)
        playbook = self._require_playbook(run.id)
        self._validate_approval_scope(playbook, approval)
        approvals = [*run.approvals, approval]
        updated = await self._store.update(
            run.model_copy(
                update={
                    "approvals": approvals,
                    "status": self._approval_status(playbook, approvals),
                },
                deep=True,
            ),
            expected_version=run.version,
        )
        await self._emit(
            "aqelyn.workflow.approval_granted",
            updated,
            approval.approver,
            {
                "step_ids": list(approval.step_ids),
                "status": updated.status,
            },
        )
        return updated

    async def get(self, run_id: str) -> Run | None:
        return await self._store.get(run_id)

    async def _require_run(self, run_id: str) -> Run:
        run = await self._store.get(run_id)
        if run is None:
            raise RunNotFound(run_id)
        return run

    def _require_playbook(self, run_id: str) -> Playbook:
        try:
            return self._playbooks[run_id]
        except KeyError as exc:
            raise RunNotFound(f"playbook snapshot missing for run: {run_id}") from exc

    async def _emit(
        self,
        event_type: str,
        run: Run,
        actor: ActorRef,
        payload: dict[str, Any],
    ) -> None:
        if self._bus is None:
            return
        now = utc_now()
        await self._bus.publish(
            Event(
                id=new_id("evt"),
                event_type=event_type,
                schema_version=1,
                tenant_id=run.tenant_id,
                occurred_at=now,
                recorded_at=now,
                producer=actor,
                subject=Subject(finding_id=run.source_finding_id),
                payload={"run_id": run.id, **payload},
                partition_key=run.id,
            )
        )

    def _approvals_cover_required_steps(
        self, playbook: Playbook, approvals: list[Approval]
    ) -> bool:
        for step in playbook.steps:
            if step.requires_approval and not self._approved(step, approvals):
                return False
        return True

    def _approved(self, step: Step, approvals: list[Approval]) -> bool:
        for approval in approvals:
            if step.id not in approval.step_ids:
                continue
            spec = self._registry.get(step.action_type).spec
            if spec.effect == "destructive" and not _has_confirm_token(approval):
                continue
            return True
        return False

    def _approval_status(self, playbook: Playbook, approvals: list[Approval]) -> RunStatus:
        if self._approvals_cover_required_steps(playbook, approvals):
            return "approved"
        return "awaiting_approval"

    def _validate_approval_scope(self, playbook: Playbook, approval: Approval) -> None:
        steps_by_id = {step.id: step for step in playbook.steps}
        unknown = [step_id for step_id in approval.step_ids if step_id not in steps_by_id]
        if unknown:
            raise SchemaValidationError(f"approval references unknown step ids: {unknown!r}")
        for step_id in approval.step_ids:
            step = steps_by_id[step_id]
            spec = self._registry.get(step.action_type).spec
            if spec.effect == "destructive" and not _has_confirm_token(approval):
                raise ConfirmationRequired(
                    f"confirm_token required for destructive step: {step.id!r}"
                )


def _run_tenant(playbook: Playbook, source_finding: Finding | None) -> str | None:
    if source_finding is None:
        return playbook.tenant_id
    if playbook.tenant_id is not None and playbook.tenant_id != source_finding.tenant_id:
        raise CrossTenantReference("playbook and source finding tenants differ")
    return playbook.tenant_id if playbook.tenant_id is not None else source_finding.tenant_id


def _required_step_ids(playbook: Playbook) -> set[str]:
    return {step.id for step in playbook.steps if step.requires_approval}


def _simulated_status(
    playbook: Playbook, safe_to_execute: bool, approvals: list[Approval]
) -> RunStatus:
    if not safe_to_execute:
        return "awaiting_approval"
    if _required_step_ids(playbook) and approvals:
        return "approved"
    return "simulated"


def _has_confirm_token(approval: Approval) -> bool:
    return approval.confirm_token is not None and bool(approval.confirm_token.strip())
