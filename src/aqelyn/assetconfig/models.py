"""Asset & Configuration Governance models and A1 config validation."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aqelyn.assetconfig.comparators import Comparator, validate_comparator, validate_regex_pattern
from aqelyn.conventions import ActorRef, require_tenant_id, require_typed_id
from aqelyn.conventions.errors import BaselineConfigInvalid
from aqelyn.findings.models import Severity

DriftStatus = Literal["pass", "fail", "unknown"]


def _require_nonempty(value: str, *, field: str) -> str:
    if not value.strip():
        raise BaselineConfigInvalid(f"{field} must not be empty")
    return value


def _require_positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise BaselineConfigInvalid(f"{field} must be >= 1")
    return value


def _require_nonnegative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BaselineConfigInvalid(f"{field} must be >= 0")
    return value


def _require_unit_interval(value: float, *, field: str) -> float:
    if not math.isfinite(value) or value < 0.0 or value > 1.0:
        raise BaselineConfigInvalid(f"{field} must be in [0,1]")
    return value


class FrameworkRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    framework: str
    requirement: str

    @field_validator("framework", "requirement")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        return _require_nonempty(value, field="framework reference")


class Check(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    expected: Any
    comparator: Comparator
    severity: Severity
    rationale: str
    framework_refs: list[FrameworkRef] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _required_fields(cls, data: object) -> object:
        if isinstance(data, dict):
            for field in ("key", "expected"):
                if field not in data:
                    raise BaselineConfigInvalid(f"check missing required field: {field}")
        return data

    @field_validator("id", "key", "rationale")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        return _require_nonempty(value, field="check field")

    @field_validator("comparator", mode="before")
    @classmethod
    def _comparator(cls, value: object) -> str:
        if not isinstance(value, str):
            raise BaselineConfigInvalid("comparator must be a string")
        return validate_comparator(value)

    @field_validator("framework_refs")
    @classmethod
    def _framework_refs(cls, values: list[FrameworkRef]) -> list[FrameworkRef]:
        keys = [(ref.framework, ref.requirement) for ref in values]
        if len(keys) != len(set(keys)):
            raise BaselineConfigInvalid("check framework_refs must not contain duplicates")
        return values

    @model_validator(mode="after")
    def _regex_expected_safe(self) -> Check:
        if self.comparator == "regex":
            validate_regex_pattern(self.expected)
        return self


class Baseline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    asset_class: str
    version: int
    checks: list[Check]
    tenant_id: str | None = None
    set_by: ActorRef
    set_at: datetime

    @field_validator("id", "name", "asset_class")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        return _require_nonempty(value, field="baseline field")

    @field_validator("version", mode="before")
    @classmethod
    def _version(cls, value: object) -> int:
        return _require_positive_int(value, field="version")

    @field_validator("checks")
    @classmethod
    def _checks(cls, values: list[Check]) -> list[Check]:
        if not values:
            raise BaselineConfigInvalid("baseline checks must not be empty")
        check_ids = [check.id for check in values]
        if len(check_ids) != len(set(check_ids)):
            raise BaselineConfigInvalid("baseline check ids must be unique")
        return values

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)


class DriftItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    check_id: str
    key: str
    expected: Any
    observed: Any = None
    status: DriftStatus
    severity: Severity
    reason: str

    @field_validator("asset_id")
    @classmethod
    def _asset_id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="asset_id")

    @field_validator("check_id", "key", "reason")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        return _require_nonempty(value, field="drift item field")


class AssetDrift(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    baseline_id: str
    evaluated: int
    passed: int
    failed: int
    score: float
    items: list[DriftItem] = Field(default_factory=list)

    @field_validator("asset_id")
    @classmethod
    def _asset_id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="asset_id")

    @field_validator("baseline_id")
    @classmethod
    def _baseline_id(cls, value: str) -> str:
        return _require_nonempty(value, field="baseline_id")

    @field_validator("evaluated", "passed", "failed", mode="before")
    @classmethod
    def _counts(cls, value: object) -> int:
        return _require_nonnegative_int(value, field="asset drift count")

    @field_validator("score")
    @classmethod
    def _score(cls, value: float) -> float:
        return _require_unit_interval(value, field="asset drift score")

    @model_validator(mode="after")
    def _consistent_counts(self) -> AssetDrift:
        if self.passed + self.failed > self.evaluated:
            raise BaselineConfigInvalid("passed + failed cannot exceed evaluated")
        return self


class ObjectTypeAssessmentCoverage(BaseModel):
    """Coverage for one object type in a completed drift assessment."""

    model_config = ConfigDict(extra="forbid")

    object_type: str
    objects_in_scope: int
    objects_assessed: int
    unassessed_object_ids: list[str] = Field(default_factory=list)

    @field_validator("object_type")
    @classmethod
    def _object_type(cls, value: str) -> str:
        return _require_nonempty(value, field="coverage object_type")

    @field_validator("objects_in_scope", "objects_assessed", mode="before")
    @classmethod
    def _counts(cls, value: object) -> int:
        return _require_nonnegative_int(value, field="assessment coverage count")

    @field_validator("unassessed_object_ids")
    @classmethod
    def _unassessed_object_ids(cls, values: list[str]) -> list[str]:
        selected = sorted(
            require_typed_id(value, "obj", field="unassessed_object_ids") for value in values
        )
        if len(selected) != len(set(selected)):
            raise BaselineConfigInvalid("unassessed_object_ids must not contain duplicates")
        return selected

    @model_validator(mode="after")
    def _consistent_counts(self) -> ObjectTypeAssessmentCoverage:
        if self.objects_assessed + len(self.unassessed_object_ids) != self.objects_in_scope:
            raise BaselineConfigInvalid(
                "coverage objects_in_scope must equal assessed plus unassessed objects"
            )
        return self


class DriftSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    tenant_id: str | None = None
    run_at: datetime
    scope: dict[str, Any] = Field(default_factory=dict)
    baseline_ids: list[str] = Field(default_factory=list)
    overall_score: float
    asset_drifts: list[AssetDrift] = Field(default_factory=list)
    coverage_complete: bool = False
    objects_in_scope: int = 0
    objects_assessed: int = 0
    unassessed_object_ids: list[str] = Field(default_factory=list)
    coverage_by_object_type: list[ObjectTypeAssessmentCoverage] = Field(default_factory=list)
    evidence_id: str | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return _require_nonempty(value, field="drift snapshot id")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("baseline_ids")
    @classmethod
    def _baseline_ids(cls, values: list[str]) -> list[str]:
        out = [_require_nonempty(value, field="baseline_ids") for value in values]
        if len(out) != len(set(out)):
            raise BaselineConfigInvalid("baseline_ids must not contain duplicates")
        return out

    @field_validator("overall_score")
    @classmethod
    def _overall_score(cls, value: float) -> float:
        return _require_unit_interval(value, field="overall_score")

    @field_validator("objects_in_scope", "objects_assessed", mode="before")
    @classmethod
    def _coverage_counts(cls, value: object) -> int:
        return _require_nonnegative_int(value, field="assessment coverage count")

    @field_validator("unassessed_object_ids")
    @classmethod
    def _unassessed_object_ids(cls, values: list[str]) -> list[str]:
        selected = sorted(
            require_typed_id(value, "obj", field="unassessed_object_ids") for value in values
        )
        if len(selected) != len(set(selected)):
            raise BaselineConfigInvalid("unassessed_object_ids must not contain duplicates")
        return selected

    @field_validator("coverage_by_object_type")
    @classmethod
    def _coverage_by_object_type(
        cls, values: list[ObjectTypeAssessmentCoverage]
    ) -> list[ObjectTypeAssessmentCoverage]:
        selected = sorted(values, key=lambda item: item.object_type)
        object_types = [item.object_type for item in selected]
        if len(object_types) != len(set(object_types)):
            raise BaselineConfigInvalid("coverage object types must not contain duplicates")
        return selected

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="evidence_id")

    @model_validator(mode="after")
    def _consistent_coverage(self) -> DriftSnapshot:
        if not self.coverage_complete:
            if (
                self.objects_in_scope != 0
                or self.objects_assessed != 0
                or self.unassessed_object_ids
                or self.coverage_by_object_type
            ):
                raise BaselineConfigInvalid(
                    "coverage fields must be empty when coverage_complete is false"
                )
            return self

        if not self.coverage_by_object_type:
            raise BaselineConfigInvalid(
                "completed assessment coverage requires per-object-type coverage"
            )
        if self.objects_assessed < 1:
            raise BaselineConfigInvalid("completed assessment coverage requires an assessed object")

        if self.objects_in_scope != sum(
            item.objects_in_scope for item in self.coverage_by_object_type
        ):
            raise BaselineConfigInvalid(
                "objects_in_scope must equal the per-object-type coverage total"
            )
        if self.objects_assessed != sum(
            item.objects_assessed for item in self.coverage_by_object_type
        ):
            raise BaselineConfigInvalid(
                "objects_assessed must equal the per-object-type coverage total"
            )

        per_type_unassessed = sorted(
            object_id
            for item in self.coverage_by_object_type
            for object_id in item.unassessed_object_ids
        )
        if self.unassessed_object_ids != per_type_unassessed:
            raise BaselineConfigInvalid(
                "unassessed_object_ids must equal the per-object-type uncovered objects"
            )

        assessed_ids = {drift.asset_id for drift in self.asset_drifts}
        if len(assessed_ids) != self.objects_assessed:
            raise BaselineConfigInvalid(
                "objects_assessed must equal the objects represented by asset_drifts"
            )
        if assessed_ids.intersection(self.unassessed_object_ids):
            raise BaselineConfigInvalid("an object cannot be both assessed and unassessed")
        return self


class ACGConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_size: int = 100
    assessable_object_types: list[str] = Field(default_factory=lambda: ["asset"])
    classification_rules: list[dict[str, Any]] = Field(default_factory=list)
    unknown_is_fail: bool = True

    @field_validator("batch_size", mode="before")
    @classmethod
    def _batch_size(cls, value: object) -> int:
        return _require_positive_int(value, field="batch_size")

    @field_validator("assessable_object_types")
    @classmethod
    def _assessable_object_types(cls, values: list[str]) -> list[str]:
        if not values:
            raise BaselineConfigInvalid("assessable_object_types must not be empty")
        selected = [_require_nonempty(value, field="assessable_object_types") for value in values]
        if len(selected) != len(set(selected)):
            raise BaselineConfigInvalid("assessable_object_types must not contain duplicates")
        return sorted(selected)

    @field_validator("classification_rules")
    @classmethod
    def _classification_rules(cls, values: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [dict(rule) for rule in values]
