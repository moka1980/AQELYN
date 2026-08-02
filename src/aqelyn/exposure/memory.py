"""In-memory ExposureStore implementation (EA-0023 E2)."""

from __future__ import annotations

import copy
from datetime import datetime

from aqelyn.conventions.errors import OptimisticConcurrencyConflict
from aqelyn.exposure.models import ExposureRecord, Reachability
from aqelyn.exposure.store import (
    validate_exposure,
    validate_exposure_id,
    validate_flagged_filter,
    validate_query_limit,
    validate_reachability_filter,
    validate_read_cursor,
    validate_tenant,
)


class InMemoryExposureStore:
    def __init__(self, *, mode: str = "local") -> None:
        self.mode = mode
        self._records: dict[str, ExposureRecord] = {}

    async def put(self, exposure: ExposureRecord) -> ExposureRecord:
        stored = validate_exposure(exposure)
        if stored.id in self._records:
            raise OptimisticConcurrencyConflict(f"exposure already exists: {stored.id}")
        self._records[stored.id] = stored.model_copy(deep=True)
        return copy.deepcopy(stored)

    async def get(self, exposure_id: str, *, tenant_id: str | None = None) -> ExposureRecord | None:
        validate_exposure_id(exposure_id)
        selected_tenant = validate_tenant(tenant_id)
        record = self._records.get(exposure_id)
        if record is None or not self._visible(record.tenant_id, selected_tenant):
            return None
        return copy.deepcopy(record)

    async def query(
        self,
        *,
        tenant_id: str | None,
        reachability: Reachability | None = None,
        flagged: bool | None = None,
        limit: int = 100,
    ) -> list[ExposureRecord]:
        selected_tenant = validate_tenant(tenant_id)
        selected_reachability = validate_reachability_filter(reachability)
        selected_flagged = validate_flagged_filter(flagged)
        selected_limit = validate_query_limit(limit)
        rows = [
            copy.deepcopy(record)
            for record in self._records.values()
            if self._visible(record.tenant_id, selected_tenant)
            and (selected_reachability is None or record.reachability == selected_reachability)
            and (selected_flagged is None or record.flagged == selected_flagged)
        ]
        rows.sort(key=lambda record: (record.discovered_at, record.id))
        return rows[:selected_limit]

    async def query_for_read(
        self,
        *,
        tenant_id: str | None,
        after: tuple[datetime, str] | None = None,
        limit: int = 100,
    ) -> tuple[list[ExposureRecord], tuple[datetime, str] | None]:
        selected_tenant = validate_tenant(tenant_id)
        selected_after = validate_read_cursor(after)
        selected_limit = validate_query_limit(limit)
        rows = sorted(
            (
                record
                for record in self._records.values()
                if self._visible(record.tenant_id, selected_tenant)
                and (selected_after is None or (record.discovered_at, record.id) > selected_after)
            ),
            key=lambda record: (record.discovered_at, record.id),
        )
        page = rows[:selected_limit]
        next_key = (page[-1].discovered_at, page[-1].id) if len(rows) > selected_limit else None
        return [copy.deepcopy(record) for record in page], next_key

    def _visible(self, row_tenant_id: str | None, requested_tenant_id: str | None) -> bool:
        if self.mode == "local" and row_tenant_id is not None:
            return False
        return requested_tenant_id is None or row_tenant_id == requested_tenant_id
