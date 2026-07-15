"""Dataset catalog validation for the Security Data Lake (EA-0019 L1)."""

from __future__ import annotations

import copy

from aqelyn.conventions.errors import CrossTenantReference
from aqelyn.lake.models import Dataset


class DatasetCatalog:
    def __init__(self) -> None:
        self._datasets: dict[tuple[str | None, str], Dataset] = {}

    async def register(self, dataset: Dataset) -> Dataset:
        stored = Dataset.model_validate(dataset.model_dump(mode="json"))
        key = (stored.tenant_id, stored.name)
        existing = self._datasets.get(key)
        if existing is not None and existing.tenant_id != stored.tenant_id:
            raise CrossTenantReference("dataset tenant_id cannot change")
        self._datasets[key] = stored
        return copy.deepcopy(stored)

    async def get(self, name: str, *, tenant_id: str | None) -> Dataset | None:
        key = (tenant_id, name)
        dataset = self._datasets.get(key)
        if dataset is None and tenant_id is not None:
            dataset = self._datasets.get((None, name))
        return None if dataset is None else copy.deepcopy(dataset)

    async def list(self, *, tenant_id: str | None) -> list[Dataset]:
        rows = [
            copy.deepcopy(dataset)
            for (row_tenant, _), dataset in self._datasets.items()
            if row_tenant is None or row_tenant == tenant_id
        ]
        rows.sort(key=lambda dataset: (dataset.tenant_id or "", dataset.name))
        return rows
