"""Response campaign planning and derived status helpers (EA-0018 R2)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.conventions.errors import (
    ApprovalRequired,
    CampaignNotFound,
    ConfirmationRequired,
    OptimisticConcurrencyConflict,
    PhaseBlocked,
    ResponseConfigInvalid,
    RunNotFound,
    StoreUnavailable,
    UnauthorizedAction,
)
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord, EvidenceStore
from aqelyn.findings import Finding
from aqelyn.findings.store import FindingStore
from aqelyn.response.approvals import (
    escalate_request,
    make_approval_request,
    request_is_overdue,
)
from aqelyn.response.metrics import IncidentReader, compute_metrics
from aqelyn.response.models import (
    ApprovalRequest,
    AutomationTrigger,
    CampaignStatus,
    Phase,
    PhaseName,
    PhaseStatus,
    RecoveryVerification,
    ResponseCampaign,
    ResponseConfig,
    ResponseMetrics,
    RunRef,
)
from aqelyn.response.recovery import (
    RecoveryAssessor,
    checks_verified,
    follow_up_playbook,
    recovery_finding,
    verification_result,
)
from aqelyn.response.store import CampaignStore, TriggerStore
from aqelyn.response.triggers import (
    PlaybookResolver,
    PolicyAuthorizer,
    build_trigger_decision_request,
    can_auto_start,
    trigger_matches,
)
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
        trigger_store: TriggerStore | None = None,
        playbook_resolver: PlaybookResolver | None = None,
        policy_authorizer: PolicyAuthorizer | None = None,
        default_approval_route: ActorRef | str = "response-approver",
        evidence_store: EvidenceStore | None = None,
        finding_store: FindingStore | None = None,
        recovery_assessor: RecoveryAssessor | None = None,
        incident_reader: IncidentReader | None = None,
        actor: ActorRef | None = None,
        source_id: str | None = None,
    ) -> None:
        self._campaign_store = campaign_store
        self._workflow = workflow
        self._run_store = run_store
        self._config = config or ResponseConfig()
        self._trigger_store = trigger_store
        self._playbook_resolver = playbook_resolver
        self._policy_authorizer = policy_authorizer
        self._default_approval_route = default_approval_route
        self._approval_routes: dict[str, ApprovalRequest] = {}
        self._approval_evidence: dict[str, str] = {}
        self._evidence_store = evidence_store
        self._finding_store = finding_store
        self._recovery_assessor = recovery_assessor
        self._incident_reader = incident_reader
        self._actor = actor or ActorRef(actor_type="system", actor_id="response_engine")
        self._source_id = source_id or new_id("src")

    @property
    def config(self) -> ResponseConfig:
        return self._config

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
        created = await self._campaign_store.upsert(campaign)
        evidence = await self._record_campaign_evidence(
            kind="campaign_planned",
            campaign=created,
            by=by,
            method="response.plan_campaign/v1",
            content={
                "incident_id": incident_id,
                "source_finding_id": created.source_finding_id,
                "phases": [phase.model_dump(mode="json") for phase in created.phases],
            },
        )
        with_evidence = self._append_campaign_evidence(created, evidence)
        if with_evidence is created:
            return created
        return await self._campaign_store.upsert(with_evidence)

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
                    update={
                        "status": _campaign_status(blocked.phases),
                        "updated_at": _updated_at(current),
                    },
                    deep=True,
                )
                evidence = await self._record_campaign_evidence(
                    kind="phase_blocked",
                    campaign=blocked,
                    by=by,
                    method="response.advance/v1",
                    content={
                        "phase": phase.name,
                        "workflow_run_id": ref.workflow_run_id,
                        "error_code": exc.code,
                        "reason": exc.message,
                    },
                )
                blocked = self._append_campaign_evidence(blocked, evidence)
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
            update={"updated_at": _updated_at(current)},
            deep=True,
        )
        advanced = advanced.model_copy(
            update={"status": _campaign_status(advanced.phases)},
            deep=True,
        )
        evidence = await self._record_campaign_evidence(
            kind="phase_advanced",
            campaign=advanced,
            by=by,
            method="response.advance/v1",
            content={
                "phase": phase.name,
                "run_refs": [ref.model_dump(mode="json") for ref in updated_refs],
            },
        )
        advanced = self._append_campaign_evidence(advanced, evidence)
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
                "updated_at": _updated_at(current),
            },
            deep=True,
        )
        return await self._campaign_store.upsert(halted)

    async def evaluate_triggers(
        self,
        *,
        tenant_id: str | None,
        findings: Sequence[Finding],
        by: ActorRef,
        approval_route: ActorRef | str | None = None,
    ) -> list[str]:
        if self._trigger_store is None:
            raise ResponseConfigInvalid("evaluate_triggers requires a TriggerStore")
        if self._playbook_resolver is None:
            raise ResponseConfigInvalid("evaluate_triggers requires a playbook resolver")

        started: list[str] = []
        triggers = await self._trigger_store.list(tenant_id=tenant_id, enabled_only=True)
        for trigger in triggers:
            for finding in findings:
                if not _same_tenant(tenant_id, trigger, finding):
                    continue
                if not trigger_matches(trigger, finding):
                    continue

                playbook = await self._playbook_resolver.resolve_playbook(
                    trigger.playbook_id,
                    tenant_id=trigger.tenant_id,
                )
                campaign = await self.plan_campaign(
                    incident_id=None,
                    tenant_id=trigger.tenant_id,
                    playbooks=[playbook],
                    by=by,
                    source_finding=finding,
                )
                trigger_evidence = await self._record_campaign_evidence(
                    kind="trigger_fired",
                    campaign=campaign,
                    by=by,
                    method="response.evaluate_triggers/v1",
                    content={
                        "trigger": trigger.model_dump(mode="json"),
                        "finding_id": finding.id,
                    },
                    finding_id=finding.id,
                )
                campaign = self._append_campaign_evidence(campaign, trigger_evidence)
                if trigger_evidence is not None:
                    campaign = await self._campaign_store.upsert(campaign)
                decision = None
                if self._policy_authorizer is not None:
                    decision = await self._policy_authorizer.authorize(
                        build_trigger_decision_request(
                            trigger=trigger,
                            finding=finding,
                            actor=by,
                        )
                    )

                if can_auto_start(trigger=trigger, finding=finding, decision=decision):
                    try:
                        await self.advance(campaign.id, by=by, expected_version=campaign.version)
                    except PhaseBlocked:
                        await self._route_campaign_for_approval(
                            campaign,
                            playbook=playbook,
                            routed_to=approval_route or self._default_approval_route,
                        )
                    else:
                        started.append(campaign.id)
                    continue

                await self._route_campaign_for_approval(
                    campaign,
                    playbook=playbook,
                    routed_to=approval_route or self._default_approval_route,
                )
        return started

    async def route_approval(
        self,
        workflow_run_id: str,
        *,
        step_ids: Sequence[str],
        routed_to: ActorRef | str,
        tenant_id: str | None = None,
        campaign_id: str | None = None,
        sla_seconds: int | None = None,
        escalate_to: ActorRef | str | None = None,
        requested_at: datetime | None = None,
    ) -> ApprovalRequest:
        request = make_approval_request(
            workflow_run_id=workflow_run_id,
            step_ids=step_ids,
            routed_to=routed_to,
            tenant_id=tenant_id,
            sla_seconds=sla_seconds or self._config.default_sla_seconds,
            escalate_to=escalate_to,
            requested_at=requested_at,
        )
        self._approval_routes[request.id] = request
        evidence = await self._record_evidence(
            kind="approval_routed",
            tenant_id=tenant_id,
            by=self._actor,
            method="response.route_approval/v1",
            content={
                "approval_request": request.model_dump(mode="json"),
                "campaign_id": campaign_id,
            },
        )
        if evidence is not None:
            self._approval_evidence[request.id] = evidence.id
        return request.model_copy(deep=True)

    async def escalate_overdue(
        self,
        *,
        tenant_id: str | None = None,
        now: datetime | None = None,
    ) -> list[ApprovalRequest]:
        escalated: list[ApprovalRequest] = []
        for request_id, request in list(self._approval_routes.items()):
            if tenant_id is not None and request.tenant_id != tenant_id:
                continue
            if request.status != "open" or not request_is_overdue(request, now=now):
                continue
            updated = escalate_request(request)
            self._approval_routes[request_id] = updated
            escalated.append(updated.model_copy(deep=True))
        return escalated

    def list_approval_requests(self, *, tenant_id: str | None = None) -> list[ApprovalRequest]:
        return [
            request.model_copy(deep=True)
            for request in self._approval_routes.values()
            if tenant_id is None or request.tenant_id == tenant_id
        ]

    async def verify_recovery(
        self,
        campaign_id: str,
        *,
        by: ActorRef,
    ) -> RecoveryVerification:
        if self._recovery_assessor is None:
            raise StoreUnavailable("verify_recovery requires a recovery assessor")
        if self._evidence_store is None:
            raise StoreUnavailable("verify_recovery requires an EvidenceStore")
        campaign = await self._require_campaign(campaign_id)
        current = await self._current_campaign(campaign)
        checks = await self._recovery_assessor.assess_recovery(current, by=by)
        verification = verification_result(current, checks)
        evidence = await self._record_campaign_evidence(
            kind="recovery_verification",
            campaign=current,
            by=by,
            method="response.verify_recovery/v1",
            content=verification.model_dump(mode="json"),
        )
        current = self._append_campaign_evidence(current, evidence)

        if not checks_verified(verification.checks):
            if self._finding_store is None:
                raise StoreUnavailable("unverified recovery requires a FindingStore")
            assert evidence is not None
            finding = await self._finding_store.raise_finding(
                recovery_finding(
                    current,
                    verification,
                    evidence_id=evidence.id,
                )
            )
            await self._workflow.propose(
                follow_up_playbook(current, finding),
                by=by,
                source_finding=finding,
            )
            verification = verification.model_copy(
                update={"reopened_finding_id": finding.id},
                deep=True,
            )

        await self._campaign_store.upsert(current)
        return verification

    async def metrics(self, *, tenant_id: str | None, since: datetime) -> ResponseMetrics:
        return await compute_metrics(
            campaign_store=self._campaign_store,
            run_store=self._run_store,
            incident_reader=self._incident_reader,
            tenant_id=tenant_id,
            since=since,
            limit=self._config.batch_size,
        )

    async def _route_campaign_for_approval(
        self,
        campaign: ResponseCampaign,
        *,
        playbook: Playbook,
        routed_to: ActorRef | str,
    ) -> ResponseCampaign:
        step_ids = _playbook_step_ids(playbook)
        evidence_ids: list[str] = []
        for phase in campaign.phases:
            for ref in phase.run_refs:
                request = await self.route_approval(
                    ref.workflow_run_id,
                    step_ids=step_ids,
                    routed_to=routed_to,
                    tenant_id=campaign.tenant_id,
                    campaign_id=campaign.id,
                )
                evidence_id = self._approval_evidence.get(request.id)
                if evidence_id is not None:
                    evidence_ids.append(evidence_id)
        if not evidence_ids:
            return campaign
        updated = self._append_campaign_evidence_ids(campaign, evidence_ids)
        return await self._campaign_store.upsert(updated)

    async def _record_campaign_evidence(
        self,
        *,
        kind: str,
        campaign: ResponseCampaign,
        by: ActorRef,
        method: str,
        content: dict[str, Any],
        finding_id: str | None = None,
    ) -> EvidenceRecord | None:
        return await self._record_evidence(
            kind=kind,
            tenant_id=campaign.tenant_id,
            by=by,
            method=method,
            content={"campaign_id": campaign.id, **content},
            finding_id=finding_id or campaign.source_finding_id,
        )

    async def _record_evidence(
        self,
        *,
        kind: str,
        tenant_id: str | None,
        by: ActorRef,
        method: str,
        content: dict[str, Any],
        finding_id: str | None = None,
    ) -> EvidenceRecord | None:
        if self._evidence_store is None:
            return None
        now = utc_now()
        record = EvidenceRecord(
            id="",
            tenant_id=tenant_id,
            evidence_type=f"response.{kind}",
            schema_version=1,
            subject=Subject(finding_id=finding_id),
            collected_at=now,
            recorded_at=now,
            collector=by,
            source_id=self._source_id,
            method=method,
            content=content,
            content_hash="",
            confidence=1.0,
            labels={"module": "EA-0018", "kind": kind},
            seq=0,
            prev_hash=None,
            record_hash="",
        )
        return await self._evidence_store.add(record)

    def _append_campaign_evidence(
        self,
        campaign: ResponseCampaign,
        evidence: EvidenceRecord | None,
    ) -> ResponseCampaign:
        if evidence is None:
            return campaign
        return self._append_campaign_evidence_ids(campaign, [evidence.id])

    def _append_campaign_evidence_ids(
        self,
        campaign: ResponseCampaign,
        evidence_ids: Sequence[str],
    ) -> ResponseCampaign:
        merged = list(dict.fromkeys([*campaign.evidence_ids, *evidence_ids]))
        return campaign.model_copy(
            update={"evidence_ids": merged, "updated_at": _updated_at(campaign)},
            deep=True,
        )

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


def _updated_at(campaign: ResponseCampaign) -> datetime:
    return max(utc_now(), campaign.created_at, campaign.updated_at)


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


def _playbook_step_ids(playbook: Playbook) -> list[str]:
    if not playbook.steps:
        raise ResponseConfigInvalid("playbook requires at least one step")
    return [step.id for step in playbook.steps]


def _same_tenant(
    tenant_id: str | None,
    trigger: AutomationTrigger,
    finding: Finding,
) -> bool:
    if tenant_id is not None and finding.tenant_id != tenant_id:
        return False
    return not (trigger.tenant_id is not None and finding.tenant_id != trigger.tenant_id)


def _nonempty(value: str, *, field: str) -> str:
    if not value.strip():
        raise ResponseConfigInvalid(f"{field} must not be empty")
    return value
