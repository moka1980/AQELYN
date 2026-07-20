"""Data Security Posture Management models and P1 config validation."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Final, Literal
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aqelyn.conventions import new_id, require_tenant_id, require_typed_id
from aqelyn.conventions.errors import DSPMConfigInvalid
from aqelyn.decision.models import Derivation
from aqelyn.exposure.models import Reachability
from aqelyn.iag.models import AccessPath, AccessRisk
from aqelyn.lake.models import VALID_CLASSIFICATIONS, Classification, SchemaType
from aqelyn.policy import Condition

__all__ = ["VALID_CLASSIFICATIONS", "Classification", "Reachability", "SchemaType"]

Sensitivity = Classification | Literal["unknown"]
ClassificationStatus = Literal["known", "unknown", "conflict"]
AssetClassificationStatus = Literal["complete", "partial", "unknown", "conflict"]
ExposureState = Literal["confirmed", "classification_gap", "reachability_pending"]
CoverageStatus = Literal["complete", "truncated", "pending"]
ClassificationSignalKind = Literal["field_name", "existing_tag", "detector_match"]
DataStoreType = Literal["bucket", "database", "fileshare", "warehouse", "other"]
DataAccessClaimKind = Literal["observed", "granted"]
AccessContextStatus = Literal["known", "pending"]

VALID_SENSITIVITIES: Final[frozenset[str]] = VALID_CLASSIFICATIONS | {"unknown"}
VALID_CLASSIFICATION_STATUSES: Final[frozenset[str]] = frozenset(("known", "unknown", "conflict"))
VALID_ASSET_CLASSIFICATION_STATUSES: Final[frozenset[str]] = frozenset(
    ("complete", "partial", "unknown", "conflict")
)
VALID_EXPOSURE_STATES: Final[frozenset[str]] = frozenset(
    ("confirmed", "classification_gap", "reachability_pending")
)
VALID_COVERAGE_STATUSES: Final[frozenset[str]] = frozenset(("complete", "truncated", "pending"))
VALID_STORE_TYPES: Final[frozenset[str]] = frozenset(
    ("bucket", "database", "fileshare", "warehouse", "other")
)
_ORDERED_CLASSIFICATIONS: Final[tuple[Classification, ...]] = (
    "public",
    "internal",
    "pii",
    "secret",
)
_CREDENTIAL_QUERY_KEYS: Final[frozenset[str]] = frozenset(
    (
        "accesskey",
        "accesskeyid",
        "apikey",
        "authorization",
        "credential",
        "password",
        "secret",
        "sig",
        "signature",
        "token",
        "xamzcredential",
        "xamzsecuritytoken",
        "xamzsignature",
    )
)


def _nonempty(value: str, *, field: str) -> str:
    if not value.strip():
        raise DSPMConfigInvalid(f"{field} must not be empty")
    return value


def _optional_nonempty(value: str | None, *, field: str) -> str | None:
    if value is None:
        return None
    return _nonempty(value, field=field)


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DSPMConfigInvalid(f"{field} must be >= 1")
    return value


def _nonnegative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DSPMConfigInvalid(f"{field} must be >= 0")
    return value


def _unit(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise DSPMConfigInvalid(f"{field} must be in [0,1]")
    selected = float(value)
    if not math.isfinite(selected) or selected < 0.0 or selected > 1.0:
        raise DSPMConfigInvalid(f"{field} must be in [0,1]")
    return selected


def _score(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise DSPMConfigInvalid("data exposure score must be in [0,100]")
    selected = float(value)
    if not math.isfinite(selected) or selected < 0.0 or selected > 100.0:
        raise DSPMConfigInvalid("data exposure score must be in [0,100]")
    return selected


def _unique_nonempty(values: list[str], *, field: str, required: bool = False) -> list[str]:
    if required and not values:
        raise DSPMConfigInvalid(f"{field} must not be empty")
    for value in values:
        _nonempty(value, field=field)
    if len(values) != len(set(values)):
        raise DSPMConfigInvalid(f"{field} must not contain duplicates")
    return list(values)


def _typed_ids(values: list[str], *, prefix: str, field: str, required: bool = False) -> list[str]:
    if required and not values:
        raise DSPMConfigInvalid(f"{field} must not be empty")
    for value in values:
        require_typed_id(value, prefix, field=field)
    if len(values) != len(set(values)):
        raise DSPMConfigInvalid(f"{field} must not contain duplicates")
    return list(values)


def _query_key_token(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _resource_ref(value: str) -> str:
    selected = _nonempty(value, field="resource_ref")
    parsed = urlsplit(selected)
    if parsed.username is not None or parsed.password is not None:
        raise DSPMConfigInvalid("resource_ref must not contain URL credentials")
    for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
        if _query_key_token(key) in _CREDENTIAL_QUERY_KEYS:
            raise DSPMConfigInvalid("resource_ref must not contain credential query parameters")
    return selected


class DSPMScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_types: list[str] = Field(default_factory=list)
    flagged: bool | None = None
    limit: int = 100
    cursor: str | None = None

    @field_validator("store_types")
    @classmethod
    def _store_types(cls, values: list[str]) -> list[str]:
        return _unique_nonempty(values, field="scope store_types")

    @field_validator("limit", mode="before")
    @classmethod
    def _limit(cls, value: object) -> int:
        return _positive_int(value, field="scope limit")

    @field_validator("cursor")
    @classmethod
    def _cursor(cls, value: str | None) -> str | None:
        return _optional_nonempty(value, field="scope cursor")


class DataStoreLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    account_ref: str | None = None
    region: str | None = None
    resource_ref: str

    @field_validator("provider")
    @classmethod
    def _provider(cls, value: str) -> str:
        return _nonempty(value, field="location provider")

    @field_validator("account_ref", "region")
    @classmethod
    def _optional_location(cls, value: str | None) -> str | None:
        return _optional_nonempty(value, field="location field")

    @field_validator("resource_ref")
    @classmethod
    def _safe_resource_ref(cls, value: str) -> str:
        return _resource_ref(value)


class ClassificationSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: ClassificationSignalKind
    detector_ref: str
    match_count: int
    evidence_id: str

    @field_validator("id", "detector_ref")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return _nonempty(value, field="classification signal field")

    @field_validator("match_count", mode="before")
    @classmethod
    def _match_count(cls, value: object) -> int:
        return _nonnegative_int(value, field="match_count")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")


class DataFieldDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    data_type: SchemaType
    signals: list[ClassificationSignal] = Field(default_factory=list)
    existing_classification: Classification | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _nonempty(value, field="field name")

    @field_validator("signals")
    @classmethod
    def _signals(cls, values: list[ClassificationSignal]) -> list[ClassificationSignal]:
        ids = [signal.id for signal in values]
        if len(ids) != len(set(ids)):
            raise DSPMConfigInvalid("field signal ids must not contain duplicates")
        return values


class DataAccessClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_id: str
    claim_kind: DataAccessClaimKind
    evidence_id: str

    @field_validator("identity_id")
    @classmethod
    def _identity_id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="identity_id")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")


class ReachabilityClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reachability: Reachability
    evidence_id: str
    reason: str

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return _nonempty(value, field="reachability reason")


class DataStoreDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_id: str
    tenant_id: str | None = None
    store_type: DataStoreType
    location: DataStoreLocation
    fields: list[DataFieldDescriptor] = Field(default_factory=list)
    access_claims: list[DataAccessClaim] = Field(default_factory=list)
    reachability_claim: ReachabilityClaim | None = None
    source_id: str
    observed_at: datetime
    evidence_id: str

    @field_validator("store_id")
    @classmethod
    def _store_id(cls, value: str) -> str:
        return _nonempty(value, field="store_id")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("fields")
    @classmethod
    def _fields(cls, values: list[DataFieldDescriptor]) -> list[DataFieldDescriptor]:
        names = [field.name for field in values]
        if len(names) != len(set(names)):
            raise DSPMConfigInvalid("descriptor field names must not contain duplicates")
        return values

    @field_validator("access_claims")
    @classmethod
    def _access_claims(cls, values: list[DataAccessClaim]) -> list[DataAccessClaim]:
        keys = [(claim.identity_id, claim.claim_kind, claim.evidence_id) for claim in values]
        if len(keys) != len(set(keys)):
            raise DSPMConfigInvalid("access claims must not contain duplicates")
        return values

    @field_validator("source_id")
    @classmethod
    def _source_id(cls, value: str) -> str:
        return require_typed_id(value, "src", field="source_id")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")


class ClassificationCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classification: Classification
    source_ref: str
    reliability: float
    evidence_id: str

    @field_validator("source_ref")
    @classmethod
    def _source_ref(cls, value: str) -> str:
        return _nonempty(value, field="classification source_ref")

    @field_validator("reliability", mode="before")
    @classmethod
    def _reliability(cls, value: object) -> float:
        return _unit(value, field="classification reliability")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")


class ClassificationConflict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    candidates: list[ClassificationCandidate]
    resolved_by: str | None = None
    unresolved: bool

    @field_validator("field")
    @classmethod
    def _field(cls, value: str) -> str:
        return _nonempty(value, field="conflict field")

    @field_validator("candidates")
    @classmethod
    def _candidates(cls, values: list[ClassificationCandidate]) -> list[ClassificationCandidate]:
        if len(values) < 2:
            raise DSPMConfigInvalid("classification conflict requires at least two candidates")
        return values

    @field_validator("resolved_by")
    @classmethod
    def _resolved_by(cls, value: str | None) -> str | None:
        return _optional_nonempty(value, field="resolved_by")

    @model_validator(mode="after")
    def _resolution_consistency(self) -> ClassificationConflict:
        candidate_sources = {candidate.source_ref for candidate in self.candidates}
        if self.unresolved:
            if self.resolved_by is not None:
                raise DSPMConfigInvalid("unresolved conflicts cannot name resolved_by")
        elif self.resolved_by is None:
            raise DSPMConfigInvalid("resolved conflicts require resolved_by")
        elif self.resolved_by not in candidate_sources:
            raise DSPMConfigInvalid("resolved_by must name a conflict candidate source")
        return self


class FieldClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    classification: Sensitivity
    status: ClassificationStatus
    flagged: bool
    rule_refs: list[str] = Field(default_factory=list)
    confidence: float
    evidence_ids: list[str]
    reason: str

    @field_validator("field", "reason")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return _nonempty(value, field="field classification field")

    @field_validator("rule_refs")
    @classmethod
    def _rule_refs(cls, values: list[str]) -> list[str]:
        return _unique_nonempty(values, field="rule_refs")

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, value: object) -> float:
        return _unit(value, field="classification confidence")

    @field_validator("evidence_ids")
    @classmethod
    def _evidence_ids(cls, values: list[str]) -> list[str]:
        return _typed_ids(values, prefix="evd", field="evidence_ids", required=True)

    @model_validator(mode="after")
    def _status_consistency(self) -> FieldClassification:
        if self.status == "known":
            if self.classification == "unknown":
                raise DSPMConfigInvalid("known classification cannot be unknown")
        else:
            if self.classification != "unknown":
                raise DSPMConfigInvalid("unknown/conflict status requires unknown classification")
            if not self.flagged:
                raise DSPMConfigInvalid("unknown/conflict classification must be flagged")
        return self


class DataAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("dsa"))
    object_id: str
    inventory_ref: str
    tenant_id: str | None = None
    store_id: str
    store_type: str
    location: DataStoreLocation
    field_classifications: list[FieldClassification] = Field(default_factory=list)
    max_known_sensitivity: Classification | None = None
    classification_status: AssetClassificationStatus
    flagged: bool
    conflicts: list[ClassificationConflict] = Field(default_factory=list)
    access_claims: list[DataAccessClaim] = Field(default_factory=list)
    reachability_claim: ReachabilityClaim | None = None
    observed_at: datetime
    evidence_id: str
    version: int = 1

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "dsa", field="id", allow_empty=True)

    @field_validator("object_id")
    @classmethod
    def _object_id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="object_id")

    @field_validator("inventory_ref")
    @classmethod
    def _inventory_ref(cls, value: str) -> str:
        return require_typed_id(value, "ast", field="inventory_ref")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("store_id", "store_type")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return _nonempty(value, field="data asset field")

    @field_validator("field_classifications")
    @classmethod
    def _field_classifications(cls, values: list[FieldClassification]) -> list[FieldClassification]:
        names = [classification.field for classification in values]
        if len(names) != len(set(names)):
            raise DSPMConfigInvalid("field classifications must not contain duplicates")
        return values

    @field_validator("access_claims")
    @classmethod
    def _access_claims(cls, values: list[DataAccessClaim]) -> list[DataAccessClaim]:
        keys = [(claim.identity_id, claim.claim_kind, claim.evidence_id) for claim in values]
        if len(keys) != len(set(keys)):
            raise DSPMConfigInvalid("access claims must not contain duplicates")
        return values

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")

    @field_validator("version", mode="before")
    @classmethod
    def _version(cls, value: object) -> int:
        return _positive_int(value, field="data asset version")

    @model_validator(mode="after")
    def _classification_consistency(self) -> DataAsset:
        known: list[Classification] = [
            item.classification
            for item in self.field_classifications
            if item.status == "known" and item.classification != "unknown"
        ]
        non_known = [item for item in self.field_classifications if item.status != "known"]
        has_conflict = any(item.status == "conflict" for item in self.field_classifications) or any(
            conflict.unresolved for conflict in self.conflicts
        )
        expected_max: Classification | None = None
        for classification in _ORDERED_CLASSIFICATIONS:
            if classification in known:
                expected_max = classification
        if self.max_known_sensitivity != expected_max:
            raise DSPMConfigInvalid("max_known_sensitivity must match known field classifications")

        if self.classification_status == "complete":
            if not self.field_classifications or non_known or has_conflict:
                raise DSPMConfigInvalid("complete asset requires every field to be known")
        elif self.classification_status == "partial":
            if not known or not non_known or has_conflict:
                raise DSPMConfigInvalid("partial asset requires known and unknown fields")
            if not self.flagged:
                raise DSPMConfigInvalid("partial asset must be flagged")
        elif self.classification_status == "unknown":
            if known or has_conflict:
                raise DSPMConfigInvalid("unknown asset cannot carry known/conflict classification")
            if not self.flagged:
                raise DSPMConfigInvalid("unknown asset must be flagged")
        else:
            if not has_conflict:
                raise DSPMConfigInvalid("conflict asset requires an unresolved conflict")
            if not self.flagged:
                raise DSPMConfigInvalid("conflict asset must be flagged")
        return self


class DataExposure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("dxe"))
    tenant_id: str | None = None
    data_asset_id: str
    object_id: str
    exposure_ref: str
    sensitivity: Sensitivity
    reachability: Reachability
    state: ExposureState
    flagged: bool
    score: float | None = None
    derivation: Derivation | None = None
    access_evidence_ids: list[str] = Field(default_factory=list)
    reason: str
    evidence_ids: list[str]
    detected_at: datetime

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "dxe", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("data_asset_id")
    @classmethod
    def _data_asset_id(cls, value: str) -> str:
        return require_typed_id(value, "dsa", field="data_asset_id")

    @field_validator("object_id")
    @classmethod
    def _object_id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="object_id")

    @field_validator("exposure_ref")
    @classmethod
    def _exposure_ref(cls, value: str) -> str:
        return require_typed_id(value, "exp", field="exposure_ref")

    @field_validator("score", mode="before")
    @classmethod
    def _score(cls, value: object) -> float | None:
        if value is None:
            return None
        return _score(value)

    @field_validator("access_evidence_ids")
    @classmethod
    def _access_evidence_ids(cls, values: list[str]) -> list[str]:
        return _typed_ids(values, prefix="evd", field="access_evidence_ids")

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return _nonempty(value, field="data exposure reason")

    @field_validator("evidence_ids")
    @classmethod
    def _evidence_ids(cls, values: list[str]) -> list[str]:
        return _typed_ids(values, prefix="evd", field="evidence_ids", required=True)

    @model_validator(mode="after")
    def _state_consistency(self) -> DataExposure:
        if (self.score is None) != (self.derivation is None):
            raise DSPMConfigInvalid("score and derivation must be present together")
        if self.state == "confirmed":
            if self.sensitivity not in {"pii", "secret"}:
                raise DSPMConfigInvalid("confirmed exposure requires pii or secret sensitivity")
            if self.reachability == "unknown":
                raise DSPMConfigInvalid("confirmed exposure requires known reachability")
            if self.score is None:
                raise DSPMConfigInvalid("confirmed exposure requires score and derivation")
        elif self.state == "classification_gap":
            if self.sensitivity != "unknown" or self.reachability == "unknown":
                raise DSPMConfigInvalid(
                    "classification gap requires unknown sensitivity and known reachability"
                )
            self._require_flagged_unscored("classification gap")
        else:
            if self.reachability != "unknown":
                raise DSPMConfigInvalid("reachability pending requires unknown reachability")
            self._require_flagged_unscored("reachability pending")
        return self

    def _require_flagged_unscored(self, state: str) -> None:
        if not self.flagged:
            raise DSPMConfigInvalid(f"{state} must be flagged")
        if self.score is not None or self.derivation is not None:
            raise DSPMConfigInvalid(f"{state} must be unscored")


class DataAccessContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_asset_id: str
    status: AccessContextStatus
    claims: list[DataAccessClaim] = Field(default_factory=list)
    paths: list[AccessPath] = Field(default_factory=list)
    risks: list[AccessRisk] = Field(default_factory=list)
    truncated: bool = False
    reason: str

    @field_validator("data_asset_id")
    @classmethod
    def _data_asset_id(cls, value: str) -> str:
        return require_typed_id(value, "dsa", field="data_asset_id")

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return _nonempty(value, field="access context reason")

    @model_validator(mode="after")
    def _status_consistency(self) -> DataAccessContext:
        if self.status == "pending" and (self.paths or self.risks):
            raise DSPMConfigInvalid("pending access context cannot carry owner results")
        if self.status == "known" and not self.claims:
            raise DSPMConfigInvalid("known access context requires evidenced claims")
        return self


class DataPostureAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("dpa"))
    tenant_id: str | None = None
    run_at: datetime
    scope: DSPMScope
    coverage_status: CoverageStatus = "pending"
    coverage_reason: str | None = None
    next_cursor: str | None = None
    stores_evaluated: int = 0
    classified_fields: int = 0
    unknown_fields: int = 0
    exposure_ids: list[str] = Field(default_factory=list)
    gap_ids: list[str] = Field(default_factory=list)
    evidence_id: str | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "dpa", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("coverage_reason", "next_cursor")
    @classmethod
    def _optional_text(cls, value: str | None) -> str | None:
        return _optional_nonempty(value, field="assessment coverage field")

    @field_validator("stores_evaluated", "classified_fields", "unknown_fields", mode="before")
    @classmethod
    def _count(cls, value: object) -> int:
        return _nonnegative_int(value, field="assessment count")

    @field_validator("exposure_ids", "gap_ids")
    @classmethod
    def _exposure_ids(cls, values: list[str]) -> list[str]:
        return _typed_ids(values, prefix="dxe", field="assessment exposure ids")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="evidence_id")

    @model_validator(mode="after")
    def _coverage_consistency(self) -> DataPostureAssessment:
        has_results = any(
            (
                self.stores_evaluated,
                self.classified_fields,
                self.unknown_fields,
                len(self.exposure_ids),
                len(self.gap_ids),
            )
        )
        if self.coverage_status == "pending":
            if has_results or self.evidence_id is not None or self.next_cursor is not None:
                raise DSPMConfigInvalid("pending assessment cannot carry completed results")
            if self.coverage_reason is None:
                raise DSPMConfigInvalid("pending assessment requires coverage_reason")
        elif self.coverage_status == "truncated":
            if self.next_cursor is None or self.coverage_reason is None:
                raise DSPMConfigInvalid("truncated assessment requires cursor and reason")
        elif self.next_cursor is not None:
            raise DSPMConfigInvalid("complete assessment cannot carry next_cursor")
        return self


class ClassifierRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    condition: Condition
    classification: Classification
    reason: str

    @field_validator("id", "reason")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return _nonempty(value, field="classifier rule field")


class DSPMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classifier_rules: list[ClassifierRule] = Field(default_factory=list)
    sensitivity_factors: dict[Classification, float]
    batch_size: int = 100
    max_work: int = 5_000
    max_fields_per_store: int = 1_000
    max_signals_per_field: int = 100

    @field_validator("classifier_rules")
    @classmethod
    def _classifier_rules(cls, values: list[ClassifierRule]) -> list[ClassifierRule]:
        ids = [rule.id for rule in values]
        if len(ids) != len(set(ids)):
            raise DSPMConfigInvalid("classifier rule ids must not contain duplicates")
        return values

    @field_validator("sensitivity_factors", mode="before")
    @classmethod
    def _sensitivity_factors(cls, value: object) -> dict[str, float]:
        if not isinstance(value, dict):
            raise DSPMConfigInvalid("sensitivity_factors must be an object")
        if set(value) != VALID_CLASSIFICATIONS:
            raise DSPMConfigInvalid("sensitivity_factors must cover the EA-0019 taxonomy")
        return {
            str(classification): _unit(factor, field=f"sensitivity_factors[{classification!r}]")
            for classification, factor in value.items()
        }

    @field_validator(
        "batch_size",
        "max_work",
        "max_fields_per_store",
        "max_signals_per_field",
        mode="before",
    )
    @classmethod
    def _positive_limit(cls, value: object) -> int:
        return _positive_int(value, field="DSPM config limit")

    @model_validator(mode="after")
    def _factor_order(self) -> DSPMConfig:
        ordered = [self.sensitivity_factors[key] for key in _ORDERED_CLASSIFICATIONS]
        if ordered != sorted(ordered):
            raise DSPMConfigInvalid("sensitivity_factors must be monotonic")
        return self
