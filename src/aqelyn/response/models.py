"""Automated Response & Orchestration models and config validation (EA-0018 R1)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Final, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from aqelyn.conventions import ActorRef, new_id, require_tenant_id, require_typed_id
from aqelyn.conventions.errors import PolicyConfigInvalid, ResponseConfigInvalid
from aqelyn.policy import Condition
from aqelyn.workflow.models import ActionEffect, RunStatus

PhaseName = Literal["contain", "remediate", "recover"]
PhaseStatus = Literal["pending", "running", "completed", "failed", "blocked"]
CampaignStatus = Literal[
    "planned",
    "awaiting_approval",
    "running",
    "completed",
    "failed",
    "halted",
]
AutoStartEffect = Literal["read_only", "reversible"]
ApprovalRequestStatus = Literal["open", "granted", "expired", "escalated"]

PHASE_ORDER: Final[tuple[PhaseName, ...]] = cast(
    tuple[PhaseName, ...], ("contain", "remediate", "recover")
)
AUTO_START_EFFECTS: Final[frozenset[str]] = frozenset(("read_only", "reversible"))


def _nonempty(value: str, *, field: str) -> str:
    if not value.strip():
        raise ResponseConfigInvalid(f"{field} must not be empty")
    return value


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ResponseConfigInvalid(f"{field} must be >= 1")
    return value


def _nonnegative_float(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ResponseConfigInvalid(f"{field} must be >= 0")
    selected = float(value)
    if not math.isfinite(selected) or selected < 0.0:
        raise ResponseConfigInvalid(f"{field} must be >= 0")
    return selected


def _optional_nonnegative_float(value: object, *, field: str) -> float | None:
    if value is None:
        return None
    return _nonnegative_float(value, field=field)


def _percent(value: object, *, field: str) -> float:
    selected = _nonnegative_float(value, field=field)
    if selected > 100.0:
        raise ResponseConfigInvalid(f"{field} must be in [0,100]")
    return selected


def _unique_nonempty(values: list[str], *, field: str) -> list[str]:
    for value in values:
        _nonempty(value, field=field)
    if len(values) != len(set(values)):
        raise ResponseConfigInvalid(f"{field} must not contain duplicates")
    return values


class RunRef(BaseModel):
    """A mirrored reference to an EA-0008 run; Workflow remains source of truth."""

    model_config = ConfigDict(extra="forbid")

    workflow_run_id: str
    action_type: str
    effect: ActionEffect
    status: RunStatus

    @field_validator("workflow_run_id")
    @classmethod
    def _workflow_run_id(cls, value: str) -> str:
        return require_typed_id(value, "run", field="workflow_run_id")

    @field_validator("action_type")
    @classmethod
    def _action_type(cls, value: str) -> str:
        return _nonempty(value, field="action_type")


class Phase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: PhaseName
    order: int
    run_refs: list[RunRef] = Field(default_factory=list)
    depends_on: list[PhaseName] = Field(default_factory=list)
    status: PhaseStatus = "pending"

    @field_validator("order", mode="before")
    @classmethod
    def _order(cls, value: object) -> int:
        return _positive_int(value, field="phase order")

    @field_validator("depends_on")
    @classmethod
    def _depends_on(cls, values: list[PhaseName]) -> list[PhaseName]:
        if len(values) != len(set(values)):
            raise ResponseConfigInvalid("depends_on must not contain duplicates")
        return values

    @model_validator(mode="after")
    def _no_self_dependency(self) -> Phase:
        if self.name in self.depends_on:
            raise ResponseConfigInvalid("phase cannot depend on itself")
        return self


class ResponseCampaign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("rsp"))
    tenant_id: str | None = None
    incident_id: str | None = None
    source_finding_id: str | None = None
    phases: list[Phase]
    status: CampaignStatus = "planned"
    created_by: ActorRef
    created_at: datetime
    updated_at: datetime
    evidence_ids: list[str] = Field(default_factory=list)
    version: int = 1

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "rsp", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("incident_id")
    @classmethod
    def _incident_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "inc", field="incident_id")

    @field_validator("source_finding_id")
    @classmethod
    def _source_finding_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "fnd", field="source_finding_id")

    @field_validator("evidence_ids")
    @classmethod
    def _evidence_ids(cls, values: list[str]) -> list[str]:
        out = [require_typed_id(value, "evd", field="evidence_ids") for value in values]
        if len(out) != len(set(out)):
            raise ResponseConfigInvalid("evidence_ids must not contain duplicates")
        return out

    @field_validator("version", mode="before")
    @classmethod
    def _version(cls, value: object) -> int:
        return _positive_int(value, field="campaign version")

    @field_validator("phases")
    @classmethod
    def _phases(cls, values: list[Phase]) -> list[Phase]:
        if not values:
            raise ResponseConfigInvalid("campaign requires at least one phase")
        names = [phase.name for phase in values]
        orders = [phase.order for phase in values]
        if len(names) != len(set(names)):
            raise ResponseConfigInvalid("campaign phase names must be unique")
        if len(orders) != len(set(orders)):
            raise ResponseConfigInvalid("campaign phase order values must be unique")
        known = set(names)
        for phase in values:
            missing = [dependency for dependency in phase.depends_on if dependency not in known]
            if missing:
                raise ResponseConfigInvalid("phase depends_on must name campaign phases")
        return values

    @model_validator(mode="after")
    def _timestamps(self) -> ResponseCampaign:
        if self.updated_at < self.created_at:
            raise ResponseConfigInvalid("updated_at must be >= created_at")
        return self


class AutomationTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("trg"))
    tenant_id: str | None = None
    name: str
    condition: Condition
    playbook_id: str
    max_effect: AutoStartEffect
    enabled: bool = True
    version: int = 1

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "trg", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("name", "playbook_id")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="automation trigger field")

    @field_validator("condition", mode="before")
    @classmethod
    def _condition(cls, value: object) -> Condition:
        if isinstance(value, Condition):
            return value
        try:
            return Condition.model_validate(value)
        except PolicyConfigInvalid as exc:
            raise ResponseConfigInvalid(exc.message) from exc

    @field_validator("max_effect", mode="before")
    @classmethod
    def _max_effect(cls, value: object) -> str:
        if not isinstance(value, str) or value not in AUTO_START_EFFECTS:
            raise ResponseConfigInvalid("max_effect must be read_only or reversible")
        return value

    @field_validator("version", mode="before")
    @classmethod
    def _version(cls, value: object) -> int:
        return _positive_int(value, field="trigger version")


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("apr"))
    tenant_id: str | None = None
    workflow_run_id: str
    step_ids: list[str]
    routed_to: ActorRef | str
    sla_seconds: int
    escalate_to: ActorRef | str | None = None
    status: ApprovalRequestStatus = "open"
    requested_at: datetime

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "apr", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("workflow_run_id")
    @classmethod
    def _workflow_run_id(cls, value: str) -> str:
        return require_typed_id(value, "run", field="workflow_run_id")

    @field_validator("step_ids")
    @classmethod
    def _step_ids(cls, values: list[str]) -> list[str]:
        if not values:
            raise ResponseConfigInvalid("step_ids must not be empty")
        return _unique_nonempty(values, field="step_ids")

    @field_validator("routed_to", "escalate_to")
    @classmethod
    def _actor_or_role(cls, value: ActorRef | str | None) -> ActorRef | str | None:
        if value is None or isinstance(value, ActorRef):
            return value
        return _nonempty(value, field="approval route")

    @field_validator("sla_seconds", mode="before")
    @classmethod
    def _sla_seconds(cls, value: object) -> int:
        return _positive_int(value, field="sla_seconds")


class RecoveryVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: str
    checks: list[dict[str, Any]]
    verified: bool
    reopened_finding_id: str | None = None
    reason: str

    @field_validator("campaign_id")
    @classmethod
    def _campaign_id(cls, value: str) -> str:
        return require_typed_id(value, "rsp", field="campaign_id")

    @field_validator("reopened_finding_id")
    @classmethod
    def _reopened_finding_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "fnd", field="reopened_finding_id")

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return _nonempty(value, field="verification reason")


class ResponseMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window: dict[str, Any]
    mttd_seconds: float | None = None
    mttr_seconds: float | None = None
    containment_seconds: float | None = None
    campaigns: int
    automated_pct: float

    @field_validator("mttd_seconds", "mttr_seconds", "containment_seconds", mode="before")
    @classmethod
    def _optional_duration(cls, value: object) -> float | None:
        return _optional_nonnegative_float(value, field="duration")

    @field_validator("campaigns", mode="before")
    @classmethod
    def _campaigns(cls, value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ResponseConfigInvalid("campaigns must be >= 0")
        return value

    @field_validator("automated_pct", mode="before")
    @classmethod
    def _automated_pct(cls, value: object) -> float:
        return _percent(value, field="automated_pct")


class ResponseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase_order: tuple[PhaseName, ...] = PHASE_ORDER
    default_sla_seconds: int = 3600
    batch_size: int = 100

    @field_validator("phase_order")
    @classmethod
    def _phase_order(cls, values: tuple[PhaseName, ...]) -> tuple[PhaseName, ...]:
        if not values:
            raise ResponseConfigInvalid("phase_order must not be empty")
        if len(values) != len(set(values)):
            raise ResponseConfigInvalid("phase_order must not contain duplicates")
        return values

    @field_validator("default_sla_seconds", "batch_size", mode="before")
    @classmethod
    def _positive_config_int(cls, value: object, info: ValidationInfo) -> int:
        return _positive_int(value, field=info.field_name or "response config integer")
