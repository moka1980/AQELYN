"""N6 acceptance tests for inventory-backed exposure and vulnerability seams."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import CoverageUnavailable
from aqelyn.exposure import AssetRef
from aqelyn.inventory import (
    DiscoverySource,
    InventoryKnownSurfaceSource,
    InventoryReport,
    InventoryVulnerabilityCoverageProvider,
)
from aqelyn.kernel import AQELYNConfig, create_inmemory_runtime, create_runtime
from aqelyn.sspm import SaaSIntegrationKnownSurfaceSource
from aqelyn.vuln import CarriedScore, VulnBasis, VulnerabilityRecord

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 17, 19, 0, tzinfo=UTC)


class _DegradedInventory:
    async def inventory(self, *, tenant_id: str | None) -> InventoryReport:
        return InventoryReport(
            assets=[new_id("ast")],
            total=1,
            as_of=NOW,
            source_freshness={"src:down": NOW},
            degraded=True,
        )


@pytest.mark.parametrize("backend", ["memory", "postgres"])
async def test_inv_seams_wired(backend: str) -> None:
    if backend == "postgres" and not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    tenant_id = None
    if backend == "memory":
        runtime = create_inmemory_runtime(AQELYNConfig(backend="memory"))
    else:
        assert PG_URL is not None
        runtime = await create_runtime(AQELYNConfig(backend="postgres", database_url=PG_URL))
        inventory_store = cast(Any, runtime.inventory_store)
        vuln_store = cast(Any, runtime.vuln_store)
        async with inventory_store._pool.acquire() as conn:
            await conn.execute("TRUNCATE aq_inventory_asset_history, aq_inventory_asset")
        async with vuln_store._pool.acquire() as conn:
            await conn.execute("TRUNCATE aq_vuln_history, aq_vuln_record")

    assert isinstance(runtime.exposure_engine.source, SaaSIntegrationKnownSurfaceSource)
    assert isinstance(runtime.exposure_engine.source.upstream, InventoryKnownSurfaceSource)
    assert runtime.exposure_engine.source.upstream.inventory is runtime.inventory_engine
    assert isinstance(
        runtime.vuln_engine.coverage_provider,
        InventoryVulnerabilityCoverageProvider,
    )
    assert runtime.vuln_engine.coverage_provider.inventory is runtime.inventory_engine
    assert runtime.vuln_engine.coverage_provider.vulnerability_store is runtime.vuln_store

    await runtime.kernel.start()
    try:
        source = DiscoverySource(
            source_id="src:cmdb",
            reliability=0.91,
            health="ok",
            as_of=NOW,
        )
        first_asset_id = new_id("ast")
        second_asset_id = new_id("ast")
        await runtime.inventory_engine.ingest(
            reports=[
                {
                    "id": first_asset_id,
                    "asset_type": "server",
                    "classification": "web",
                    "ref": "cmdb:web-1",
                    "evidence_id": new_id("evd"),
                },
                {
                    "id": second_asset_id,
                    "asset_type": "server",
                    "classification": "database",
                    "ref": "cmdb:db-1",
                    "evidence_id": new_id("evd"),
                },
            ],
            source=source,
            tenant_id=tenant_id,
        )
        await runtime.vuln_engine.ingest(
            records=[_vulnerability(first_asset_id, tenant_id=tenant_id)],
            tenant_id=tenant_id,
        )

        surface = await runtime.exposure_engine.derive_surface(tenant_id=tenant_id)
        coverage = await runtime.vuln_engine.coverage_provider.coverage(tenant_id=tenant_id)

        inventory_surface = {
            asset.asset_ref.ref_id: asset
            for asset in surface
            if asset.asset_ref.ref_id in {first_asset_id, second_asset_id}
        }
        assert set(inventory_surface) == {first_asset_id, second_asset_id}
        assert {asset.basis[0].ref for asset in inventory_surface.values()} == {
            f"inventory:{first_asset_id}",
            f"inventory:{second_asset_id}",
        }
        assert coverage.scanned == [first_asset_id]
        assert coverage.unscanned == [second_asset_id]
        assert coverage.computed_at == NOW

        degraded_provider = InventoryVulnerabilityCoverageProvider(
            _DegradedInventory(),
            runtime.vuln_store,
        )
        with pytest.raises(CoverageUnavailable):
            await degraded_provider.coverage(tenant_id=tenant_id)
    finally:
        await runtime.kernel.stop()


def _vulnerability(asset_id: str, *, tenant_id: str | None) -> VulnerabilityRecord:
    return VulnerabilityRecord(
        tenant_id=tenant_id,
        cve_id="CVE-2026-2525",
        scanner="nessus",
        asset_ref=AssetRef(kind="asset", ref_id=asset_id, evidence_id=new_id("evd")),
        severity="high",
        cvss=CarriedScore(
            source="nvd:cve-2026-2525",
            value=9.1,
            vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
            as_of=NOW,
        ),
        confidence=0.8,
        basis=[
            VulnBasis(
                kind="scanner",
                ref="scanner:nessus:run-25",
                as_of=NOW,
                evidence_id=new_id("evd"),
            )
        ],
        discovered_at=NOW,
    )
