"""Event-type registry (EA-0003 §7). Each spec registers the types it owns."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aqelyn.conventions.errors import EventSchemaValidationError, UnknownEventType

PayloadValidator = Callable[[dict[str, Any]], None]

# Foundation core events (EA-0003 §7). Evidence/Finding register their own.
CORE_EVENTS: dict[str, int] = {
    "aqelyn.kernel.runtime_started": 1,
    "aqelyn.kernel.runtime_stopped": 1,
    "aqelyn.object.created": 1,
    "aqelyn.object.updated": 1,
    "aqelyn.object.state_changed": 1,
    "aqelyn.object.merged": 1,
    "aqelyn.relationship.created": 1,
}


class EventTypeRegistry:
    def __init__(self, *, with_core: bool = True) -> None:
        self._types: dict[str, tuple[int, PayloadValidator | None]] = {}
        if with_core:
            for name, ver in CORE_EVENTS.items():
                self.register(name, ver, None)

    def register(
        self, event_type: str, schema_version: int, validator: PayloadValidator | None = None
    ) -> None:
        self._types[event_type] = (schema_version, validator)

    def is_registered(self, event_type: str) -> bool:
        return event_type in self._types

    def validate(self, event_type: str, payload: dict[str, Any]) -> None:
        if event_type not in self._types:
            raise UnknownEventType(f"event_type not registered: {event_type!r}")
        _, validator = self._types[event_type]
        if validator is not None:
            try:
                validator(payload)
            except EventSchemaValidationError:
                raise
            except Exception as exc:  # normalize to typed error
                raise EventSchemaValidationError(str(exc)) from exc
