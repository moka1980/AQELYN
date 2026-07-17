"""N2 acceptance tests for AssetStore, handed-in ingest, and reconciliation."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

import pytest

from aqelyn.conventions import new_id
from aqelyn.inventory import (
    AssetBasis,
    AssetRecord,
    AssetStore,
    DiscoverySource,
    InMemoryAssetStore,
    InventoryIntelligenceEngine,
    Ownership,
    PostgresAssetStore,
)

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 17, 15, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000250101"
OTHER_TENANT = "018f0000-0000-7000-8000-000000250102"


class _Closable(Protocol):
    async def close(self) -> None: ...


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
    source_id: str,
    reliability: float,
    *,
    as_of: datetime = NOW,
) -> DiscoverySource:
    return DiscoverySource(
        source_id=source_id,
        reliability=reliability,
        health="ok",
        as_of=as_of,
    )


def _basis(ref: str = "cmdb:web-1") -> AssetBasis:
    return AssetBasis(kind="discovery", ref=ref, as_of=NOW, evidence_id=new_id("evd"))


def _owner(team: str, *, source_id: str = "src:cmdb") -> Ownership:
    return Ownership(
        business_owner=team,
        technical_owner=f"{team}-platform",
        custodian=f"{team}-sre",
        rationale=f"{source_id} reported ownership.",
        source_id=source_id,
    )


def _asset(
    *,
    asset_id: str | None = None,
    tenant_id: str | None = TENANT,
    discovery_source: str = "src:cmdb",
    classification: str | None = "server",
    confidence: float = 0.82,
    first_seen_at: datetime = NOW,
) -> AssetRecord:
    return AssetRecord(
        id=asset_id or new_id("ast"),
        tenant_id=tenant_id,
        asset_type="server",
        discovery_source=discovery_source,
        classification=classification,
        owner=_owner("payments", source_id=discovery_source),
        lifecycle_state="active",
        confidence=confidence,
        basis=[_basis(f"{discovery_source}:web-1")],
        first_seen_at=first_seen_at,
        last_reported_at=first_seen_at,
    )


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_inv_store_contract(kind: str) -> None:
    async for store in _store(kind):
        first = await store.put(_asset())
        other = await store.put(
            _asset(
                tenant_id=OTHER_TENANT,
                discovery_source="src:edr",
                first_seen_at=NOW + timedelta(minutes=1),
            )
        )

        assert await store.get(first.id, tenant_id=TENANT) == first
        assert await store.get(first.id, tenant_id=OTHER_TENANT) is None
        assert [row.id for row in await store.query(tenant_id=TENANT)] == [first.id]
        assert [row.id for row in await store.query(tenant_id=OTHER_TENANT)] == [other.id]
        assert [
            row.id for row in await store.query(tenant_id=TENANT, lifecycle_state="active")
        ] == [first.id]

        changed = first.model_copy(update={"classification": "database"}, deep=True)
        updated = await store.put(changed)
        assert updated.classification == "database"
        assert (await store.get(first.id, tenant_id=TENANT)) == updated

        history = await store.history(first.id)
        assert len(history) == 2
        assert history[0]["snapshot"]["classification"] == "server"
        assert history[1]["snapshot"]["classification"] == "database"

        if kind == "postgres":
            pg = cast(PostgresAssetStore, store)
            async with pg._pool.acquire() as conn:
                with pytest.raises(Exception, match="append-only"):
                    await conn.execute(
                        "UPDATE aq_inventory_asset_history SET snapshot=snapshot WHERE asset_id=$1",
                        first.id,
                    )


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_inv_confidence_from_trust(kind: str) -> None:
    async for store in _store(kind):
        engine = InventoryIntelligenceEngine(store)
        saved = (
            await engine.ingest(
                reports=[
                    {
                        "asset_type": "server",
                        "classification": "web",
                        "ref": "cmdb:web-1",
                        "evidence_id": new_id("evd"),
                    }
                ],
                source=_source("src:cmdb", 0.42),
                tenant_id=TENANT,
            )
        )[0]

        assert saved.discovery_source == "src:cmdb"
        assert saved.confidence == 0.42
        assert saved.basis[0].kind == "discovery"
        assert saved.basis[0].ref == "src:cmdb:cmdb:web-1"
        assert await store.get(saved.id, tenant_id=TENANT) == saved


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_inv_reconcile_reliability_precedence(kind: str) -> None:
    async for store in _store(kind):
        engine = InventoryIntelligenceEngine(store)
        asset_id = new_id("ast")
        await engine.ingest(
            reports=[
                {
                    "id": asset_id,
                    "asset_type": "server",
                    "classification": "critical_server",
                    "owner": _owner("payments", source_id="src:cmdb").model_dump(mode="json"),
                }
            ],
            source=_source("src:cmdb", 0.95, as_of=NOW),
            tenant_id=TENANT,
        )
        await engine.ingest(
            reports=[
                {
                    "id": asset_id,
                    "asset_type": "server",
                    "classification": "generic_server",
                    "owner": _owner("unknown", source_id="src:edr").model_dump(mode="json"),
                }
            ],
            source=_source("src:edr", 0.20, as_of=NOW + timedelta(minutes=1)),
            tenant_id=TENANT,
        )

        last_writer = await store.get(asset_id, tenant_id=TENANT)
        reconciled = await engine.reconcile(asset_id, tenant_id=TENANT)

        assert last_writer is not None
        assert last_writer.classification == "generic_server"
        assert reconciled.classification == "critical_server"
        assert reconciled.owner is not None
        assert reconciled.owner.business_owner == "payments"
        assert {conflict.field for conflict in reconciled.conflicts} == {
            "classification",
            "owner",
        }
        classification = next(
            conflict for conflict in reconciled.conflicts if conflict.field == "classification"
        )
        assert classification.resolved_by == "src:cmdb"
        assert classification.unresolved is False
        assert [(c.source_id, c.reliability) for c in classification.candidates] == [
            ("src:cmdb", 0.95),
            ("src:edr", 0.20),
        ]


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_inv_reconcile_records_conflicts(kind: str) -> None:
    async for store in _store(kind):
        engine = InventoryIntelligenceEngine(store)
        asset_id = new_id("ast")
        await engine.ingest(
            reports=[
                {
                    "id": asset_id,
                    "asset_type": "server",
                    "classification": "database",
                    "owner": _owner("finance", source_id="src:cmdb").model_dump(mode="json"),
                }
            ],
            source=_source("src:cmdb", 0.8),
            tenant_id=TENANT,
        )
        await engine.ingest(
            reports=[
                {
                    "id": asset_id,
                    "asset_type": "server",
                    "classification": "web",
                    "owner": _owner("platform", source_id="src:edr").model_dump(mode="json"),
                }
            ],
            source=_source("src:edr", 0.6, as_of=NOW + timedelta(minutes=1)),
            tenant_id=TENANT,
        )

        reconciled = await engine.reconcile(asset_id, tenant_id=TENANT)
        conflicts = {conflict.field: conflict for conflict in reconciled.conflicts}

        assert set(conflicts) == {"classification", "owner"}
        assert [candidate.source_id for candidate in conflicts["classification"].candidates] == [
            "src:cmdb",
            "src:edr",
        ]
        assert {candidate.value for candidate in conflicts["classification"].candidates} == {
            "database",
            "web",
        }
        assert conflicts["classification"].resolved_by == "src:cmdb"


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_inv_reconcile_tie_unresolved(kind: str) -> None:
    async for store in _store(kind):
        engine = InventoryIntelligenceEngine(store)
        asset_id = new_id("ast")
        await engine.ingest(
            reports=[
                {
                    "id": asset_id,
                    "asset_type": "server",
                    "classification": "database",
                }
            ],
            source=_source("src:cmdb", 0.5),
            tenant_id=TENANT,
        )
        await engine.ingest(
            reports=[
                {
                    "id": asset_id,
                    "asset_type": "server",
                    "classification": "web",
                }
            ],
            source=_source("src:edr", 0.5, as_of=NOW + timedelta(minutes=1)),
            tenant_id=TENANT,
        )

        reconciled = await engine.reconcile(asset_id, tenant_id=TENANT)
        classification = next(
            conflict for conflict in reconciled.conflicts if conflict.field == "classification"
        )

        assert reconciled.classification is None
        assert classification.unresolved is True
        assert classification.resolved_by is None
        assert {candidate.value for candidate in classification.candidates} == {"database", "web"}
