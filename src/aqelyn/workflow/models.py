"""Workflow Engine models (EA-0008 W1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from aqelyn.conventions import ActorRef, require_tenant_id, require_typed_id
from aqelyn.conventions.errors import SchemaValidationError

ActionEffect = Literal["read_only", "reversible", "destructive"]
RunStatus = Literal[
    "proposed",
    "simulated",
    "awaiting_approval",
    "approved",
    "running",
    "completed",
    "failed",
    "halted",
]


def _require_nonempty(value: str, *, field: str) -> str:
    if not value.strip():
        raise SchemaValidationError(f"{field} must not be empty")
    return value


class ActionSpec(BaseModel):
    action_type: str
    capability: str
    effect: ActionEffect
    reversible: bool
    description: str

    @field_validator("action_type", "capability", "description")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        return _require_nonempty(value, field="workflow action field")

    @model_validator(mode="after")
    def _consistent_effect(self) -> ActionSpec:
        if self.effect == "read_only" and self.reversible:
            raise SchemaValidationError("read_only actions must not be marked reversible")
        if self.effect == "reversible" and not self.reversible:
            raise SchemaValidationError("reversible actions must set reversible=true")
        return self


class Step(BaseModel):
    id: str
    action_type: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str
    requires_approval: bool = False

    @field_validator("id", "action_type", "idempotency_key")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        return _require_nonempty(value, field="workflow step field")


class Playbook(BaseModel):
    id: str
    version: int
    name: str
    description: str
    steps: list[Step]
    tenant_id: str | None = None

    @field_validator("id", "name", "description")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        return _require_nonempty(value, field="playbook field")

    @field_validator("version")
    @classmethod
    def _version(cls, value: int) -> int:
        if isinstance(value, bool) or value < 1:
            raise SchemaValidationError("playbook version must be >= 1")
        return value

    @field_validator("steps")
    @classmethod
    def _steps(cls, values: list[Step]) -> list[Step]:
        if not values:
            raise SchemaValidationError("playbook requires at least one step")
        step_ids = [step.id for step in values]
        if len(step_ids) != len(set(step_ids)):
            raise SchemaValidationError("playbook step ids must be unique")
        return values

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)


class Approval(BaseModel):
    step_ids: list[str]
    approver: ActorRef
    reason: str
    confirm_token: str | None = None
    at: datetime

    @field_validator("step_ids")
    @classmethod
    def _step_ids(cls, values: list[str]) -> list[str]:
        if not values:
            raise SchemaValidationError("approval must name at least one step")
        if any(not value.strip() for value in values):
            raise SchemaValidationError("approval step ids must not be empty")
        if len(values) != len(set(values)):
            raise SchemaValidationError("approval step ids must be unique")
        return values

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return _require_nonempty(value, field="approval reason")

    @field_validator("confirm_token")
    @classmethod
    def _confirm_token(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise SchemaValidationError("confirm_token must be non-empty when present")
        return value


class StepResult(BaseModel):
    step_id: str
    status: str
    outcome: dict[str, Any] = Field(default_factory=dict)
    evidence_id: str
    rollback_ref: str | None = None
    error: str | None = None

    @field_validator("step_id", "status")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        return _require_nonempty(value, field="step result field")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")


class Run(BaseModel):
    id: str
    playbook_id: str
    playbook_version: int
    tenant_id: str | None = None
    status: RunStatus
    source_finding_id: str | None = None
    results: list[StepResult] = Field(default_factory=list)
    approvals: list[Approval] = Field(default_factory=list)
    created_by: ActorRef
    created_at: datetime
    updated_at: datetime
    version: int = 1

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "run", field="id", allow_empty=True)

    @field_validator("playbook_id")
    @classmethod
    def _playbook_id(cls, value: str) -> str:
        return _require_nonempty(value, field="playbook_id")

    @field_validator("playbook_version", "version")
    @classmethod
    def _positive_version(cls, value: int) -> int:
        if isinstance(value, bool) or value < 1:
            raise SchemaValidationError("run version fields must be >= 1")
        return value

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("source_finding_id")
    @classmethod
    def _source_finding_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "fnd", field="source_finding_id")


class PlannedAction(BaseModel):
    step_id: str
    action_type: str
    effect: ActionEffect
    requires_approval: bool
    predicted: dict[str, Any] = Field(default_factory=dict)

    @field_validator("step_id", "action_type")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        return _require_nonempty(value, field="planned action field")


class SimulationResult(BaseModel):
    run_id: str
    planned: list[PlannedAction] = Field(default_factory=list)
    safe_to_execute: bool

    @field_validator("run_id")
    @classmethod
    def _run_id(cls, value: str) -> str:
        return require_typed_id(value, "run", field="run_id")
