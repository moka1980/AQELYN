"""Expose crypto assets through EA-0023's composable known-surface seam."""

from __future__ import annotations

from collections.abc import Sequence

from aqelyn.conventions.errors import StoreUnavailable
from aqelyn.exposure import AssetRef, ExposureBasis, KnownSurfaceRecord, KnownSurfaceSource
from aqelyn.secrets.ingest import asset_observed_at, crypto_asset_kind
from aqelyn.secrets.models import CertificateAsset, CryptoQuery
from aqelyn.secrets.store import CryptoStore

_PAGE_SIZE = 1_000


class CryptoKnownSurfaceSource:
    """Overlay value-free crypto metadata without discarding upstream reachability."""

    def __init__(self, upstream: KnownSurfaceSource, store: CryptoStore) -> None:
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
                CryptoQuery(
                    tenant_id=tenant_id,
                    cursor=cursor,
                    limit=_PAGE_SIZE,
                )
            )
            assets.extend(page)
            if next_cursor is None:
                break
            if not page:
                raise StoreUnavailable("CryptoStore returned an empty page with a cursor")
            if next_cursor == cursor or next_cursor in seen_cursors:
                raise StoreUnavailable("CryptoStore returned a repeated pagination cursor")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

        by_ref = {row.asset_ref.ref_id: row.model_copy(deep=True) for row in upstream_rows}
        for asset in assets:
            upstream = by_ref.get(asset.inventory_ref)
            observed_at = asset_observed_at(asset)
            crypto_basis = ExposureBasis(
                kind="inventory",
                ref=f"secrets:crypto_asset:{asset.id}",
                as_of=observed_at,
                evidence_id=asset.evidence_id,
            )
            if upstream is None:
                basis = [crypto_basis]
                reachability = None
                rationale = (
                    "EA-0032 reported a value-free crypto asset; reachability remains unknown "
                    "until an evidence-backed source establishes it."
                )
            else:
                basis = _merge_basis(upstream.basis, crypto_basis)
                reachability = upstream.reachability
                upstream_as_of = upstream.observed_at or min(item.as_of for item in upstream.basis)
                observed_at = min(observed_at, upstream_as_of)
                rationale = (
                    "EA-0032 overlaid credential metadata while preserving the upstream "
                    f"reachability claim: {upstream.rationale or 'no upstream rationale'}"
                )
            by_ref[asset.inventory_ref] = KnownSurfaceRecord(
                asset_ref=AssetRef(
                    kind="cert" if isinstance(asset, CertificateAsset) else "asset",
                    ref_id=asset.inventory_ref,
                    object_id=asset.object_id,
                    evidence_id=asset.evidence_id,
                ),
                classification=f"crypto_{crypto_asset_kind(asset)}",
                exposure_type="crypto_asset_surface",
                reachability=reachability,
                basis=basis,
                observed_at=observed_at,
                rationale=rationale,
            )
        return [by_ref[key] for key in sorted(by_ref)]


def _merge_basis(
    upstream: Sequence[ExposureBasis],
    crypto_basis: ExposureBasis,
) -> list[ExposureBasis]:
    selected = {
        (item.kind, item.ref, item.evidence_id): item.model_copy(deep=True) for item in upstream
    }
    selected[(crypto_basis.kind, crypto_basis.ref, crypto_basis.evidence_id)] = crypto_basis
    return [selected[key] for key in sorted(selected, key=repr)]
