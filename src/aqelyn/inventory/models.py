"""Cyber Asset Discovery & Inventory Intelligence models (EA-0025 N1)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aqelyn.conventions import new_id, require_tenant_id, require_typed_id
from aqelyn.conventions.errors import AssetBasisMissing, InventoryConfigInvalid

LifecycleState = Literal[
    "provisioned",
    "active",
    "modified",
    "unreported",
    "decommissioned",
    "archived",
]
SourceHealth = Literal["ok", "degraded", "unknown"]
AssetBasisKind = Literal["discovery", "config", "identity", "relationship"]

VALID_LIFECYCLE_STATES: Final[frozenset[str]] = frozenset(
    ("provisioned", "active", "modified", "unreported", "decommissioned", "archived")
)
VALID_SOURCE_HEALTH: Final[frozenset[str]] = frozenset(("ok", "degraded", "unknown"))
VALID_MIN_SOURCE_HEALTH: Final[frozenset[str]] = frozenset(("ok", "degraded"))
VALID_ASSET_BASIS_KINDS: Final[frozenset[str]] = frozenset(
    ("discovery", "config", "identity", "relationship")
)


def _nonempty(value: str, *, field: str) -> str:
    if not value.strip():
        raise InventoryConfigInvalid(f"{field} must not be empty")
    return value


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InventoryConfigInvalid(f"{field} must be >= 1")
    return value


def _nonnegative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InventoryConfigInvalid(f"{field} must be >= 0")
    return value


def _finite(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InventoryConfigInvalid(f"{field} must be a finite number")
    selected = float(value)
    if not math.isfinite(selected):
        raise InventoryConfigInvalid(f"{field} must be a finite number")
    return selected


def _unit(value: object, *, field: str) -> float:
    selected = _finite(value, field=field)
    if selected < 0.0 or selected > 1.0:
        raise InventoryConfigInvalid(f"{field} must be in [0,1]")
    return selected


def _refs(values: list[str], *, field: str) -> list[str]:
    for value in values:
        _nonempty(value, field=field)
    if len(values) != len(set(values)):
        raise InventoryConfigInvalid(f"{field} must not contain duplicates")
    return values


class DiscoverySource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    reliability: float | None = None
    health: str
    as_of: datetime

    @field_validator("source_id")
    @classmethod
    def _source_id(cls, value: str) -> str:
        return _nonempty(value, field="discovery source_id")

    @field_validator("reliability")
    @classmethod
    def _reliability(cls, value: float | None) -> float | None:
        if value is None:
            return None
        return _unit(value, field="source reliability")

    @field_validator("health")
    @classmethod
    def _health(cls, value: str) -> str:
        if value not in VALID_SOURCE_HEALTH:
            raise InventoryConfigInvalid(f"unknown source health: {value!r}")
        return value


class AssetBasis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    ref: str
    as_of: datetime
    evidence_id: str | None = None

    @field_validator("kind")
    @classmethod
    def _kind(cls, value: str) -> str:
        if value not in VALID_ASSET_BASIS_KINDS:
            raise InventoryConfigInvalid(f"unknown asset basis kind: {value!r}")
        return value

    @field_validator("ref")
    @classmethod
    def _ref(cls, value: str) -> str:
        return _nonempty(value, field="asset basis ref")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="evidence_id")


class ConflictCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Any
    source_id: str
    reliability: float | None = None

    @field_validator("source_id")
    @classmethod
    def _source_id(cls, value: str) -> str:
        return _nonempty(value, field="conflict candidate source_id")

    @field_validator("reliability")
    @classmethod
    def _reliability(cls, value: float | None) -> float | None:
        if value is None:
            return None
        return _unit(value, field="conflict candidate reliability")


class FieldConflict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    candidates: list[ConflictCandidate]
    resolved_by: str | None = None
    unresolved: bool = False

    @field_validator("field")
    @classmethod
    def _field(cls, value: str) -> str:
        return _nonempty(value, field="conflict field")

    @field_validator("candidates")
    @classmethod
    def _candidates(cls, values: list[ConflictCandidate]) -> list[ConflictCandidate]:
        if not values:
            raise InventoryConfigInvalid("field conflict requires candidates")
        return values

    @field_validator("resolved_by")
    @classmethod
    def _resolved_by(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _nonempty(value, field="resolved_by")

    @model_validator(mode="after")
    def _resolution_consistency(self) -> FieldConflict:
        if self.unresolved and self.resolved_by is not None:
            raise InventoryConfigInvalid("unresolved conflicts cannot have resolved_by")
        if not self.unresolved and self.resolved_by is None:
            raise InventoryConfigInvalid("resolved conflicts require resolved_by")
        return self


class Ownership(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_owner: str | None = None
    technical_owner: str | None = None
    custodian: str | None = None
    rationale: str
    source_id: str

    @field_validator("business_owner", "technical_owner", "custodian")
    @classmethod
    def _owner(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _nonempty(value, field="ownership field")

    @field_validator("rationale", "source_id")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return _nonempty(value, field="ownership field")


class AssetRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("ast"))
    tenant_id: str | None = None
    asset_type: str
    discovery_source: str
    classification: str | None = None
    owner: Ownership | None = None
    lifecycle_state: str = "active"
    confidence: float
    basis: list[AssetBasis]
    conflicts: list[FieldConflict] = Field(default_factory=list)
    first_seen_at: datetime
    last_reported_at: datetime
    unreported_since: datetime | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "ast", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("asset_type", "discovery_source")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return _nonempty(value, field="asset record field")

    @field_validator("classification")
    @classmethod
    def _classification(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _nonempty(value, field="classification")

    @field_validator("lifecycle_state")
    @classmethod
    def _lifecycle_state(cls, value: str) -> str:
        if value not in VALID_LIFECYCLE_STATES:
            raise InventoryConfigInvalid(f"unknown lifecycle state: {value!r}")
        return value

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, value: object) -> float:
        return _unit(value, field="confidence")

    @field_validator("basis")
    @classmethod
    def _basis(cls, values: list[AssetBasis]) -> list[AssetBasis]:
        if not values:
            raise AssetBasisMissing("asset record requires at least one basis")
        return values


class AssetRelationship(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("arl"))
    tenant_id: str | None = None
    source_asset: str
    target_asset: str
    relationship_type: str
    confidence: float
    inferred_from: str
    evidence_id: str | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "arl", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("source_asset", "target_asset", "relationship_type", "inferred_from")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return _nonempty(value, field="asset relationship field")

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, value: object) -> float:
        return _unit(value, field="relationship confidence")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="evidence_id")


class InventoryReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assets: list[str]
    total: int
    as_of: datetime
    source_freshness: dict[str, datetime]
    degraded: bool = False

    @field_validator("assets")
    @classmethod
    def _assets(cls, values: list[str]) -> list[str]:
        return _refs(values, field="inventory asset")

    @field_validator("total", mode="before")
    @classmethod
    def _total(cls, value: object) -> int:
        return _nonnegative_int(value, field="inventory total")

    @field_validator("source_freshness")
    @classmethod
    def _source_freshness(cls, value: dict[str, datetime]) -> dict[str, datetime]:
        for key in value:
            _nonempty(key, field="source freshness key")
        return dict(value)


class InventoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stale_after_days: int = 30
    min_source_health: str = "ok"
    max_relationship_work: int = 50_000

    @field_validator("stale_after_days", "max_relationship_work", mode="before")
    @classmethod
    def _positive(cls, value: object) -> int:
        return _positive_int(value, field="inventory config limit")

    @field_validator("min_source_health")
    @classmethod
    def _min_source_health(cls, value: str) -> str:
        if value not in VALID_MIN_SOURCE_HEALTH:
            raise InventoryConfigInvalid(f"unknown minimum source health: {value!r}")
        return value
