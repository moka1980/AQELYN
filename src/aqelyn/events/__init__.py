"""Event Envelope & Bus (T3). Implements EA-0003-event-envelope-and-bus.spec.md:
Event, EventBus (in-memory + Redis Streams), append-only event log."""

from aqelyn.events.bus import EventBus, EventHandler, Subscription
from aqelyn.events.memory import InMemoryEventBus
from aqelyn.events.models import Event, Subject
from aqelyn.events.registry import CORE_EVENTS, EventTypeRegistry

__all__ = [
    "CORE_EVENTS",
    "Event",
    "EventBus",
    "EventHandler",
    "EventTypeRegistry",
    "InMemoryEventBus",
    "Subject",
    "Subscription",
]
