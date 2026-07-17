"""N3 acceptance tests for inventory lifecycle and fail-closed inventory()."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import (
    DecommissionRequiresEvidence,
    InventoryUnavailable,
    SourceHealthUnknown,
    StoreUnavailable,
)
from aqelyn.inventory import (
    AssetRecord,
    AssetStore,
    DiscoverySource,
    InMemoryAssetStore,
    InventoryIntelligenceEngine,
    PostgresAssetStore,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 17, 16, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000250201"
ACTOR = ActorRef(actor_type="user", actor_id="asset-owner@example.com")


class _Closable(Protocol):
    async def close(self) -> None: ...


class _UnavailableStore:
    async def put(self, asset: AssetRecord) -> AssetRecord:
        raise StoreUnavailable("store down")

    async def get(self, asset_id: str, *, tenant_id: str | None = None) -> AssetRecord | None:
        raise StoreUnavailable("store down")

    async def query(
        self,
        *,
        tenant_id: str | None,
        lifecycle_state: str | None = None,
        limit: int = 100,
    ) -> list[AssetRecord]:
        raise StoreUnavailable("store down")

    async def history(self, asset_id: str) -> list[dict[str, Any]]:
        raise StoreUnavailable("store down")


async def _store(kind: str) -> AsyncIterator[AssetStore]:
    if kind == "inmemory":
        yield InMemoryAssetStore(mode="enterprise")
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")
    store = await PostgresAssetStore.connect(PG_URL, mode="enterprise")
    async with store._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_inventory_asset_history, aq_inventory_asset")
    try:
        yield store
    finally:
        await cast(_Closable, store).close()


def _source(
    source_id: str = "src:cmdb",
    *,
    reliability: float = 0.8,
    health: str = "ok",
    as_of: datetime = NOW,
) -> DiscoverySource:
    return DiscoverySource(
        source_id=source_id,
        reliability=reliability,
        health=health,
        as_of=as_of,
    )


async def _ingest_asset(
    engine: InventoryIntelligenceEngine,
    *,
    source: DiscoverySource,
    asset_id: str | None = None,
    asset_type: str = "server",
    classification: str = "web",
) -> AssetRecord:
    return (
        await engine.ingest(
            reports=[
                {
                    "id": asset_id or new_id("ast"),
                    "asset_type": asset_type,
                    "classification": classification,
                    "ref": f"{source.source_id}:{classification}",
                    "evidence_id": new_id("evd"),
                }
            ],
            source=source,
            tenant_id=TENANT,
        )
    )[0]


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_inv_absence_not_decommission(kind: str) -> None:
    async for store in _store(kind):
        engine = InventoryIntelligenceEngine(store)
        saved = await _ingest_asset(engine, source=_source(as_of=NOW))

        changed = await engine.sweep_unreported(
            source=_source(as_of=NOW + timedelta(days=2)),
            tenant_id=TENANT,
        )
        stored = await store.get(saved.id, tenant_id=TENANT)

        assert [asset.id for asset in changed] == [saved.id]
        assert stored is not None
        assert stored.lifecycle_state == "unreported"
        assert stored.lifecycle_state != "decommissioned"
        assert stored.unreported_since == NOW + timedelta(days=2)


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_inv_sweep_refuses_unknown_health(kind: str) -> None:
    async for store in _store(kind):
        engine = InventoryIntelligenceEngine(store)
        saved = await _ingest_asset(engine, source=_source(as_of=NOW))

        with pytest.raises(SourceHealthUnknown):
            await engine.sweep_unreported(
                source=_source(health="unknown", as_of=NOW + timedelta(days=2)),
                tenant_id=TENANT,
            )

        stored = await store.get(saved.id, tenant_id=TENANT)
        assert stored is not None
        assert stored.lifecycle_state == "active"


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_inv_decommission_requires_evidence(kind: str) -> None:
    async for store in _store(kind):
        engine = InventoryIntelligenceEngine(store)
        saved = await _ingest_asset(engine, source=_source(as_of=NOW))

        with pytest.raises(DecommissionRequiresEvidence):
            await engine.decommission(saved.id, by=ACTOR, evidence_id=None, tenant_id=TENANT)

        still_active = await store.get(saved.id, tenant_id=TENANT)
        assert still_active is not None
        assert still_active.lifecycle_state == "active"

        decommissioned = await engine.decommission(
            saved.id,
            by=ACTOR,
            evidence_id=new_id("evd"),
            tenant_id=TENANT,
        )

        assert decommissioned.lifecycle_state == "decommissioned"
        assert decommissioned.basis[-1].evidence_id is not None
        assert "decommission:evidence" in decommissioned.basis[-1].ref


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_inv_inventory_declares_freshness(kind: str) -> None:
    async for store in _store(kind):
        engine = InventoryIntelligenceEngine(store)
        cmdb = await _ingest_asset(
            engine,
            source=_source("src:cmdb", as_of=NOW),
            classification="web",
        )
        edr = await _ingest_asset(
            engine,
            source=_source("src:edr", as_of=NOW + timedelta(hours=2)),
            classification="workstation",
        )
        await engine.sweep_unreported(
            source=_source("src:cmdb", as_of=NOW + timedelta(days=1)),
            tenant_id=TENANT,
        )

        report = await engine.inventory(tenant_id=TENANT)

        assert report.assets == sorted([cmdb.id, edr.id])
        assert report.total == 2
        assert report.source_freshness == {
            "src:cmdb": NOW,
            "src:edr": NOW + timedelta(hours=2),
        }
        assert report.as_of == NOW
        assert report.degraded is False


async def test_inv_inventory_fails_not_shrinks() -> None:
    engine = InventoryIntelligenceEngine(cast(AssetStore, _UnavailableStore()))

    with pytest.raises(InventoryUnavailable):
        await engine.inventory(tenant_id=TENANT)


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_inv_lifecycle_append_only(kind: str) -> None:
    async for store in _store(kind):
        engine = InventoryIntelligenceEngine(store)
        saved = await _ingest_asset(engine, source=_source(as_of=NOW))
        unreported = await engine.mark_unreported(saved.id, tenant_id=TENANT)
        decommissioned = await engine.decommission(
            saved.id,
            by=ACTOR,
            evidence_id=None,
            decision_ref=new_id("run"),
            tenant_id=TENANT,
        )
        history = await store.history(saved.id)

        assert unreported.lifecycle_state == "unreported"
        assert decommissioned.lifecycle_state == "decommissioned"
        assert len(history) == 3
        assert [entry["seq"] for entry in history] == sorted(entry["seq"] for entry in history)
        assert [entry["snapshot"]["lifecycle_state"] for entry in history] == [
            "active",
            "unreported",
            "decommissioned",
        ]

        if kind == "postgres":
            pg = cast(PostgresAssetStore, store)
            async with pg._pool.acquire() as conn:
                with pytest.raises(Exception, match="append-only"):
                    await conn.execute(
                        "DELETE FROM aq_inventory_asset_history WHERE asset_id=$1",
                        saved.id,
                    )
