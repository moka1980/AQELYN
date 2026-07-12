"""Service contract + health/state types (EA-0001 §5-§6)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class HealthStatus(BaseModel):
    status: str  # healthy | degraded | unavailable
    ready: bool
    detail: str | None = None
    dependencies: dict[str, str] = Field(default_factory=dict)


class KernelState(BaseModel):
    phase: str  # created|starting|running|degraded|stopping|stopped
    services: dict[str, HealthStatus] = Field(default_factory=dict)


@runtime_checkable
class AQService(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def dependencies(self) -> Sequence[str]: ...
    @property
    def critical(self) -> bool: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def health(self) -> HealthStatus: ...
