"""Threat feed normalization helpers (EA-0014 T1)."""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from aqelyn.conventions import ActorRef, utc_now
from aqelyn.conventions.errors import MalformedFeedRecord, ThreatConfigInvalid
from aqelyn.objects import AQObject, NaturalKey, SourceRef
from aqelyn.objects.registry import ObjectTypeRegistry
from aqelyn.threat.models import (
    THREAT_INDICATOR_OBJECT_TYPE,
    THREAT_OBJECT_TYPES,
    FeedRecord,
    FusionConfig,
    IndicatorType,
    ThreatIndicator,
)

_TYPE_ALIASES: dict[str, IndicatorType] = {
    "domain": "domain",
    "domain_name": "domain",
    "fqdn": "domain",
    "ip": "ip",
    "ipv4": "ip",
    "ipv6": "ip",
    "ip_address": "ip",
    "hash": "hash",
    "file_hash": "hash",
    "sha1": "hash",
    "sha256": "hash",
    "md5": "hash",
    "url": "url",
    "uri": "url",
}
_ACTOR = ActorRef(actor_type="system", actor_id="threat_fusion_engine")


class _ObjectStoreRegistry(Protocol):
    registry: ObjectTypeRegistry


def register_threat_object_types(registry: ObjectTypeRegistry) -> None:
    for object_type in THREAT_OBJECT_TYPES:
        registry.register(object_type, 1, None)


def normalize_record(
    record: FeedRecord,
    *,
    tenant_id: str | None,
    config: FusionConfig | None = None,
) -> ThreatIndicator:
    selected_config = config or FusionConfig()
    raw = record.raw
    indicator_type = _normalize_type(_raw_string(raw, ("indicator_type", "type", "kind")))
    value = _normalize_value(indicator_type, _raw_string(raw, ("value", "indicator", "observable")))
    now = record.received_at
    expires_at = _optional_datetime(raw.get("expires_at"))
    confidence = _raw_confidence(raw.get("confidence"), record.source_id, selected_config)
    return ThreatIndicator(
        tenant_id=tenant_id,
        indicator_type=indicator_type,
        value=value,
        ttps=_raw_string_list(raw.get("ttps", []), field="ttps"),
        actor_ids=_raw_string_list(raw.get("actor_ids", []), field="actor_ids"),
        campaign_ids=_raw_string_list(raw.get("campaign_ids", []), field="campaign_ids"),
        confidence=confidence,
        first_seen_at=now,
        last_seen_at=now,
        sources=[
            SourceRef(
                source_id=record.source_id,
                evidence_id=record.evidence_id,
                observed_at=record.received_at,
                method="threat.feed_record/v1",
            )
        ],
        expires_at=expires_at,
    )


def indicator_to_object(indicator: ThreatIndicator, *, by: ActorRef = _ACTOR) -> AQObject:
    return AQObject(
        id=indicator.id,
        object_type=THREAT_INDICATOR_OBJECT_TYPE,
        schema_version=1,
        tenant_id=indicator.tenant_id,
        display_name=f"{indicator.indicator_type}:{indicator.value}",
        attributes={
            "indicator_type": indicator.indicator_type,
            "value": indicator.value,
            "ttps": list(indicator.ttps),
            "actor_ids": list(indicator.actor_ids),
            "campaign_ids": list(indicator.campaign_ids),
            "expires_at": (
                None if indicator.expires_at is None else indicator.expires_at.isoformat()
            ),
        },
        labels={
            "module": "EA-0014",
            "kind": "threat_indicator",
            "indicator_type": indicator.indicator_type,
        },
        natural_keys=[
            NaturalKey(
                namespace=f"threat_indicator.{indicator.indicator_type}",
                value=indicator.value,
            )
        ],
        sources=list(indicator.sources),
        confidence=indicator.confidence,
        first_seen_at=indicator.first_seen_at,
        last_seen_at=indicator.last_seen_at,
        created_at=indicator.first_seen_at,
        updated_at=indicator.last_seen_at,
        created_by=by,
        updated_by=by,
    )


