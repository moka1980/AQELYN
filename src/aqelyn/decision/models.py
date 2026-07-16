"""AI Decision Intelligence models and config validation (EA-0020 E1)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aqelyn.conventions import ActorRef, new_id, require_tenant_id, require_typed_id
from aqelyn.conventions.errors import DecisionConfigInvalid
from aqelyn.decision.operations import DEFAULT_OPERATION_NAMES

ClaimKind = Literal["finding", "risk", "detection", "trust", "mission", "case"]
DecisionOutcome = Literal["accepted", "rejected", "modified"]

VALID_CLAIM_KINDS: Final[frozenset[str]] = frozenset(
    ("finding", "risk", "detection", "trust", "mission", "case")
)
VALID_DECISIONS: Final[frozenset[str]] = frozenset(("accepted", "rejected", "modified"))


def _nonempty(value: str, *, field: str) -> str:
    if not value.strip():
        raise DecisionConfigInvalid(f"{field} must not be empty")
    return value


def _unique_nonempty(values: list[str], *, field: str) -> list[str]:
    if not values:
        raise DecisionConfigInvalid(f"{field} must not be empty")
    for value in values:
        _nonempty(value, field=field)
    if len(values) != len(set(values)):
        raise DecisionConfigInvalid(f"{field} must not contain duplicates")
    return values


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DecisionConfigInvalid(f"{field} must be >= 1")
    return value


def _unit(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise DecisionConfigInvalid(f"{field} must be in [0,1]")
    selected = float(value)
    if not math.isfinite(selected) or selected < 0.0 or selected > 1.0:
        raise DecisionConfigInvalid(f"{field} must be in [0,1]")
    return selected


class ClaimRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    ref_id: str
    evidence_id: str | None = None

    @field_validator("kind")
    @classmethod
    def _kind(cls, value: str) -> str:
        if value not in VALID_CLAIM_KINDS:
            raise DecisionConfigInvalid(f"unknown claim kind: {value!r}")
        return value

    @field_validator("ref_id")
    @classmethod
    def _ref_id(cls, value: str) -> str:
        return _nonempty(value, field="ref_id")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="evidence_id")


class DerivationStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int
    op: str
    input_refs: list[str]
    params: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any]
    note: str

    @field_validator("seq", mode="before")
    @classmethod
    def _seq(cls, value: object) -> int:
        return _positive_int(value, field="derivation step seq")

    @field_validator("op", "note")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="derivation step field")

    @field_validator("input_refs")
    @classmethod
    def _input_refs(cls, values: list[str]) -> list[str]:
        return _unique_nonempty(values, field="input_refs")

    @field_validator("output")
    @classmethod
    def _output(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise DecisionConfigInvalid("derivation step output must not be empty")
        return dict(value)


class Derivation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inputs: list[ClaimRef]
    steps: list[DerivationStep]
    result: dict[str, Any]
    model_version: int
    engine_version: str

    @field_validator("inputs")
    @classmethod
    def _inputs(cls, values: list[ClaimRef]) -> list[ClaimRef]:
        if not values:
            raise DecisionConfigInvalid("derivation inputs must not be empty")
        return values

    @field_validator("steps")
    @classmethod
    def _steps(cls, values: list[DerivationStep]) -> list[DerivationStep]:
        if not values:
            raise DecisionConfigInvalid("derivation steps must not be empty")
        seqs = [step.seq for step in values]
        expected = list(range(1, len(values) + 1))
        if seqs != expected:
            raise DecisionConfigInvalid("derivation step seq must be contiguous from 1")
        return values

    @field_validator("result")
    @classmethod
    def _result(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise DecisionConfigInvalid("derivation result must not be empty")
        return dict(value)

    @field_validator("model_version", mode="before")
    @classmethod
    def _model_version(cls, value: object) -> int:
        return _positive_int(value, field="model_version")

    @field_validator("engine_version")
    @classmethod
    def _engine_version(cls, value: str) -> str:
        return _nonempty(value, field="engine_version")


class Recommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("rec"))
    tenant_id: str | None = None
    subject_ref: str
    statement: str
    action_hint: dict[str, Any] | None = None
    confidence: float
    derivation: Derivation
    advisory: bool = True
    created_at: datetime

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "rec", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("subject_ref", "statement")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="recommendation field")

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, value: object) -> float:
        return _unit(value, field="confidence")

    @field_validator("advisory")
    @classmethod
    def _advisory(cls, value: bool) -> bool:
        if value is not True:
            raise DecisionConfigInvalid("recommendations are advisory only")
        return value


class DecisionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("dec"))
    recommendation_id: str
    decision: str
    decided_by: ActorRef
    reason: str
    at: datetime
    workflow_run_id: str | None = None
    evidence_id: str

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "dec", field="id", allow_empty=True)

    @field_validator("recommendation_id")
    @classmethod
    def _recommendation_id(cls, value: str) -> str:
        return require_typed_id(value, "rec", field="recommendation_id")

    @field_validator("decision")
    @classmethod
    def _decision(cls, value: str) -> str:
        if value not in VALID_DECISIONS:
            raise DecisionConfigInvalid(f"unknown decision: {value!r}")
        return value

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return _nonempty(value, field="decision reason")

    @field_validator("workflow_run_id")
    @classmethod
    def _workflow_run_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "run", field="workflow_run_id")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")


class LearningRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("lrn"))
    recommendation_id: str
    feedback: str
    proposed_change: dict[str, Any]
    applied: bool = False
    recorded_at: datetime

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "lrn", field="id", allow_empty=True)

    @field_validator("recommendation_id")
    @classmethod
    def _recommendation_id(cls, value: str) -> str:
        return require_typed_id(value, "rec", field="recommendation_id")

    @field_validator("feedback")
    @classmethod
    def _feedback(cls, value: str) -> str:
        return _nonempty(value, field="feedback")

    @field_validator("proposed_change")
    @classmethod
    def _proposed_change(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise DecisionConfigInvalid("proposed_change must not be empty")
        return dict(value)

    @field_validator("applied")
    @classmethod
    def _applied(cls, value: bool) -> bool:
        if value is not False:
            raise DecisionConfigInvalid("learning records are never auto-applied")
        return value


class ModelVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    params: dict[str, Any]
    promoted_by: ActorRef | None = None
    promoted_at: datetime | None = None
    active: bool = False
    evidence_id: str | None = None

    @field_validator("version", mode="before")
    @classmethod
    def _version(cls, value: object) -> int:
        return _positive_int(value, field="model version")

    @field_validator("params")
    @classmethod
    def _params(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise DecisionConfigInvalid("model params must not be empty")
        return dict(value)

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="evidence_id")

    @model_validator(mode="after")
    def _promotion_integrity(self) -> ModelVersion:
        promoted = (
            self.promoted_by is not None
            or self.promoted_at is not None
            or self.evidence_id is not None
        )
        if self.active and (
            self.promoted_by is None or self.promoted_at is None or self.evidence_id is None
        ):
            raise DecisionConfigInvalid("active model versions require attributed promotion")
        if promoted and (
            self.promoted_by is None or self.promoted_at is None or self.evidence_id is None
        ):
            raise DecisionConfigInvalid("model promotion metadata must be complete")
        return self


class SimilarityHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    score: float
    shared: dict[str, Any]
    reason: str

    @field_validator("case_id", "reason")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="similarity hit field")

    @field_validator("score", mode="before")
    @classmethod
    def _score(cls, value: object) -> float:
        return _unit(value, field="score")

    @field_validator("shared")
    @classmethod
    def _shared(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise DecisionConfigInvalid("shared must not be empty")
        return dict(value)


class DecisionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operations_allowed: list[str] = Field(default_factory=lambda: list(DEFAULT_OPERATION_NAMES))
    max_steps: int = 32
    min_confidence: float = 0.0
    batch_size: int = 100

    @field_validator("operations_allowed")
    @classmethod
    def _operations_allowed(cls, values: list[str]) -> list[str]:
        selected = _unique_nonempty(values, field="operations_allowed")
        allowed = set(DEFAULT_OPERATION_NAMES)
        for value in selected:
            if value not in allowed:
                raise DecisionConfigInvalid(f"unknown operation in config: {value!r}")
        return selected

    @field_validator("max_steps", "batch_size", mode="before")
    @classmethod
    def _positive(cls, value: object) -> int:
        return _positive_int(value, field="decision config integer")

    @field_validator("min_confidence", mode="before")
    @classmethod
    def _min_confidence(cls, value: object) -> float:
        return _unit(value, field="min_confidence")
