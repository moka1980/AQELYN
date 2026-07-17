"""N4 acceptance tests for classification and relationship owner reuse."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Protocol, cast

import pytest

from aqelyn.conventions import new_id
from aqelyn.graph import Path
from aqelyn.inventory import (
    AssetBasis,
    AssetRecord,
    AssetStore,
    DiscoverySource,
    InMemoryAssetStore,
    InventoryConfig,
    InventoryIntelligenceEngine,
    PostgresAssetStore,
)
from aqelyn.objects import AQRelationship

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 17, 17, 0, tzinfo=UTC)
TENANT = "018f0000-0000-7000-8000-000000250401"


class _Closable(Protocol):
    async def close(self) -> None: ...


class _ClassifierSpy:
    def __init__(self, classification: str) -> None:
        self.classification = classification
        self.calls: list[tuple[str, str | None]] = []

    async def classify(self, asset_id: str, *, tenant_id: str | None = None) -> str:
        self.calls.append((asset_id, tenant_id))
        return self.classification


class _PathSpy:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def paths(
        self,
        from_id: str,
        to_id: str,
        *,
        direction: str = "both",
        relation_types: Sequence[str] | None = None,
        max_depth: int = 6,
        max_paths: int = 10,
        max_work: int = 50_000,
    ) -> list[Path]:
        self.calls.append(
            {
                "from_id": from_id,
                "to_id": to_id,
                "direction": direction,
                "relation_types": tuple(relation_types or ()),
                "max_depth": max_depth,
                "max_paths": max_paths,
                "max_work": max_work,
            }
        )
        return [Path(node_ids=[from_id, to_id], edges=[], length=1)]


class _RelationshipStoreSpy:
    def __init__(self) -> None:
        self.calls: list[AQRelationship] = []

    async def relate(self, rel: AQRelationship) -> AQRelationship:
        self.calls.append(rel)
        return rel.model_copy(update={"id": new_id("rel")}, deep=True)


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


def _source() -> DiscoverySource:
    return DiscoverySource(source_id="src:cmdb", reliability=0.82, health="ok", as_of=NOW)


async def _ingest_asset(
    engine: InventoryIntelligenceEngine,
    *,
    basis: list[AssetBasis] | None = None,
) -> AssetRecord:
    report: dict[str, object] = {
        "id": new_id("ast"),
        "asset_type": "server",
        "classification": "unknown",
        "ref": "cmdb:web-1",
        "evidence_id": new_id("evd"),
    }
    if basis is not None:
        report["basis"] = [item.model_dump(mode="json") for item in basis]
    return (await engine.ingest(reports=[report], source=_source(), tenant_id=TENANT))[0]


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_inv_classify_delegates_acg(kind: str) -> None:
    async for store in _store(kind):
        classifier = _ClassifierSpy("database")
        engine = InventoryIntelligenceEngine(store, classifier=classifier)
        saved = await _ingest_asset(engine)

        classified = await engine.classify(saved.id, tenant_id=TENANT)
        stored = await store.get(saved.id, tenant_id=TENANT)

        assert classifier.calls == [(saved.id, TENANT)]
        assert classified.classification == "database"
        assert stored == classified
        assert classified.basis[-1].kind == "config"
        assert classified.basis[-1].ref == f"ea0012:classify:{saved.id}"


@pytest.mark.parametrize("kind", ["inmemory", "postgres"])
async def test_inv_relationships_reuse(kind: str) -> None:
    async for store in _store(kind):
        source_object_id = new_id("obj")
        target_object_id = new_id("obj")
        evidence_id = new_id("evd")
        relationship_ref = f"{source_object_id}|depends_on|{target_object_id}"
        path_spy = _PathSpy()
        relationship_store = _RelationshipStoreSpy()
        engine = InventoryIntelligenceEngine(
            store,
            config=InventoryConfig(max_relationship_work=17),
            relationship_store=relationship_store,
            graph=path_spy,
            source_id=new_id("src"),
        )
        saved = await _ingest_asset(
            engine,
            basis=[
                AssetBasis(
                    kind="relationship",
                    ref=relationship_ref,
                    as_of=NOW,
                    evidence_id=evidence_id,
                )
            ],
        )

        inferred = await engine.infer_relationships(saved.id, tenant_id=TENANT)

        assert path_spy.calls == [
            {
                "from_id": source_object_id,
                "to_id": target_object_id,
                "direction": "out",
                "relation_types": ("depends_on",),
                "max_depth": 6,
                "max_paths": 1,
                "max_work": 17,
            }
        ]
        assert len(relationship_store.calls) == 1
        related = relationship_store.calls[0]
        assert related.from_id == source_object_id
        assert related.to_id == target_object_id
        assert related.relation_type == "depends_on"
        assert related.attributes == {
            "inferred_from": relationship_ref,
            "inventory_asset_id": saved.id,
        }
        assert related.sources[0].evidence_id == evidence_id
        assert related.sources[0].method == "inventory_relationship_inference"
        inferred_links = [
            (item.source_asset, item.target_asset, item.relationship_type) for item in inferred
        ]
        assert inferred_links == [(source_object_id, target_object_id, "depends_on")]
        assert inferred[0].inferred_from == relationship_ref
        assert inferred[0].evidence_id == evidence_id
