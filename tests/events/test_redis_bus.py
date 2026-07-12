"""T3 Redis Streams integration test (EA-0003 §11). Gated on AQELYN_REDIS_URL."""

import os
from datetime import UTC, datetime

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.events import Event, Subject
from aqelyn.events.registry import EventTypeRegistry

REDIS_URL = os.getenv("AQELYN_REDIS_URL")
SYS = ActorRef(actor_type="system", actor_id="test")


def _event() -> Event:
    now = datetime.now(UTC)
    object_id = new_id("obj")
    return Event(
        id=new_id("evt"),
        event_type="aqelyn.object.created",
        schema_version=1,
        occurred_at=now,
        recorded_at=now,
        producer=SYS,
        subject=Subject(object_ids=[object_id]),
        payload={"object_type": "generic"},
        partition_key=object_id,
    )


@pytest.mark.skipif(not REDIS_URL, reason="AQELYN_REDIS_URL not set")
async def test_redis_bus_publish_consume_replay() -> None:
    from aqelyn.events.redis_bus import DLQ, STREAM, RedisStreamsEventBus

    assert REDIS_URL is not None
    bus = await RedisStreamsEventBus.connect(REDIS_URL, registry=EventTypeRegistry())
    # isolate this run
    await bus._r.delete(STREAM, DLQ)
    seen: list[str] = []

    async def handler(e: Event) -> None:
        seen.append(e.id)

    await bus.subscribe("aqelyn.object.*", handler, group="workers")
    ev = _event()
    await bus.publish(ev)
    delivered = await bus.poll()
    assert delivered == 1
    assert seen == [ev.id]

    replayed: list[str] = []

    async def collect(e: Event) -> None:
        replayed.append(e.id)

    n = await bus.replay(since=None, handler=collect)
    assert n == 1
    await bus.close()


@pytest.mark.skipif(not REDIS_URL, reason="AQELYN_REDIS_URL not set")
async def test_redis_bus_dlq_on_failure() -> None:
    from aqelyn.events.redis_bus import DLQ, STREAM, RedisStreamsEventBus

    assert REDIS_URL is not None
    bus = await RedisStreamsEventBus.connect(
        REDIS_URL, registry=EventTypeRegistry(), max_attempts=2
    )
    await bus._r.delete(STREAM, DLQ)

    async def boom(_e: Event) -> None:
        raise RuntimeError("fail")

    await bus.subscribe("aqelyn.*", boom, group="g")
    await bus.publish(_event())
    await bus.poll()
    dlq_len = await bus._r.xlen(DLQ)
    assert dlq_len == 1
    await bus.close()
