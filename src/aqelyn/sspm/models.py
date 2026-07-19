"""SaaS Security Posture Management types and Z1 config validation."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from aqelyn.conventions import require_tenant_id, require_typed_id
from aqelyn.conventions.errors import SaaSConfigInvalid

GrantorKind = Literal["api", "identity"]
OverScopedStatus = Literal["over_scoped", "within_scope", "unknown"]
SaaSRouteOwner = Literal["inventory", "assetconfig", "compliance", "exposure", "iag", "risk"]

MAX_INTEGRATION_NODES: Final[int] = 100_000
VALID_GRANTOR_KINDS: Final[frozenset[str]] = frozenset(("api", "identity"))
VALID_OVER_SCOPED_STATUSES: Final[frozenset[str]] = frozenset(
    ("over_scoped", "within_scope", "unknown")
)
VALID_ROUTE_OWNERS: Final[frozenset[str]] = frozenset(
    ("inventory", "assetconfig", "compliance", "exposure", "iag", "risk")
)
RESERVED_VERDICT_KEYS: Final[frozenset[str]] = frozenset(
    (
        "severity",
        "score",
        "risk_score",
        "compliance_status",
        "finding",
        "action",
        "vendor_score",
        "vendor_trust",
        "vendor_verdict",
        "confidence",
        "reputation",
        "trust",
        "verdict",
    )
)
RESERVED_VERDICT_TOKENS: Final[frozenset[str]] = frozenset(
    "".join(character for character in value.casefold() if character.isalnum())
    for value in RESERVED_VERDICT_KEYS
)


def _nonempty(value: str, *, field: str) -> str:
    if not value.strip():
        raise SaaSConfigInvalid(f"{field} must not be empty")
    return value


def _positive_int(value: object, *, field: str, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SaaSConfigInvalid(f"{field} must be >= 1")
    if maximum is not None and value > maximum:
        raise SaaSConfigInvalid(f"{field} must be <= {maximum}")
    return value


def _unit(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SaaSConfigInvalid(f"{field} must be in [0,1]")
    selected = float(value)
    if not math.isfinite(selected) or selected < 0.0 or selected > 1.0:
        raise SaaSConfigInvalid(f"{field} must be in [0,1]")
    return selected


def _unique_nonempty(values: list[str], *, field: str) -> list[str]:
    for value in values:
        _nonempty(value, field=field)
    if len(values) != len(set(values)):
        raise SaaSConfigInvalid(f"{field} must not contain duplicates")
    return list(values)


def _typed_unique(values: list[str], *, prefix: str, field: str) -> list[str]:
    for value in values:
        require_typed_id(value, prefix, field=field)
    if len(values) != len(set(values)):
        raise SaaSConfigInvalid(f"{field} must not contain duplicates")
    return list(values)


def _known_strings(info: ValidationInfo, key: str) -> frozenset[str] | None:
    context = info.context
    if not isinstance(context, dict):
        return None
    raw = context.get(key)
    if raw is None:
        return None
    if not isinstance(raw, Iterable) or isinstance(raw, str):
        raise SaaSConfigInvalid(f"{key} must be an iterable of strings")

    known: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise SaaSConfigInvalid(f"{key} must contain only strings")
        known.append(_nonempty(item, field=key))
    return frozenset(known)


def _flat_fact_value(value: object, *, key: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise SaaSConfigInvalid(f"native_facts[{key!r}] must be finite")
    if isinstance(value, str | int | float | bool) or value is None:
        return
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, item in enumerate(value):
            if isinstance(item, float) and not math.isfinite(item):
                raise SaaSConfigInvalid(f"native_facts[{key!r}][{index}] must be finite")
            if not (isinstance(item, str | int | float | bool) or item is None):
                raise SaaSConfigInvalid(
                    f"native_facts[{key!r}][{index}] must be a scalar; "
                    "structured provider material belongs in raw evidence"
                )
        return
    raise SaaSConfigInvalid(
        f"native_facts[{key!r}] must be a scalar or a list of scalars; "
        "structured provider material belongs in raw evidence"
    )


def _reject_reserved_keys(value: object, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if isinstance(key, str) and _key_token(key) in RESERVED_VERDICT_TOKENS:
                raise SaaSConfigInvalid(f"reserved verdict key at {path}.{key}")
            _reject_reserved_keys(nested, path=f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, nested in enumerate(value):
            _reject_reserved_keys(nested, path=f"{path}[{index}]")


def _key_token(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


class SaaSAppDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    tenant: str
    app_id: str
    app_name: str
    resource_type: str
    raw: dict[str, Any]
    observed_at: datetime
    source_id: str
    evidence_id: str | None = None

    @field_validator("provider", "tenant", "app_id", "app_name", "resource_type")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return _nonempty(value, field="SaaS app descriptor field")

    @field_validator("source_id")
    @classmethod
    def _source_id(cls, value: str) -> str:
        return require_typed_id(value, "src", field="source_id")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="evidence_id")


class IntegrationDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    integration_id: str
    grantor_ref: str
    grantor_kind: GrantorKind
    third_party_app: str
    third_party_external: bool
    scopes: list[str] = Field(default_factory=list)
    granted_by: str | None = None
    granted_at: datetime | None = None
    observed_at: datetime
    raw: dict[str, Any]
    source_id: str
    evidence_id: str | None = None

    @field_validator("integration_id")
    @classmethod
    def _integration_id(cls, value: str) -> str:
        return _nonempty(value, field="integration_id")

    @field_validator("grantor_ref", "third_party_app")
    @classmethod
    def _object_ref(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="integration object reference")

    @field_validator("scopes")
    @classmethod
    def _scopes(cls, values: list[str]) -> list[str]:
        return _unique_nonempty(values, field="scopes")

    @field_validator("granted_by")
    @classmethod
    def _granted_by(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _nonempty(value, field="granted_by")

    @field_validator("source_id")
    @classmethod
    def _source_id(cls, value: str) -> str:
        return require_typed_id(value, "src", field="source_id")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "evd", field="evidence_id")


class NormalizedSaaSObject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    tenant_id: str | None = None
    object_type: str
    provider: str
    tenant: str
    native_facts: dict[str, Any] = Field(default_factory=dict)
    field_provenance: dict[str, str] = Field(default_factory=dict)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    evidence_id: str
    flagged: bool = False

    @field_validator("object_id")
    @classmethod
    def _object_id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="object_id")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("object_type", "provider", "tenant")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return _nonempty(value, field="normalized SaaS field")

    @field_validator("field_provenance")
    @classmethod
    def _field_provenance(cls, values: dict[str, str]) -> dict[str, str]:
        for key, raw_path in values.items():
            _nonempty(key, field="field_provenance key")
            _nonempty(raw_path, field=f"field_provenance[{key!r}]")
        return dict(values)

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")

    @model_validator(mode="after")
    def _provenance_and_verdict_boundary(self) -> NormalizedSaaSObject:
        facts = set(self.native_facts)
        provenance = set(self.field_provenance)
        if facts != provenance:
            missing = sorted(facts - provenance)
            orphaned = sorted(provenance - facts)
            raise SaaSConfigInvalid(
                "native_facts and field_provenance keys must match exactly; "
                f"missing provenance={missing}, orphaned provenance={orphaned}"
            )
        for key, value in self.native_facts.items():
            _flat_fact_value(value, key=key)
        _reject_reserved_keys(self.native_facts, path="native_facts")
        _reject_reserved_keys(self.field_provenance, path="field_provenance")
        _reject_reserved_keys(self.conflicts, path="conflicts")
        return self


class BlastRadius(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_ids: list[str] = Field(default_factory=list)
    truncated: bool = False

    @field_validator("object_ids")
    @classmethod
    def _object_ids(cls, values: list[str]) -> list[str]:
        return _typed_unique(values, prefix="obj", field="object_ids")


class SaaSIntegration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    tenant_id: str | None = None
    integration_id: str
    grantor_ref: str
    grantor_kind: GrantorKind
    third_party_app: str
    third_party_external: bool
    scopes: list[str] = Field(default_factory=list)
    over_scoped: OverScopedStatus
    reachable_object_ids: list[str] = Field(default_factory=list)
    reachable_truncated: bool = False
    known_surface_ref: str | None = None
    claim_confidence: float
    evidence_id: str
    observed_at: datetime
    reason: str

    @field_validator("object_id", "grantor_ref", "third_party_app")
    @classmethod
    def _object_ref(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="integration object reference")

    @field_validator("tenant_id")
    @classmethod
    def _tenant_id(cls, value: str | None) -> str | None:
        return require_tenant_id(value)

    @field_validator("integration_id", "reason")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return _nonempty(value, field="SaaS integration field")

    @field_validator("scopes")
    @classmethod
    def _scopes(cls, values: list[str]) -> list[str]:
        return _unique_nonempty(values, field="scopes")

    @field_validator("reachable_object_ids")
    @classmethod
    def _reachable_object_ids(cls, values: list[str]) -> list[str]:
        return _typed_unique(values, prefix="obj", field="reachable_object_ids")

    @field_validator("known_surface_ref")
    @classmethod
    def _known_surface_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "obj", field="known_surface_ref")

    @field_validator("claim_confidence", mode="before")
    @classmethod
    def _claim_confidence(cls, value: object) -> float:
        return _unit(value, field="claim_confidence")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, value: str) -> str:
        return require_typed_id(value, "evd", field="evidence_id")

    @model_validator(mode="after")
    def _known_surface_state(self) -> SaaSIntegration:
        if self.over_scoped == "over_scoped":
            if not self.third_party_external:
                raise SaaSConfigInvalid("over_scoped integration must be external")
            if self.known_surface_ref != self.object_id:
                raise SaaSConfigInvalid(
                    "over_scoped integration requires known_surface_ref == object_id"
                )
        elif self.known_surface_ref is not None:
            raise SaaSConfigInvalid(
                "known_surface_ref is permitted only for an over_scoped integration"
            )
        return self


class SaaSRoutingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    routed_to: list[SaaSRouteOwner] = Field(default_factory=list)
    routing_pending: list[SaaSRouteOwner] = Field(default_factory=list)
    inventory_ref: str | None = None
    iam_refs: list[str] = Field(default_factory=list)
    known_surface_refs: list[str] = Field(default_factory=list)
    integration_ref: str | None = None

    @field_validator("object_id")
    @classmethod
    def _object_id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="object_id")

    @field_validator("routed_to", "routing_pending")
    @classmethod
    def _owners(cls, values: list[SaaSRouteOwner]) -> list[SaaSRouteOwner]:
        if len(values) != len(set(values)):
            raise SaaSConfigInvalid("routing owners must not contain duplicates")
        return list(values)

    @field_validator("inventory_ref", "integration_ref")
    @classmethod
    def _optional_object_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_typed_id(value, "obj", field="routing object reference")

    @field_validator("iam_refs", "known_surface_refs")
    @classmethod
    def _object_refs(cls, values: list[str]) -> list[str]:
        return _typed_unique(values, prefix="obj", field="routing object references")

    @model_validator(mode="after")
    def _owner_sets_do_not_overlap(self) -> SaaSRoutingResult:
        overlap = sorted(set(self.routed_to) & set(self.routing_pending))
        if overlap:
            raise SaaSConfigInvalid(f"routed and pending owners overlap: {overlap}")
        return self


class SaaSConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type_map: dict[str, str] = Field(default_factory=dict)
    baseline_ids: list[str] = Field(default_factory=list)
    sensitive_scopes: list[str] = Field(default_factory=list)
    batch_size: int = 100
    integration_max_nodes: int = 10_000

    @field_validator("type_map")
    @classmethod
    def _type_map(cls, values: dict[str, str]) -> dict[str, str]:
        for resource_type, object_type in values.items():
            _nonempty(resource_type, field="type_map resource type")
            _nonempty(object_type, field=f"type_map[{resource_type!r}]")
        return dict(values)

    @field_validator("baseline_ids")
    @classmethod
    def _baseline_ids(cls, values: list[str]) -> list[str]:
        return _unique_nonempty(values, field="baseline_ids")

    @field_validator("sensitive_scopes")
    @classmethod
    def _sensitive_scopes(cls, values: list[str]) -> list[str]:
        return _unique_nonempty(values, field="sensitive_scopes")

    @field_validator("batch_size", mode="before")
    @classmethod
    def _batch_size(cls, value: object) -> int:
        return _positive_int(value, field="batch_size")

    @field_validator("integration_max_nodes", mode="before")
    @classmethod
    def _integration_max_nodes(cls, value: object) -> int:
        return _positive_int(
            value,
            field="integration_max_nodes",
            maximum=MAX_INTEGRATION_NODES,
        )

    @model_validator(mode="after")
    def _known_references(self, info: ValidationInfo) -> SaaSConfig:
        known_object_types = _known_strings(info, "known_object_types")
        if known_object_types is not None:
            for resource_type, object_type in self.type_map.items():
                if object_type not in known_object_types:
                    raise SaaSConfigInvalid(
                        f"type_map {resource_type!r} references unknown object type {object_type!r}"
                    )

        known_baseline_ids = _known_strings(info, "known_baseline_ids")
        if known_baseline_ids is not None:
            for baseline_id in self.baseline_ids:
                if baseline_id not in known_baseline_ids:
                    raise SaaSConfigInvalid(f"unknown baseline_id: {baseline_id!r}")
        return self
