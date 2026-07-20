"""In-memory append-only DSPM store (EA-0031 P2)."""

from __future__ import annotations

import copy

from aqelyn.conventions.errors import CrossTenantReference, OptimisticConcurrencyConflict
from aqelyn.dspm.models import (
    AssetClassificationStatus,
    Classification,
    DataAsset,
    DataExposure,
    DataPostureAssessment,
)
from aqelyn.dspm.store import (
    validate_assessment,
    validate_asset,
    validate_asset_id,
    validate_classification_filter,
    validate_exposure,
    validate_query_cursor,
    validate_query_limit,
    validate_status_filter,
    validate_store_id,
    validate_tenant_scope,
)


class InMemoryDSPMStore:
    def __init__(self, *, mode: str = "local") -> None:
        self.mode = mode
        self._assets: dict[str, list[DataAsset]] = {}
        self._store_ids: dict[tuple[str | None, str], str] = {}
        self._exposures: dict[str, DataExposure] = {}
        self._assessments: dict[str, DataPostureAssessment] = {}

    async def put_asset(self, asset: DataAsset) -> DataAsset:
        stored = validate_asset(asset)
        history = self._assets.get(stored.id)
        identity_key = (stored.tenant_id, stored.store_id)
        if history:
            latest = history[-1]
            if latest.tenant_id != stored.tenant_id:
                raise CrossTenantReference("data asset tenant_id cannot change")
            if stored.version != latest.version + 1:
                raise OptimisticConcurrencyConflict(
                    f"data asset {stored.id} expected version {latest.version + 1}"
                )
            if (
                stored.store_id != latest.store_id
                or stored.object_id != latest.object_id
                or stored.inventory_ref != latest.inventory_ref
            ):
                raise OptimisticConcurrencyConflict("data asset identity cannot change")
        elif stored.version != 1:
            raise OptimisticConcurrencyConflict("new data asset must start at version 1")
        mapped = self._store_ids.get(identity_key)
        if mapped is not None and mapped != stored.id:
            raise OptimisticConcurrencyConflict(
                f"store_id already belongs to another data asset: {stored.store_id}"
            )
        self._store_ids[identity_key] = stored.id
        selected_history = self._assets.setdefault(stored.id, [])
        selected_history.append(stored.model_copy(deep=True))
        return copy.deepcopy(stored)

    async def get_asset(
        self,
        asset_id: str,
        *,
        tenant_id: str | None,
    ) -> DataAsset | None:
        selected_id = validate_asset_id(asset_id)
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        history = self._assets.get(selected_id)
        if not history or not self._visible(history[-1].tenant_id, selected_tenant):
            return None
        return copy.deepcopy(history[-1])

    async def get_asset_by_store_id(
        self,
        store_id: str,
        *,
        tenant_id: str | None,
    ) -> DataAsset | None:
        selected_store = validate_store_id(store_id)
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        asset_id = self._store_ids.get((selected_tenant, selected_store))
        if asset_id is None:
            return None
        return copy.deepcopy(self._assets[asset_id][-1])

    async def put_exposure(self, exposure: DataExposure) -> DataExposure:
        stored = validate_exposure(exposure)
        existing = self._exposures.get(stored.id)
        if existing is not None:
            if existing.tenant_id != stored.tenant_id:
                raise CrossTenantReference("data exposure tenant_id cannot change")
            raise OptimisticConcurrencyConflict(f"data exposure already exists: {stored.id}")
        self._exposures[stored.id] = stored.model_copy(deep=True)
        return copy.deepcopy(stored)

    async def put_assessment(
        self,
        assessment: DataPostureAssessment,
    ) -> DataPostureAssessment:
        stored = validate_assessment(assessment)
        existing = self._assessments.get(stored.id)
        if existing is not None:
            if existing.tenant_id != stored.tenant_id:
                raise CrossTenantReference("data assessment tenant_id cannot change")
            raise OptimisticConcurrencyConflict(f"data assessment already exists: {stored.id}")
        self._assessments[stored.id] = stored.model_copy(deep=True)
        return copy.deepcopy(stored)

    async def query_assets(
        self,
        *,
        tenant_id: str | None,
        classification: Classification | None = None,
        status: AssetClassificationStatus | None = None,
        flagged: bool | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[list[DataAsset], str | None]:
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        selected_classification = validate_classification_filter(classification)
        selected_status = validate_status_filter(status)
        selected_limit = validate_query_limit(limit)
        selected_cursor = validate_query_cursor(cursor)
        rows = [
            history[-1]
            for history in self._assets.values()
            if self._visible(history[-1].tenant_id, selected_tenant)
            and (
                selected_classification is None
                or history[-1].max_known_sensitivity == selected_classification
            )
            and (selected_status is None or history[-1].classification_status == selected_status)
            and (flagged is None or history[-1].flagged is flagged)
            and (selected_cursor is None or history[-1].id > selected_cursor)
        ]
        rows.sort(key=lambda item: item.id)
        page = rows[:selected_limit]
        next_cursor = page[-1].id if len(rows) > selected_limit else None
        return [copy.deepcopy(item) for item in page], next_cursor

    def _visible(self, row_tenant_id: str | None, requested_tenant_id: str | None) -> bool:
        if self.mode == "local":
            return row_tenant_id is None and requested_tenant_id is None
        return row_tenant_id == requested_tenant_id
