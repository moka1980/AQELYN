"""Identity threat models and structural dignity boundaries (EA-0027 I1)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aqelyn.conventions import ActorRef, new_id, require_tenant_id, require_typed_id
from aqelyn.conventions.errors import (
    IdentityBasisMissing,
    IdentityCorroborationMissing,
    IdThreatConfigInvalid,
)
from aqelyn.decision.models import Derivation

DetectionType = Literal[
    "impossible_travel",
    "credential_reuse",
    "session_hijack",
    "first_time_privilege_use",
    "dormant_account_use",
    "mfa_anomaly",
]
IdentityBasisKind = Literal["profile", "entitlement", "event"]
IdentityDetectionStatus = Literal["open", "reviewed", "closed"]

VALID_DETECTION_TYPES: Final[frozenset[str]] = frozenset(
    (
        "impossible_travel",
        "credential_reuse",
        "session_hijack",
        "first_time_privilege_use",
        "dormant_account_use",
        "mfa_anomaly",
    )
)
VALID_BASIS_KINDS: Final[frozenset[str]] = frozenset(("profile", "entitlement", "event"))
VALID_DETECTION_STATUS: Final[frozenset[str]] = frozenset(("open", "reviewed", "closed"))

_ACCOUNT_SUBJECT_NAMESPACES: Final[frozenset[str]] = frozenset(
    ("acct", "account", "credential", "session")
)


def _nonempty(value: str, *, field: str) -> str:
    if not value.strip():
        raise IdThreatConfigInvalid(f"{field} must not be empty")
    return value


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise IdThreatConfigInvalid(f"{field} must be >= 1")
    return value


def _unit(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise IdThreatConfigInvalid(f"{field} must be in [0,1]")
    selected = float(value)
    if not math.isfinite(selected) or selected < 0.0 or selected > 1.0:
        raise IdThreatConfigInvalid(f"{field} must be in [0,1]")
    return selected


def _account_subject_ref(value: str) -> str:
    selected = _nonempty(value, field="subject_ref")
    namespace, separator, identifier = selected.partition(":")
    if separator != ":" or namespace not in _ACCOUNT_SUBJECT_NAMESPACES or not identifier.strip():
        raise IdThreatConfigInvalid("subject_ref must identify an account, credential, or session")
    return selected


def _detection_type(value: str) -> str:
    if value not in VALID_DETECTION_TYPES:
        raise IdThreatConfigInvalid(f"unknown identity detection type: {value!r}")
    return value


class SignalRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    ref: str
    as_of: datetime
    evidence_id: str | None = None

    @field_validator("kind", "ref")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="signal ref")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="evidence_id")


class IdentityBasis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    ref: str
    as_of: datetime
    evidence_id: str | None = None

    @field_validator("kind")
    @classmethod
    def _kind(cls, value: str) -> str:
        if value not in VALID_BASIS_KINDS:
            raise IdThreatConfigInvalid(f"unknown identity basis kind: {value!r}")
        return value

    @field_validator("ref")
    @classmethod
    def _ref(cls, value: str) -> str:
        return _nonempty(value, field="identity basis ref")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="evidence_id")


class IdentityObservation(BaseModel):
    """Handed-in observed signals plus the versions needed for reproducibility."""

    model_config = ConfigDict(extra="forbid")

    subject_ref: str
    identity_id: str
    detection_type: str
    signals: list[SignalRef]
    profile_ref: str
    profile_version: int
    rule_ref: str
    rule_version: int
    detected_at: datetime

    @field_validator("subject_ref")
    @classmethod
    def _subject_ref(cls, value: str) -> str:
        return _account_subject_ref(value)

    @field_validator("identity_id")
    @classmethod
    def _identity_id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="identity_id")

    @field_validator("detection_type")
    @classmethod
    def _observation_type(cls, value: str) -> str:
        return _detection_type(value)

    @field_validator("profile_ref")
    @classmethod
    def _profile_ref(cls, value: str) -> str:
        return require_typed_id(value, "prf", field="profile_ref")

    @field_validator("profile_version", "rule_version", mode="before")
    @classmethod
    def _version(cls, value: object) -> int:
        return _positive_int(value, field="version")

    @field_validator("rule_ref")
    @classmethod
    def _rule_ref(cls, value: str) -> str:
        return _nonempty(value, field="rule_ref")


class IdentityDetection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("idt"))
    tenant_id: str | None = None
    subject_ref: str
    detection_type: str
    statement: str
    corroboration: list[SignalRef]
    confidence: float
    basis: list[IdentityBasis]
    derivation: Derivation
    profile_ref: str | None = None
    entitlement_refs: list[str] = Field(default_factory=list)
    status: str = "open"
    detected_at: datetime

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "idt", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("subject_ref")
    @classmethod
    def _subject_ref(cls, value: str) -> str:
        return _account_subject_ref(value)

    @field_validator("detection_type")
    @classmethod
    def _identity_detection_type(cls, value: str) -> str:
        return _detection_type(value)

    @field_validator("statement")
    @classmethod
    def _statement(cls, value: str) -> str:
        return _nonempty(value, field="statement")

    @field_validator("corroboration")
    @classmethod
    def _corroboration(cls, values: list[SignalRef]) -> list[SignalRef]:
        if independent_signal_count(values) < 2:
            raise IdentityCorroborationMissing(
                "identity detection requires at least two independent signals"
            )
        return values

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, value: object) -> float:
        return _unit(value, field="confidence")

    @field_validator("basis")
    @classmethod
    def _basis(cls, values: list[IdentityBasis]) -> list[IdentityBasis]:
        if not values:
            raise IdentityBasisMissing("identity detection requires at least one basis")
        return values

    @field_validator("profile_ref")
    @classmethod
    def _profile_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "prf", field="profile_ref")

    @field_validator("entitlement_refs")
    @classmethod
    def _entitlement_refs(cls, values: list[str]) -> list[str]:
        for value in values:
            require_typed_id(value, "obj", field="entitlement_refs")
        if len(values) != len(set(values)):
            raise IdThreatConfigInvalid("entitlement_refs must not contain duplicates")
        return values

    @field_validator("status")
    @classmethod
    def _status(cls, value: str) -> str:
        if value not in VALID_DETECTION_STATUS:
            raise IdThreatConfigInvalid(f"unknown identity detection status: {value!r}")
        return value


class IdentityReview(BaseModel):
    """One evidenced human review appended without mutating the detection."""

    model_config = ConfigDict(extra="forbid")

    detection_id: str
    tenant_id: str | None = None
    outcome: str
    reviewed_by: ActorRef
    reviewed_at: datetime
    evidence_id: str

    @field_validator("detection_id")
    @classmethod
    def _detection_id(cls, value: str) -> str:
        return require_typed_id(value, "idt", field="detection_id")

    @field_validator("tenant_id")
    @classmethod
    def _review_tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("outcome")
    @classmethod
    def _outcome(cls, value: str) -> str:
        return _nonempty(value, field="review outcome")

    @field_validator("evidence_id")
    @classmethod
    def _review_evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")


class IdThreatConfig(BaseModel):
    # Frozen: the dignity floors are not knobs, so a constructed config cannot be
    # lowered afterwards (EA-0027 S3/§11). `assert_dignity_floors` re-checks at the
    # point of use, for configs minted through validation-skipping pydantic APIs.
    model_config = ConfigDict(extra="forbid", frozen=True)

    min_corroboration: int
    min_confidence: float
    platform_default: float

    @field_validator("min_corroboration", mode="before")
    @classmethod
    def _min_corroboration(cls, value: object) -> int:
        return _positive_int(value, field="min_corroboration")

    @field_validator("min_confidence", "platform_default", mode="before")
    @classmethod
    def _confidence_floor(cls, value: object) -> float:
        return _unit(value, field="confidence floor")

    @model_validator(mode="after")
    def _dignity_floors(self) -> IdThreatConfig:
        assert_dignity_floors(self)
        return self


def assert_dignity_floors(config: IdThreatConfig) -> None:
    """Raise unless the config honours both dignity floors (EA-0027 S3/§11).

    Checked at construction *and* at every use: `model_construct`/`model_copy`
    skip validation by design, so a config that never passed the constructor can
    still exist. A lowered floor must not be usable, however it was minted.
    """
    if config.min_corroboration < 2:
        raise IdThreatConfigInvalid("min_corroboration must be >= 2")
    if config.min_confidence <= config.platform_default:
        raise IdThreatConfigInvalid("min_confidence must be strictly greater than platform_default")


def independent_signal_count(signals: list[SignalRef]) -> int:
    """Count independent occurrences by shared ref or shared evidence (ECR-0017)."""

    if not signals:
        return 0
    parents = list(range(len(signals)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    seen_refs: dict[str, int] = {}
    seen_evidence: dict[str, int] = {}
    for index, signal in enumerate(signals):
        if signal.ref in seen_refs:
            union(index, seen_refs[signal.ref])
        else:
            seen_refs[signal.ref] = index
        if signal.evidence_id is not None:
            if signal.evidence_id in seen_evidence:
                union(index, seen_evidence[signal.evidence_id])
            else:
                seen_evidence[signal.evidence_id] = index
    return len({find(index) for index in range(len(signals))})
