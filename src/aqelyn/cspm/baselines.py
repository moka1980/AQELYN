"""EA-0012 adapter for cloud-scoped baseline assessment."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from aqelyn.assetconfig import AssetConfigAnalyzer, Baseline, BaselineStore
from aqelyn.conventions.errors import CloudConfigInvalid
from aqelyn.objects import ObjectQuery


class _SelectedBaselineStore:
    def __init__(self, store: BaselineStore, selected_ids: frozenset[str]) -> None:
        self.store = store
        self.selected_ids = selected_ids

    async def put(self, baseline: Baseline) -> Baseline:
        if baseline.id not in self.selected_ids:
            raise CloudConfigInvalid("cannot add an unselected cloud baseline")
        return await self.store.put(baseline)

    async def get(self, baseline_id: str) -> Baseline | None:
        if baseline_id not in self.selected_ids:
            return None
        return await self.store.get(baseline_id)

    async def list(
        self,
        *,
        tenant_id: str | None,
        asset_class: str | None = None,
    ) -> list[Baseline]:
        rows = await self.store.list(tenant_id=tenant_id, asset_class=asset_class)
        return [row for row in rows if row.id in self.selected_ids]


class AssetConfigCloudBaselineRouter:
    """Delegate configured cloud baseline assessment to EA-0012."""

    def __init__(self, engine: AssetConfigAnalyzer, baseline_store: BaselineStore) -> None:
        self.engine = engine
        self.baseline_store = baseline_store

    async def apply(
        self,
        baseline_ids: Sequence[str],
        *,
        tenant_id: str | None,
        scope: Mapping[str, object] | None = None,
    ) -> str:
        selected_ids = frozenset(baseline_ids)
        for baseline_id in sorted(selected_ids):
            baseline = await self.baseline_store.get(baseline_id)
            if baseline is None or not _tenant_visible(baseline.tenant_id, tenant_id):
                raise CloudConfigInvalid(f"cloud baseline unavailable: {baseline_id!r}")

        query_data = {} if scope is None else dict(scope)
        use_scope_limit = "limit" in query_data
        labels = query_data.get("labels")
        if labels is not None and not isinstance(labels, Mapping):
            raise CloudConfigInvalid("cloud baseline scope labels must be a mapping")
        selected_labels = {} if labels is None else dict(labels)
        if selected_labels.get("module") not in (None, "EA-0028"):
            raise CloudConfigInvalid("cloud baseline scope cannot select another module")
        selected_labels["module"] = "EA-0028"
        query_data["labels"] = selected_labels
        query = ObjectQuery.model_validate(query_data)

        delegated = AssetConfigAnalyzer(
            self.engine.object_store,
            [],
            baseline_store=_SelectedBaselineStore(self.baseline_store, selected_ids),
            snapshot_store=self.engine.snapshot_store,
            evidence_store=self.engine.evidence_store,
            actor=self.engine.actor,
            source_id=self.engine.source_id,
            config=self.engine.config,
        )
        snapshot = await delegated.assess(
            tenant_id=tenant_id,
            scope=query,
            use_scope_limit=use_scope_limit,
        )
        return snapshot.id


def _tenant_visible(baseline_tenant: str | None, tenant_id: str | None) -> bool:
    if tenant_id is None:
        return baseline_tenant is None
    return baseline_tenant in (None, tenant_id)
