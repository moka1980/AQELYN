"""Deliberately forbidden event registrations proving GC-002 has teeth (rule 19).

Each control *performs* the forbidden act — registering a rogue event type into a
real ``EventTypeRegistry`` — rather than asserting about it. If a checker is
neutered, its control stops failing; that is how the suite is verified by mutation.
"""

from __future__ import annotations

from aqelyn.events.registry import EventTypeRegistry

# New prefix for an existing capability — the exact IS-037 hazard. Caught by AC-2
# (no `cyber` package owns it) and also by AC-1 (absent from the golden set).
CYBER_EVENT = "aqelyn.cyber.exposure_detected"

# The subtler variant: a NEW event smuggled under an owner that legitimately
# exists. AC-2 passes it (`exposure` is owned); only AC-1's frozen closure catches it.
SMUGGLED_EVENT = "aqelyn.exposure.cyber_discovered"


def register_cyber_event(registry: EventTypeRegistry) -> str:
    """Mint a parallel `aqelyn.cyber.*` namespace on a live registry."""
    registry.register(CYBER_EVENT, 1, None)
    return CYBER_EVENT


def register_smuggled_event(registry: EventTypeRegistry) -> str:
    """Add a new event under the existing `aqelyn.exposure.*` prefix."""
    registry.register(SMUGGLED_EVENT, 1, None)
    return SMUGGLED_EVENT
