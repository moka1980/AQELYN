"""Cloud Security Posture Management models and Y1 config validation."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from aqelyn.conventions import require_tenant_id, require_typed_id
from aqelyn.conventions.errors import CloudConfigInvalid

Provider = Literal["aws", "azure", "gcp", "oci", "other"]
CloudChangeKind = Literal["observed", "reported_deleted"]
RouteOwner = Literal["inventory", "assetconfig", "compliance", "exposure", "iag", "risk"]
OwnerRouteStatus = Literal["accepted", "failed"]
CloudRoutingStatus = Literal["complete", "partial", "failed"]

ROUTE_OWNERS: Final[frozenset[str]] = frozenset(
    ("inventory", "assetconfig", "compliance", "exposure", "iag", "risk")
)
RESERVED_VERDICT_KEYS: Final[frozenset[str]] = frozenset(
    ("severity", "score", "risk_score", "compliance_status", "finding", "action")
)


def _nonempty(value: str, *, field: str) -> str:
    if not value.strip():
        raise CloudConfigInvalid(f"{field} must not be empty")
    return value


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CloudConfigInvalid(f"{field} must be >= 1")
    return value


def _unique_nonempty(values: list[str], *, field: str) -> list[str]:
    for value in values:
        _nonempty(value, field=field)
    if len(values) != len(set(values)):
        raise CloudConfigInvalid(f"{field} must not contain duplicates")
    return values


def _known_strings(info: ValidationInfo, key: str) -> frozenset[str] | None:
    context = info.context
    if not isinstance(context, dict):
        return None
    raw = context.get(key)
    if raw is None:
        return None
    if not isinstance(raw, Iterable) or isinstance(raw, str):
        raise CloudConfigInvalid(f"{key} must be an iterable of strings")

    known: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise CloudConfigInvalid(f"{key} must contain only strings")
        known.append(_nonempty(item, field=key))
    return frozenset(known)


def _json_pointer(value: str, *, field: str) -> str:
    _nonempty(value, field=field)
    if not value.startswith("/"):
        raise CloudConfigInvalid(f"{field} must be an absolute RFC 6901 JSON Pointer")
    index = 0
    while index < len(value):
        if value[index] != "~":
            index += 1
            continue
        if index + 1 >= len(value) or value[index + 1] not in {"0", "1"}:
            raise CloudConfigInvalid(f"{field} contains an invalid JSON Pointer escape")
        index += 2
    return value


def _flat_fact_value(value: object, *, key: str) -> None:
    """Normalized facts are flat, so top-level provenance binding covers every key.

    A nested mapping would carry keys no `field_provenance` entry declares, which is
    where an invented verdict could hide (ECR-0023). Structured provider material
    belongs in the raw EA-0004 evidence block, not in normalized state.
    """
    if isinstance(value, float) and not math.isfinite(value):
        raise CloudConfigInvalid(f"native_facts[{key!r}] must be finite")
    if isinstance(value, str | int | float | bool) or value is None:
        return
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, item in enumerate(value):
            if isinstance(item, float) and not math.isfinite(item):
                raise CloudConfigInvalid(f"native_facts[{key!r}][{index}] must be finite")
            if not (isinstance(item, str | int | float | bool) or item is None):
                raise CloudConfigInvalid(
                    f"native_facts[{key!r}][{index}] must be a scalar; "
                    "structured provider material belongs in raw evidence"
                )
        return
    raise CloudConfigInvalid(
        f"native_facts[{key!r}] must be a scalar or a list of scalars; "
        "structured provider material belongs in raw evidence"
    )


def _reject_reserved_keys(value: object, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if isinstance(key, str) and key.casefold() in RESERVED_VERDICT_KEYS:
                raise CloudConfigInvalid(f"reserved verdict key at {path}.{key}")
            _reject_reserved_keys(nested, path=f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, nested in enumerate(value):
            _reject_reserved_keys(nested, path=f"{path}[{index}]")


class CloudResourceDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Provider
    account: str
    region: str | None = None
    resource_type: str
    resource_id: str
    raw: dict[str, Any]
    observed_at: datetime
    source_id: str
    evidence_id: str | None = None
    change_kind: CloudChangeKind = "observed"

    @field_validator("account", "resource_type", "resource_id")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return _nonempty(value, field="cloud descriptor field")

    @field_validator("region")
    @classmethod
    def _region(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _nonempty(value, field="region")

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


class NormalizedCloudObject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    object_type: str
    tenant_id: str | None = None
    provider: Provider
    account: str
    region: str | None = None
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

    @field_validator("object_type", "account")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return _nonempty(value, field="normalized cloud field")

    @field_validator("region")
    @classmethod
    def _region(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _nonempty(value, field="region")

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
    def _provenance_and_verdict_boundary(self) -> NormalizedCloudObject:
        facts = set(self.native_facts)
        provenance = set(self.field_provenance)
        if facts != provenance:
            missing = sorted(facts - provenance)
            orphaned = sorted(provenance - facts)
            raise CloudConfigInvalid(
                "native_facts and field_provenance keys must match exactly; "
                f"missing provenance={missing}, orphaned provenance={orphaned}"
            )
        for key, value in self.native_facts.items():
            _flat_fact_value(value, key=key)
        _reject_reserved_keys(self.field_provenance, path="field_provenance")
        _reject_reserved_keys(self.native_facts, path="native_facts")
        _reject_reserved_keys(self.conflicts, path="conflicts")
        return self


class OwnerRouteOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner: RouteOwner
    status: OwnerRouteStatus
    refs: list[str] = Field(default_factory=list)
    detail: str | None = None

    @field_validator("refs")
    @classmethod
    def _refs(cls, values: list[str]) -> list[str]:
        return _unique_nonempty(values, field="route ref")

    @field_validator("detail")
    @classmethod
    def _detail(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _nonempty(value, field="route detail")

    @model_validator(mode="after")
    def _failed_route_has_detail(self) -> OwnerRouteOutcome:
        if self.status == "failed" and self.detail is None:
            raise CloudConfigInvalid("failed owner route requires detail")
        return self


class CloudRoutingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    status: CloudRoutingStatus
    outcomes: list[OwnerRouteOutcome]

    @field_validator("object_id")
    @classmethod
    def _object_id(cls, value: str) -> str:
        return require_typed_id(value, "obj", field="object_id")

    @field_validator("outcomes")
    @classmethod
    def _outcomes(cls, values: list[OwnerRouteOutcome]) -> list[OwnerRouteOutcome]:
        if not values:
            raise CloudConfigInvalid("routing result requires owner outcomes")
        owners = [outcome.owner for outcome in values]
        if len(owners) != len(set(owners)):
            raise CloudConfigInvalid("routing result owners must be unique")
        return values

    @model_validator(mode="after")
    def _status_matches_outcomes(self) -> CloudRoutingResult:
        accepted = sum(outcome.status == "accepted" for outcome in self.outcomes)
        expected: CloudRoutingStatus
        if accepted == len(self.outcomes):
            expected = "complete"
        elif accepted == 0:
            expected = "failed"
        else:
            expected = "partial"
        if self.status != expected:
            raise CloudConfigInvalid(
                f"routing status must be {expected!r} for the supplied owner outcomes"
            )
        return self


class CloudNormalizationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type_map: dict[str, str] = Field(default_factory=dict)
    fact_paths: dict[str, dict[str, str]] = Field(default_factory=dict)
    baseline_ids: list[str] = Field(default_factory=list)
    batch_size: int = 100

    @field_validator("type_map")
    @classmethod
    def _type_map(cls, values: dict[str, str]) -> dict[str, str]:
        for resource_type, object_type in values.items():
            _nonempty(resource_type, field="type_map resource type")
            _nonempty(object_type, field=f"type_map[{resource_type!r}]")
        return dict(values)

    @field_validator("fact_paths")
    @classmethod
    def _fact_paths(cls, values: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        selected: dict[str, dict[str, str]] = {}
        for mapping_key, paths in values.items():
            _nonempty(mapping_key, field="fact_paths mapping key")
            normalized: dict[str, str] = {}
            for fact_key, pointer in paths.items():
                _nonempty(fact_key, field=f"fact_paths[{mapping_key!r}] fact key")
                _reject_reserved_keys({fact_key: None}, path=f"fact_paths.{mapping_key}")
                normalized[fact_key] = _json_pointer(
                    pointer,
                    field=f"fact_paths[{mapping_key!r}][{fact_key!r}]",
                )
            if len(normalized.values()) != len(set(normalized.values())):
                raise CloudConfigInvalid(
                    f"fact_paths[{mapping_key!r}] must not map one raw path more than once"
                )
            selected[mapping_key] = normalized
        return selected

    @field_validator("baseline_ids")
    @classmethod
    def _baseline_ids(cls, values: list[str]) -> list[str]:
        return _unique_nonempty(values, field="baseline_ids")

    @field_validator("batch_size", mode="before")
    @classmethod
    def _batch_size(cls, value: object) -> int:
        return _positive_int(value, field="batch_size")

    @model_validator(mode="after")
    def _known_references(self, info: ValidationInfo) -> CloudNormalizationConfig:
        orphaned_fact_maps = sorted(set(self.fact_paths) - set(self.type_map))
        if orphaned_fact_maps:
            raise CloudConfigInvalid(
                f"fact_paths require matching type_map entries: {orphaned_fact_maps}"
            )

        known_object_types = _known_strings(info, "known_object_types")
        if known_object_types is not None:
            for resource_type, object_type in self.type_map.items():
                if object_type not in known_object_types:
                    raise CloudConfigInvalid(
                        f"type_map {resource_type!r} references unknown object type {object_type!r}"
                    )

        known_baseline_ids = _known_strings(info, "known_baseline_ids")
        if known_baseline_ids is not None:
            for baseline_id in self.baseline_ids:
                if baseline_id not in known_baseline_ids:
                    raise CloudConfigInvalid(f"unknown baseline_id: {baseline_id!r}")
        return self
