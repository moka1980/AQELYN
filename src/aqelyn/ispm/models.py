"""Identity Security Posture Management models and config (EA-0033 G1)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aqelyn.assetconfig.comparators import (
    Comparator,
    validate_comparator,
    validate_regex_pattern,
)
from aqelyn.conventions import ActorRef, new_id, require_tenant_id, require_typed_id
from aqelyn.conventions.errors import (
    BaselineConfigInvalid,
    ISPMConfigInvalid,
    SchemaValidationError,
)
from aqelyn.decision.models import Derivation
from aqelyn.findings.models import Severity
from aqelyn.iag.models import AccessRisk

IdentityKind = Literal[
    "human",
    "service",
    "machine",
    "application",
    "federated",
    "temporary",
]
NormalizedIdentityKind = IdentityKind | Literal["unknown"]
ControlState = Literal["present", "absent", "unknown"]
FactorStatus = Literal["known", "unknown"]
DriftStatus = Literal["pass", "fail", "unknown"]
AssessmentStatus = Literal["computed", "truncated", "pending"]
AccessRelationType = Literal["has_role", "grants_entitlement", "member_of"]

VALID_IDENTITY_KINDS: Final[frozenset[str]] = frozenset(
    ("human", "service", "machine", "application", "federated", "temporary")
)
VALID_CONTROL_STATES: Final[frozenset[str]] = frozenset(("present", "absent", "unknown"))
VALID_ASSESSMENT_STATUSES: Final[frozenset[str]] = frozenset(("computed", "truncated", "pending"))
VALID_ACCESS_RELATION_TYPES: Final[frozenset[str]] = frozenset(
    ("has_role", "grants_entitlement", "member_of")
)
ISPM_EVENTS: Final[dict[str, int]] = {
    "aqelyn.ispm.identity_normalized": 1,
    "aqelyn.ispm.posture_scored": 1,
    "aqelyn.ispm.posture_drift_detected": 1,
    "aqelyn.ispm.controls_unknown": 1,
}


def _nonempty(value: str, *, field: str) -> str:
    if not value.strip():
        raise ISPMConfigInvalid(f"{field} must not be empty")
    return value


def _optional_nonempty(value: str | None, *, field: str) -> str | None:
    if value is None:
        return None
    return _nonempty(value, field=field)


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ISPMConfigInvalid(f"{field} must be >= 1")
    return value


def _nonnegative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ISPMConfigInvalid(f"{field} must be >= 0")
    return value


def _finite(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ISPMConfigInvalid(f"{field} must be finite")
    selected = float(value)
    if not math.isfinite(selected):
        raise ISPMConfigInvalid(f"{field} must be finite")
    return selected


def _unit(value: object, *, field: str) -> float:
    selected = _finite(value, field=field)
    if selected < 0.0 or selected > 1.0:
        raise ISPMConfigInvalid(f"{field} must be in [0,1]")
    return selected


def _score(value: object) -> float:
    selected = _finite(value, field="posture score")
    if selected < 0.0 or selected > 100.0:
        raise ISPMConfigInvalid("posture score must be in [0,100]")
    return selected


def _unique_nonempty(values: list[str], *, field: str) -> list[str]:
    for value in values:
        _nonempty(value, field=field)
    if len(values) != len(set(values)):
        raise ISPMConfigInvalid(f"{field} must not contain duplicates")
    return list(values)


class ControlFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: ControlState = "unknown"
    established_by: str | None = None
    evidence_id: str | None = None
    reason: str

    @field_validator("established_by")
    @classmethod
    def _established_by(cls, value: str | None) -> str | None:
        return _optional_nonempty(value, field="control established_by")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="control evidence_id")

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return _nonempty(value, field="control reason")

    @model_validator(mode="after")
    def _evidence_consistency(self) -> ControlFact:
        has_source = self.established_by is not None
        has_evidence = self.evidence_id is not None
        if has_source != has_evidence:
            raise ISPMConfigInvalid(
                "control established_by and evidence_id must be supplied together"
            )
        if self.state != "unknown" and not has_source:
            raise ISPMConfigInvalid("known control state requires source and evidence")
        return self


def _unknown_control(reason: str) -> ControlFact:
    return ControlFact(reason=reason)


class IdentityControls(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mfa: ControlFact = Field(
        default_factory=lambda: _unknown_control("MFA state has not been established.")
    )
    lifecycle: ControlFact = Field(
        default_factory=lambda: _unknown_control("Lifecycle state has not been established.")
    )
    last_activity: ControlFact = Field(
        default_factory=lambda: _unknown_control("Last activity has not been established.")
    )


class IdentityAccountDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: str
    display_name: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime
    evidence_id: str

    @field_validator("external_id", "display_name")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="account descriptor field")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="account evidence_id")


class IdentityAccessEdgeDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_external_id: str
    to_object_id: str
    relation_type: AccessRelationType
    observed_at: datetime
    evidence_id: str

    @field_validator("from_external_id")
    @classmethod
    def _from_external_id(cls, value: str) -> str:
        return _nonempty(value, field="access edge from_external_id")

    @field_validator("to_object_id")
    @classmethod
    def _to_object_id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="access edge to_object_id")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="access edge evidence_id")


class IdentityDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    provider: str
    external_id: str
    identity_kind: IdentityKind | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    controls: dict[str, Any] = Field(default_factory=dict)
    accounts: list[IdentityAccountDescriptor] = Field(default_factory=list)
    access_edges: list[IdentityAccessEdgeDescriptor] = Field(default_factory=list)
    observed_at: datetime
    evidence_id: str | None = None

    @field_validator("source_id")
    @classmethod
    def _source_id(cls, value: str) -> str:
        return require_typed_id(value, "src", field="source_id")

    @field_validator("provider", "external_id")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="identity descriptor field")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="identity evidence_id")

    @field_validator("accounts")
    @classmethod
    def _accounts(cls, values: list[IdentityAccountDescriptor]) -> list[IdentityAccountDescriptor]:
        external_ids = [account.external_id for account in values]
        if len(external_ids) != len(set(external_ids)):
            raise ISPMConfigInvalid("account external_ids must not contain duplicates")
        return values

    @model_validator(mode="after")
    def _access_edge_sources(self) -> IdentityDescriptor:
        local_refs = {self.external_id, *(account.external_id for account in self.accounts)}
        edge_keys: list[tuple[str, str, str]] = []
        for edge in self.access_edges:
            if edge.from_external_id not in local_refs:
                raise ISPMConfigInvalid(
                    "access edge from_external_id must name the identity or a supplied account"
                )
            edge_keys.append((edge.from_external_id, edge.to_object_id, edge.relation_type))
        if len(edge_keys) != len(set(edge_keys)):
            raise ISPMConfigInvalid("access edge claims must not contain duplicates")
        return self


class NormalizedIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    tenant_id: str | None = None
    external_id: str
    provider: str
    identity_kind: NormalizedIdentityKind = "unknown"
    account_object_ids: list[str] = Field(default_factory=list)
    relationship_ids: list[str] = Field(default_factory=list)
    controls: IdentityControls = Field(default_factory=IdentityControls)
    field_provenance: dict[str, str]
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    flagged: bool = False
    evidence_id: str

    @field_validator("object_id")
    @classmethod
    def _object_id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="object_id")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("external_id", "provider")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="normalized identity field")

    @field_validator("account_object_ids")
    @classmethod
    def _account_object_ids(cls, values: list[str]) -> list[str]:
        selected = [require_typed_id(value, "obj", field="account_object_ids") for value in values]
        if len(selected) != len(set(selected)):
            raise ISPMConfigInvalid("account_object_ids must not contain duplicates")
        return selected

    @field_validator("relationship_ids")
    @classmethod
    def _relationship_ids(cls, values: list[str]) -> list[str]:
        selected = [require_typed_id(value, "rel", field="relationship_ids") for value in values]
        if len(selected) != len(set(selected)):
            raise ISPMConfigInvalid("relationship_ids must not contain duplicates")
        return selected

    @field_validator("field_provenance")
    @classmethod
    def _field_provenance(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ISPMConfigInvalid("field_provenance must not be empty")
        return {
            _nonempty(key, field="field_provenance key"): _nonempty(
                source, field="field_provenance source"
            )
            for key, source in value.items()
        }

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")

    @model_validator(mode="after")
    def _graph_refs_consistent(self) -> NormalizedIdentity:
        if self.object_id in self.account_object_ids:
            raise ISPMConfigInvalid("identity object_id cannot also be an account object id")
        if len(self.relationship_ids) < len(self.account_object_ids):
            raise ISPMConfigInvalid("every normalized account requires a has_account relationship")
        if self.identity_kind == "unknown" and not self.flagged:
            raise ISPMConfigInvalid("unknown identity_kind must be flagged")
        if (
            any(bool(conflict.get("unresolved")) for conflict in self.conflicts)
            and not self.flagged
        ):
            raise ISPMConfigInvalid("unresolved identity conflicts must be flagged")
        return self


class PostureFactor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: float | None = None
    weight: float
    status: FactorStatus
    source_ref: dict[str, Any]
    reason: str

    @field_validator("name", "reason")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="posture factor field")

    @field_validator("value", mode="before")
    @classmethod
    def _value(cls, value: object) -> float | None:
        if value is None:
            return None
        return _finite(value, field="posture factor value")

    @field_validator("weight", mode="before")
    @classmethod
    def _weight(cls, value: object) -> float:
        return _unit(value, field="posture factor weight")

    @field_validator("source_ref")
    @classmethod
    def _source_ref(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ISPMConfigInvalid("posture factor source_ref must not be empty")
        return dict(value)

    @model_validator(mode="after")
    def _status_consistency(self) -> PostureFactor:
        if self.status == "known" and self.value is None:
            raise ISPMConfigInvalid("known posture factor requires a value")
        if self.status == "unknown" and self.value is not None:
            raise ISPMConfigInvalid("unknown posture factor cannot carry a value")
        return self


class IdentityPostureScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("ips"))
    tenant_id: str | None = None
    subject_ref: str
    score: float
    factors: list[PostureFactor]
    iag_risks: list[AccessRisk] = Field(default_factory=list)
    derivation: Derivation
    confidence: float
    statement: str
    computed_at: datetime
    evidence_id: str

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "ips", field="id")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("subject_ref")
    @classmethod
    def _subject_ref(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="subject_ref")

    @field_validator("score", mode="before")
    @classmethod
    def _score(cls, value: object) -> float:
        return _score(value)

    @field_validator("factors")
    @classmethod
    def _factors(cls, values: list[PostureFactor]) -> list[PostureFactor]:
        if not values:
            raise ISPMConfigInvalid("posture score requires factors")
        names = [factor.name for factor in values]
        if len(names) != len(set(names)):
            raise ISPMConfigInvalid("posture factor names must be unique")
        return values

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, value: object) -> float:
        return _unit(value, field="posture confidence")

    @field_validator("statement")
    @classmethod
    def _statement(cls, value: str) -> str:
        return _nonempty(value, field="posture statement")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")


class IdentityBaselineEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    expected: Any
    comparator: Comparator
    severity: Severity

    @field_validator("key")
    @classmethod
    def _key(cls, value: str) -> str:
        return _nonempty(value, field="baseline entry key")

    @field_validator("comparator", mode="before")
    @classmethod
    def _comparator(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ISPMConfigInvalid("baseline comparator must be a string")
        try:
            return validate_comparator(value)
        except BaselineConfigInvalid as exc:
            raise ISPMConfigInvalid(str(exc)) from exc

    @model_validator(mode="after")
    def _regex_safe(self) -> IdentityBaselineEntry:
        if self.comparator == "regex":
            try:
                validate_regex_pattern(self.expected)
            except BaselineConfigInvalid as exc:
                raise ISPMConfigInvalid(str(exc)) from exc
        return self


class IdentityBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("ibl"))
    tenant_id: str | None = None
    name: str
    version: int = 1
    identity_kind: IdentityKind
    entries: list[IdentityBaselineEntry]
    approved_by: ActorRef | None = None
    approved_at: datetime | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "ibl", field="id")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _nonempty(value, field="baseline name")

    @field_validator("version", mode="before")
    @classmethod
    def _version(cls, value: object) -> int:
        return _positive_int(value, field="baseline version")

    @field_validator("entries")
    @classmethod
    def _entries(cls, values: list[IdentityBaselineEntry]) -> list[IdentityBaselineEntry]:
        if not values:
            raise ISPMConfigInvalid("identity baseline requires entries")
        keys = [entry.key for entry in values]
        if len(keys) != len(set(keys)):
            raise ISPMConfigInvalid("identity baseline entry keys must be unique")
        return values

    @model_validator(mode="after")
    def _approval_consistency(self) -> IdentityBaseline:
        if (self.approved_by is None) != (self.approved_at is None):
            raise ISPMConfigInvalid(
                "baseline approval actor and timestamp must be supplied together"
            )
        return self


class IdentityDriftItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_id: str
    key: str
    expected: Any
    observed: Any = None
    status: DriftStatus
    reason: str

    @field_validator("identity_id")
    @classmethod
    def _identity_id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="identity_id")

    @field_validator("key", "reason")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="identity drift field")


class IdentityDriftSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("idr"))
    tenant_id: str | None = None
    run_at: datetime
    baseline_id: str
    evaluated: int
    passed: int
    failed: int
    unknown: int
    items: list[IdentityDriftItem] = Field(default_factory=list)
    evidence_id: str

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "idr", field="id")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("baseline_id")
    @classmethod
    def _baseline_id(cls, value: str) -> str:
        return require_typed_id(value, "ibl", field="baseline_id")

    @field_validator("evaluated", "passed", "failed", "unknown", mode="before")
    @classmethod
    def _counts(cls, value: object) -> int:
        return _nonnegative_int(value, field="identity drift count")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")

    @model_validator(mode="after")
    def _counts_consistent(self) -> IdentityDriftSnapshot:
        if self.passed + self.failed + self.unknown != self.evaluated:
            raise ISPMConfigInvalid("drift status counts must equal evaluated")
        if len(self.items) != self.evaluated:
            raise ISPMConfigInvalid("drift item count must equal evaluated")
        actual = {
            "pass": sum(item.status == "pass" for item in self.items),
            "fail": sum(item.status == "fail" for item in self.items),
            "unknown": sum(item.status == "unknown" for item in self.items),
        }
        if actual != {"pass": self.passed, "fail": self.failed, "unknown": self.unknown}:
            raise ISPMConfigInvalid("drift item statuses must match summary counts")
        keys = [(item.identity_id, item.key) for item in self.items]
        if len(keys) != len(set(keys)):
            raise ISPMConfigInvalid("drift items must not duplicate identity/key pairs")
        return self


class ISPMAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("ipa"))
    tenant_id: str | None = None
    run_at: datetime
    scope: dict[str, Any] = Field(default_factory=dict)
    identities_evaluated: int = 0
    scored: int = 0
    unknown_controls: int = 0
    drift_snapshot_id: str | None = None
    status: AssessmentStatus = "pending"
    inventory_complete: bool = False
    inventory_note: str = "Inventory completeness has not been established."
    evidence_id: str | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "ipa", field="id")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("identities_evaluated", "scored", "unknown_controls", mode="before")
    @classmethod
    def _counts(cls, value: object) -> int:
        return _nonnegative_int(value, field="ISPM assessment count")

    @field_validator("drift_snapshot_id")
    @classmethod
    def _drift_snapshot_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "idr", field="drift_snapshot_id")

    @field_validator("inventory_note")
    @classmethod
    def _inventory_note(cls, value: str) -> str:
        return _nonempty(value, field="inventory_note")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="evidence_id")

    @model_validator(mode="after")
    def _status_consistency(self) -> ISPMAssessment:
        result_fields = (
            self.identities_evaluated,
            self.scored,
            self.unknown_controls,
            self.drift_snapshot_id is not None,
        )
        if self.status == "pending":
            if any(result_fields) or self.evidence_id is not None or self.inventory_complete:
                raise ISPMConfigInvalid("pending assessment cannot carry completed results")
        elif self.evidence_id is None:
            raise ISPMConfigInvalid("computed or truncated assessment requires evidence_id")
        if self.scored > self.identities_evaluated:
            raise ISPMConfigInvalid("scored cannot exceed identities_evaluated")
        if self.unknown_controls > self.identities_evaluated * 3:
            raise ISPMConfigInvalid("unknown_controls cannot exceed three per identity")
        return self


class ISPMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    factor_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "iag_risk": 0.5,
            "mfa": 0.2,
            "lifecycle": 0.15,
            "last_activity": 0.15,
        }
    )
    baseline_ids: list[str] = Field(default_factory=list)
    stale_activity_days: int = 90
    batch_size: int = 100
    page_budget: int = 10_000

    @field_validator("factor_weights", mode="before")
    @classmethod
    def _factor_weights(cls, value: object) -> dict[str, float]:
        if not isinstance(value, dict) or not value:
            raise ISPMConfigInvalid("factor_weights must be a non-empty object")
        selected: dict[str, float] = {}
        for name, weight in value.items():
            if not isinstance(name, str):
                raise ISPMConfigInvalid("factor_weights keys must be strings")
            key = _nonempty(name, field="factor weight name")
            selected[key] = _unit(weight, field=f"factor_weights[{key!r}]")
        if not math.isclose(sum(selected.values()), 1.0, rel_tol=0.0, abs_tol=1e-6):
            raise ISPMConfigInvalid("factor_weights must sum to 1 within 1e-6")
        return selected

    @field_validator("baseline_ids")
    @classmethod
    def _baseline_ids(cls, values: list[str]) -> list[str]:
        try:
            selected = [require_typed_id(value, "ibl", field="baseline_ids") for value in values]
        except SchemaValidationError as exc:
            raise ISPMConfigInvalid("baseline_ids must contain known ibl_ ids") from exc
        if len(selected) != len(set(selected)):
            raise ISPMConfigInvalid("baseline_ids must not contain duplicates")
        return selected

    @field_validator("stale_activity_days", "batch_size", "page_budget", mode="before")
    @classmethod
    def _positive_config(cls, value: object) -> int:
        return _positive_int(value, field="ISPM config value")
