"""Workflow Engine (EA-0008)."""

from aqelyn.workflow.gating import (
    VALID_AUTOMATION_ELIGIBILITY,
    ensure_playbook_may_execute,
    ensure_step_may_execute,
    gate_playbook,
    gate_step,
)
from aqelyn.workflow.models import (
    ActionEffect,
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
from aqelyn.workflow.registry import (
    ActionHandler,
    ActionRegistry,
    InMemoryActionRegistry,
    ReadOnlyEchoHandler,
)

__all__ = [
    "VALID_AUTOMATION_ELIGIBILITY",
    "ActionEffect",
    "ActionHandler",
    "ActionRegistry",
    "ActionSpec",
    "Approval",
    "InMemoryActionRegistry",
    "PlannedAction",
    "Playbook",
    "ReadOnlyEchoHandler",
    "Run",
    "RunStatus",
    "SimulationResult",
    "Step",
    "StepResult",
    "ensure_playbook_may_execute",
    "ensure_step_may_execute",
    "gate_playbook",
    "gate_step",
]
