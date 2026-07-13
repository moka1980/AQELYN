"""Workflow safety and authorization gates (EA-0008 W1)."""

from __future__ import annotations

from collections.abc import Sequence, Set

from aqelyn.conventions.errors import (
    ApprovalRequired,
    ConfirmationRequired,
    SchemaValidationError,
    UnauthorizedAction,
)
from aqelyn.findings import Finding
from aqelyn.workflow.models import ActionSpec, Approval, Playbook, Step
from aqelyn.workflow.registry import ActionRegistry

AUTOMATION_NONE = "none"
AUTOMATION_ASSISTED = "assisted"
AUTOMATION_AUTOMATIC = "automatic"
VALID_AUTOMATION_ELIGIBILITY: frozenset[str] = frozenset(
    (AUTOMATION_NONE, AUTOMATION_ASSISTED, AUTOMATION_AUTOMATIC)
)


def gate_step(
    step: Step,
    spec: ActionSpec,
    *,
    source_finding: Finding | None = None,
) -> Step:
    requires_approval = step.requires_approval or spec.effect in ("reversible", "destructive")
    if source_finding is not None:
        eligibility = _eligibility(source_finding)
        if (
            eligibility in (AUTOMATION_NONE, AUTOMATION_ASSISTED)
            or source_finding.automation.requires_approval
        ):
            requires_approval = True
    return step.model_copy(update={"requires_approval": requires_approval}, deep=True)


def gate_playbook(
    playbook: Playbook,
    registry: ActionRegistry,
    *,
    source_finding: Finding | None = None,
) -> Playbook:
    gated_steps: list[Step] = []
    for step in playbook.steps:
        handler = registry.get(step.action_type)
        gated_steps.append(gate_step(step, handler.spec, source_finding=source_finding))
    return playbook.model_copy(update={"steps": gated_steps}, deep=True)


def ensure_step_may_execute(
    step: Step,
    registry: ActionRegistry,
    *,
    granted_capabilities: Set[str],
    approvals: Sequence[Approval] = (),
    source_finding: Finding | None = None,
) -> None:
    handler = registry.get(step.action_type)
    spec = handler.spec
    if spec.capability not in granted_capabilities:
        raise UnauthorizedAction(f"capability not granted: {spec.capability!r}")
    if source_finding is not None and _eligibility(source_finding) == AUTOMATION_NONE:
        raise UnauthorizedAction("finding automation eligibility 'none' blocks execution")

    gated_step = gate_step(step, spec, source_finding=source_finding)
    if not gated_step.requires_approval:
        return

    matching_approvals = _matching_approvals(gated_step.id, approvals)
    if not matching_approvals:
        raise ApprovalRequired(f"approval required for step: {gated_step.id!r}")
    if spec.effect == "destructive" and not _has_confirm_token(matching_approvals):
        raise ConfirmationRequired(f"confirm_token required for destructive step: {step.id!r}")


def ensure_playbook_may_execute(
    playbook: Playbook,
    registry: ActionRegistry,
    *,
    granted_capabilities: Set[str],
    approvals: Sequence[Approval] = (),
    source_finding: Finding | None = None,
) -> None:
    gated = gate_playbook(playbook, registry, source_finding=source_finding)
    for step in gated.steps:
        ensure_step_may_execute(
            step,
            registry,
            granted_capabilities=granted_capabilities,
            approvals=approvals,
            source_finding=source_finding,
        )


def _eligibility(finding: Finding) -> str:
    eligibility = finding.automation.eligibility
    if eligibility not in VALID_AUTOMATION_ELIGIBILITY:
        raise SchemaValidationError(
            "finding.automation.eligibility must be none, assisted, or automatic"
        )
    return eligibility


def _matching_approvals(step_id: str, approvals: Sequence[Approval]) -> list[Approval]:
    return [approval for approval in approvals if step_id in approval.step_ids]


def _has_confirm_token(approvals: Sequence[Approval]) -> bool:
    return any(
        approval.confirm_token is not None and bool(approval.confirm_token.strip())
        for approval in approvals
    )
