"""Source reliability registry (EA-0006 TR1)."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from aqelyn.conventions import ActorRef, require_typed_id, utc_now
from aqelyn.conventions.errors import SchemaValidationError, TrustConfigInvalid
from aqelyn.trust.models import SourceReliability

_DEFAULT_KEY = "*"
_DEFAULT_ACTOR = ActorRef(actor_type="system", actor_id="trust")


@runtime_checkable
class SourceReliabilityRegistry(Protocol):
    async def get(
        self, *, source_id: str | None = None, method: str | None = None
    ) -> SourceReliability: ...
    async def set(self, entry: SourceReliability) -> SourceReliability: ...
    async def list(self) -> list[SourceReliability]: ...


class InMemorySourceReliabilityRegistry:
    def __init__(
        self,
        *,
        default: SourceReliability | None = None,
        default_reliability: float = 0.5,
        default_set_by: ActorRef = _DEFAULT_ACTOR,
        default_set_at: datetime | None = None,
    ) -> None:
        default_entry = default or SourceReliability(
            key=_DEFAULT_KEY,
            weight=default_reliability,
            rationale="default reliability for unknown source or method",
            set_by=default_set_by,
            set_at=default_set_at or utc_now(),
            version=1,
        )
        if default_entry.key != _DEFAULT_KEY:
            raise TrustConfigInvalid("default reliability entry must use key '*'")
        self._entries: dict[str, SourceReliability] = {
            default_entry.key: default_entry.model_copy(deep=True)
        }

    async def get(
        self, *, source_id: str | None = None, method: str | None = None
    ) -> SourceReliability:
        if source_id is not None:
            source_key = _source_key(source_id)
            if source_key in self._entries:
                return self._copy(self._entries[source_key])
        if method is not None:
            method_key = _method_key(method)
            if method_key in self._entries:
                return self._copy(self._entries[method_key])
        return self._copy(self._entries[_DEFAULT_KEY])

    async def set(self, entry: SourceReliability) -> SourceReliability:
        self._entries[entry.key] = entry.model_copy(deep=True)
        return self._copy(self._entries[entry.key])

    async def list(self) -> list[SourceReliability]:
        return [self._copy(self._entries[key]) for key in sorted(self._entries)]

    def _copy(self, entry: SourceReliability) -> SourceReliability:
        return entry.model_copy(deep=True)


def _source_key(source_id: str) -> str:
    try:
        return require_typed_id(source_id, "src", field="source_id")
    except SchemaValidationError as exc:
        raise TrustConfigInvalid("source_id must be a valid src_ typed id") from exc


def _method_key(method: str) -> str:
    if not method.strip():
        raise TrustConfigInvalid("method must not be empty")
    return f"method:{method}"
