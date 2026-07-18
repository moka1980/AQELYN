"""Identity threat models and structural dignity boundaries (EA-0027 I1)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aqelyn.conventions import new_id, require_tenant_id, require_typed_id
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
        selected = _nonempty(value, field="subject_ref")
        namespace, separator, identifier = selected.partition(":")
        if (
            separator != ":"
            or namespace not in _ACCOUNT_SUBJECT_NAMESPACES
            or not identifier.strip()
        ):
            raise IdThreatConfigInvalid(
                "subject_ref must identify an account, credential, or session"
            )
        return selected

    @field_validator("detection_type")
    @classmethod
    def _detection_type(cls, value: str) -> str:
        if value not in VALID_DETECTION_TYPES:
            raise IdThreatConfigInvalid(f"unknown identity detection type: {value!r}")
        return value

    @field_validator("statement")
    @classmethod
    def _statement(cls, value: str) -> str:
        return _nonempty(value, field="statement")

    @field_validator("corroboration")
    @classmethod
    def _corroboration(cls, values: list[SignalRef]) -> list[SignalRef]:
        independent = {(signal.kind, signal.ref) for signal in values}
        if len(values) < 2 or len(independent) < 2:
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


class IdThreatConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
