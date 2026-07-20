"""Secrets and cryptographic-asset models (EA-0032 W1)."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Final, Literal
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aqelyn.conventions import new_id, require_tenant_id, require_typed_id
from aqelyn.conventions.errors import (
    CryptoConfigInvalid,
    SchemaValidationError,
    SecretValueRejected,
)
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
    status: LifecycleStatus = "unknown"
    reason: str

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return _nonempty(value, field="authenticity reason")


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
    strength: Lifecycle
    rotation: Lifecycle
    claim_confidence: float
    source_id: str
    evidence_id: str

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
    evidence_id: str

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
        if self.status == "confirmed" and self.exposure_record_id is None:
            raise CryptoConfigInvalid(
                "confirmed cryptographic exposure requires exposure_record_id"
            )
        if self.status == "reachability_pending" and self.exposure_record_id is not None:
            raise CryptoConfigInvalid(
                "reachability-pending exposure cannot carry exposure_record_id"
            )
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
        return self


class CryptoConfig(_ValueFreeModel):
    expiry_warning_days: int = 30
    weak_algorithms: list[str] = Field(default_factory=lambda: ["md5", "sha1", "des", "3des"])
    min_key_sizes: dict[str, int] = Field(default_factory=lambda: {"rsa": 2048, "ec": 256})
    max_key_age_days: int = 365
    batch_size: int = 100
    max_work: int = 50_000

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
