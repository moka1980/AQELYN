"""ObjectStore interface + shared event-sink protocol (EA-0002 §13)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from aqelyn.conventions import ActorRef, require_typed_id
from aqelyn.objects.models import AQObject, AQRelationship, ObjectQuery


@runtime_checkable
class ObjectEventSink(Protocol):
    """Kernel-supplied adapter that turns object changes into EA-0003 events."""

    async def object_event(
        self,
        event_type: str,
        *,
        object_id: str,
        tenant_id: str | None,
        payload: dict[str, Any],
        actor: ActorRef,
    ) -> None: ...


class ObjectStore(Protocol):
    async def get(self, object_id: str, *, resolve_merged: bool = True) -> AQObject | None: ...
    async def upsert(self, obj: AQObject) -> AQObject: ...
    async def update(self, obj: AQObject, *, expected_version: int) -> AQObject: ...
    async def query(self, q: ObjectQuery) -> tuple[list[AQObject], str | None]: ...
    async def relate(self, rel: AQRelationship) -> AQRelationship: ...
    async def relationships(
        self, object_id: str, *, direction: str = "both", relation_type: str | None = None
    ) -> list[AQRelationship]: ...
    async def merge(self, survivor_id: str, duplicate_id: str, *, by: ActorRef) -> AQObject: ...
    async def set_state(
        self, object_id: str, state: str, *, by: ActorRef, expected_version: int
    ) -> AQObject: ...
    async def history(self, object_id: str) -> list[dict[str, Any]]: ...


VALID_TRANSITIONS: dict[str, set[str]] = {
    "active": {"archived", "merged", "deleted"},
    "archived": {"active", "merged", "deleted"},
    "merged": set(),
    "deleted": set(),
}


def merge_attributes(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Last-writer-wins per field (EA-0002 §20 resolved decision)."""
    out = dict(base)
    out.update(incoming)
    return out


def validate_object_id(value: str, *, field: str = "object_id") -> str:
    return require_typed_id(value, "obj", field=field)


def dedupe_sources(items: Sequence[Any]) -> list[Any]:
    seen: set[tuple[Any, ...]] = set()
    out: list[Any] = []
    for it in items:
        key = (it.source_id, it.evidence_id, it.method, it.observed_at.isoformat())
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out
