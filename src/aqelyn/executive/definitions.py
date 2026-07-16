"""Versioned KPI definition registry for EA-0022 X1."""

from __future__ import annotations

import copy
from typing import Protocol

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.conventions.errors import ExecutiveConfigInvalid, KPIDefinitionNotFound
from aqelyn.executive.models import KPIDefinition, validate_limit, validate_version


class KPIDefinitionStore(Protocol):
    async def propose(self, definition: KPIDefinition, *, by: ActorRef) -> KPIDefinition: ...

    async def promote(
        self,
        key: str,
        version: int,
        *,
        by: ActorRef,
        reason: str,
    ) -> KPIDefinition: ...

    async def active(self, key: str) -> KPIDefinition: ...


class InMemoryKPIDefinitionStore:
    def __init__(self) -> None:
        self._definitions: dict[tuple[str, int], KPIDefinition] = {}

    async def propose(self, definition: KPIDefinition, *, by: ActorRef) -> KPIDefinition:
        _ = by
        stored = KPIDefinition.model_validate(definition.model_dump(mode="json"))
        version = self._next_version(stored.key)
        proposed = stored.model_copy(
            update={
                "id": new_id("kdf"),
                "version": version,
                "active": False,
                "promoted_by": None,
                "promoted_at": None,
            },
            deep=True,
        )
        self._definitions[(proposed.key, proposed.version)] = proposed
        return copy.deepcopy(proposed)

    async def promote(
        self,
        key: str,
        version: int,
        *,
        by: ActorRef,
        reason: str,
    ) -> KPIDefinition:
        selected_key = _nonempty(key, field="key")
        selected_version = validate_version(version)
        _nonempty(reason, field="promotion reason")
        existing = self._definitions.get((selected_key, selected_version))
        if existing is None:
            raise KPIDefinitionNotFound(
                f"kpi definition not found: {selected_key} v{selected_version}"
            )
        promoted = existing.model_copy(
            update={
                "active": True,
                "promoted_by": by,
                "promoted_at": utc_now(),
            },
            deep=True,
        )
        self._definitions[(selected_key, selected_version)] = KPIDefinition.model_validate(
            promoted.model_dump(mode="json")
        )
        return copy.deepcopy(self._definitions[(selected_key, selected_version)])

    async def active(self, key: str) -> KPIDefinition:
        selected_key = _nonempty(key, field="key")
        candidates = [
            definition
            for (stored_key, _), definition in self._definitions.items()
            if stored_key == selected_key and definition.active
        ]
        if not candidates:
            raise KPIDefinitionNotFound(f"active kpi definition not found: {selected_key}")
        selected = max(candidates, key=lambda definition: definition.version)
        return copy.deepcopy(selected)

    async def get(self, key: str, version: int) -> KPIDefinition | None:
        selected_key = _nonempty(key, field="key")
        selected_version = validate_version(version)
        existing = self._definitions.get((selected_key, selected_version))
        return None if existing is None else copy.deepcopy(existing)

    async def versions(self, key: str, *, limit: int = 100) -> list[KPIDefinition]:
        selected_key = _nonempty(key, field="key")
        selected_limit = validate_limit(limit)
        rows = [
            copy.deepcopy(definition)
            for (stored_key, _), definition in self._definitions.items()
            if stored_key == selected_key
        ]
        rows.sort(key=lambda definition: definition.version)
        return rows[:selected_limit]

    def _next_version(self, key: str) -> int:
        versions = [version for stored_key, version in self._definitions if stored_key == key]
        return max(versions, default=0) + 1


def _nonempty(value: str, *, field: str) -> str:
    if not value.strip():
        raise ExecutiveConfigInvalid(f"{field} must not be empty")
    return value
