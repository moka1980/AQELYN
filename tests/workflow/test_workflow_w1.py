"""W1 acceptance tests for Workflow Engine safety and authorization gates."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import (
    ALL_ERROR_CODES,
    ApprovalRequired,
    ConfirmationRequired,
    UnauthorizedAction,
    UnknownAction,
)
from aqelyn.findings import Automation, Finding, Remediation
from aqelyn.workflow import (
    ActionEffect,
    ActionSpec,
    Approval,
    InMemoryActionRegistry,
    Playbook,
    ReadOnlyEchoHandler,
    Step,
    ensure_playbook_may_execute,
    ensure_step_may_execute,
    gate_playbook,
    gate_step,
)

SYS = ActorRef(actor_type="system", actor_id="workflow-test")


class _StaticHandler:
    def __init__(self, spec: ActionSpec) -> None:
        self.spec = spec

    async def simulate(self, inputs: dict[str, Any], *, tenant_id: str | None) -> dict[str, Any]:
        return {"inputs": dict(inputs), "tenant_id": tenant_id}

    async def execute(
        self,
        inputs: dict[str, Any],
        *,
        tenant_id: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        raise AssertionError("W1 tests must not execute action handlers")

    async def rollback(self, rollback_ref: str, *, tenant_id: str | None) -> None:
        return None


def _now() -> datetime:
    return datetime.now(UTC)


def _step(action_type: str = "workflow.echo", *, step_id: str = "step-1") -> Step:
    return Step(
        id=step_id,
        action_type=action_type,
        inputs={"target": "example"},
        idempotency_key=f"{step_id}-once",
    )


def _playbook(*steps: Step) -> Playbook:
    return Playbook(
        id="pb-remediate",
        version=1,
        name="Safe remediation",
        description="Exercise workflow safety gates",
        steps=list(steps) or [_step()],
        tenant_id=None,
    )


def _approval(
    *step_ids: str,
    reason: str = "Reviewed and approved",
    confirm_token: str | None = None,
) -> Approval:
    return Approval(
        step_ids=list(step_ids),
        approver=SYS,
        reason=reason,
        confirm_token=confirm_token,
        at=_now(),
    )


def _finding(eligibility: str, *, requires_approval: bool = True) -> Finding:
    now = _now()
    return Finding(
        id=new_id("fnd"),
        finding_type="aqelyn.finding.workflow.test",
        schema_version=1,
        dedup_key=new_id("fnd"),
        title="Workflow gate finding",
        severity="high",
        severity_score=75.0,
        what_happened="A workflow action was proposed.",
        why_it_matters="The workflow engine must not exceed automation eligibility.",
        how_determined="Workflow W1 acceptance test.",
        risk_of_inaction="Unsafe automation could run without authorization.",
        evidence_ids=[new_id("evd")],
        remediation=Remediation(
            summary="Review the proposed workflow.",
            steps=["Check authorization and approval gates."],
            difficulty="medium",
            expected_outcome="Unsafe execution is refused.",
        ),
        automation=Automation(
            eligibility=eligibility,
            requires_approval=requires_approval,
            risk_note="exercise workflow safety gates",
        ),
        confidence=1.0,
        source_engine="workflow-test",
        first_detected_at=now,
        last_detected_at=now,
    )


def _registry(*handlers: _StaticHandler | ReadOnlyEchoHandler) -> InMemoryActionRegistry:
    registry = InMemoryActionRegistry()
    for handler in handlers:
        registry.register(handler)
    return registry


def _handler(
    action_type: str, capability: str, effect: ActionEffect, *, reversible: bool
) -> _StaticHandler:
    return _StaticHandler(
        ActionSpec(
            action_type=action_type,
            capability=capability,
            effect=effect,
            reversible=reversible,
            description=f"{effect} test action",
        )
    )


def test_wf_deny_by_default() -> None:
    registry = _registry()
    with pytest.raises(UnknownAction):
        gate_playbook(_playbook(_step("workflow.missing")), registry)

    read_handler = ReadOnlyEchoHandler()
    registry.register(read_handler)
    with pytest.raises(UnauthorizedAction, match="capability not granted"):
        ensure_step_may_execute(
            _step(),
            registry,
            granted_capabilities=frozenset(),
        )

    ensure_step_may_execute(
        _step(),
        registry,
        granted_capabilities=frozenset({read_handler.spec.capability}),
    )
    assert "UnknownAction" in ALL_ERROR_CODES
    assert "UnauthorizedAction" in ALL_ERROR_CODES


def test_wf_gating_by_effect() -> None:
    read = ReadOnlyEchoHandler(action_type="workflow.read", capability="cap.read")
    reversible = _handler(
        "workflow.reversible",
        "cap.reversible",
        "reversible",
        reversible=True,
    )
    destructive = _handler(
        "workflow.destructive",
        "cap.destructive",
        "destructive",
        reversible=False,
    )

    assert gate_step(_step("workflow.read"), read.spec).requires_approval is False
    assert gate_step(_step("workflow.reversible"), reversible.spec).requires_approval is True
    assert gate_step(_step("workflow.destructive"), destructive.spec).requires_approval is True

    registry = _registry(read, reversible, destructive)
    with pytest.raises(ApprovalRequired):
        ensure_step_may_execute(
            _step("workflow.reversible"),
            registry,
            granted_capabilities=frozenset({"cap.reversible"}),
        )
    ensure_step_may_execute(
        _step("workflow.reversible"),
        registry,
        granted_capabilities=frozenset({"cap.reversible"}),
        approvals=[_approval("step-1")],
    )
    assert "ApprovalRequired" in ALL_ERROR_CODES


def test_wf_destructive_confirm() -> None:
    destructive = _handler(
        "workflow.destroy",
        "cap.destroy",
        "destructive",
        reversible=False,
    )
    registry = _registry(destructive)
    step = _step("workflow.destroy")

    with pytest.raises(ApprovalRequired):
        ensure_step_may_execute(
            step,
            registry,
            granted_capabilities=frozenset({"cap.destroy"}),
        )
    with pytest.raises(ConfirmationRequired):
        ensure_step_may_execute(
            step,
            registry,
            granted_capabilities=frozenset({"cap.destroy"}),
            approvals=[_approval("step-1")],
        )

    ensure_step_may_execute(
        step,
        registry,
        granted_capabilities=frozenset({"cap.destroy"}),
        approvals=[_approval("step-1", confirm_token="CONFIRM-step-1")],
    )
    assert "ConfirmationRequired" in ALL_ERROR_CODES


def test_wf_eligibility_none_no_exec() -> None:
    registry = _registry(ReadOnlyEchoHandler())
    finding = _finding("none", requires_approval=False)
    gated = gate_playbook(_playbook(), registry, source_finding=finding)

    assert gated.steps[0].requires_approval is True
    with pytest.raises(UnauthorizedAction, match="eligibility 'none'"):
        ensure_step_may_execute(
            gated.steps[0],
            registry,
            granted_capabilities=frozenset({"workflow.read"}),
            approvals=[_approval("step-1", confirm_token="CONFIRM-step-1")],
            source_finding=finding,
        )


def test_wf_eligibility_assisted() -> None:
    registry = _registry(ReadOnlyEchoHandler())
    finding = _finding("assisted", requires_approval=False)
    gated = gate_playbook(_playbook(), registry, source_finding=finding)

    assert gated.steps[0].requires_approval is True
    with pytest.raises(ApprovalRequired):
        ensure_playbook_may_execute(
            gated,
            registry,
            granted_capabilities=frozenset({"workflow.read"}),
            source_finding=finding,
        )
    ensure_playbook_may_execute(
        gated,
        registry,
        granted_capabilities=frozenset({"workflow.read"}),
        approvals=[_approval("step-1")],
        source_finding=finding,
    )


def test_wf_eligibility_automatic_scope() -> None:
    read = ReadOnlyEchoHandler(action_type="workflow.read", capability="cap.read")
    reversible = _handler("workflow.reversible", "cap.reversible", "reversible", reversible=True)
    destructive = _handler("workflow.destroy", "cap.destroy", "destructive", reversible=False)
    registry = _registry(read, reversible, destructive)
    automatic = _finding("automatic", requires_approval=False)

    read_step = gate_step(_step("workflow.read"), read.spec, source_finding=automatic)
    assert read_step.requires_approval is False
    ensure_step_may_execute(
        read_step,
        registry,
        granted_capabilities=frozenset({"cap.read"}),
        source_finding=automatic,
    )

    approval_required_finding = _finding("automatic", requires_approval=True)
    gated_read = gate_step(
        _step("workflow.read"),
        read.spec,
        source_finding=approval_required_finding,
    )
    assert gated_read.requires_approval is True

    reversible_step = gate_step(
        _step("workflow.reversible"),
        reversible.spec,
        source_finding=automatic,
    )
    assert reversible_step.requires_approval is True
    with pytest.raises(ApprovalRequired):
        ensure_step_may_execute(
            reversible_step,
            registry,
            granted_capabilities=frozenset({"cap.reversible"}),
            source_finding=automatic,
        )

    destructive_step = gate_step(_step("workflow.destroy"), destructive.spec)
    with pytest.raises(ConfirmationRequired):
        ensure_step_may_execute(
            destructive_step,
            registry,
            granted_capabilities=frozenset({"cap.destroy"}),
            approvals=[_approval("step-1")],
            source_finding=automatic,
        )


def test_wf_unknown_action_at_propose() -> None:
    registry = _registry(ReadOnlyEchoHandler())

    with pytest.raises(UnknownAction, match=r"workflow\.unregistered"):
        gate_playbook(_playbook(_step("workflow.unregistered")), registry)
