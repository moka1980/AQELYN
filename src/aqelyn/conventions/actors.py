"""Canonical shared types used across all specs (CONVENTIONS §6)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

ActorType = Literal["system", "connector", "user", "agent"]


class ActorRef(BaseModel):
    """The responsible actor for a created/changed record or an event."""

    actor_type: ActorType
    actor_id: str
