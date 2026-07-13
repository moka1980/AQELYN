"""Compliance & Governance Engine models and G1 config validation (EA-0010)."""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from aqelyn.conventions import require_tenant_id, require_typed_id
from aqelyn.conventions.errors import GovernanceConfigInvalid
from aqelyn.findings.models import Severity


def _require_nonempty(value: str, *, field: str) -> str:
    if not value.strip():
        raise GovernanceConfigInvalid(f"{field} must not be empty")
    return value


def _require_nonempty_list(values: list[str], *, field: str) -> list[str]:
    if not values:
        raise GovernanceConfigInvalid(f"{field} must not be empty")
    for value in values:
        _require_nonempty(value, field=field)
    if len(values) != len(set(values)):
        raise GovernanceConfigInvalid(f"{field} must not contain duplicates")
    return values


def _require_unit_interval(value: float, *, field: str) -> float:
    if not math.isfinite(value) or value < 0.0 or value > 1.0:
        raise GovernanceConfigInvalid(f"{field} must be in [0,1]")
    return value


def _require_nonnegative_int(value: int, *, field: str) -> int:
    if isinstance(value, bool) or value < 0:
        raise GovernanceConfigInvalid(f"{field} must be >= 0")
    return value


def _require_positive_int(value: int, *, field: str) -> int:
    if isinstance(value, bool) or value < 1:
        raise GovernanceConfigInvalid(f"{field} must be >= 1")
    return value


def _known_policy_ids(info: ValidationInfo) -> frozenset[str] | None:
    context = info.context
    if not isinstance(context, dict):
        return None
    raw = context.get("known_policy_ids")
    if raw is None:
        return None
    if not isinstance(raw, Iterable) or isinstance(raw, str):
        raise GovernanceConfigInvalid("known_policy_ids must be an iterable of strings")

    known: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise GovernanceConfigInvalid("known_policy_ids must contain only strings")
        known.append(_require_nonempty(item, field="known_policy_ids"))
    return frozenset(known)


class FrameworkRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    framework: str
    requirement: str

    @field_validator("framework", "requirement")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        return _require_nonempty(value, field="framework reference")


class Control(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str
    policy_ids: list[str]
    framework_refs: list[FrameworkRef] = Field(default_factory=list)
    severity: Severity

    @field_validator("id", "name", "description")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        return _require_nonempty(value, field="control field")

    @field_validator("policy_ids")
    @classmethod
    def _policy_ids(cls, values: list[str]) -> list[str]:
        return _require_nonempty_list(values, field="control policy_ids")

    @field_validator("framework_refs")
    @classmethod
    def _framework_refs(cls, values: list[FrameworkRef]) -> list[FrameworkRef]:
        keys = [(ref.framework, ref.requirement) for ref in values]
        if len(keys) != len(set(keys)):
            raise GovernanceConfigInvalid("control framework_refs must not contain duplicates")
        return values


class ControlResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    control_id: str
    evaluated: int
    passed: int
    failed: int
    failing_subject_ids: list[str] = Field(default_factory=list)
    score: float
    reason: str

    @field_validator("control_id", "reason")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        return _require_nonempty(value, field="control result field")

    @field_validator("evaluated", "passed", "failed")
    @classmethod
    def _count(cls, value: int) -> int:
        return _require_nonnegative_int(value, field="control result count")

    @field_validator("failing_subject_ids")
    @classmethod
    def _failing_subject_ids(cls, values: list[str]) -> list[str]:
        for value in values:
            require_typed_id(value, "obj", field="failing_subject_ids")
        if len(values) != len(set(values)):
            raise GovernanceConfigInvalid("failing_subject_ids must not contain duplicates")
        return values

    @field_validator("score")
    @classmethod
    def _score(cls, value: float) -> float:
        return _require_unit_interval(value, field="control result score")

    @model_validator(mode="after")
    def _consistent_counts(self) -> ControlResult:
        if self.passed + self.failed != self.evaluated:
            raise GovernanceConfigInvalid("passed + failed must equal evaluated")
        if len(self.failing_subject_ids) != self.failed:
            raise GovernanceConfigInvalid("failing_subject_ids count must equal failed")
        return self


class ComplianceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    tenant_id: str | None = None
    run_at: datetime
    scope: dict[str, Any] = Field(default_factory=dict)
    overall_score: float
    control_results: list[ControlResult] = Field(default_factory=list)
    framework_scores: dict[str, float] = Field(default_factory=dict)
    evidence_id: str | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "snap", field="id")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("overall_score")
    @classmethod
    def _overall_score(cls, value: float) -> float:
        return _require_unit_interval(value, field="overall_score")

    @field_validator("framework_scores")
    @classmethod
    def _framework_scores(cls, values: dict[str, float]) -> dict[str, float]:
        out: dict[str, float] = {}
        for framework, score in values.items():
            out[_require_nonempty(framework, field="framework_scores key")] = (
                _require_unit_interval(score, field=f"framework_scores[{framework!r}]")
            )
        return out

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="evidence_id")

    @field_validator("control_results")
    @classmethod
    def _control_results(cls, values: list[ControlResult]) -> list[ControlResult]:
        control_ids = [result.control_id for result in values]
        if len(control_ids) != len(set(control_ids)):
            raise GovernanceConfigInvalid("control_results must not contain duplicate controls")
        return values


class FrameworkCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    framework: str
    requirements: int
    covered: int
    coverage: float
    score: float

    @field_validator("framework")
    @classmethod
    def _framework(cls, value: str) -> str:
        return _require_nonempty(value, field="framework")

    @field_validator("requirements", "covered")
    @classmethod
    def _count(cls, value: int) -> int:
        return _require_nonnegative_int(value, field="framework coverage count")

    @field_validator("coverage", "score")
    @classmethod
    def _unit_interval(cls, value: float) -> float:
        return _require_unit_interval(value, field="framework coverage score")

    @model_validator(mode="after")
    def _consistent(self) -> FrameworkCoverage:
        if self.covered > self.requirements:
            raise GovernanceConfigInvalid("covered requirements cannot exceed total requirements")
        if self.requirements == 0 and self.covered != 0:
            raise GovernanceConfigInvalid("covered requirements must be 0 when requirements is 0")
        return self


class GovernanceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    controls: list[Control]
    frameworks: dict[str, list[str]] = Field(default_factory=dict)
    batch_size: int = 100
    min_confidence: float = 0.0

    @field_validator("controls")
    @classmethod
    def _controls(cls, values: list[Control]) -> list[Control]:
        if not values:
            raise GovernanceConfigInvalid("controls must not be empty")
        control_ids = [control.id for control in values]
        if len(control_ids) != len(set(control_ids)):
            raise GovernanceConfigInvalid("control ids must be unique")
        return values

    @field_validator("frameworks")
    @classmethod
    def _frameworks(cls, values: dict[str, list[str]]) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for framework, requirements in values.items():
            key = _require_nonempty(framework, field="framework")
            out[key] = _require_nonempty_list(requirements, field=f"frameworks[{key!r}]")
        return out

    @field_validator("batch_size")
    @classmethod
    def _batch_size(cls, value: int) -> int:
        return _require_positive_int(value, field="batch_size")

    @field_validator("min_confidence")
    @classmethod
    def _min_confidence(cls, value: float) -> float:
        return _require_unit_interval(value, field="min_confidence")

    @model_validator(mode="after")
    def _references_defined(self, info: ValidationInfo) -> GovernanceConfig:
        for control in self.controls:
            for ref in control.framework_refs:
                requirements = self.frameworks.get(ref.framework)
                if requirements is None:
                    raise GovernanceConfigInvalid(
                        f"control {control.id!r} references unknown framework {ref.framework!r}"
                    )
                if ref.requirement not in requirements:
                    raise GovernanceConfigInvalid(
                        f"control {control.id!r} references unknown requirement "
                        f"{ref.framework!r}:{ref.requirement!r}"
                    )

        known_policy_ids = _known_policy_ids(info)
        if known_policy_ids is not None:
            for control in self.controls:
                for policy_id in control.policy_ids:
                    if policy_id not in known_policy_ids:
                        raise GovernanceConfigInvalid(
                            f"control {control.id!r} references unknown policy {policy_id!r}"
                        )
        return self
