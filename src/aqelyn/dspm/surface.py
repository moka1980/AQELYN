"""Expose classified data stores through EA-0023's known-surface seam."""

from __future__ import annotations

from collections.abc import Sequence

from aqelyn.conventions.errors import StoreUnavailable
from aqelyn.dspm.store import DSPMStore
from aqelyn.exposure import AssetRef, ExposureBasis, KnownSurfaceRecord, KnownSurfaceSource

_PAGE_SIZE = 1_000


class DataStoreKnownSurfaceSource:
    def __init__(self, upstream: KnownSurfaceSource, store: DSPMStore) -> None:
        self.upstream = upstream
        self.store = store

    async def list_known_surface(
        self,
        *,
        tenant_id: str | None,
    ) -> Sequence[KnownSurfaceRecord]:
        upstream_rows = list(await self.upstream.list_known_surface(tenant_id=tenant_id))
        assets = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            page, next_cursor = await self.store.query_assets(
                tenant_id=tenant_id,
                limit=_PAGE_SIZE,
                cursor=cursor,
            )
            assets.extend(page)
            if next_cursor is None:
                break
            if not page:
                raise StoreUnavailable("DSPMStore returned an empty page with a cursor")
            if next_cursor == cursor or next_cursor in seen_cursors:
                raise StoreUnavailable("DSPMStore returned a repeated pagination cursor")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

        by_ref = {row.asset_ref.ref_id: row.model_copy(deep=True) for row in upstream_rows}
        for asset in assets:
            claim = asset.reachability_claim
            if claim is None:
                continue
            by_ref[asset.inventory_ref] = KnownSurfaceRecord(
                asset_ref=AssetRef(
                    kind="asset",
                    ref_id=asset.inventory_ref,
                    object_id=asset.object_id,
                    evidence_id=claim.evidence_id,
                ),
                classification=asset.max_known_sensitivity or "unknown",
                exposure_type="data_store_reachability",
                reachability=claim.reachability,
                basis=[
                    ExposureBasis(
                        kind="inventory",
                        ref=f"dspm:data_asset:{asset.id}",
                        as_of=asset.observed_at,
                        evidence_id=claim.evidence_id,
                    )
                ],
                observed_at=asset.observed_at,
                rationale=claim.reason,
            )
        return [by_ref[key] for key in sorted(by_ref)]
