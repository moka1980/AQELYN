"""Selective SaaS descriptor normalization helpers (EA-0029 Z2)."""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping, Sequence
from typing import Any, Protocol, cast

from aqelyn.conventions import ActorRef
from aqelyn.conventions.errors import SaaSConfigInvalid
from aqelyn.objects import AQObject, NaturalKey, SourceRef
from aqelyn.objects.registry import ObjectTypeRegistry
from aqelyn.sspm.models import (
    RESERVED_VERDICT_TOKENS,
    NormalizedSaaSObject,
    SaaSAppDescriptor,
    SaaSConfig,
)

SAAS_UNKNOWN_OBJECT_TYPE = "saas_unknown"
SAAS_INTEGRATION_OBJECT_TYPE = "saas_integration"


class _ObjectStoreRegistry(Protocol):
    registry: ObjectTypeRegistry


def register_saas_object_types(registry: ObjectTypeRegistry, config: SaaSConfig) -> None:
    for object_type in sorted(
        {*config.type_map.values(), SAAS_UNKNOWN_OBJECT_TYPE, SAAS_INTEGRATION_OBJECT_TYPE}
    ):
        registry.register(object_type, 1, None)


def ensure_saas_object_types(object_store: object, config: SaaSConfig) -> None:
    registry = getattr(object_store, "registry", None)
    if isinstance(registry, ObjectTypeRegistry):
        register_saas_object_types(registry, config)
        return
    if registry is not None:
        register_saas_object_types(cast(_ObjectStoreRegistry, object_store).registry, config)


def mapping_key(descriptor: SaaSAppDescriptor, config: SaaSConfig) -> str | None:
    provider_scoped = f"{descriptor.provider}:{descriptor.resource_type}"
    for candidate in (provider_scoped, descriptor.resource_type):
        if candidate in config.type_map:
            return candidate
    return None


def object_type_for(descriptor: SaaSAppDescriptor, config: SaaSConfig) -> tuple[str, str | None]:
    selected_key = mapping_key(descriptor, config)
    if selected_key is None:
        return SAAS_UNKNOWN_OBJECT_TYPE, None
    return config.type_map[selected_key], selected_key


def extract_native_facts(raw: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Select flat provider facts; structured material remains in raw evidence."""
    facts: dict[str, Any] = {}
    provenance: dict[str, str] = {}
    for key in sorted(raw):
        if _key_token(key) in RESERVED_VERDICT_TOKENS:
            continue
        value = raw[key]
        if not _is_flat_fact(value):
            continue
        facts[key] = copy.deepcopy(value)
        provenance[key] = f"/{_pointer_token(key)}"
    return facts, provenance


def saas_natural_key(descriptor: SaaSAppDescriptor) -> NaturalKey:
    return NaturalKey(
        namespace=f"saas_app.{descriptor.provider}.{descriptor.tenant}",
        value=descriptor.app_id,
    )


def normalized_to_object(
    obj: NormalizedSaaSObject,
    *,
    descriptor: SaaSAppDescriptor,
    actor: ActorRef,
    confidence: float,
) -> AQObject:
    source = SourceRef(
        source_id=descriptor.source_id,
        evidence_id=obj.evidence_id,
        observed_at=descriptor.observed_at,
        method="sspm.normalize/v1",
    )
    return AQObject(
        id=obj.object_id,
        object_type=obj.object_type,
        schema_version=1,
        tenant_id=obj.tenant_id,
        display_name=f"{descriptor.provider}:{descriptor.tenant}:{descriptor.app_name}",
        attributes={
            "provider": obj.provider,
            "provider_tenant": obj.tenant,
            "app_id": descriptor.app_id,
            "native_facts": copy.deepcopy(obj.native_facts),
            "observed_state": copy.deepcopy(obj.native_facts),
            "field_provenance": dict(obj.field_provenance),
            "conflicts": copy.deepcopy(obj.conflicts),
            "flagged": obj.flagged,
        },
        labels={
            "module": "EA-0029",
            "kind": "saas_app",
            "provider": obj.provider,
        },
        natural_keys=[saas_natural_key(descriptor)],
        sources=[source],
        confidence=confidence,
        first_seen_at=descriptor.observed_at,
        last_seen_at=descriptor.observed_at,
        created_at=descriptor.observed_at,
        updated_at=descriptor.observed_at,
        created_by=actor,
        updated_by=actor,
    )


def _key_token(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _is_flat_fact(value: object) -> bool:
    if isinstance(value, float) and not math.isfinite(value):
        raise SaaSConfigInvalid("normalized SaaS facts must be finite")
    if isinstance(value, str | int | float | bool) or value is None:
        return True
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for item in value:
            if isinstance(item, float) and not math.isfinite(item):
                raise SaaSConfigInvalid("normalized SaaS facts must be finite")
            if not (isinstance(item, str | int | float | bool) or item is None):
                return False
        return True
    return False
