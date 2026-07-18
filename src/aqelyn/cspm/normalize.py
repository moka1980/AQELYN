"""Selective cloud descriptor normalization helpers (EA-0028 Y2)."""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping, Sequence
from typing import Any, Protocol, cast

from aqelyn.conventions import ActorRef
from aqelyn.conventions.errors import CloudConfigInvalid
from aqelyn.cspm.models import (
    CloudNormalizationConfig,
    CloudResourceDescriptor,
    NormalizedCloudObject,
)
from aqelyn.objects import AQObject, NaturalKey, SourceRef
from aqelyn.objects.registry import ObjectTypeRegistry

CLOUD_UNKNOWN_OBJECT_TYPE = "cloud_unknown"
_MISSING = object()


class _ObjectStoreRegistry(Protocol):
    registry: ObjectTypeRegistry


def register_cloud_object_types(
    registry: ObjectTypeRegistry,
    config: CloudNormalizationConfig,
) -> None:
    for object_type in sorted({*config.type_map.values(), CLOUD_UNKNOWN_OBJECT_TYPE}):
        registry.register(object_type, 1, None)


def ensure_cloud_object_types(object_store: object, config: CloudNormalizationConfig) -> None:
    registry = getattr(object_store, "registry", None)
    if isinstance(registry, ObjectTypeRegistry):
        register_cloud_object_types(registry, config)
        return
    if registry is not None:
        register_cloud_object_types(cast(_ObjectStoreRegistry, object_store).registry, config)


def mapping_key(
    descriptor: CloudResourceDescriptor,
    config: CloudNormalizationConfig,
) -> str | None:
    provider_scoped = f"{descriptor.provider}:{descriptor.resource_type}"
    for candidate in (provider_scoped, descriptor.resource_type):
        if candidate in config.type_map:
            return candidate
    return None


def object_type_for(
    descriptor: CloudResourceDescriptor,
    config: CloudNormalizationConfig,
) -> tuple[str, str | None]:
    selected_key = mapping_key(descriptor, config)
    if selected_key is None:
        return CLOUD_UNKNOWN_OBJECT_TYPE, None
    return config.type_map[selected_key], selected_key


def extract_native_facts(
    raw: Mapping[str, Any],
    paths: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, str]]:
    facts: dict[str, Any] = {}
    provenance: dict[str, str] = {}
    for fact_key in sorted(paths):
        pointer = paths[fact_key]
        value = resolve_json_pointer(raw, pointer)
        if value is _MISSING:
            continue
        _validate_selected_value(value, pointer=pointer)
        facts[fact_key] = copy.deepcopy(value)
        provenance[fact_key] = pointer
    return facts, provenance


def resolve_json_pointer(document: object, pointer: str) -> object:
    current = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if token not in current:
                return _MISSING
            current = current[token]
            continue
        if isinstance(current, Sequence) and not isinstance(current, str | bytes | bytearray):
            if not token.isdigit():
                return _MISSING
            index = int(token)
            if index >= len(current):
                return _MISSING
            current = current[index]
            continue
        return _MISSING
    return current


def cloud_natural_key(descriptor: CloudResourceDescriptor) -> NaturalKey:
    return NaturalKey(
        namespace=f"cloud_resource.{descriptor.provider}.{descriptor.account}",
        value=descriptor.resource_id,
    )


def normalized_to_object(
    obj: NormalizedCloudObject,
    *,
    descriptor: CloudResourceDescriptor,
    actor: ActorRef,
    confidence: float,
) -> AQObject:
    source = SourceRef(
        source_id=descriptor.source_id,
        evidence_id=obj.evidence_id,
        observed_at=descriptor.observed_at,
        method="cspm.normalize/v1",
    )
    return AQObject(
        id=obj.object_id,
        object_type=obj.object_type,
        schema_version=1,
        tenant_id=obj.tenant_id,
        display_name=f"{descriptor.provider}:{descriptor.account}:{descriptor.resource_id}",
        attributes={
            "provider": obj.provider,
            "account": obj.account,
            "region": obj.region,
            "resource_id": descriptor.resource_id,
            "native_facts": copy.deepcopy(obj.native_facts),
            "field_provenance": dict(obj.field_provenance),
            "conflicts": copy.deepcopy(obj.conflicts),
            "flagged": obj.flagged,
        },
        labels={
            "module": "EA-0028",
            "kind": "cloud_resource",
            "provider": obj.provider,
        },
        natural_keys=[cloud_natural_key(descriptor)],
        sources=[source],
        confidence=confidence,
        first_seen_at=descriptor.observed_at,
        last_seen_at=descriptor.observed_at,
        created_at=descriptor.observed_at,
        updated_at=descriptor.observed_at,
        created_by=actor,
        updated_by=actor,
    )


def _validate_selected_value(value: object, *, pointer: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise CloudConfigInvalid(f"configured fact path {pointer!r} selected a non-finite number")
    if isinstance(value, str | int | float | bool) or value is None:
        return
    if (
        isinstance(value, Sequence)
        and not isinstance(value, str | bytes | bytearray)
        and all(isinstance(item, str | int | float | bool) or item is None for item in value)
    ):
        if any(isinstance(item, float) and not math.isfinite(item) for item in value):
            raise CloudConfigInvalid(
                f"configured fact path {pointer!r} selected a non-finite number"
            )
        return
    raise CloudConfigInvalid(
        f"configured fact path {pointer!r} selected structured provider material; "
        "select scalar leaves instead"
    )
