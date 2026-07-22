"""Threat Exposure & Attack Surface models (EA-0023 E1)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aqelyn.conventions import new_id, require_tenant_id, require_typed_id
from aqelyn.conventions.errors import (
    ExposureBasisMissing,
    ExposureConfigInvalid,
    ScanNotPermitted,
    SchemaValidationError,
)
from aqelyn.decision import Derivation
from aqelyn.workflow.models import ActionSpec

Reachability = Literal["external", "internal", "unknown"]
AssetKind = Literal["asset", "cloud", "api", "identity", "domain", "cert"]
ExposureBasisKind = Literal["inventory", "telemetry", "access", "graph"]
ExposureStatus = Literal["open", "revalidated", "closed"]
ExposureLevel = Literal["high", "medium", "low", "unknown"]
ExposureImpactKind = Literal["data_sensitivity", "credential_sensitivity", "identity_sensitivity"]
ExposureImpactStatus = Literal["known", "unknown"]

VALID_REACHABILITY: Final[frozenset[str]] = frozenset(("external", "internal", "unknown"))
VALID_ASSET_KINDS: Final[frozenset[str]] = frozenset(
    ("asset", "cloud", "api", "identity", "domain", "cert")
)
VALID_BASIS_KINDS: Final[frozenset[str]] = frozenset(("inventory", "telemetry", "access", "graph"))
VALID_EXPOSURE_STATUS: Final[frozenset[str]] = frozenset(("open", "revalidated", "closed"))
VALID_EXPOSURE_LEVELS: Final[frozenset[str]] = frozenset(("high", "medium", "low", "unknown"))
ACTIVE_SCAN_CAPABILITY: Final[str] = "scan.active"


def _nonempty(value: str, *, field: str) -> str:
    if not value.strip():
        raise ExposureConfigInvalid(f"{field} must not be empty")
    return value


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ExposureConfigInvalid(f"{field} must be >= 1")
    return value


def _finite(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ExposureConfigInvalid(f"{field} must be a finite number")
    selected = float(value)
    if not math.isfinite(selected):
        raise ExposureConfigInvalid(f"{field} must be a finite number")
    return selected


def _unit(value: object, *, field: str) -> float:
    selected = _finite(value, field=field)
    if selected < 0.0 or selected > 1.0:
        raise ExposureConfigInvalid(f"{field} must be in [0,1]")
    return selected


class AssetRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    ref_id: str
    object_id: str | None = None
    evidence_id: str | None = None

    @field_validator("kind")
    @classmethod
    def _kind(cls, value: str) -> str:
        if value not in VALID_ASSET_KINDS:
            raise ExposureConfigInvalid(f"unknown asset kind: {value!r}")
        return value

    @field_validator("ref_id")
    @classmethod
    def _ref_id(cls, value: str) -> str:
        return _nonempty(value, field="asset ref_id")

    @field_validator("object_id")
    @classmethod
    def _object_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return require_typed_id(value, "obj", field="asset object_id")
        except SchemaValidationError as exc:
            raise ExposureConfigInvalid(exc.message) from exc

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="evidence_id")

    @model_validator(mode="after")
    def _identity_consistency(self) -> AssetRef:
        if self.ref_id.startswith("obj_"):
            try:
                subject = require_typed_id(self.ref_id, "obj", field="asset ref_id")
            except SchemaValidationError as exc:
                raise ExposureConfigInvalid(exc.message) from exc
            if self.object_id is not None and self.object_id != subject:
                raise ExposureConfigInvalid(
                    "asset object_id must match ref_id when the surface identity is obj_"
                )
        return self


class ExposureBasis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    ref: str
    as_of: datetime
    evidence_id: str | None = None

    @field_validator("kind")
    @classmethod
    def _kind(cls, value: str) -> str:
        if value not in VALID_BASIS_KINDS:
            raise ExposureConfigInvalid(f"unknown exposure basis kind: {value!r}")
        return value

    @field_validator("ref")
    @classmethod
    def _ref(cls, value: str) -> str:
        return _nonempty(value, field="exposure basis ref")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="evidence_id")


class ExposureImpactContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ExposureImpactKind = "data_sensitivity"
    status: ExposureImpactStatus
    factor: float | None = None
    source_ref: str
    evidence_id: str
    reason: str

    @field_validator("source_ref", "reason")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="exposure impact context field")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="impact context evidence_id")

    @field_validator("factor", mode="before")
    @classmethod
    def _factor(cls, value: object) -> float | None:
        if value is None:
            return None
        return _unit(value, field="impact context factor")

    @model_validator(mode="after")
    def _status_consistency(self) -> ExposureImpactContext:
        if self.status == "known" and self.factor is None:
            raise ExposureConfigInvalid("known impact context requires a factor")
        if self.status == "unknown" and self.factor is not None:
            raise ExposureConfigInvalid("unknown impact context cannot carry a factor")
        return self


class ExposureRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("exp"))
    tenant_id: str | None = None
    asset_ref: AssetRef
    exposure_type: str
    reachability: str
    basis: list[ExposureBasis]
    impact_context: ExposureImpactContext | None = None
    score: float | None = None
    confidence: float | None = None
    derivation: Derivation | None = None
    rationale: str
    flagged: bool
    discovered_at: datetime
    validated_at: datetime | None = None
    status: str = "open"

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "exp", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("exposure_type", "rationale")
    @classmethod
    def _text(cls, value: str) -> str:
        return _nonempty(value, field="exposure field")

    @field_validator("reachability")
    @classmethod
    def _reachability(cls, value: str) -> str:
        if value not in VALID_REACHABILITY:
            raise ExposureConfigInvalid(f"unknown reachability: {value!r}")
        return value

    @field_validator("basis")
    @classmethod
    def _basis(cls, values: list[ExposureBasis]) -> list[ExposureBasis]:
        if not values:
            raise ExposureBasisMissing("exposure requires at least one basis")
        return values

    @field_validator("score")
    @classmethod
    def _score(cls, value: float | None) -> float | None:
        if value is None:
            return None
        selected = _finite(value, field="exposure score")
        if selected < 0.0 or selected > 100.0:
            raise ExposureConfigInvalid("exposure score must be in [0,100]")
        return selected

    @field_validator("confidence")
    @classmethod
    def _confidence(cls, value: float | None) -> float | None:
        if value is None:
            return None
        return _unit(value, field="exposure confidence")

    @field_validator("status")
    @classmethod
    def _status(cls, value: str) -> str:
        if value not in VALID_EXPOSURE_STATUS:
            raise ExposureConfigInvalid(f"unknown exposure status: {value!r}")
        return value

    @model_validator(mode="after")
    def _unknown_is_flagged(self) -> ExposureRecord:
        if self.reachability == "unknown" and not self.flagged:
            raise ExposureConfigInvalid("unknown reachability must be flagged")
        if (
            self.score is not None
            and self.impact_context is not None
            and self.impact_context.status != "known"
        ):
            raise ExposureConfigInvalid("scored exposure cannot carry unknown impact context")
        return self


class AttackSurfaceAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("asa"))
    tenant_id: str | None = None
    asset_ref: AssetRef
    classification: str
    exposure_level: str
    discovered_at: datetime
    validated_at: datetime | None = None
    basis: list[ExposureBasis]

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        return require_typed_id(value, "asa", field="id", allow_empty=True)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("classification")
    @classmethod
    def _classification(cls, value: str) -> str:
        return _nonempty(value, field="classification")

    @field_validator("exposure_level")
    @classmethod
    def _exposure_level(cls, value: str) -> str:
        if value not in VALID_EXPOSURE_LEVELS:
            raise ExposureConfigInvalid(f"unknown exposure level: {value!r}")
        return value

    @field_validator("basis")
    @classmethod
    def _basis(cls, values: list[ExposureBasis]) -> list[ExposureBasis]:
        if not values:
            raise ExposureBasisMissing("attack surface asset requires at least one basis")
        return values


class ReachablePath(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_ref: str
    path: list[str]
    via: str = "graph"
    max_work: int

    @field_validator("target_ref")
    @classmethod
    def _target_ref(cls, value: str) -> str:
        return _nonempty(value, field="target_ref")

    @field_validator("path")
    @classmethod
    def _path(cls, values: list[str]) -> list[str]:
        if not values:
            raise ExposureConfigInvalid("reachable path must not be empty")
        for value in values:
            _nonempty(value, field="reachable path segment")
        return values

    @field_validator("via")
    @classmethod
    def _via(cls, value: str) -> str:
        if value != "graph":
            raise ExposureConfigInvalid("reachable paths must use via='graph'")
        return value

    @field_validator("max_work", mode="before")
    @classmethod
    def _max_work(cls, value: object) -> int:
        return _positive_int(value, field="max_work")


class ExposureConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_paths: int = 20
    max_work: int = 50_000
    default_level: str = "unknown"
    score_weights: dict[str, float] = Field(
        default_factory=lambda: {"mission": 0.45, "trust": 0.25, "risk": 0.30}
    )

    @field_validator("max_paths", "max_work", mode="before")
    @classmethod
    def _positive(cls, value: object) -> int:
        return _positive_int(value, field="exposure config limit")

    @field_validator("default_level")
    @classmethod
    def _default_level(cls, value: str) -> str:
        if value not in VALID_EXPOSURE_LEVELS:
            raise ExposureConfigInvalid(f"unknown default exposure level: {value!r}")
        return value

    @field_validator("score_weights")
    @classmethod
    def _score_weights(cls, values: dict[str, float]) -> dict[str, float]:
        if not values:
            raise ExposureConfigInvalid("score_weights must not be empty")
        out: dict[str, float] = {}
        for key, value in values.items():
            selected_key = _nonempty(key, field="score weight key")
            selected = _finite(value, field=f"score_weights[{selected_key!r}]")
            if selected < 0.0:
                raise ExposureConfigInvalid("score weights must be non-negative")
            out[selected_key] = selected
        return out


def active_reachability_action_spec() -> ActionSpec:
    """Describe future active scanning as a gated EA-0008 action, not execution."""

    return ActionSpec(
        action_type="exposure.active_reachability_collection",
        capability=ACTIVE_SCAN_CAPABILITY,
        effect="reversible",
        reversible=True,
        description="Request active reachability collection through a gated connector.",
    )


async def refuse_active_reachability_collection() -> None:
    raise ScanNotPermitted(
        "active reachability collection must be proposed as an EA-0008 scan.active action"
    )
