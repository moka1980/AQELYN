"""Threat source reliability registry (EA-0014 T2)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from aqelyn.conventions import ActorRef, require_typed_id, utc_now
from aqelyn.conventions.errors import SchemaValidationError, ThreatConfigInvalid
from aqelyn.threat.models import ThreatSource

_DEFAULT_SOURCE_ID = "*"
_DEFAULT_ACTOR = ActorRef(actor_type="system", actor_id="threat_fusion_engine")


@runtime_checkable
class ThreatSourceRegistry(Protocol):
    async def get(self, source_id: str) -> ThreatSource: ...
    async def set(
        self,
        source_id: str,
        *,
        reliability: float,
        meta: Mapping[str, Any],
        by: ActorRef,
    ) -> ThreatSource: ...
    async def list(self) -> list[ThreatSource]: ...


class InMemoryThreatSourceRegistry:
    def __init__(
        self,
        *,
        default_reliability: float = 0.5,
        default_set_by: ActorRef = _DEFAULT_ACTOR,
        default_set_at: datetime | None = None,
    ) -> None:
        self._entries: dict[str, ThreatSource] = {
            _DEFAULT_SOURCE_ID: ThreatSource(
                source_id=_DEFAULT_SOURCE_ID,
                reliability=default_reliability,
                meta={"default": True, "reason": "unknown threat source"},
                set_by=default_set_by,
                set_at=default_set_at or utc_now(),
                version=1,
            )
        }

    async def get(self, source_id: str) -> ThreatSource:
        key = _source_key(source_id)
        if key in self._entries:
            return self._copy(self._entries[key])
        return self._copy(self._entries[_DEFAULT_SOURCE_ID])

    async def set(
        self,
        source_id: str,
        *,
        reliability: float,
        meta: Mapping[str, Any],
        by: ActorRef,
    ) -> ThreatSource:
        key = _source_key(source_id)
        previous = self._entries.get(key)
        stored = ThreatSource(
            source_id=key,
            reliability=reliability,
            meta=dict(meta),
            set_by=by,
            set_at=utc_now(),
            version=1 if previous is None else previous.version + 1,
        )
        self._entries[key] = stored
        return self._copy(stored)

    async def list(self) -> list[ThreatSource]:
        return [self._copy(self._entries[key]) for key in sorted(self._entries)]

    def _copy(self, source: ThreatSource) -> ThreatSource:
        return source.model_copy(deep=True)


def _source_key(source_id: str) -> str:
    if source_id == _DEFAULT_SOURCE_ID:
        return source_id
    try:
        return require_typed_id(source_id, "src", field="source_id")
    except SchemaValidationError as exc:
        raise ThreatConfigInvalid("source_id must be a valid src_ typed id") from exc
