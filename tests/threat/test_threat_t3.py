"""T3 acceptance tests for threat correlation against the estate."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.graph import InMemoryKnowledgeGraph, KnowledgeGraph, PostgresKnowledgeGraph
from aqelyn.objects import AQObject, AQRelationship, InMemoryObjectStore, ObjectStore, SourceRef
from aqelyn.objects.postgres import PostgresObjectStore
from aqelyn.objects.registry import ObjectTypeRegistry
from aqelyn.threat import FeedRecord, FusionConfig, ThreatFusionEngine

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 14, 16, 0, tzinfo=UTC)
TENANT_A = "018f0000-0000-7000-8000-000000000001"
TENANT_B = "018f0000-0000-7000-8000-000000000002"
SYS = ActorRef(actor_type="system", actor_id="threat-test")


@dataclass
class ThreatGraphHarness:
    kind: str
    object_store: ObjectStore
    graph: KnowledgeGraph


@pytest.fixture(params=["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def threat_graph_harness(
    request: pytest.FixtureRequest,
) -> AsyncIterator[ThreatGraphHarness]:
    if request.param == "inmemory":
        store = InMemoryObjectStore(registry=ObjectTypeRegistry(), mode="enterprise")
        yield ThreatGraphHarness(
            kind="inmemory",
            object_store=store,
            graph=InMemoryKnowledgeGraph(store),
        )
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    postgres_store = await PostgresObjectStore.connect(
        PG_URL,
        registry=ObjectTypeRegistry(),
        mode="enterprise",
    )
    async with postgres_store._pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE aq_relationship, aq_object_natural_key, aq_object_history, aq_object "
            "RESTART IDENTITY"
        )
    try:
        yield ThreatGraphHarness(
            kind="postgres",
            object_store=postgres_store,
            graph=PostgresKnowledgeGraph(postgres_store._pool),
        )
    finally:
        await postgres_store.close()


async def test_tif_correlate_matches(threat_graph_harness: ThreatGraphHarness) -> None:
    engine = _engine(threat_graph_harness)
    evidence_id = new_id("evd")
    [indicator] = await engine.ingest(
        [
            _record(
                evidence_id=evidence_id,
                raw={"type": "domain", "value": "evil.example", "confidence": 0.9},
            )
        ],
        tenant_id=TENANT_A,
    )
    attribute_asset = await _asset(
        threat_graph_harness.object_store,
        "web",
        tenant_id=TENANT_A,
        attributes={"domains": ["evil.example"], "owner": "platform"},
    )
    graph_asset = await _asset(
        threat_graph_harness.object_store,
        "mail",
        tenant_id=TENANT_A,
        attributes={"domains": ["benign.example"]},
    )
    indicator_obj = await threat_graph_harness.object_store.get(indicator.id)
    assert indicator_obj is not None
    await _relate(
        threat_graph_harness.object_store,
        indicator_obj,
        graph_asset,
        relation_type="observed_on",
    )

    report = await engine.correlate(tenant_id=TENANT_A, now=NOW)

    assert report.evaluated == 1
    assert report.truncated is False
    by_asset = {match.asset_id: match for match in report.matches}
    assert set(by_asset) == {attribute_asset.id, graph_asset.id}
    assert by_asset[attribute_asset.id].match_type == "attribute:domain"
    assert by_asset[attribute_asset.id].evidence_id == evidence_id
    assert by_asset[graph_asset.id].match_type == "graph:domain"
    via = by_asset[graph_asset.id].via
    assert via is not None
    assert via.edges[0].sources[0].evidence_id is not None

    explanation = engine.explain(by_asset[attribute_asset.id])
    assert explanation["indicator_id"] == indicator.id
    assert explanation["asset_id"] == attribute_asset.id
    assert explanation["evidence_id"] == evidence_id
    assert "matched asset attribute" in str(explanation["reason"])


async def test_tif_tenant_and_truncation(threat_graph_harness: ThreatGraphHarness) -> None:
    engine = _engine(threat_graph_harness, config=FusionConfig(correlation={"max_nodes": 1}))
    [indicator_a] = await engine.ingest(
        [_record(raw={"type": "domain", "value": "shared.example"})],
        tenant_id=TENANT_A,
    )
    await engine.ingest(
        [_record(raw={"type": "domain", "value": "shared.example"})],
        tenant_id=TENANT_B,
    )
    asset_a = await _asset(
        threat_graph_harness.object_store,
        "tenant-a-web",
        tenant_id=TENANT_A,
        attributes={"domains": ["shared.example"]},
    )
    neighbor_a = await _asset(
        threat_graph_harness.object_store,
        "tenant-a-neighbor",
        tenant_id=TENANT_A,
        attributes={"domains": ["internal.example"]},
    )
    asset_b = await _asset(
        threat_graph_harness.object_store,
        "tenant-b-web",
        tenant_id=TENANT_B,
        attributes={"domains": ["shared.example"]},
    )
    await _relate(threat_graph_harness.object_store, asset_a, neighbor_a)

    report = await engine.correlate(tenant_id=TENANT_A, now=NOW)

    assert report.evaluated == 1
    assert report.truncated is True
    assert [(match.indicator_id, match.asset_id) for match in report.matches] == [
        (indicator_a.id, asset_a.id)
    ]
    assert asset_b.id not in {match.asset_id for match in report.matches}


async def test_tif_expiry(threat_graph_harness: ThreatGraphHarness) -> None:
    engine = _engine(threat_graph_harness)
    [active] = await engine.ingest(
        [
            _record(
                raw={"type": "domain", "value": "active.example", "confidence": 0.8},
            )
        ],
        tenant_id=TENANT_A,
    )
    [expired] = await engine.ingest(
        [
            _record(
                raw={
                    "type": "domain",
                    "value": "expired.example",
                    "expires_at": (NOW - timedelta(days=1)).isoformat(),
                },
            )
        ],
        tenant_id=TENANT_A,
    )
    active_asset = await _asset(
        threat_graph_harness.object_store,
        "active-asset",
        tenant_id=TENANT_A,
        attributes={"domains": ["active.example"]},
    )
    expired_asset = await _asset(
        threat_graph_harness.object_store,
        "expired-asset",
        tenant_id=TENANT_A,
        attributes={"domains": ["expired.example"]},
    )

    report = await engine.correlate(tenant_id=TENANT_A, now=NOW)

    assert [(match.indicator_id, match.asset_id) for match in report.matches] == [
        (active.id, active_asset.id)
    ]
    assert expired.id not in {match.indicator_id for match in report.matches}
    assert expired_asset.id not in {match.asset_id for match in report.matches}


async def test_tif_correlate_not_starved_by_indicators(
    threat_graph_harness: ThreatGraphHarness,
) -> None:
    # The engine's own indicator objects must not consume the asset query budget
    # (ECR-0004). With limit=1 the unfiltered asset query would return the
    # (lower-id, ingested-first) indicator and strip it -> zero assets.
    engine = _engine(threat_graph_harness, config=FusionConfig(correlation={"limit": 1}))
    await engine.ingest(
        [_record(raw={"type": "domain", "value": "evil.example"})],
        tenant_id=TENANT_A,
    )
    asset = await _asset(
        threat_graph_harness.object_store,
        "web",
        tenant_id=TENANT_A,
        attributes={"domains": ["evil.example"]},
    )

    report = await engine.correlate(tenant_id=TENANT_A, now=NOW)

    assert [match.asset_id for match in report.matches] == [asset.id]


async def test_tif_match_limit_truncates(threat_graph_harness: ThreatGraphHarness) -> None:
    # More matches than the configured limit must be reported as truncated,
    # never silently dropped as a clean result (§11/FR-6). Two indicators each
    # matching two assets yield four matches -> sliced to two with limit=2.
    engine = _engine(threat_graph_harness, config=FusionConfig(correlation={"limit": 2}))
    both = ["one.example", "two.example"]
    await engine.ingest(
        [
            _record(raw={"type": "domain", "value": "one.example"}),
            _record(raw={"type": "domain", "value": "two.example"}),
        ],
        tenant_id=TENANT_A,
    )
    for name in ("asset-one", "asset-two"):
        await _asset(
            threat_graph_harness.object_store,
            name,
            tenant_id=TENANT_A,
            attributes={"domains": both},
        )

    report = await engine.correlate(tenant_id=TENANT_A, now=NOW)

    assert len(report.matches) == 2
    assert report.truncated is True


def _engine(
    harness: ThreatGraphHarness,
    *,
    config: FusionConfig | None = None,
) -> ThreatFusionEngine:
    return ThreatFusionEngine(harness.object_store, config=config, graph=harness.graph)


def _record(
    *,
    raw: dict[str, Any],
    evidence_id: str | None = None,
) -> FeedRecord:
    return FeedRecord(
        source_id=new_id("src"),
        evidence_id=evidence_id or new_id("evd"),
        received_at=NOW,
        raw=raw,
    )


async def _asset(
    store: ObjectStore,
    display_name: str,
    *,
    tenant_id: str,
    attributes: dict[str, Any],
) -> AQObject:
    now = NOW
    return await store.upsert(
        AQObject(
            id="",
            object_type="generic",
            schema_version=1,
            tenant_id=tenant_id,
            display_name=display_name,
            attributes=attributes,
            sources=[_source("asset.inventory/v1")],
            first_seen_at=now,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
            created_by=SYS,
            updated_by=SYS,
        )
    )


async def _relate(
    store: ObjectStore,
    from_obj: AQObject,
    to_obj: AQObject,
    *,
    relation_type: str = "depends_on",
) -> AQRelationship:
    return await store.relate(
        AQRelationship(
            id="",
            from_id=from_obj.id,
            to_id=to_obj.id,
            relation_type=relation_type,
            sources=[_source(f"relationship.{relation_type}")],
            created_at=NOW,
            updated_at=NOW,
            created_by=SYS,
            updated_by=SYS,
        )
    )


def _source(method: str) -> SourceRef:
    return SourceRef(
        source_id=new_id("src"),
        evidence_id=new_id("evd"),
        observed_at=NOW,
        method=method,
    )
