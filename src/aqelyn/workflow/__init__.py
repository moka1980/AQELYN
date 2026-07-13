"""Workflow Engine (EA-0008)."""

from aqelyn.workflow.engine import WORKFLOW_EVENTS, WorkflowEngine, register_workflow_events
from aqelyn.workflow.gating import (
    VALID_AUTOMATION_ELIGIBILITY,
    ensure_playbook_may_execute,
    ensure_step_may_execute,
    gate_playbook,
    gate_step,
)
from aqelyn.workflow.memory import InMemoryRunStore
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
from aqelyn.workflow.postgres import PostgresRunStore
from aqelyn.workflow.registry import (
    ActionHandler,
    ActionRegistry,
    InMemoryActionRegistry,
    ReadOnlyEchoHandler,
)
from aqelyn.workflow.store import RunStore, validate_run_id

__all__ = [
    "VALID_AUTOMATION_ELIGIBILITY",
    "WORKFLOW_EVENTS",
    "ActionEffect",
    "ActionHandler",
    "ActionRegistry",
    "ActionSpec",
    "Approval",
    "InMemoryActionRegistry",
    "InMemoryRunStore",
    "PlannedAction",
    "Playbook",
    "PostgresRunStore",
    "ReadOnlyEchoHandler",
    "Run",
    "RunStatus",
    "RunStore",
    "SimulationResult",
    "Step",
    "StepResult",
    "WorkflowEngine",
    "ensure_playbook_may_execute",
    "ensure_step_may_execute",
    "gate_playbook",
    "gate_step",
    "register_workflow_events",
    "validate_run_id",
]
