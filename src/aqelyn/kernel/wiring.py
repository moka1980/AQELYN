"""Adapters that connect subsystems (EA-0001 §7): object changes -> events."""

from __future__ import annotations

from typing import Any

from aqelyn.conventions import new_id, utc_now
from aqelyn.conventions.actors import ActorRef
from aqelyn.events import Event, EventBus, Subject


class BusObjectEventSink:
    """Implements objects.ObjectEventSink by publishing EA-0003 events."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    async def object_event(
        self,
        event_type: str,
        *,
        object_id: str,
        tenant_id: str | None,
        payload: dict[str, Any],
        actor: ActorRef,
    ) -> None:
        now = utc_now()
        await self._bus.publish(
            Event(
                id=new_id("evt"),
                event_type=event_type,
                schema_version=1,
                tenant_id=tenant_id,
                occurred_at=now,
                recorded_at=now,
                producer=actor,
                subject=Subject(object_ids=[object_id]),
                payload=payload,
                partition_key=object_id,
            )
        )
