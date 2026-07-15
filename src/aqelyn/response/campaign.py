"""Response campaign planning and derived status helpers (EA-0018 R2)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from aqelyn.conventions import ActorRef, utc_now
from aqelyn.conventions.errors import (
    ApprovalRequired,
    CampaignNotFound,
    ConfirmationRequired,
    OptimisticConcurrencyConflict,
    PhaseBlocked,
    ResponseConfigInvalid,
    RunNotFound,
    UnauthorizedAction,
)
from aqelyn.findings import Finding
from aqelyn.response.models import (
    CampaignStatus,
    Phase,
    PhaseName,
    PhaseStatus,
    ResponseCampaign,
    ResponseConfig,
    RunRef,
)
from aqelyn.response.store import CampaignStore
from aqelyn.workflow.models import ActionEffect, Playbook, Run


class WorkflowProposer(Protocol):
    async def propose(
        self,
        playbook: Playbook,
        *,
        by: ActorRef,
        source_finding: Finding | None = None,
    ) -> Run: ...


class WorkflowController(WorkflowProposer, Protocol):
    async def execute(self, run_id: str, *, by: ActorRef) -> Run: ...

    async def halt(self, run_id: str, *, by: ActorRef, reason: str) -> Run: ...


class RunReader(Protocol):
    async def get(self, run_id: str, *, tenant_id: str | None = None) -> Run | None: ...


class ResponseOrchestrationEngine:
    """R2 campaign planner. Execution arrives in R3 and stays in EA-0008."""

    def __init__(
        self,
        *,
        campaign_store: CampaignStore,
        workflow: WorkflowController,
        run_store: RunReader | None = None,
        config: ResponseConfig | None = None,
    ) -> None:
        self._campaign_store = campaign_store
        self._workflow = workflow
        self._run_store = run_store
        self._config = config or ResponseConfig()

    async def plan_campaign(
        self,
        *,
        incident_id: str | None,
        tenant_id: str | None,
        playbooks: Sequence[Playbook | Mapping[str, Any]],
        by: ActorRef,
        source_finding: Finding | None = None,
    ) -> ResponseCampaign:
        if not playbooks:
            raise ResponseConfigInvalid("plan_campaign requires at least one playbook")

        phase_run_refs: dict[PhaseName, list[RunRef]] = {
            phase: [] for phase in self._config.phase_order
        }
        for item in playbooks:
            planned = _planned_playbook(item, allowed_phases=self._config.phase_order)
            run = await self._workflow.propose(
                planned.playbook,
                by=by,
                source_finding=source_finding,
            )
            phase_run_refs[planned.phase].append(
                RunRef(
                    workflow_run_id=run.id,
                    action_type=planned.action_type,
                    effect=planned.effect,
                    status=run.status,
                )
            )

        phases = _build_phases(self._config.phase_order, phase_run_refs)
        now = utc_now()
        campaign = ResponseCampaign(
            id="",
            tenant_id=tenant_id,
            incident_id=incident_id,
            source_finding_id=source_finding.id if source_finding is not None else None,
            phases=phases,
            status=_campaign_status(phases),
            created_by=by,
            created_at=now,
            updated_at=now,
            evidence_ids=[],
            version=1,
        )
        return await self._campaign_store.upsert(campaign)

    async def advance(
        self,
        campaign_id: str,
        *,
        by: ActorRef,
        expected_version: int,
    ) -> ResponseCampaign:
        campaign = await self._require_campaign(campaign_id)
        _ensure_expected_version(campaign, expected_version)
        current = await self._current_campaign(campaign)
        selected = _next_phase(current)
        if selected is None:
            return current

        phase = selected
        updated_refs: list[RunRef] = []
        for ref in phase.run_refs:
            try:
                run = await self._workflow.execute(ref.workflow_run_id, by=by)
            except (ApprovalRequired, ConfirmationRequired, UnauthorizedAction, RunNotFound) as exc:
                blocked = _replace_phase(
                    current,
                    phase.name,
                    phase.model_copy(
                        update={
                            "run_refs": [*updated_refs, ref, *_remaining_refs(phase, ref)],
                            "status": "blocked",
                        },
                        deep=True,
                    ),
                )
                blocked = blocked.model_copy(
                    update={"status": _campaign_status(blocked.phases), "updated_at": utc_now()},
                    deep=True,
                )
                await self._campaign_store.upsert(blocked)
                raise PhaseBlocked(
                    f"phase {phase.name!r} blocked by Workflow refusal",
                    details={
                        "campaign_id": current.id,
                        "phase": phase.name,
                        "workflow_run_id": ref.workflow_run_id,
                        "error_code": exc.code,
                        "reason": exc.message,
                    },
                ) from exc
            updated_refs.append(ref.model_copy(update={"status": run.status}, deep=True))

        advanced_phase = phase.model_copy(
            update={"run_refs": updated_refs, "status": _phase_status(updated_refs)},
            deep=True,
        )
        advanced = _replace_phase(current, phase.name, advanced_phase)
        advanced = _apply_dependency_blocks(advanced).model_copy(
            update={"updated_at": utc_now()},
            deep=True,
        )
        advanced = advanced.model_copy(
            update={"status": _campaign_status(advanced.phases)},
            deep=True,
        )
        return await self._campaign_store.upsert(advanced)

    async def halt_campaign(
        self,
        campaign_id: str,
        *,
        by: ActorRef,
        reason: str,
        expected_version: int,
    ) -> ResponseCampaign:
        _nonempty(reason, field="halt reason")
        campaign = await self._require_campaign(campaign_id)
        _ensure_expected_version(campaign, expected_version)
        current = await self._current_campaign(campaign)
        halted_phases: list[Phase] = []
        for phase in current.phases:
            halted_refs: list[RunRef] = []
            for ref in phase.run_refs:
                if ref.status in {"completed", "failed", "halted"}:
                    halted_refs.append(ref)
                    continue
                run = await self._workflow.halt(ref.workflow_run_id, by=by, reason=reason)
                halted_refs.append(ref.model_copy(update={"status": run.status}, deep=True))
            halted_phases.append(
                phase.model_copy(
                    update={"run_refs": halted_refs, "status": _phase_status(halted_refs)},
                    deep=True,
                )
            )
        halted = current.model_copy(
            update={
                "phases": halted_phases,
                "status": "halted",
                "updated_at": utc_now(),
            },
            deep=True,
        )
        return await self._campaign_store.upsert(halted)

    async def _require_campaign(self, campaign_id: str) -> ResponseCampaign:
        campaign = await self._campaign_store.get(campaign_id)
        if campaign is None:
            raise CampaignNotFound(campaign_id)
        return campaign

    async def _current_campaign(self, campaign: ResponseCampaign) -> ResponseCampaign:
        if self._run_store is None:
            return campaign
        return _apply_dependency_blocks(await derive_campaign_status(campaign, self._run_store))


async def derive_campaign_status(
    campaign: ResponseCampaign,
    run_store: RunReader,
) -> ResponseCampaign:
    refreshed_phases: list[Phase] = []
    for phase in campaign.phases:
        refreshed_refs: list[RunRef] = []
        for ref in phase.run_refs:
            run = await run_store.get(ref.workflow_run_id, tenant_id=campaign.tenant_id)
            refreshed_refs.append(
                ref.model_copy(update={"status": run.status if run is not None else ref.status})
            )
        refreshed_phase = phase.model_copy(
            update={
                "run_refs": refreshed_refs,
                "status": _phase_status(refreshed_refs),
            },
            deep=True,
        )
        refreshed_phases.append(refreshed_phase)
    return campaign.model_copy(
        update={
            "phases": refreshed_phases,
            "status": _campaign_status(refreshed_phases),
        },
        deep=True,
    )


class _PlannedPlaybook:
    def __init__(
        self,
        *,
        playbook: Playbook,
        phase: PhaseName,
        effect: ActionEffect,
        action_type: str,
    ) -> None:
        self.playbook = playbook
        self.phase = phase
        self.effect = effect
        self.action_type = action_type


def _planned_playbook(
    item: Playbook | Mapping[str, Any],
    *,
    allowed_phases: tuple[PhaseName, ...],
) -> _PlannedPlaybook:
    if isinstance(item, Playbook):
        playbook = item
        phase = allowed_phases[0]
        effect: ActionEffect = "read_only"
        action_type = _first_action_type(playbook)
        return _PlannedPlaybook(
            playbook=playbook,
            phase=phase,
            effect=effect,
            action_type=action_type,
        )

    raw_playbook = item.get("playbook", item)
    playbook = (
        raw_playbook
        if isinstance(raw_playbook, Playbook)
        else Playbook.model_validate(raw_playbook)
    )
    phase = _phase_name(item.get("phase", allowed_phases[0]), allowed_phases=allowed_phases)
    effect = _action_effect(item.get("effect", "read_only"))
    raw_action_type = item.get("action_type")
    action_type = (
        _nonempty(raw_action_type, field="action_type")
        if isinstance(raw_action_type, str)
        else _first_action_type(playbook)
    )
    return _PlannedPlaybook(
        playbook=playbook,
        phase=phase,
        effect=effect,
        action_type=action_type,
    )


def _build_phases(
    phase_order: tuple[PhaseName, ...],
    phase_run_refs: dict[PhaseName, list[RunRef]],
) -> list[Phase]:
    phases: list[Phase] = []
    included: list[PhaseName] = []
    for order, phase_name in enumerate(phase_order, start=1):
        run_refs = phase_run_refs.get(phase_name, [])
        if not run_refs:
            continue
        phases.append(
            Phase(
                name=phase_name,
                order=order,
                run_refs=run_refs,
                depends_on=[included[-1]] if included else [],
                status=_phase_status(run_refs),
            )
        )
        included.append(phase_name)
    if not phases:
        raise ResponseConfigInvalid("plan_campaign produced no phases")
    return phases


def _phase_status(run_refs: Sequence[RunRef]) -> PhaseStatus:
    if not run_refs:
        return "pending"
    statuses = {ref.status for ref in run_refs}
    if "failed" in statuses or "halted" in statuses:
        return "failed"
    if statuses <= {"completed"}:
        return "completed"
    if "running" in statuses:
        return "running"
    if "awaiting_approval" in statuses:
        return "blocked"
    return "pending"


def _campaign_status(phases: Sequence[Phase]) -> CampaignStatus:
    if not phases:
        return "planned"
    phase_statuses = {phase.status for phase in phases}
    if "failed" in phase_statuses:
        return "failed"
    if phase_statuses <= {"completed"}:
        return "completed"
    if "running" in phase_statuses:
        return "running"
    if "blocked" in phase_statuses:
        return "awaiting_approval"
    if "completed" in phase_statuses:
        return "running"
    return "planned"


def _next_phase(campaign: ResponseCampaign) -> Phase | None:
    phases = sorted(campaign.phases, key=lambda phase: phase.order)
    by_name = {phase.name: phase for phase in phases}
    for phase in phases:
        if phase.status in {"completed", "failed", "blocked"}:
            continue
        dependencies = [by_name[name] for name in phase.depends_on if name in by_name]
        dependencies_complete = all(dependency.status == "completed" for dependency in dependencies)
        if dependencies and not dependencies_complete:
            continue
        return phase
    return None


def _replace_phase(
    campaign: ResponseCampaign,
    phase_name: PhaseName,
    replacement: Phase,
) -> ResponseCampaign:
    return campaign.model_copy(
        update={
            "phases": [
                replacement if phase.name == phase_name else phase for phase in campaign.phases
            ]
        },
        deep=True,
    )


def _apply_dependency_blocks(campaign: ResponseCampaign) -> ResponseCampaign:
    phases = sorted(campaign.phases, key=lambda phase: phase.order)
    by_name = {phase.name: phase for phase in phases}
    updated: list[Phase] = []
    for phase in campaign.phases:
        dependencies = [by_name[name] for name in phase.depends_on if name in by_name]
        if (
            phase.status == "pending"
            and dependencies
            and any(dependency.status in {"failed", "blocked"} for dependency in dependencies)
        ):
            updated.append(phase.model_copy(update={"status": "blocked"}, deep=True))
        else:
            updated.append(phase)
    return campaign.model_copy(
        update={"phases": updated, "status": _campaign_status(updated)},
        deep=True,
    )


def _remaining_refs(phase: Phase, current: RunRef) -> list[RunRef]:
    seen = False
    remaining: list[RunRef] = []
    for ref in phase.run_refs:
        if seen:
            remaining.append(ref)
        elif ref.workflow_run_id == current.workflow_run_id:
            seen = True
    return remaining


def _ensure_expected_version(campaign: ResponseCampaign, expected_version: int) -> None:
    if expected_version < 1:
        raise ResponseConfigInvalid("expected_version must be >= 1")
    if campaign.version != expected_version:
        raise OptimisticConcurrencyConflict(
            f"expected v{expected_version}, found v{campaign.version}"
        )


def _phase_name(value: object, *, allowed_phases: tuple[PhaseName, ...]) -> PhaseName:
    if value not in allowed_phases:
        raise ResponseConfigInvalid(f"phase must be one of {', '.join(allowed_phases)}")
    return value


def _action_effect(value: object) -> ActionEffect:
    if value not in {"read_only", "reversible", "destructive"}:
        raise ResponseConfigInvalid("effect must be read_only, reversible, or destructive")
    return value


def _first_action_type(playbook: Playbook) -> str:
    if not playbook.steps:
        raise ResponseConfigInvalid("playbook requires at least one step")
    return playbook.steps[0].action_type


def _nonempty(value: str, *, field: str) -> str:
    if not value.strip():
        raise ResponseConfigInvalid(f"{field} must not be empty")
    return value
