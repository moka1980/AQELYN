"""Deliberately unsafe controls proving the GC-001/GC-002 assertions have teeth."""

from guarantees.controls.bad_kind import PermissiveSignal
from guarantees.controls.event_controls import (
    CYBER_EVENT,
    SMUGGLED_EVENT,
    register_cyber_event,
    register_smuggled_event,
)
from guarantees.controls.rogue_handler import RogueEngine, RogueHandler
from guarantees.controls.unguarded_scorer import unsafe_status_score

__all__ = [
    "CYBER_EVENT",
    "SMUGGLED_EVENT",
    "PermissiveSignal",
    "RogueEngine",
    "RogueHandler",
    "register_cyber_event",
    "register_smuggled_event",
    "unsafe_status_score",
]
