"""EventBus protocol + shared pieces (EA-0003 §10)."""

from __future__ import annotations

import fnmatch
from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from aqelyn.events.models import Event

EventHandler = Callable[[Event], Awaitable[None]]
TenantResolver = Callable[[str], str | None]  # object_id -> tenant_id


@runtime_checkable
class Subscription(Protocol):
    id: str

    async def unsubscribe(self) -> None: ...


class EventBus(Protocol):
    async def publish(self, event: Event) -> None: ...
    async def publish_many(self, events: list[Event]) -> None: ...
    async def subscribe(
        self, pattern: str, handler: EventHandler, *, group: str | None = None
    ) -> Subscription: ...
    async def replay(
        self, *, since: object, pattern: str | None = None, handler: EventHandler
    ) -> int: ...


def pattern_matches(pattern: str, event_type: str) -> bool:
    return fnmatch.fnmatchcase(event_type, pattern)
