"""RunStore protocol for Workflow Engine persistence (EA-0008 W2)."""

from __future__ import annotations

from typing import Protocol

from aqelyn.conventions import require_typed_id
from aqelyn.conventions.errors import SchemaValidationError
from aqelyn.workflow.models import Run


class RunStore(Protocol):
    async def create(self, run: Run) -> Run: ...

    async def get(self, run_id: str, *, tenant_id: str | None = None) -> Run | None: ...

    async def update(self, run: Run, *, expected_version: int) -> Run: ...

    async def list(self, *, tenant_id: str | None = None, limit: int = 100) -> list[Run]: ...


def validate_run_id(value: str, *, field: str = "run_id", allow_empty: bool = False) -> str:
    return require_typed_id(value, "run", field=field, allow_empty=allow_empty)


def validate_positive(value: int, *, field: str) -> int:
    if isinstance(value, bool) or value < 1:
        raise SchemaValidationError(f"{field} must be >= 1")
    return value