def object_to_indicator(obj: AQObject) -> ThreatIndicator:
    if obj.object_type != THREAT_INDICATOR_OBJECT_TYPE:
        raise ThreatConfigInvalid(f"not a threat indicator object: {obj.object_type!r}")
    attributes = obj.attributes
    return ThreatIndicator(
        id=obj.id,
        tenant_id=obj.tenant_id,
        indicator_type=_normalize_type(_attribute_string(attributes, "indicator_type")),
        value=_attribute_string(attributes, "value"),
        ttps=_attribute_string_list(attributes.get("ttps", []), field="ttps"),
        actor_ids=_attribute_string_list(attributes.get("actor_ids", []), field="actor_ids"),
        campaign_ids=_attribute_string_list(
            attributes.get("campaign_ids", []), field="campaign_ids"
        ),
        confidence=obj.confidence,
        first_seen_at=obj.first_seen_at,
        last_seen_at=obj.last_seen_at,
        sources=list(obj.sources),
        expires_at=_optional_datetime(attributes.get("expires_at")),
    )


def ensure_threat_object_types(object_store: object) -> None:
    registry = getattr(object_store, "registry", None)
    if isinstance(registry, ObjectTypeRegistry):
        register_threat_object_types(registry)
        return
    if registry is not None:
        register_threat_object_types(cast(_ObjectStoreRegistry, object_store).registry)


def _normalize_type(raw_type: str) -> IndicatorType:
    selected = raw_type.strip().lower()
    normalized = _TYPE_ALIASES.get(selected)
    if normalized is None:
        raise MalformedFeedRecord(f"unsupported indicator type: {raw_type!r}")
    return normalized


def _normalize_value(indicator_type: IndicatorType, raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        raise MalformedFeedRecord("indicator value must not be empty")
    if indicator_type == "domain":
        if any(char.isspace() for char in value):
            raise MalformedFeedRecord("domain indicator must not contain whitespace")
        return value.rstrip(".").lower()
    if indicator_type == "ip":
        try:
            return str(ipaddress.ip_address(value))
        except ValueError as exc:
            raise MalformedFeedRecord(f"invalid ip indicator: {value!r}") from exc
    if indicator_type == "hash":
        normalized = value.lower()
        if not all(char in "0123456789abcdef" for char in normalized):
            raise MalformedFeedRecord("hash indicator must be hexadecimal")
        return normalized
    if indicator_type == "url":
        if any(char.isspace() for char in value):
            raise MalformedFeedRecord("url indicator must not contain whitespace")
        return value
    raise MalformedFeedRecord(f"unsupported indicator type: {indicator_type!r}")


def _raw_string(raw: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value
    raise MalformedFeedRecord(f"feed record missing required field: {'/'.join(keys)}")


def _raw_string_list(value: Any, *, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise MalformedFeedRecord(f"{field} must be a list of strings")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise MalformedFeedRecord(f"{field} must contain only non-empty strings")
        out.append(item)
    if len(out) != len(set(out)):
        raise MalformedFeedRecord(f"{field} must not contain duplicates")
    return out


def _attribute_string(attributes: Mapping[str, Any], key: str) -> str:
    value = attributes.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ThreatConfigInvalid(f"indicator attribute {key!r} must be a non-empty string")
    return value


def _attribute_string_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ThreatConfigInvalid(f"indicator attribute {field!r} must be a list")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ThreatConfigInvalid(f"indicator attribute {field!r} must contain strings")
        out.append(item)
    return out


def _optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    raise MalformedFeedRecord("expires_at must be an RFC3339 timestamp when present")


def _raw_confidence(value: Any, source_id: str, config: FusionConfig) -> float:
    if value is None:
        return config.source_reliability.get(source_id, 0.5)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise MalformedFeedRecord("confidence must be numeric when present")
    confidence = float(value)
    if confidence < 0.0 or confidence > 1.0:
        raise MalformedFeedRecord("confidence must be in [0,1]")
    return confidence


def quarantine_time() -> datetime:
    return utc_now()
