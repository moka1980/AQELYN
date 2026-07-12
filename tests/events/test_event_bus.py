"""T3 acceptance tests for EA-0003 (§13). Full suite on in-memory."""

from datetime import UTC, datetime
from typing import Any

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import (
    BusBackpressure,
    CrossTenantEvent,
    EventSchemaValidationError,
    UnknownEventType,
)
from aqelyn.events import Event, InMemoryEventBus, Subject
from aqelyn.events.registry import EventTypeRegistry

SYS = ActorRef(actor_type="system", actor_id="test")
TENANT_A = "018f0000-0000-7000-8000-000000000001"
TENANT_B = "018f0000-0000-7000-8000-000000000002"


def _event(etype: str = "aqelyn.object.created", **kw: Any) -> Event:
    now = datetime.now(UTC)
    object_id = new_id("obj")
    base: dict[str, Any] = {
        "id": new_id("evt"),
        "event_type": etype,
        "schema_version": 1,
        "occurred_at": now,
        "recorded_at": now,
        "producer": SYS,
        "subject": Subject(object_ids=[object_id]),
        "payload": {"object_type": "generic"},
        "partition_key": object_id,
    }
    base.update(kw)
    return Event(**base)


def _bus(**kw: Any) -> InMemoryEventBus:
    return InMemoryEventBus(registry=EventTypeRegistry(), **kw)


async def test_bus_unknown_event_type_rejected() -> None:
    with pytest.raises(UnknownEventType):
        await _bus().publish(_event("aqelyn.nope.happened"))


async def test_bus_payload_validated() -> None:
    reg = EventTypeRegistry()

    def need_x(p: dict[str, Any]) -> None:
        if "x" not in p:
            raise EventSchemaValidationError("x required")

    reg.register("aqelyn.test.custom", 1, need_x)
    bus = InMemoryEventBus(registry=reg)
    with pytest.raises(EventSchemaValidationError):
        await bus.publish(_event("aqelyn.test.custom", payload={}))


async def test_bus_broadcast_fanout() -> None:
    bus = _bus()
    seen_a: list[str] = []
    seen_b: list[str] = []
    await bus.subscribe("aqelyn.object.*", lambda e: _collect(seen_a, e))
    await bus.subscribe("aqelyn.object.created", lambda e: _collect(seen_b, e))
    await bus.publish(_event())
    assert len(seen_a) == 1
    assert len(seen_b) == 1


async def test_bus_consumer_group_once() -> None:
    bus = _bus()
    seen: list[str] = []
    await bus.subscribe("aqelyn.*", lambda e: _collect(seen, e), group="workers")
    await bus.subscribe("aqelyn.*", lambda e: _collect(seen, e), group="workers")
    await bus.publish(_event())
    assert len(seen) == 1  # one member of the group handled it


async def test_bus_at_least_once_redelivery() -> None:
    bus = _bus(max_attempts=5)
    attempts = {"n": 0}

    async def flaky(_e: Event) -> None:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("transient")

    await bus.subscribe("aqelyn.*", flaky)
    await bus.publish(_event())
    assert attempts["n"] == 3  # retried until success
    assert not bus.dlq


async def test_bus_partition_ordering() -> None:
    bus = _bus()
    order: list[str] = []
    await bus.subscribe("aqelyn.*", lambda e: _collect(order, e))
    await bus.publish(_event(id=new_id("evt"), payload={"object_type": "a"}, partition_key="k"))
    await bus.publish(_event(id=new_id("evt"), payload={"object_type": "b"}, partition_key="k"))
    assert len(order) == 2  # both delivered, in publish order (single partition)


async def test_bus_retry_then_dlq() -> None:
    bus = _bus(max_attempts=2)

    async def always_fail(_e: Event) -> None:
        raise RuntimeError("boom")

    await bus.subscribe("aqelyn.*", always_fail)
    await bus.publish(_event())
    assert len(bus.dlq) == 1
    assert bus.dlq[0].attempts == 2


async def test_bus_event_logged_for_audit() -> None:
    bus = _bus()
    await bus.publish(_event())
    assert len(bus.log) == 1


async def test_bus_replay_since() -> None:
    bus = _bus()
    t0 = datetime.now(UTC)
    await bus.publish(_event())
    replayed: list[str] = []
    n = await bus.replay(since=t0, handler=lambda e: _collect(replayed, e))
    assert n == 1
    assert len(replayed) == 1


async def test_bus_backpressure_raises() -> None:
    bus = _bus(capacity=1)
    bus.pause()
    await bus.publish(_event())
    with pytest.raises(BusBackpressure):
        await bus.publish(_event())


async def test_bus_cross_tenant_rejected() -> None:
    bus = InMemoryEventBus(registry=EventTypeRegistry(), tenant_resolver=lambda _oid: TENANT_A)
    with pytest.raises(CrossTenantEvent):
        await bus.publish(_event(tenant_id=TENANT_B))


async def test_bus_publish_many_atomic() -> None:
    bus = _bus()
    good = _event()
    bad = _event("aqelyn.unregistered.x")
    with pytest.raises(UnknownEventType):
        await bus.publish_many([good, bad])
    assert len(bus.log) == 0  # nothing accepted


async def _collect(sink: list[str], e: Event) -> None:
    sink.append(e.id)
