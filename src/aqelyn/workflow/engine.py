"""WorkflowEngine orchestration (EA-0008 W3/W4)."""

from __future__ import annotations

import asyncio
from collections.abc import Set
from dataclasses import dataclass
from typing import Any, Protocol

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.conventions.errors import (
    ApprovalRequired,
    ConfirmationRequired,
    CrossTenantReference,
    RunNotFound,
    SchemaValidationError,
)
from aqelyn.events import Event, EventBus, Subject
from aqelyn.events.registry import EventTypeRegistry
from aqelyn.evidence import EvidenceRecord, EvidenceStore
from aqelyn.findings import Finding
from aqelyn.workflow.gating import ensure_step_may_execute, gate_playbook
from aqelyn.workflow.models import (
    ActionSpec,
    Approval,
    PlannedAction,
    Playbook,
    Run,
    RunStatus,
    SimulationResult,
    Step,
    StepResult,
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


@dataclass(frozen=True)
class StepAuthorization:
    granted_capabilities: frozenset[str]
    requires_approval: bool = False
    reason: str | None = None


class StepAuthorizer(Protocol):
    async def authorize_step(
        self,
        *,
        step: Step,
        spec: ActionSpec,
        run: Run,
        actor: ActorRef,
        source_finding: Finding | None = None,
    ) -> StepAuthorization: ...


def register_workflow_events(registry: EventTypeRegistry) -> None:
    for event_type, schema_version in WORKFLOW_EVENTS.items():
        registry.register(event_type, schema_version, None)


class WorkflowEngine:
    def __init__(
        self,
        *,
        store: RunStore,
        registry: ActionRegistry,
        evidence_store: EvidenceStore,
        event_bus: EventBus | None = None,
        granted_capabilities: Set[str] = frozenset(),
        policy_authorizer: StepAuthorizer | None = None,
        step_timeout_seconds: float = 30.0,
    ) -> None:
        if step_timeout_seconds <= 0:
            raise SchemaValidationError("step_timeout_seconds must be > 0")
        self._store = store
        self._registry = registry
        self._evidence_store = evidence_store
        self._bus = event_bus
        self._granted_capabilities = frozenset(granted_capabilities)
        self._policy_authorizer = policy_authorizer
        self._step_timeout_seconds = step_timeout_seconds
        self._playbooks: dict[str, Playbook] = {}
        self._source_findings: dict[str, Finding | None] = {}

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
        self._source_findings[created.id] = source_finding
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
            await self._record_action_evidence(
                run=run,
                step=step,
                actor=SYSTEM_ACTOR,
                method="workflow.simulate/v1",
                status="simulated",
                inputs=step.inputs,
                outcome=predicted,
            )
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

    async def execute(self, run_id: str, *, by: ActorRef) -> Run:
        run = await self._require_run(run_id)
        playbook = self._require_playbook(run.id)
        source_finding = self._source_findings.get(run.id)
        if run.status == "completed" and _all_steps_succeeded(playbook, run):
            return run

        for step in playbook.steps:
            if _step_succeeded(run, step.id):
                continue

            handler = self._registry.get(step.action_type)
            granted_capabilities = await self._granted_capabilities_for_step(
                step,
                handler.spec,
                run,
                by=by,
                source_finding=source_finding,
            )
            ensure_step_may_execute(
                step,
                self._registry,
                granted_capabilities=granted_capabilities,
                approvals=run.approvals,
                source_finding=source_finding,
            )
            try:
                outcome = await asyncio.wait_for(
                    handler.execute(
                        step.inputs,
                        tenant_id=run.tenant_id,
                        idempotency_key=step.idempotency_key,
                    ),
                    timeout=self._step_timeout_seconds,
                )
            except TimeoutError:
                return await self._fail_step(
                    run,
                    step,
                    by=by,
                    error=f"step timed out after {self._step_timeout_seconds:g}s",
                )
            except Exception as exc:
                return await self._fail_step(
                    run, step, by=by, error=str(exc) or exc.__class__.__name__
                )

            rollback_ref = _rollback_ref(outcome)
            evidence = await self._record_action_evidence(
                run=run,
                step=step,
                actor=by,
                method="workflow.execute/v1",
                status="succeeded",
                inputs=step.inputs,
                outcome=outcome,
                rollback_ref=rollback_ref,
            )
            result = StepResult(
                step_id=step.id,
                status="succeeded",
                outcome=outcome,
                evidence_id=evidence.id,
                rollback_ref=rollback_ref,
            )
            run = await self._store.update(
                run.model_copy(update={"results": [*run.results, result]}, deep=True),
                expected_version=run.version,
            )
            await self._emit_step_event(run, step, result, by)

        completed = await self._store.update(
            run.model_copy(update={"status": "completed"}, deep=True),
            expected_version=run.version,
        )
        await self._emit(
            "aqelyn.workflow.run_completed",
            completed,
            by,
            {"result_count": len(completed.results), "status": completed.status},
        )
        return completed

    async def halt(self, run_id: str, *, by: ActorRef, reason: str) -> Run:
        if not reason.strip():
            raise SchemaValidationError("halt reason must not be empty")
        run = await self._require_run(run_id)
        halted = await self._store.update(
            run.model_copy(update={"status": "halted"}, deep=True),
            expected_version=run.version,
        )
        await self._emit(
            "aqelyn.workflow.run_halted",
            halted,
            by,
            {"reason": reason, "status": halted.status},
        )
        return halted

    async def rollback(self, run_id: str, *, by: ActorRef) -> Run:
        run = await self._require_run(run_id)
        playbook = self._require_playbook(run.id)
        steps_by_id = {step.id: step for step in playbook.steps}
        rollback_results: list[StepResult] = []
        for result in reversed(run.results):
            if result.status != "succeeded":
                continue
            step = steps_by_id.get(result.step_id)
            if step is None:
                continue
            handler = self._registry.get(step.action_type)
            spec = handler.spec
            if spec.reversible and result.rollback_ref is not None:
                try:
                    await handler.rollback(result.rollback_ref, tenant_id=run.tenant_id)
                    status = "rolled_back"
                    error = None
                except Exception as exc:
                    status = "rollback_failed"
                    error = str(exc) or exc.__class__.__name__
            else:
                status = "rollback_skipped"
                error = "step is not reversible or has no rollback_ref"
            evidence = await self._record_action_evidence(
                run=run,
                step=step,
                actor=by,
                method="workflow.rollback/v1",
                status=status,
                inputs={"rollback_ref": result.rollback_ref},
                outcome={"source_evidence_id": result.evidence_id},
                error=error,
            )
            rollback_results.append(
                StepResult(
                    step_id=step.id,
                    status=status,
                    outcome={"source_evidence_id": result.evidence_id},
                    evidence_id=evidence.id,
                    error=error,
                )
            )

        halted = await self._store.update(
            run.model_copy(
                update={"results": [*run.results, *rollback_results], "status": "halted"},
                deep=True,
            ),
            expected_version=run.version,
        )
        await self._emit(
            "aqelyn.workflow.run_halted",
            halted,
            by,
            {
                "reason": "rollback",
                "rolled_back": sum(
                    1 for result in rollback_results if result.status == "rolled_back"
                ),
                "skipped": sum(
                    1 for result in rollback_results if result.status == "rollback_skipped"
                ),
                "failed": sum(
                    1 for result in rollback_results if result.status == "rollback_failed"
                ),
            },
        )
        return halted

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

    async def _granted_capabilities_for_step(
        self,
        step: Step,
        spec: ActionSpec,
        run: Run,
        *,
        by: ActorRef,
        source_finding: Finding | None,
    ) -> Set[str]:
        if self._policy_authorizer is None:
            return self._granted_capabilities

        authorization = await self._policy_authorizer.authorize_step(
            step=step,
            spec=spec,
            run=run,
            actor=by,
            source_finding=source_finding,
        )
        if authorization.requires_approval and not self._approved(step, run.approvals):
            raise ApprovalRequired(
                f"policy approval required for step: {step.id!r}; "
                f"{authorization.reason or 'policy requires approval'}"
            )
        return authorization.granted_capabilities

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

    async def _fail_step(self, run: Run, step: Step, *, by: ActorRef, error: str) -> Run:
        evidence = await self._record_action_evidence(
            run=run,
            step=step,
            actor=by,
            method="workflow.execute/v1",
            status="failed",
            inputs=step.inputs,
            outcome={},
            error=error,
        )
        result = StepResult(
            step_id=step.id,
            status="failed",
            outcome={},
            evidence_id=evidence.id,
            error=error,
        )
        failed = await self._store.update(
            run.model_copy(
                update={"results": [*run.results, result], "status": "failed"}, deep=True
            ),
            expected_version=run.version,
        )
        await self._emit_step_event(failed, step, result, by)
        await self._emit(
            "aqelyn.workflow.run_failed",
            failed,
            by,
            {"failed_step_id": step.id, "error": error, "status": failed.status},
        )
        return failed

    async def _emit_step_event(
        self, run: Run, step: Step, result: StepResult, actor: ActorRef
    ) -> None:
        await self._emit(
            "aqelyn.workflow.step_executed",
            run,
            actor,
            {
                "step_id": step.id,
                "action_type": step.action_type,
                "status": result.status,
                "evidence_id": result.evidence_id,
            },
        )

    async def _record_action_evidence(
        self,
        *,
        run: Run,
        step: Step,
        actor: ActorRef,
        method: str,
        status: str,
        inputs: dict[str, Any],
        outcome: dict[str, Any],
        rollback_ref: str | None = None,
        error: str | None = None,
    ) -> EvidenceRecord:
        now = utc_now()
        return await self._evidence_store.add(
            EvidenceRecord(
                id="",
                tenant_id=run.tenant_id,
                evidence_type="workflow.action",
                schema_version=1,
                subject=Subject(finding_id=run.source_finding_id),
                collected_at=now,
                recorded_at=now,
                collector=actor,
                source_id=new_id("src"),
                method=method,
                content={
                    "run_id": run.id,
                    "playbook_id": run.playbook_id,
                    "step_id": step.id,
                    "action_type": step.action_type,
                    "idempotency_key": step.idempotency_key,
                    "status": status,
                    "inputs": inputs,
                    "outcome": outcome,
                    "rollback_ref": rollback_ref,
                    "error": error,
                },
                content_hash="",
                labels={
                    "workflow.run_id": run.id,
                    "workflow.step_id": step.id,
                    "workflow.status": status,
                },
                seq=0,
                prev_hash=None,
                record_hash="",
            )
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


def _step_succeeded(run: Run, step_id: str) -> bool:
    return any(result.step_id == step_id and result.status == "succeeded" for result in run.results)


def _all_steps_succeeded(playbook: Playbook, run: Run) -> bool:
    succeeded = {result.step_id for result in run.results if result.status == "succeeded"}
    return all(step.id in succeeded for step in playbook.steps)


def _rollback_ref(outcome: dict[str, Any]) -> str | None:
    value = outcome.get("rollback_ref")
    if isinstance(value, str) and value.strip():
        return value
    return None
