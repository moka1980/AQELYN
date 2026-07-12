"""In-memory EventBus (EA-0003). Reference implementation + test double."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

from aqelyn.conventions.errors import (
    BusBackpressure,
    CrossTenantEvent,
)
from aqelyn.events.bus import EventHandler, TenantResolver, pattern_matches
from aqelyn.events.models import Event
from aqelyn.events.registry import EventTypeRegistry


@dataclass
class _Sub:
    id: str
    pattern: str
    handler: EventHandler
    group: str | None
    bus: InMemoryEventBus

    async def unsubscribe(self) -> None:
        self.bus._subs.pop(self.id, None)


@dataclass
class _DeadLetter:
    event: Event
    error: str
    attempts: int


@dataclass
class InMemoryEventBus:
    registry: EventTypeRegistry = field(default_factory=EventTypeRegistry)
    capacity: int = 10_000
    max_attempts: int = 5
    tenant_resolver: TenantResolver | None = None

    def __post_init__(self) -> None:
        self._subs: dict[str, _Sub] = {}
        self._log: list[Event] = []
        self._dlq: list[_DeadLetter] = []
        self._group_rr: dict[tuple[str, str], int] = {}
        self._paused = False
        self._counter = 0

    def pause(self) -> None:
        self._paused = True

    async def resume(self) -> None:
        self._paused = False

    @property
    def dlq(self) -> list[_DeadLetter]:
        return list(self._dlq)

    @property
    def log(self) -> list[Event]:
        return list(self._log)

    def _check_tenant(self, event: Event) -> None:
        if self.tenant_resolver is None:
            return
        for oid in event.subject.object_ids:
            t = self.tenant_resolver(oid)
            if t != event.tenant_id:
                raise CrossTenantEvent(f"event tenant {event.tenant_id} != subject tenant {t}")

    async def _accept(self, event: Event) -> None:
        self.registry.validate(event.event_type, event.payload)
        self._check_tenant(event)
        if len(self._log) >= self.capacity and self._paused:
            raise BusBackpressure("event buffer full")
        self._log.append(event)  # FR-7: append-only audit log

    async def _dispatch(self, event: Event) -> None:
        # Broadcast subscribers (one delivery each) + one member per consumer group.
        groups: dict[str, list[_Sub]] = {}
        broadcast: list[_Sub] = []
        for sub in list(self._subs.values()):
            if not pattern_matches(sub.pattern, event.event_type):
                continue
            if sub.group is None:
                broadcast.append(sub)
            else:
                groups.setdefault(sub.group, []).append(sub)
        targets = list(broadcast)
        for gname, members in groups.items():
            idx = self._group_rr.get((gname, event.partition_key), 0) % len(members)
            self._group_rr[(gname, event.partition_key)] = idx + 1
            targets.append(members[idx])
        for sub in targets:
            await self._deliver(sub, event)

    async def _deliver(self, sub: _Sub, event: Event) -> None:
        attempt = 0
        while True:
            try:
                await sub.handler(event)
                return
            except Exception as exc:  # retry then dead-letter (FR-6)
                attempt += 1
                if attempt >= self.max_attempts:
                    self._dlq.append(_DeadLetter(event=event, error=str(exc), attempts=attempt))
                    return
                await asyncio.sleep(0)  # yield; backoff is time-based in production

    async def publish(self, event: Event) -> None:
        await self._accept(event)
        if not self._paused:
            await self._dispatch(event)

    async def publish_many(self, events: list[Event]) -> None:
        for e in events:  # validate all first -> atomic accept (FR-12)
            self.registry.validate(e.event_type, e.payload)
            self._check_tenant(e)
        for e in events:
            await self.publish(e)

    async def subscribe(
        self, pattern: str, handler: EventHandler, *, group: str | None = None
    ) -> _Sub:
        self._counter += 1
        sub = _Sub(
            id=f"sub_{self._counter}", pattern=pattern, handler=handler, group=group, bus=self
        )
        self._subs[sub.id] = sub
        return sub

    async def replay(
        self, *, since: object, pattern: str | None = None, handler: EventHandler
    ) -> int:
        count = 0
        since_dt = since if isinstance(since, datetime) else None
        for event in self._log:
            if since_dt is not None and event.recorded_at < since_dt:
                continue
            if pattern is not None and not pattern_matches(pattern, event.event_type):
                continue
            await handler(event)
            count += 1
        return count
