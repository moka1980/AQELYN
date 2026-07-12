"""Redis Streams EventBus (EA-0003 §11).

Durable transport backed by a Redis Stream (which is itself the append-only
event log). Delivery is drained via ``poll()`` so callers control timing; the
Kernel runs ``poll()`` on its loop. Broadcast subscribers each get a private
consumer group; named groups share one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

import redis.asyncio as aioredis

from aqelyn.conventions.errors import CrossTenantEvent
from aqelyn.events.bus import EventHandler, TenantResolver, pattern_matches
from aqelyn.events.models import Event
from aqelyn.events.registry import EventTypeRegistry

STREAM = "aqelyn:events"
DLQ = "aqelyn:dlq"


@dataclass
class _RedisSub:
    id: str
    pattern: str
    handler: EventHandler
    group: str
    consumer: str
    bus: RedisStreamsEventBus

    async def unsubscribe(self) -> None:
        self.bus._subs.pop(self.id, None)


class RedisStreamsEventBus:
    def __init__(
        self,
        client: aioredis.Redis,
        *,
        registry: EventTypeRegistry | None = None,
        max_attempts: int = 5,
        tenant_resolver: TenantResolver | None = None,
    ) -> None:
        self._r = client
        self.registry = registry or EventTypeRegistry()
        self.max_attempts = max_attempts
        self.tenant_resolver = tenant_resolver
        self._subs: dict[str, _RedisSub] = {}
        self._counter = 0

    @classmethod
    async def connect(cls, url: str, **kw: Any) -> RedisStreamsEventBus:
        client = aioredis.from_url(url, decode_responses=True)
        return cls(client, **kw)

    async def close(self) -> None:
        await self._r.aclose()

    def _check_tenant(self, event: Event) -> None:
        if self.tenant_resolver is None:
            return
        for oid in event.subject.object_ids:
            if self.tenant_resolver(oid) != event.tenant_id:
                raise CrossTenantEvent("event tenant mismatch with subject")

    async def publish(self, event: Event) -> None:
        self.registry.validate(event.event_type, event.payload)
        self._check_tenant(event)
        await self._r.xadd(STREAM, {"data": event.model_dump_json()})

    async def publish_many(self, events: list[Event]) -> None:
        for e in events:
            self.registry.validate(e.event_type, e.payload)
            self._check_tenant(e)
        async with self._r.pipeline(transaction=True) as pipe:
            for e in events:
                pipe.xadd(STREAM, {"data": e.model_dump_json()})
            await pipe.execute()

    async def subscribe(
        self, pattern: str, handler: EventHandler, *, group: str | None = None
    ) -> _RedisSub:
        self._counter += 1
        gname = group or f"broadcast_{self._counter}"
        try:
            await self._r.xgroup_create(STREAM, gname, id="0", mkstream=True)
        except aioredis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        sub = _RedisSub(
            id=f"sub_{self._counter}",
            pattern=pattern,
            handler=handler,
            group=gname,
            consumer=f"c_{self._counter}",
            bus=self,
        )
        self._subs[sub.id] = sub
        return sub

    async def poll(self, *, count: int = 100) -> int:
        """Drain available messages to all subscriptions. Returns delivered count."""
        delivered = 0
        for sub in list(self._subs.values()):
            resp = cast(
                Any,
                await self._r.xreadgroup(
                    sub.group, sub.consumer, {STREAM: ">"}, count=count, block=None
                ),
            )
            for _stream, entries in resp or []:
                for msg_id, fields in entries:
                    event = Event.model_validate_json(fields["data"])
                    if not pattern_matches(sub.pattern, event.event_type):
                        await self._r.xack(STREAM, sub.group, msg_id)
                        continue
                    ok = await self._deliver(sub, event)
                    if ok:
                        delivered += 1
                    await self._r.xack(STREAM, sub.group, msg_id)
        return delivered

    async def _deliver(self, sub: _RedisSub, event: Event) -> bool:
        attempt = 0
        while True:
            try:
                await sub.handler(event)
                return True
            except Exception as exc:  # retry then dead-letter
                attempt += 1
                if attempt >= self.max_attempts:
                    await self._r.xadd(
                        DLQ,
                        {"data": event.model_dump_json(), "error": str(exc), "attempts": attempt},
                    )
                    return False

    async def replay(
        self, *, since: object, pattern: str | None = None, handler: EventHandler
    ) -> int:
        since_dt = since if isinstance(since, datetime) else None
        count = 0
        entries = cast(Any, await self._r.xrange(STREAM))
        for _msg_id, fields in entries:
            event = Event.model_validate_json(fields["data"])
            if since_dt is not None and event.recorded_at < since_dt:
                continue
            if pattern is not None and not pattern_matches(pattern, event.event_type):
                continue
            await handler(event)
            count += 1
        return count
