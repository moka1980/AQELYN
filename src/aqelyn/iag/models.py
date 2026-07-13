"""Identity & Access Governance models and config validation (EA-0011 I1)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from aqelyn.conventions import ActorRef, require_tenant_id, require_typed_id
from aqelyn.conventions.errors import IAGConfigInvalid
from aqelyn.findings.models import Severity
from aqelyn.graph import Path

AccessRiskKind = Literal[
    "orphaned",
    "dormant",
    "over_privilege",
    "sod_conflict",
    "privileged_unreviewed",
]
ReviewDecision = Literal["pending", "approved", "revoked", "delegated"]
CertificationStatus = Literal["open", "in_progress", "completed", "expired"]


def _require_nonempty(value: str, *, field: str) -> str:
    if not value.strip():
        raise IAGConfigInvalid(f"{field} must not be empty")
    return value


def _require_nonempty_list(values: list[str], *, field: str) -> list[str]:
    if not values:
        raise IAGConfigInvalid(f"{field} must not be empty")
    for value in values:
        _require_nonempty(value, field=field)
    if len(values) != len(set(values)):
        raise IAGConfigInvalid(f"{field} must not contain duplicates")
    return values


def _require_nonnegative_int(value: int, *, field: str) -> int:
    if isinstance(value, bool) or value < 0:
        raise IAGConfigInvalid(f"{field} must be >= 0")
    return value


def _require_positive_int(value: int, *, field: str) -> int:
    if isinstance(value, bool) or value < 1:
        raise IAGConfigInvalid(f"{field} must be >= 1")
    return value


def _known_privileged_roles(info: ValidationInfo) -> frozenset[str] | None:
    context = info.context
    if not isinstance(context, dict):
        return None
    raw = context.get("known_privileged_roles")
    if raw is None:
        return None
    if not isinstance(raw, Iterable) or isinstance(raw, str):
        raise IAGConfigInvalid("known_privileged_roles must be an iterable of strings")

    known: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise IAGConfigInvalid("known_privileged_roles must contain only strings")
        known.append(_require_nonempty(item, field="known_privileged_roles"))
    return frozenset(known)


class AccessPath(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_id: str
    account_id: str | None = None
    entitlement_ids: list[str] = Field(default_factory=list)
    via: Path

    @field_validator("identity_id")
    @classmethod
    def _identity_id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="identity_id")

    @field_validator("account_id")
    @classmethod
    def _account_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "obj", field="account_id")

    @field_validator("entitlement_ids")
    @classmethod
    def _entitlement_ids(cls, values: list[str]) -> list[str]:
        for value in values:
            require_typed_id(value, "obj", field="entitlement_ids")
        if len(values) != len(set(values)):
            raise IAGConfigInvalid("entitlement_ids must not contain duplicates")
        return values


class AccessRisk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: AccessRiskKind
    subject_id: str
    detail: dict[str, Any] = Field(default_factory=dict)
    severity: Severity
    evidence_path: Path | None = None
    reason: str

    @field_validator("subject_id")
    @classmethod
    def _subject_id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="subject_id")

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return _require_nonempty(value, field="reason")


class AccessRiskReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risks: list[AccessRisk] = Field(default_factory=list)
    evaluated: int
    truncated: bool = False

    @field_validator("evaluated")
    @classmethod
    def _evaluated(cls, value: int) -> int:
        return _require_nonnegative_int(value, field="evaluated")


class ReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    identity_id: str
    account_id: str | None = None
    entitlement_id: str | None = None
    current_state: dict[str, Any] = Field(default_factory=dict)
    recommendation: str
    decision: ReviewDecision = "pending"
    decided_by: ActorRef | None = None
    decided_at: datetime | None = None
    evidence_id: str | None = None
    note: str | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "rvi", field="id", allow_empty=True)

    @field_validator("identity_id")
    @classmethod
    def _identity_id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="identity_id")

    @field_validator("account_id", "entitlement_id")
    @classmethod
    def _optional_object_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "obj", field="review object ref")

    @field_validator("recommendation")
    @classmethod
    def _recommendation(cls, value: str) -> str:
        return _require_nonempty(value, field="recommendation")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="evidence_id")

    @field_validator("note")
    @classmethod
    def _note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_nonempty(value, field="note")

    @model_validator(mode="after")
    def _decision_consistent(self) -> ReviewItem:
        if self.decision == "pending":
            if self.decided_by is not None or self.decided_at is not None or self.evidence_id:
                raise IAGConfigInvalid("pending review items must not carry decision metadata")
            return self
        if self.decided_by is None or self.decided_at is None or self.evidence_id is None:
            raise IAGConfigInvalid("decided review items require actor, timestamp, and evidence")
        return self


class Certification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    tenant_id: str | None = None
    name: str
    scope: dict[str, Any] = Field(default_factory=dict)
    status: CertificationStatus = "open"
    items: list[ReviewItem] = Field(default_factory=list)
    created_by: ActorRef
    created_at: datetime
    due_at: datetime | None = None
    version: int = 1

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "cert", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _require_nonempty(value, field="name")

    @field_validator("items")
    @classmethod
    def _items(cls, values: list[ReviewItem]) -> list[ReviewItem]:
        item_ids = [item.id for item in values if item.id]
        if len(item_ids) != len(set(item_ids)):
            raise IAGConfigInvalid("review item ids must be unique")
        return values

    @field_validator("version")
    @classmethod
    def _version(cls, value: int) -> int:
        return _require_positive_int(value, field="version")

    @model_validator(mode="after")
    def _due_after_created(self) -> Certification:
        if self.due_at is not None and self.due_at <= self.created_at:
            raise IAGConfigInvalid("due_at must be after created_at")
        return self


class IAGConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dormant_days: int = 90
    privileged_roles: list[str] = Field(default_factory=list)
    peer_baseline: str | None = None
    review_default_due_days: int = 30

    @field_validator("dormant_days", "review_default_due_days")
    @classmethod
    def _positive_days(cls, value: int, info: ValidationInfo) -> int:
        return _require_positive_int(value, field=info.field_name or "days")

    @field_validator("privileged_roles")
    @classmethod
    def _privileged_roles(cls, values: list[str], info: ValidationInfo) -> list[str]:
        if not values:
            return values
        out = _require_nonempty_list(values, field="privileged_roles")
        known = _known_privileged_roles(info)
        if known is not None:
            unknown = sorted(set(out) - known)
            if unknown:
                raise IAGConfigInvalid(f"unknown privileged_roles: {', '.join(unknown)}")
        return out

    @field_validator("peer_baseline")
    @classmethod
    def _peer_baseline(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_nonempty(value, field="peer_baseline")
