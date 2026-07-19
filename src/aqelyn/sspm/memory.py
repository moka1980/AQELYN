"""In-memory SaaSNormalizationStore implementation (EA-0029 Z2)."""

from __future__ import annotations

import copy
from collections.abc import Iterable

from aqelyn.conventions.errors import CrossTenantReference
from aqelyn.sspm.models import NormalizedSaaSObject, OverScopedStatus, SaaSIntegration
from aqelyn.sspm.store import (
    validate_object_id,
    validate_over_scoped_filter,
    validate_provider_filter,
    validate_query_cursor,
    validate_query_limit,
    validate_saas_integration,
    validate_saas_object,
    validate_tenant_scope,
)


class InMemorySaaSNormalizationStore:
    def __init__(self, *, mode: str = "local") -> None:
        self.mode = mode
        self._objects: dict[str, NormalizedSaaSObject] = {}
        self._integrations: dict[str, SaaSIntegration] = {}

    async def put(self, obj: NormalizedSaaSObject) -> NormalizedSaaSObject:
        stored = validate_saas_object(obj)
        self._guard_tenant(self._objects.get(stored.object_id), stored.tenant_id)
        self._objects[stored.object_id] = stored.model_copy(deep=True)
        return stored.model_copy(deep=True)

    async def put_integration(self, integration: SaaSIntegration) -> SaaSIntegration:
        stored = validate_saas_integration(integration)
        self._guard_tenant(self._integrations.get(stored.object_id), stored.tenant_id)
        self._integrations[stored.object_id] = stored.model_copy(deep=True)
        return stored.model_copy(deep=True)

    async def get(
        self,
        object_id: str,
        *,
        tenant_id: str | None,
    ) -> NormalizedSaaSObject | None:
        return self._get(self._objects, object_id, tenant_id=tenant_id)

    async def get_integration(
        self,
        object_id: str,
        *,
        tenant_id: str | None,
    ) -> SaaSIntegration | None:
        return self._get(self._integrations, object_id, tenant_id=tenant_id)

    async def query(
        self,
        *,
        tenant_id: str | None,
        provider: str | None = None,
        limit: int = 1000,
        cursor: str | None = None,
    ) -> tuple[list[NormalizedSaaSObject], str | None]:
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        selected_provider = validate_provider_filter(provider)
        return _page(
            (
                record
                for record in self._objects.values()
                if self._visible(record.tenant_id, selected_tenant)
                and (selected_provider is None or record.provider == selected_provider)
            ),
            limit=validate_query_limit(limit),
            cursor=validate_query_cursor(cursor),
        )

    async def query_integrations(
        self,
        *,
        tenant_id: str | None,
        over_scoped: OverScopedStatus | None = None,
        limit: int = 1000,
        cursor: str | None = None,
    ) -> tuple[list[SaaSIntegration], str | None]:
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        selected_status = validate_over_scoped_filter(over_scoped)
        return _page(
            (
                record
                for record in self._integrations.values()
                if self._visible(record.tenant_id, selected_tenant)
                and (selected_status is None or record.over_scoped == selected_status)
            ),
            limit=validate_query_limit(limit),
            cursor=validate_query_cursor(cursor),
        )

    def _get[RecordT: (NormalizedSaaSObject, SaaSIntegration)](
        self,
        records: dict[str, RecordT],
        object_id: str,
        *,
        tenant_id: str | None,
    ) -> RecordT | None:
        selected_id = validate_object_id(object_id)
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        record = records.get(selected_id)
        if record is None or not self._visible(record.tenant_id, selected_tenant):
            return None
        return copy.deepcopy(record)

    @staticmethod
    def _guard_tenant(
        existing: NormalizedSaaSObject | SaaSIntegration | None,
        tenant_id: str | None,
    ) -> None:
        if existing is not None and existing.tenant_id != tenant_id:
            raise CrossTenantReference("SaaS record tenant_id cannot change")

    def _visible(self, row_tenant_id: str | None, requested_tenant_id: str | None) -> bool:
        if self.mode == "local":
            return row_tenant_id is None and requested_tenant_id is None
        return row_tenant_id == requested_tenant_id


def _page[RecordT: (NormalizedSaaSObject, SaaSIntegration)](
    records: Iterable[RecordT],
    *,
    limit: int,
    cursor: str | None,
) -> tuple[list[RecordT], str | None]:
    selected = sorted(
        (record for record in records if cursor is None or record.object_id > cursor),
        key=lambda record: record.object_id,
    )
    page = selected[:limit]
    next_cursor = page[-1].object_id if len(selected) > limit else None
    return [copy.deepcopy(record) for record in page], next_cursor
