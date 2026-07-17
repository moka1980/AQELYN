"""In-memory AssetStore implementation (EA-0025 N2)."""

from __future__ import annotations

import copy
from typing import Any

from aqelyn.conventions import utc_now
from aqelyn.conventions.errors import CrossTenantReference
from aqelyn.inventory.models import AssetRecord, LifecycleState
from aqelyn.inventory.store import (
    validate_asset,
    validate_asset_id,
    validate_lifecycle_filter,
    validate_query_limit,
    validate_tenant,
)


class InMemoryAssetStore:
    def __init__(self, *, mode: str = "local") -> None:
        self.mode = mode
        self._records: dict[str, AssetRecord] = {}
        self._history: dict[str, list[dict[str, Any]]] = {}

    async def put(self, asset: AssetRecord) -> AssetRecord:
        stored = validate_asset(asset)
        existing = self._records.get(stored.id)
        if existing is not None and existing.tenant_id != stored.tenant_id:
            raise CrossTenantReference("asset tenant_id cannot change")
        self._records[stored.id] = stored.model_copy(deep=True)
        self._append_history(stored)
        return copy.deepcopy(stored)

    async def get(self, asset_id: str, *, tenant_id: str | None = None) -> AssetRecord | None:
        validate_asset_id(asset_id)
        selected_tenant = validate_tenant(tenant_id)
        record = self._records.get(asset_id)
        if record is None or not self._visible(record.tenant_id, selected_tenant):
            return None
        return copy.deepcopy(record)

    async def query(
        self,
        *,
        tenant_id: str | None,
        lifecycle_state: LifecycleState | None = None,
        limit: int = 100,
    ) -> list[AssetRecord]:
        selected_tenant = validate_tenant(tenant_id)
        selected_lifecycle = validate_lifecycle_filter(lifecycle_state)
        selected_limit = validate_query_limit(limit)
        rows = [
            copy.deepcopy(record)
            for record in self._records.values()
            if self._visible(record.tenant_id, selected_tenant)
            and (selected_lifecycle is None or record.lifecycle_state == selected_lifecycle)
        ]
        rows.sort(key=lambda record: (record.first_seen_at, record.id))
        return rows[:selected_limit]

    async def history(self, asset_id: str) -> list[dict[str, Any]]:
        validate_asset_id(asset_id)
        return copy.deepcopy(self._history.get(asset_id, []))

    def _append_history(self, asset: AssetRecord) -> None:
        entries = self._history.setdefault(asset.id, [])
        entries.append(
            {
                "seq": len(entries) + 1,
                "asset_id": asset.id,
                "snapshot": asset.model_dump(mode="json"),
                "changed_at": utc_now(),
            }
        )

    def _visible(self, row_tenant_id: str | None, requested_tenant_id: str | None) -> bool:
        if self.mode == "local" and row_tenant_id is not None:
            return False
        return requested_tenant_id is None or row_tenant_id == requested_tenant_id
