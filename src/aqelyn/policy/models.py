"""Policy Engine models and P1 config validation (EA-0009)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aqelyn.conventions import ActorRef, require_tenant_id
from aqelyn.conventions.errors import PolicyConfigInvalid
from aqelyn.policy.interpreter import DEFAULT_MAX_DEPTH

Op = Literal["eq", "ne", "in", "nin", "gt", "gte", "lt", "lte", "exists", "contains"]
RuleKind = Literal["authorization", "compliance"]
RuleEffect = Literal["permit", "deny", "require_approval", "require"]
DecisionEffect = Literal["permit", "deny", "require_approval"]

VALID_OPS: Final[frozenset[str]] = frozenset(
    ("eq", "ne", "in", "nin", "gt", "gte", "lt", "lte", "exists", "contains")
)
VALID_RULE_KINDS: Final[frozenset[str]] = frozenset(("authorization", "compliance"))
VALID_RULE_EFFECTS: Final[frozenset[str]] = frozenset(
    ("permit", "deny", "require_approval", "require")
)
VALID_DECISION_EFFECTS: Final[frozenset[str]] = frozenset(("permit", "deny", "require_approval"))


def _require_nonempty(value: str, *, field: str) -> str:
    if not value.strip():
        raise PolicyConfigInvalid(f"{field} must not be empty")
    return value


def _require_nonempty_list(values: list[str], *, field: str) -> list[str]:
    if not values:
        raise PolicyConfigInvalid(f"{field} must not be empty")
    for value in values:
        _require_nonempty(value, field=field)
    if len(values) != len(set(values)):
        raise PolicyConfigInvalid(f"{field} must not contain duplicates")
    return values


class Condition(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    op: str | None = None
    attr: str | None = None
    value: Any = None
    all: list[Condition] | None = None
    any: list[Condition] | None = None
    not_: Condition | None = Field(default=None, alias="not")

    @model_validator(mode="after")
    def _valid_shape(self) -> Condition:
        if self.model_extra:
            raise PolicyConfigInvalid("condition contains unsupported fields")
        forms = [
            self.op is not None or self.attr is not None,
            self.all is not None,
            self.any is not None,
            self.not_ is not None,
        ]
        if sum(1 for active in forms if active) != 1:
            raise PolicyConfigInvalid("condition must use exactly one form")

        if self.op is not None or self.attr is not None:
            self._validate_leaf()
        elif self.all is not None:
            if not self.all:
                raise PolicyConfigInvalid("condition all must not be empty")
        elif self.any is not None and not self.any:
            raise PolicyConfigInvalid("condition any must not be empty")

        if condition_depth(self) > DEFAULT_MAX_DEPTH:
            raise PolicyConfigInvalid(f"condition depth must be <= {DEFAULT_MAX_DEPTH}")
        return self

    def _validate_leaf(self) -> None:
        if self.op is None or self.attr is None:
            raise PolicyConfigInvalid("leaf condition requires op and attr")
        if self.op not in VALID_OPS:
            raise PolicyConfigInvalid(f"unknown condition op: {self.op!r}")
        _require_nonempty(self.attr, field="condition attr")
        if "." in self.attr:
            for part in self.attr.split("."):
                _require_nonempty(part, field="condition attr path")


def condition_depth(condition: Condition) -> int:
    if condition.op is not None:
        return 1
    if condition.all is not None:
        return 1 + max(condition_depth(item) for item in condition.all)
    if condition.any is not None:
        return 1 + max(condition_depth(item) for item in condition.any)
    if condition.not_ is not None:
        return 1 + condition_depth(condition.not_)
    raise PolicyConfigInvalid("malformed condition")


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actions: list[str] | None = None
    resource_types: list[str] | None = None

    @field_validator("actions", "resource_types")
    @classmethod
    def _nonempty_list(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return _require_nonempty_list(values, field="target")


class Obligation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def _type(cls, value: str) -> str:
        return _require_nonempty(value, field="obligation type")


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    description: str
    target: Target
    condition: Condition | None = None
    effect: str
    obligations: list[Obligation] = Field(default_factory=list)
    priority: int = 0

    @field_validator("id", "description")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        return _require_nonempty(value, field="rule field")

    @field_validator("kind")
    @classmethod
    def _kind(cls, value: str) -> str:
        if value not in VALID_RULE_KINDS:
            raise PolicyConfigInvalid(f"unknown rule kind: {value!r}")
        return value

    @field_validator("effect")
    @classmethod
    def _effect(cls, value: str) -> str:
        if value not in VALID_RULE_EFFECTS:
            raise PolicyConfigInvalid(f"unknown rule effect: {value!r}")
        return value

    @field_validator("priority", mode="before")
    @classmethod
    def _priority(cls, value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise PolicyConfigInvalid("rule priority must be an int")
        return value

    @model_validator(mode="after")
    def _kind_effect_match(self) -> Rule:
        if self.kind == "authorization" and self.effect == "require":
            raise PolicyConfigInvalid("authorization rules cannot use require effect")
        if self.kind == "compliance" and self.effect != "require":
            raise PolicyConfigInvalid("compliance rules must use require effect")
        return self


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: int
    name: str
    description: str
    tenant_id: str | None = None
    rules: list[Rule]
    standard: str | None = None
    set_by: ActorRef
    set_at: datetime

    @field_validator("id", "name", "description")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        return _require_nonempty(value, field="policy field")

    @field_validator("version", mode="before")
    @classmethod
    def _version(cls, value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise PolicyConfigInvalid("policy version must be >= 1")
        return value

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("rules")
    @classmethod
    def _rules(cls, values: list[Rule]) -> list[Rule]:
        if not values:
            raise PolicyConfigInvalid("policy requires at least one rule")
        rule_ids = [rule.id for rule in values]
        if len(rule_ids) != len(set(rule_ids)):
            raise PolicyConfigInvalid("policy rule ids must be unique")
        return values

    @field_validator("standard")
    @classmethod
    def _standard(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_nonempty(value, field="policy standard")


class DecisionResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    type: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    tenant_id: str | None = None

    @field_validator("id", "type")
    @classmethod
    def _optional_nonempty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_nonempty(value, field="decision resource field")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: ActorRef
    action: str
    resource: DecisionResource
    context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("action")
    @classmethod
    def _action(cls, value: str) -> str:
        return _require_nonempty(value, field="decision action")


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effect: str
    matched_rules: list[str] = Field(default_factory=list)
    obligations: list[Obligation] = Field(default_factory=list)
    reason: str

    @field_validator("effect")
    @classmethod
    def _effect(cls, value: str) -> str:
        if value not in VALID_DECISION_EFFECTS:
            raise PolicyConfigInvalid(f"unknown decision effect: {value!r}")
        return value

    @field_validator("matched_rules")
    @classmethod
    def _matched_rules(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise PolicyConfigInvalid("matched_rules must not contain empty ids")
        return values

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return _require_nonempty(value, field="decision reason")


class ComplianceViolation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str
    rule_id: str
    subject_ref: str
    requirement: str
    reason: str

    @field_validator("policy_id", "rule_id", "subject_ref", "requirement", "reason")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        return _require_nonempty(value, field="compliance violation field")


class ComplianceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    compliant: bool
    violations: list[ComplianceViolation] = Field(default_factory=list)
    evaluated: int

    @field_validator("evaluated", mode="before")
    @classmethod
    def _evaluated(cls, value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise PolicyConfigInvalid("evaluated must be >= 0")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> ComplianceResult:
        if self.compliant and self.violations:
            raise PolicyConfigInvalid("compliant result cannot contain violations")
        return self
