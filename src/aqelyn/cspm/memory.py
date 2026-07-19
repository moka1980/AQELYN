"""In-memory CloudNormalizationStore implementation (EA-0028 Y2)."""

from __future__ import annotations

import copy

from aqelyn.conventions.errors import CrossTenantReference
from aqelyn.cspm.models import NormalizedCloudObject
from aqelyn.cspm.store import (
    validate_cloud_object,
    validate_cloud_object_id,
    validate_provider_filter,
    validate_query_cursor,
    validate_query_limit,
    validate_tenant_scope,
)


class InMemoryCloudNormalizationStore:
    def __init__(self, *, mode: str = "local") -> None:
        self.mode = mode
        self._records: dict[str, NormalizedCloudObject] = {}

    async def put(self, obj: NormalizedCloudObject) -> NormalizedCloudObject:
        stored = validate_cloud_object(obj)
        existing = self._records.get(stored.object_id)
        if existing is not None and existing.tenant_id != stored.tenant_id:
            raise CrossTenantReference("normalized cloud object tenant_id cannot change")
        self._records[stored.object_id] = stored.model_copy(deep=True)
        return copy.deepcopy(stored)

    async def get(
        self,
        object_id: str,
        *,
        tenant_id: str | None,
    ) -> NormalizedCloudObject | None:
        selected_id = validate_cloud_object_id(object_id)
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        record = self._records.get(selected_id)
        if record is None or not self._visible(record.tenant_id, selected_tenant):
            return None
        return copy.deepcopy(record)

    async def query(
        self,
        *,
        tenant_id: str | None,
        provider: str | None = None,
        limit: int = 1000,
        cursor: str | None = None,
    ) -> tuple[list[NormalizedCloudObject], str | None]:
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        selected_provider = validate_provider_filter(provider)
        selected_limit = validate_query_limit(limit)
        selected_cursor = validate_query_cursor(cursor)
        rows = [
            copy.deepcopy(record)
            for record in self._records.values()
            if self._visible(record.tenant_id, selected_tenant)
            and (selected_provider is None or record.provider == selected_provider)
            and (selected_cursor is None or record.object_id > selected_cursor)
        ]
        rows.sort(key=lambda record: record.object_id)
        page = rows[:selected_limit]
        next_cursor = page[-1].object_id if len(rows) > selected_limit else None
        return page, next_cursor

    def _visible(self, row_tenant_id: str | None, requested_tenant_id: str | None) -> bool:
        if self.mode == "local":
            return row_tenant_id is None and requested_tenant_id is None
        return row_tenant_id == requested_tenant_id
