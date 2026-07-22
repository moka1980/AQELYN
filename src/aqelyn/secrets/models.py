"""Secrets and cryptographic-asset models (EA-0032 W1)."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Final, Literal
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aqelyn.conventions import new_id, require_tenant_id, require_typed_id
from aqelyn.conventions.errors import (
    CryptoConfigInvalid,
    SchemaValidationError,
    SecretValueRejected,
)
from aqelyn.decision import Derivation
from aqelyn.exposure.models import ExposureImpactContext

LifecycleStatus = Literal["valid", "invalid", "unknown"]
AssessmentStatus = Literal["pending", "complete", "truncated"]
SecretKind = Literal[
    "api_key",
    "token",
    "private_key",
    "password",
    "connection_string",
    "ssh_key",
    "other",
]
SecretLocationKind = Literal[
    "repository",
    "configuration",
    "vault_reference",
    "runtime_reference",
    "other",
]
KeyUsage = Literal["signing", "encryption", "authentication", "key_agreement", "other"]
CryptoAssetKind = Literal["secret", "key", "certificate"]
CryptoExposureStatus = Literal["confirmed", "reachability_pending"]
GovernanceFactorStatus = Literal["known", "unknown"]
GovernanceScoringStatus = Literal["pending", "complete", "partial"]
StorageSafetyStatus = Literal["approved", "unsafe", "unknown"]
StorageLocationKind = SecretLocationKind | Literal["external_key_reference", "unreported"]
CryptoClaimField = Literal[
    "kind",
    "location",
    "external_key_ref",
    "algorithm",
    "key_size",
    "usages",
    "last_rotated_at",
    "serial",
    "subject",
    "issuer",
    "not_after",
]

VALID_LIFECYCLE_STATUSES: Final[frozenset[str]] = frozenset(("valid", "invalid", "unknown"))
VALID_ASSESSMENT_STATUSES: Final[frozenset[str]] = frozenset(("pending", "complete", "truncated"))
VALID_SECRET_KINDS: Final[frozenset[str]] = frozenset(
    ("api_key", "token", "private_key", "password", "connection_string", "ssh_key", "other")
)
VALID_SECRET_LOCATION_KINDS: Final[frozenset[str]] = frozenset(
    ("repository", "configuration", "vault_reference", "runtime_reference", "other")
)
VALID_KEY_USAGES: Final[frozenset[str]] = frozenset(
    ("signing", "encryption", "authentication", "key_agreement", "other")
)
VALID_CRYPTO_ASSET_KINDS: Final[frozenset[str]] = frozenset(("secret", "key", "certificate"))
LEGACY_GOVERNANCE_FACTOR_NAMES: Final[tuple[str, ...]] = (
    "owner_risk",
    "lifecycle",
    "ownership",
    "exposure",
    "trust",
    "compliance",
)
GOVERNANCE_FACTOR_NAMES: Final[tuple[str, ...]] = (
    "owner_risk",
    "lifecycle",
    "storage_safety",
    "ownership",
    "exposure",
    "trust",
    "compliance",
)
GOVERNANCE_FACTOR_SETS: Final[tuple[frozenset[str], ...]] = (
    frozenset(LEGACY_GOVERNANCE_FACTOR_NAMES),
    frozenset(GOVERNANCE_FACTOR_NAMES),
)
GOVERNANCE_UNKNOWN_PENALTY_POINTS: Final[float] = 10.0
GOVERNANCE_ACTIVE_EXPOSURE_CAP: Final[float] = 69.0
GOVERNANCE_CRITICAL_EXPOSURE_THRESHOLD: Final[float] = 70.0

_FINGERPRINT_RE: Final[re.Pattern[str]] = re.compile(r"^hmac-sha256:[0-9a-f]{64}$")
_FORBIDDEN_VALUE_KEY_TOKENS: Final[frozenset[str]] = frozenset(
    (
        "raw",
        "value",
        "sample",
        "content",
        "payload",
        "blob",
        "credential",
        "token",
        "password",
        "privatekey",
    )
)
_CREDENTIAL_QUERY_KEY_TOKENS: Final[frozenset[str]] = frozenset(
    (
        "accesskey",
        "accesskeyid",
        "apikey",
        "authorization",
        "credential",
        "password",
        "privatekey",
        "secret",
        "sig",
        "signature",
        "token",
        "xamzcredential",
        "xamzsecuritytoken",
        "xamzsignature",
    )
)


def _key_token(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _reject_value_keys(value: object, *, path: str) -> None:
    """Reject value-bearing mapping keys without inspecting scalar values."""
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if isinstance(key, str):
                token = _key_token(key)
                if any(forbidden in token for forbidden in _FORBIDDEN_VALUE_KEY_TOKENS):
                    raise SecretValueRejected(f"value-bearing field name at {path}.{key}")
            _reject_value_keys(nested, path=f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, nested in enumerate(value):
            _reject_value_keys(nested, path=f"{path}[{index}]")


def _nonempty(value: str, *, field: str) -> str:
    if not value.strip():
        raise CryptoConfigInvalid(f"{field} must not be empty")
    return value


def _optional_nonempty(value: str | None, *, field: str) -> str | None:
    if value is None:
        return None
    return _nonempty(value, field=field)


def _positive_int(value: object, *, field: str, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CryptoConfigInvalid(f"{field} must be >= 1")
    if maximum is not None and value > maximum:
        raise CryptoConfigInvalid(f"{field} must be <= {maximum}")
    return value


def _nonnegative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CryptoConfigInvalid(f"{field} must be >= 0")
    return value


def _unit(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise CryptoConfigInvalid(f"{field} must be in [0,1]")
    selected = float(value)
    if not math.isfinite(selected) or selected < 0.0 or selected > 1.0:
        raise CryptoConfigInvalid(f"{field} must be in [0,1]")
    return selected


def _fingerprint(value: str) -> str:
    if _FINGERPRINT_RE.fullmatch(value) is None:
        raise CryptoConfigInvalid("fingerprint must be hmac-sha256 followed by 64 lowercase hex")
    return value


def _resource_ref(value: str) -> str:
    selected = _nonempty(value, field="resource_ref")
    parsed = urlsplit(selected)
    if parsed.username is not None or parsed.password is not None:
        raise SecretValueRejected("resource_ref must not contain URL credentials")
    for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
        token = _key_token(key)
        if token in _CREDENTIAL_QUERY_KEY_TOKENS:
            raise SecretValueRejected("resource_ref must not contain credential query parameters")
    return selected


def _unique_text(values: list[str], *, field: str) -> list[str]:
    for value in values:
        _nonempty(value, field=field)
    if len(values) != len(set(values)):
        raise CryptoConfigInvalid(f"{field} must not contain duplicates")
    return list(values)


def _crypto_asset_id(value: str, *, field: str) -> str:
    for prefix in ("sct", "cky", "x509"):
        try:
            return require_typed_id(value, prefix, field=field)
        except SchemaValidationError:
            pass
    raise CryptoConfigInvalid(f"{field} must use sct_, cky_, or x509_ prefix")


class _ValueFreeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _value_free(cls, data: object) -> object:
        _reject_value_keys(data, path=cls.__name__)
        return data


class Lifecycle(_ValueFreeModel):
    status: LifecycleStatus = "unknown"
    source_ref: str | None = None
    evidence_id: str | None = None
    reason: str

    @field_validator("source_ref")
    @classmethod
    def _source_ref(cls, value: str | None) -> str | None:
        return _optional_nonempty(value, field="lifecycle source_ref")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="evidence_id")

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return _nonempty(value, field="lifecycle reason")

    @model_validator(mode="after")
    def _state_consistency(self) -> Lifecycle:
        has_source = self.source_ref is not None
        has_evidence = self.evidence_id is not None
        if has_source != has_evidence:
            raise CryptoConfigInvalid(
                "lifecycle source_ref and evidence_id must be supplied together"
            )
        if self.status != "unknown" and not has_source:
            raise CryptoConfigInvalid("known lifecycle state requires source_ref and evidence_id")
        return self


class SecretLocation(_ValueFreeModel):
    kind: SecretLocationKind
    resource_ref: str
    path_hint: str | None = None
    line: int | None = None

    @field_validator("resource_ref")
    @classmethod
    def _safe_resource_ref(cls, value: str) -> str:
        return _resource_ref(value)

    @field_validator("path_hint")
    @classmethod
    def _path_hint(cls, value: str | None) -> str | None:
        return _optional_nonempty(value, field="path_hint")

    @field_validator("line", mode="before")
    @classmethod
    def _line(cls, value: object) -> int | None:
        if value is None:
            return None
        return _positive_int(value, field="line")


class StorageSafetyClassification(_ValueFreeModel):
    asset_id: str
    status: StorageSafetyStatus = "unknown"
    location_kind: StorageLocationKind = "unreported"
    location_ref: str | None = None
    matched_policy_prefix: str | None = None
    evidence_id: str
    reason: str
    flagged: bool = True

    @field_validator("asset_id")
    @classmethod
    def _asset_id(cls, value: str) -> str:
        return _crypto_asset_id(value, field="asset_id")

    @field_validator("location_ref")
    @classmethod
    def _location_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _resource_ref(value)

    @field_validator("matched_policy_prefix")
    @classmethod
    def _matched_policy_prefix(cls, value: str | None) -> str | None:
        if value is None:
            return None
        selected = _resource_ref(value)
        if not selected.endswith(("/", ":", "#")):
            raise CryptoConfigInvalid(
                "matched storage policy prefixes must end with '/', ':', or '#'"
            )
        return selected

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return _nonempty(value, field="storage safety reason")

    @model_validator(mode="after")
    def _state_consistency(self) -> StorageSafetyClassification:
        if self.status == "approved":
            if self.location_ref is None or self.matched_policy_prefix is None:
                raise CryptoConfigInvalid(
                    "approved storage requires a location and matched policy prefix"
                )
            if not self.location_ref.startswith(self.matched_policy_prefix):
                raise CryptoConfigInvalid("approved storage location must match its policy prefix")
            if self.flagged:
                raise CryptoConfigInvalid("approved storage cannot be flagged")
        else:
            if self.matched_policy_prefix is not None:
                raise CryptoConfigInvalid(
                    "unsafe or unknown storage cannot name an approved policy prefix"
                )
            if not self.flagged:
                raise CryptoConfigInvalid("unsafe or unknown storage must be flagged")
        if self.location_kind == "unreported" and self.location_ref is not None:
            raise CryptoConfigInvalid("unreported storage cannot carry a location reference")
        if self.status != "unknown" and self.location_ref is None:
            raise CryptoConfigInvalid("known storage safety requires a location reference")
        return self


class SecretScanDescriptor(_ValueFreeModel):
    tenant_id: str | None = None
    kind: SecretKind
    fingerprint: str
    location: SecretLocation
    source_id: str
    observed_at: datetime
    evidence_id: str

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("fingerprint")
    @classmethod
    def _fingerprint(cls, value: str) -> str:
        return _fingerprint(value)

    @field_validator("source_id")
    @classmethod
    def _source_id(cls, value: str) -> str:
        return require_typed_id(value, "src", field="source_id")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")


class CryptographicKeyDescriptor(_ValueFreeModel):
    tenant_id: str | None = None
    external_key_ref: str
    fingerprint: str
    algorithm: str | None = None
    key_size: int | None = None
    usages: list[KeyUsage] = Field(default_factory=list)
    last_rotated_at: datetime | None = None
    source_id: str
    observed_at: datetime
    evidence_id: str

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("external_key_ref")
    @classmethod
    def _external_key_ref(cls, value: str) -> str:
        return _resource_ref(value)

    @field_validator("fingerprint")
    @classmethod
    def _fingerprint(cls, value: str) -> str:
        return _fingerprint(value)

    @field_validator("algorithm")
    @classmethod
    def _algorithm(cls, value: str | None) -> str | None:
        return _optional_nonempty(value, field="algorithm")

    @field_validator("key_size", mode="before")
    @classmethod
    def _key_size(cls, value: object) -> int | None:
        if value is None:
            return None
        return _positive_int(value, field="key_size")

    @field_validator("usages")
    @classmethod
    def _usages(cls, values: list[KeyUsage]) -> list[KeyUsage]:
        if len(values) != len(set(values)):
            raise CryptoConfigInvalid("key usages must not contain duplicates")
        return values

    @field_validator("source_id")
    @classmethod
    def _source_id(cls, value: str) -> str:
        return require_typed_id(value, "src", field="source_id")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")


class CertificateDescriptor(_ValueFreeModel):
    tenant_id: str | None = None
    fingerprint: str
    serial: str
    subject: str
    issuer: str
    not_after: datetime | None = None
    source_id: str
    observed_at: datetime
    evidence_id: str

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("fingerprint")
    @classmethod
    def _fingerprint(cls, value: str) -> str:
        return _fingerprint(value)

    @field_validator("serial", "subject", "issuer")
    @classmethod
    def _certificate_text(cls, value: str) -> str:
        return _nonempty(value, field="certificate field")

    @field_validator("source_id")
    @classmethod
    def _source_id(cls, value: str) -> str:
        return require_typed_id(value, "src", field="source_id")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")


class AuthenticityCheck(_ValueFreeModel):
    certificate_fingerprint: str
    basis_evidence_id: str
    status: LifecycleStatus = "unknown"
    reason: str

    @field_validator("certificate_fingerprint")
    @classmethod
    def _certificate_fingerprint(cls, value: str) -> str:
        return _fingerprint(value)

    @field_validator("basis_evidence_id")
    @classmethod
    def _basis_evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="basis_evidence_id")

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return _nonempty(value, field="authenticity reason")


class SecretClaim(_ValueFreeModel):
    asset_kind: Literal["secret"] = "secret"
    kind: SecretKind
    location: SecretLocation


class KeyClaim(_ValueFreeModel):
    asset_kind: Literal["key"] = "key"
    external_key_ref: str
    algorithm: str | None = None
    key_size: int | None = None
    usages: list[KeyUsage] = Field(default_factory=list)
    last_rotated_at: datetime | None = None

    @field_validator("external_key_ref")
    @classmethod
    def _external_key_ref(cls, value: str) -> str:
        return _resource_ref(value)

    @field_validator("algorithm")
    @classmethod
    def _algorithm(cls, value: str | None) -> str | None:
        return _optional_nonempty(value, field="algorithm")

    @field_validator("key_size", mode="before")
    @classmethod
    def _key_size(cls, value: object) -> int | None:
        if value is None:
            return None
        return _positive_int(value, field="key_size")

    @field_validator("usages")
    @classmethod
    def _usages(cls, values: list[KeyUsage]) -> list[KeyUsage]:
        if len(values) != len(set(values)):
            raise CryptoConfigInvalid("key usages must not contain duplicates")
        return values


class CertificateClaim(_ValueFreeModel):
    asset_kind: Literal["certificate"] = "certificate"
    serial: str
    subject: str
    issuer: str
    not_after: datetime | None = None

    @field_validator("serial", "subject", "issuer")
    @classmethod
    def _certificate_text(cls, value: str) -> str:
        return _nonempty(value, field="certificate claim field")


CryptoClaim = SecretClaim | KeyClaim | CertificateClaim


class CryptoConflictCandidate(_ValueFreeModel):
    source_id: str
    evidence_id: str
    observed_at: datetime
    reliability: float
    claim: CryptoClaim

    @field_validator("source_id")
    @classmethod
    def _source_id(cls, value: str) -> str:
        return require_typed_id(value, "src", field="source_id")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")

    @field_validator("reliability", mode="before")
    @classmethod
    def _reliability(cls, value: object) -> float:
        return _unit(value, field="conflict candidate reliability")


class CryptoClaimConflict(_ValueFreeModel):
    fields: list[CryptoClaimField]
    candidates: list[CryptoConflictCandidate]
    resolved_by: str | None = None
    resolved_evidence_id: str | None = None
    unresolved: bool
    reason: str

    @field_validator("fields")
    @classmethod
    def _fields(cls, values: list[CryptoClaimField]) -> list[CryptoClaimField]:
        if not values:
            raise CryptoConfigInvalid("crypto claim conflict requires fields")
        if len(values) != len(set(values)):
            raise CryptoConfigInvalid("crypto claim conflict fields must be unique")
        return values

    @field_validator("candidates")
    @classmethod
    def _candidates(cls, values: list[CryptoConflictCandidate]) -> list[CryptoConflictCandidate]:
        if len(values) < 2:
            raise CryptoConfigInvalid("crypto claim conflict requires at least two candidates")
        return values

    @field_validator("resolved_by")
    @classmethod
    def _resolved_by(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "src", field="resolved_by")

    @field_validator("resolved_evidence_id")
    @classmethod
    def _resolved_evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="resolved_evidence_id")

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return _nonempty(value, field="crypto claim conflict reason")

    @model_validator(mode="after")
    def _conflict_consistency(self) -> CryptoClaimConflict:
        kinds = {candidate.claim.asset_kind for candidate in self.candidates}
        if len(kinds) != 1:
            raise CryptoConfigInvalid("crypto claim conflict candidates must share one asset kind")
        allowed = {
            "secret": {"kind", "location"},
            "key": {"external_key_ref", "algorithm", "key_size", "usages", "last_rotated_at"},
            "certificate": {"serial", "subject", "issuer", "not_after"},
        }
        asset_kind = next(iter(kinds))
        if not set(self.fields) <= allowed[asset_kind]:
            raise CryptoConfigInvalid("crypto claim conflict fields do not match the asset kind")
        for field in self.fields:
            values = {
                repr(candidate.claim.model_dump(mode="json").get(field))
                for candidate in self.candidates
            }
            if len(values) < 2:
                raise CryptoConfigInvalid("crypto claim conflict fields must actually disagree")
        if self.unresolved:
            if self.resolved_by is not None or self.resolved_evidence_id is not None:
                raise CryptoConfigInvalid("unresolved crypto conflicts cannot name a resolution")
        elif self.resolved_by is None or self.resolved_evidence_id is None:
            raise CryptoConfigInvalid("resolved crypto conflicts require source and evidence")
        return self


class SecretAsset(_ValueFreeModel):
    id: str = Field(default_factory=lambda: new_id("sct"))
    tenant_id: str | None = None
    object_id: str
    inventory_ref: str
    kind: SecretKind
    fingerprint: str
    location: SecretLocation
    classification: Literal["secret"] = "secret"
    rotation: Lifecycle
    claim_confidence: float
    source_id: str
    detected_at: datetime
    evidence_id: str
    conflicts: list[CryptoClaimConflict] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "sct", field="id")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("object_id")
    @classmethod
    def _object_id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="object_id")

    @field_validator("inventory_ref")
    @classmethod
    def _inventory_ref(cls, value: str) -> str:
        return require_typed_id(value, "ast", field="inventory_ref")

    @field_validator("fingerprint")
    @classmethod
    def _fingerprint(cls, value: str) -> str:
        return _fingerprint(value)

    @field_validator("claim_confidence", mode="before")
    @classmethod
    def _claim_confidence(cls, value: object) -> float:
        return _unit(value, field="claim_confidence")

    @field_validator("source_id")
    @classmethod
    def _source_id(cls, value: str) -> str:
        return require_typed_id(value, "src", field="source_id")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")

    @model_validator(mode="after")
    def _conflict_kind(self) -> SecretAsset:
        if any(
            candidate.claim.asset_kind != "secret"
            for conflict in self.conflicts
            for candidate in conflict.candidates
        ):
            raise CryptoConfigInvalid("secret asset conflicts must contain secret claims")
        return self


class CryptographicKey(_ValueFreeModel):
    id: str = Field(default_factory=lambda: new_id("cky"))
    tenant_id: str | None = None
    object_id: str
    inventory_ref: str
    external_key_ref: str
    fingerprint: str
    algorithm: str | None = None
    key_size: int | None = None
    usages: list[KeyUsage] = Field(default_factory=list)
    last_rotated_at: datetime | None = None
    strength: Lifecycle
    rotation: Lifecycle
    claim_confidence: float
    source_id: str
    observed_at: datetime
    evidence_id: str
    conflicts: list[CryptoClaimConflict] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "cky", field="id")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("object_id")
    @classmethod
    def _object_id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="object_id")

    @field_validator("inventory_ref")
    @classmethod
    def _inventory_ref(cls, value: str) -> str:
        return require_typed_id(value, "ast", field="inventory_ref")

    @field_validator("external_key_ref")
    @classmethod
    def _external_key_ref(cls, value: str) -> str:
        return _resource_ref(value)

    @field_validator("fingerprint")
    @classmethod
    def _fingerprint(cls, value: str) -> str:
        return _fingerprint(value)

    @field_validator("algorithm")
    @classmethod
    def _algorithm(cls, value: str | None) -> str | None:
        return _optional_nonempty(value, field="algorithm")

    @field_validator("key_size", mode="before")
    @classmethod
    def _key_size(cls, value: object) -> int | None:
        if value is None:
            return None
        return _positive_int(value, field="key_size")

    @field_validator("usages")
    @classmethod
    def _usages(cls, values: list[KeyUsage]) -> list[KeyUsage]:
        if len(values) != len(set(values)):
            raise CryptoConfigInvalid("key usages must not contain duplicates")
        return values

    @field_validator("claim_confidence", mode="before")
    @classmethod
    def _claim_confidence(cls, value: object) -> float:
        return _unit(value, field="claim_confidence")

    @field_validator("source_id")
    @classmethod
    def _source_id(cls, value: str) -> str:
        return require_typed_id(value, "src", field="source_id")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")

    @model_validator(mode="after")
    def _conflict_kind(self) -> CryptographicKey:
        if any(
            candidate.claim.asset_kind != "key"
            for conflict in self.conflicts
            for candidate in conflict.candidates
        ):
            raise CryptoConfigInvalid("cryptographic key conflicts must contain key claims")
        return self


class CertificateAsset(_ValueFreeModel):
    id: str = Field(default_factory=lambda: new_id("x509"))
    tenant_id: str | None = None
    object_id: str
    inventory_ref: str
    fingerprint: str
    serial: str
    subject: str
    issuer: str
    not_after: datetime | None = None
    expiry: Lifecycle
    chain: Lifecycle
    revocation: Lifecycle
    integrity: Lifecycle
    authenticity: Lifecycle
    claim_confidence: float
    source_id: str
    observed_at: datetime
    evidence_id: str
    conflicts: list[CryptoClaimConflict] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "x509", field="id")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("object_id")
    @classmethod
    def _object_id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="object_id")

    @field_validator("inventory_ref")
    @classmethod
    def _inventory_ref(cls, value: str) -> str:
        return require_typed_id(value, "ast", field="inventory_ref")

    @field_validator("fingerprint")
    @classmethod
    def _fingerprint(cls, value: str) -> str:
        return _fingerprint(value)

    @field_validator("serial", "subject", "issuer")
    @classmethod
    def _certificate_text(cls, value: str) -> str:
        return _nonempty(value, field="certificate field")

    @field_validator("claim_confidence", mode="before")
    @classmethod
    def _claim_confidence(cls, value: object) -> float:
        return _unit(value, field="claim_confidence")

    @field_validator("source_id")
    @classmethod
    def _source_id(cls, value: str) -> str:
        return require_typed_id(value, "src", field="source_id")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")

    @model_validator(mode="after")
    def _conflict_kind(self) -> CertificateAsset:
        if any(
            candidate.claim.asset_kind != "certificate"
            for conflict in self.conflicts
            for candidate in conflict.candidates
        ):
            raise CryptoConfigInvalid("certificate asset conflicts must contain certificate claims")
        return self


CryptoAsset = SecretAsset | CryptographicKey | CertificateAsset


class CryptoScope(_ValueFreeModel):
    kinds: list[CryptoAssetKind] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)

    @field_validator("kinds")
    @classmethod
    def _kinds(cls, values: list[CryptoAssetKind]) -> list[CryptoAssetKind]:
        if len(values) != len(set(values)):
            raise CryptoConfigInvalid("scope kinds must not contain duplicates")
        return values

    @field_validator("asset_ids")
    @classmethod
    def _asset_ids(cls, values: list[str]) -> list[str]:
        for value in values:
            _crypto_asset_id(value, field="scope asset_ids")
        if len(values) != len(set(values)):
            raise CryptoConfigInvalid("scope asset_ids must not contain duplicates")
        return values


class CryptoQuery(_ValueFreeModel):
    tenant_id: str | None = None
    kind: CryptoAssetKind | None = None
    cursor: str | None = None
    limit: int = 100

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("cursor")
    @classmethod
    def _cursor(cls, value: str | None) -> str | None:
        return _optional_nonempty(value, field="cursor")

    @field_validator("limit", mode="before")
    @classmethod
    def _limit(cls, value: object) -> int:
        return _positive_int(value, field="query limit", maximum=1_000)


class CryptographicExposure(_ValueFreeModel):
    id: str
    tenant_id: str | None = None
    asset_id: str
    surface_ref: str
    object_id: str
    exposure_record_id: str | None = None
    status: CryptoExposureStatus
    impact_context: ExposureImpactContext
    reason: str
    evidence_id: str

    @field_validator("id", "reason")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="cryptographic exposure field")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("asset_id")
    @classmethod
    def _asset_id(cls, value: str) -> str:
        return _crypto_asset_id(value, field="asset_id")

    @field_validator("surface_ref")
    @classmethod
    def _surface_ref(cls, value: str) -> str:
        return require_typed_id(value, "ast", field="surface_ref")

    @field_validator("object_id")
    @classmethod
    def _object_id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="object_id")

    @field_validator("exposure_record_id")
    @classmethod
    def _exposure_record_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "exp", field="exposure_record_id")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")

    @model_validator(mode="after")
    def _state_consistency(self) -> CryptographicExposure:
        if self.impact_context.kind != "credential_sensitivity":
            raise CryptoConfigInvalid(
                "cryptographic exposure requires credential_sensitivity impact context"
            )
        if self.status == "confirmed" and self.exposure_record_id is None:
            raise CryptoConfigInvalid(
                "confirmed cryptographic exposure requires exposure_record_id"
            )
        if self.status == "reachability_pending" and self.exposure_record_id is not None:
            raise CryptoConfigInvalid(
                "reachability-pending exposure cannot carry exposure_record_id"
            )
        return self


class GovernanceFactor(_ValueFreeModel):
    name: str
    rating: float | None = None
    weight: float
    status: GovernanceFactorStatus
    source_ref: dict[str, Any]
    reason: str

    @field_validator("name", "reason")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="governance factor field")

    @field_validator("rating", mode="before")
    @classmethod
    def _rating(cls, value: object) -> float | None:
        if value is None:
            return None
        return _unit(value, field="governance factor rating")

    @field_validator("weight", mode="before")
    @classmethod
    def _weight(cls, value: object) -> float:
        return _unit(value, field="governance factor weight")

    @field_validator("source_ref")
    @classmethod
    def _source_ref(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise CryptoConfigInvalid("governance factor source_ref must not be empty")
        return dict(value)

    @model_validator(mode="after")
    def _status_consistency(self) -> GovernanceFactor:
        if self.status == "known" and self.rating is None:
            raise CryptoConfigInvalid("known governance factor requires a rating")
        if self.status == "unknown" and self.rating is not None:
            raise CryptoConfigInvalid("unknown governance factor cannot carry a rating")
        return self


class CredentialGovernanceScore(_ValueFreeModel):
    id: str = Field(default_factory=lambda: new_id("cgs"))
    tenant_id: str | None = None
    asset_id: str
    object_id: str
    score: float
    factors: list[GovernanceFactor]
    active_critical_exposure_ids: list[str] = Field(default_factory=list)
    derivation: Derivation
    confidence: float
    statement: str
    computed_at: datetime
    evidence_id: str

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "cgs", field="id")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("asset_id")
    @classmethod
    def _asset_id(cls, value: str) -> str:
        return _crypto_asset_id(value, field="asset_id")

    @field_validator("object_id")
    @classmethod
    def _object_id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="object_id")

    @field_validator("score", mode="before")
    @classmethod
    def _score(cls, value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise CryptoConfigInvalid("governance score must be in [0,100]")
        selected = float(value)
        if not math.isfinite(selected) or selected < 0.0 or selected > 100.0:
            raise CryptoConfigInvalid("governance score must be in [0,100]")
        return selected

    @field_validator("factors")
    @classmethod
    def _factors(cls, values: list[GovernanceFactor]) -> list[GovernanceFactor]:
        names = [factor.name for factor in values]
        selected = frozenset(names)
        if selected not in GOVERNANCE_FACTOR_SETS or len(names) != len(selected):
            raise CryptoConfigInvalid(
                "governance factors must define the v1 or v2 factor set exactly once"
            )
        return values

    @field_validator("active_critical_exposure_ids")
    @classmethod
    def _active_exposure_ids(cls, values: list[str]) -> list[str]:
        selected = [
            require_typed_id(value, "exp", field="active_critical_exposure_ids") for value in values
        ]
        if len(selected) != len(set(selected)):
            raise CryptoConfigInvalid("active critical exposure ids must be unique")
        return selected

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, value: object) -> float:
        return _unit(value, field="governance confidence")

    @field_validator("statement")
    @classmethod
    def _statement(cls, value: str) -> str:
        selected = _nonempty(value, field="governance statement")
        lowered = selected.casefold()
        if "governance hygiene" not in lowered or "not safety" not in lowered:
            raise CryptoConfigInvalid(
                "governance statement must say the score measures governance hygiene, not safety"
            )
        return selected

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")

    @model_validator(mode="after")
    def _score_consistency(self) -> CredentialGovernanceScore:
        total_weight = sum(factor.weight for factor in self.factors)
        if not math.isclose(total_weight, 1.0, rel_tol=0.0, abs_tol=1e-6):
            raise CryptoConfigInvalid("governance factor weights must sum to 1 within 1e-6")
        known = [factor for factor in self.factors if factor.status == "known"]
        if not known:
            raise CryptoConfigInvalid("governance score requires at least one known factor")
        known_weight = sum(factor.weight for factor in known)
        weighted = sum(
            factor.weight * (factor.rating if factor.rating is not None else 0.0)
            for factor in known
        )
        known_only = weighted / known_weight
        coverage_adjustment = known_weight / total_weight
        unknown_weight = total_weight - known_weight
        expected = max(
            0.0,
            known_only * coverage_adjustment * 100.0
            - unknown_weight * GOVERNANCE_UNKNOWN_PENALTY_POINTS,
        )
        if self.active_critical_exposure_ids:
            expected = min(expected, GOVERNANCE_ACTIVE_EXPOSURE_CAP)
            if "active critical exposure" not in self.statement.casefold():
                raise CryptoConfigInvalid(
                    "active critical exposures must be named in the governance statement"
                )
        if not math.isclose(self.score, round(expected, 6), rel_tol=0.0, abs_tol=1e-6):
            raise CryptoConfigInvalid("governance score does not match its factors")
        return self


class CryptoAssessment(_ValueFreeModel):
    id: str = Field(default_factory=lambda: new_id("cas"))
    tenant_id: str | None = None
    run_at: datetime
    scope: CryptoScope
    status: AssessmentStatus = "pending"
    assets_evaluated: int = 0
    secrets: int = 0
    keys: int = 0
    certificates: int = 0
    expiring_soon: int = 0
    unknown_lifecycle: int = 0
    exposure_ids: list[str] = Field(default_factory=list)
    governance_scoring_status: GovernanceScoringStatus = "pending"
    governance_score_ids: list[str] = Field(default_factory=list)
    governance_incomplete_reason: str | None = "Governance scoring has not run."
    incomplete_reason: str | None = None
    evidence_id: str | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "cas", field="id")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator(
        "assets_evaluated",
        "secrets",
        "keys",
        "certificates",
        "expiring_soon",
        "unknown_lifecycle",
        mode="before",
    )
    @classmethod
    def _count(cls, value: object) -> int:
        return _nonnegative_int(value, field="assessment count")

    @field_validator("exposure_ids")
    @classmethod
    def _exposure_ids(cls, values: list[str]) -> list[str]:
        for value in values:
            require_typed_id(value, "exp", field="exposure_ids")
        if len(values) != len(set(values)):
            raise CryptoConfigInvalid("exposure_ids must not contain duplicates")
        return values

    @field_validator("governance_score_ids")
    @classmethod
    def _governance_score_ids(cls, values: list[str]) -> list[str]:
        selected = [
            require_typed_id(value, "cgs", field="governance_score_ids") for value in values
        ]
        if len(selected) != len(set(selected)):
            raise CryptoConfigInvalid("governance_score_ids must not contain duplicates")
        return selected

    @field_validator("governance_incomplete_reason")
    @classmethod
    def _governance_incomplete_reason(cls, value: str | None) -> str | None:
        return _optional_nonempty(value, field="governance_incomplete_reason")

    @field_validator("incomplete_reason")
    @classmethod
    def _incomplete_reason(cls, value: str | None) -> str | None:
        return _optional_nonempty(value, field="incomplete_reason")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="evidence_id")

    @model_validator(mode="after")
    def _coverage_consistency(self) -> CryptoAssessment:
        result_counts = (
            self.assets_evaluated,
            self.secrets,
            self.keys,
            self.certificates,
            self.expiring_soon,
            self.unknown_lifecycle,
            len(self.exposure_ids),
            len(self.governance_score_ids),
        )
        if self.status == "pending":
            if any(result_counts) or self.evidence_id is not None:
                raise CryptoConfigInvalid("pending assessment cannot carry completed results")
        elif self.evidence_id is None:
            raise CryptoConfigInvalid("completed assessment requires evidence_id")

        if self.status == "complete" and self.incomplete_reason is not None:
            raise CryptoConfigInvalid("complete assessment cannot carry incomplete_reason")
        if self.status == "truncated" and self.incomplete_reason is None:
            raise CryptoConfigInvalid("truncated assessment requires incomplete_reason")
        if self.secrets + self.keys + self.certificates != self.assets_evaluated:
            raise CryptoConfigInvalid("asset-kind counts must equal assets_evaluated")
        if self.expiring_soon > self.certificates:
            raise CryptoConfigInvalid("expiring_soon cannot exceed certificates")
        if self.unknown_lifecycle > self.assets_evaluated:
            raise CryptoConfigInvalid("unknown_lifecycle cannot exceed assets_evaluated")
        if len(self.exposure_ids) > self.assets_evaluated:
            raise CryptoConfigInvalid("exposure_ids cannot exceed assets_evaluated")
        if len(self.governance_score_ids) > self.assets_evaluated:
            raise CryptoConfigInvalid("governance_score_ids cannot exceed assets_evaluated")
        if self.governance_scoring_status == "complete":
            if len(self.governance_score_ids) != self.assets_evaluated:
                raise CryptoConfigInvalid(
                    "complete governance scoring requires one score per evaluated asset"
                )
            if self.governance_incomplete_reason is not None:
                raise CryptoConfigInvalid(
                    "complete governance scoring cannot carry an incomplete reason"
                )
        elif self.governance_scoring_status == "pending":
            if self.governance_score_ids:
                raise CryptoConfigInvalid("pending governance scoring cannot carry score ids")
            if self.governance_incomplete_reason is None:
                raise CryptoConfigInvalid("pending governance scoring requires a reason")
        elif self.governance_incomplete_reason is None:
            raise CryptoConfigInvalid("partial governance scoring requires a reason")
        return self


class CryptoConfig(_ValueFreeModel):
    expiry_warning_days: int = 30
    weak_algorithms: list[str] = Field(default_factory=lambda: ["md5", "sha1", "des", "3des"])
    min_key_sizes: dict[str, int] = Field(default_factory=lambda: {"rsa": 2048, "ec": 256})
    max_key_age_days: int = 365
    batch_size: int = 100
    max_work: int = 50_000
    approved_storage_location_prefixes: list[str] = Field(default_factory=list)
    governance_factor_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "owner_risk": 0.18,
            "lifecycle": 0.18,
            "storage_safety": 0.10,
            "ownership": 0.135,
            "exposure": 0.18,
            "trust": 0.09,
            "compliance": 0.135,
        }
    )

    @field_validator("expiry_warning_days", "max_key_age_days", mode="before")
    @classmethod
    def _positive_days(cls, value: object) -> int:
        return _positive_int(value, field="crypto config days")

    @field_validator("batch_size", mode="before")
    @classmethod
    def _batch_size(cls, value: object) -> int:
        return _positive_int(value, field="batch_size", maximum=1_000)

    @field_validator("max_work", mode="before")
    @classmethod
    def _max_work(cls, value: object) -> int:
        return _positive_int(value, field="max_work", maximum=100_000)

    @field_validator("weak_algorithms")
    @classmethod
    def _weak_algorithms(cls, values: list[str]) -> list[str]:
        return _unique_text(values, field="weak_algorithms")

    @field_validator("min_key_sizes", mode="before")
    @classmethod
    def _min_key_sizes(cls, value: object) -> dict[str, int]:
        if not isinstance(value, dict) or not value:
            raise CryptoConfigInvalid("min_key_sizes must be a non-empty object")
        selected: dict[str, int] = {}
        for algorithm, minimum in value.items():
            if not isinstance(algorithm, str):
                raise CryptoConfigInvalid("min_key_sizes keys must be strings")
            key = _nonempty(algorithm, field="min_key_sizes algorithm")
            selected[key] = _positive_int(minimum, field=f"min_key_sizes[{key!r}]")
        return selected

    @field_validator("approved_storage_location_prefixes")
    @classmethod
    def _approved_storage_location_prefixes(cls, values: list[str]) -> list[str]:
        selected: list[str] = []
        for value in values:
            prefix = _resource_ref(value)
            if not prefix.endswith(("/", ":", "#")):
                raise CryptoConfigInvalid(
                    "approved storage location prefixes must end with '/', ':', or '#'"
                )
            selected.append(prefix)
        if len(selected) != len(set(selected)):
            raise CryptoConfigInvalid("approved storage location prefixes must be unique")
        return selected

    @field_validator("governance_factor_weights", mode="before")
    @classmethod
    def _governance_factor_weights(cls, value: object) -> dict[str, float]:
        if not isinstance(value, dict) or not value:
            raise CryptoConfigInvalid("governance_factor_weights must be a non-empty object")
        selected: dict[str, float] = {}
        for name, weight in value.items():
            if not isinstance(name, str):
                raise CryptoConfigInvalid("governance factor names must be strings")
            selected[_nonempty(name, field="governance factor name")] = _unit(
                weight,
                field=f"governance_factor_weights[{name!r}]",
            )
        if set(selected) != set(GOVERNANCE_FACTOR_NAMES):
            raise CryptoConfigInvalid(
                "governance_factor_weights must define owner_risk, lifecycle, storage_safety, "
                "ownership, exposure, trust, and compliance"
            )
        if not math.isclose(sum(selected.values()), 1.0, rel_tol=0.0, abs_tol=1e-6):
            raise CryptoConfigInvalid("governance_factor_weights must sum to 1 within 1e-6")
        return selected
