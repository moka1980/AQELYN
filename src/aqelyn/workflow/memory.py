"""In-memory RunStore implementation (EA-0008 W2)."""

from __future__ import annotations

import copy

from aqelyn.conventions import new_id, utc_now
from aqelyn.conventions.errors import (
    CrossTenantReference,
    OptimisticConcurrencyConflict,
    RunNotFound,
    TenantScopeRequired,
)
from aqelyn.workflow.models import Run
from aqelyn.workflow.store import validate_positive, validate_run_id


class InMemoryRunStore:
    def __init__(self, *, mode: str = "local") -> None:
        self._runs: dict[str, Run] = {}
        self.mode = mode

    def _visible(self, run: Run, tenant_id: str | None) -> bool:
        if self.mode == "local" and run.tenant_id is not None:
            return False
        return tenant_id is None or run.tenant_id == tenant_id

    async def create(self, run: Run) -> Run:
        created = run.model_copy(deep=True)
        if not created.id:
            created.id = new_id("run")
        validate_run_id(created.id, field="id")
        if created.id in self._runs:
            raise OptimisticConcurrencyConflict(f"run already exists: {created.id}")
        now = utc_now()
        created.version = 1
        created.created_at = now
        created.updated_at = now
        self._runs[created.id] = created
        return copy.deepcopy(created)

    async def get(self, run_id: str, *, tenant_id: str | None = None) -> Run | None:
        validate_run_id(run_id)
        run = self._runs.get(run_id)
        if run is None or not self._visible(run, tenant_id):
            return None
        return copy.deepcopy(run)

    async def update(self, run: Run, *, expected_version: int) -> Run:
        validate_positive(expected_version, field="expected_version")
        validate_run_id(run.id, field="id")
        existing = self._runs.get(run.id)
        if existing is None:
            raise RunNotFound(run.id)
        if existing.tenant_id != run.tenant_id:
            raise CrossTenantReference("run tenant_id cannot change")
        if existing.version != expected_version:
            raise OptimisticConcurrencyConflict(
                f"expected v{expected_version}, found v{existing.version}"
            )
        updated = run.model_copy(deep=True)
        updated.version = existing.version + 1
        updated.created_at = existing.created_at
        updated.updated_at = max(utc_now(), existing.updated_at)
        self._runs[updated.id] = updated
        return copy.deepcopy(updated)

    async def list(self, *, tenant_id: str | None = None, limit: int = 100) -> list[Run]:
        validate_positive(limit, field="limit")
        if self.mode == "enterprise" and tenant_id is None:
            raise TenantScopeRequired("run list must be tenant-scoped in enterprise mode")
        rows = [copy.deepcopy(run) for run in self._runs.values() if self._visible(run, tenant_id)]
        rows.sort(key=lambda run: run.id)
        return rows[:limit]
