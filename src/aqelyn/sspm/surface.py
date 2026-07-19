"""Expose stored SaaS grants through EA-0023's known-surface contract."""

from __future__ import annotations

from collections.abc import Sequence

from aqelyn.exposure import AssetRef, ExposureBasis, KnownSurfaceRecord, KnownSurfaceSource
from aqelyn.sspm.store import SaaSNormalizationStore

_PAGE_SIZE = 1_000


class SaaSIntegrationKnownSurfaceSource:
    def __init__(
        self,
        upstream: KnownSurfaceSource,
        store: SaaSNormalizationStore,
    ) -> None:
        self.upstream = upstream
        self.store = store

    async def list_known_surface(
        self,
        *,
        tenant_id: str | None,
    ) -> Sequence[KnownSurfaceRecord]:
        upstream_rows = list(await self.upstream.list_known_surface(tenant_id=tenant_id))
        integrations = []
        cursor: str | None = None
        while True:
            page, cursor = await self.store.query_integrations(
                tenant_id=tenant_id,
                over_scoped="over_scoped",
                limit=_PAGE_SIZE,
                cursor=cursor,
            )
            integrations.extend(page)
            if cursor is None:
                break

        by_ref = {row.asset_ref.ref_id: row.model_copy(deep=True) for row in upstream_rows}
        for integration in integrations:
            by_ref[integration.object_id] = KnownSurfaceRecord(
                asset_ref=AssetRef(
                    kind=integration.grantor_kind,
                    ref_id=integration.object_id,
                    evidence_id=integration.evidence_id,
                ),
                classification="saas_integration",
                exposure_type="saas_integration_grant",
                reachability="external",
                basis=[
                    ExposureBasis(
                        kind="access",
                        ref=f"sspm:integration:{integration.object_id}",
                        as_of=integration.observed_at,
                        evidence_id=integration.evidence_id,
                    )
                ],
                observed_at=integration.observed_at,
                rationale=integration.reason,
            )
        return [by_ref[key] for key in sorted(by_ref)]
