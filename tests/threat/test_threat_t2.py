"""T2 acceptance tests for threat confidence and source registry."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import ThreatConfigInvalid
from aqelyn.objects import InMemoryObjectStore, SourceRef
from aqelyn.objects.registry import ObjectTypeRegistry
from aqelyn.threat import (
    FusionConfig,
    InMemoryThreatSourceRegistry,
    ThreatFusionEngine,
    ThreatIndicator,
    ThreatSourceRegistry,
    score_confidence,
)
from aqelyn.threat.postgres import PostgresThreatSourceRegistry

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 14, 16, 0, tzinfo=UTC)
ACTOR = ActorRef(actor_type="system", actor_id="threat-test")


@dataclass
class SourceRegistryHarness:
    kind: str
    registry: ThreatSourceRegistry


@pytest.fixture(params=["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def source_registry_harness(
    request: pytest.FixtureRequest,
) -> AsyncIterator[SourceRegistryHarness]:
    if request.param == "inmemory":
        yield SourceRegistryHarness(
            kind="inmemory",
            registry=InMemoryThreatSourceRegistry(default_set_at=NOW),
        )
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    registry = await PostgresThreatSourceRegistry.connect(PG_URL)
    async with registry._pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_threat_source")
    try:
        yield SourceRegistryHarness(kind="postgres", registry=registry)
    finally:
        await registry.close()


async def test_tif_source_contract(source_registry_harness: SourceRegistryHarness) -> None:
    registry = source_registry_harness.registry
    source_id = new_id("src")
    unknown_source = new_id("src")

    unknown = await registry.get(unknown_source)
    assert unknown.source_id == "*"
    assert unknown.reliability == 0.5
    assert unknown.meta["default"] is True

    stored = await registry.set(
        source_id,
        reliability=0.8,
        meta={"feed": "vendor-a", "rationale": "curated commercial feed"},
        by=ACTOR,
    )
    assert stored.source_id == source_id
    assert stored.reliability == 0.8
    assert stored.meta["feed"] == "vendor-a"
    assert stored.set_by == ACTOR
    assert stored.version == 1

    updated = await registry.set(
        source_id,
        reliability=0.9,
        meta={"feed": "vendor-a", "rationale": "manual reliability review"},
        by=ACTOR,
    )
    assert updated.version == 2
    assert updated.reliability == 0.9
    assert (await registry.get(source_id)).meta["rationale"] == "manual reliability review"

    listed = await registry.list()
    assert [source.source_id for source in listed] == ["*", source_id]

    with pytest.raises(ThreatConfigInvalid):
        await registry.get("not-a-source-id")


async def test_tif_confidence() -> None:
    first_source = new_id("src")
    second_source = new_id("src")
    registry = InMemoryThreatSourceRegistry(default_set_at=NOW)
    await registry.set(
        first_source,
        reliability=0.8,
        meta={"rationale": "primary feed"},
        by=ACTOR,
    )
    await registry.set(
        second_source,
        reliability=0.6,
        meta={"rationale": "secondary feed"},
        by=ACTOR,
    )
    indicator = _indicator(
        sources=[
            SourceRef(
                source_id=first_source,
                evidence_id=new_id("evd"),
                observed_at=NOW,
                method="threat.feed_record/v1",
            ),
            SourceRef(
                source_id=second_source,
                evidence_id=new_id("evd"),
                observed_at=NOW - timedelta(days=10),
                method="threat.feed_record/v1",
            ),
        ]
    )
    config = FusionConfig(recency_half_life_days=10.0)

    score = await score_confidence(indicator, registry=registry, config=config, now=NOW)
    repeat = await score_confidence(indicator, registry=registry, config=config, now=NOW)
    one_source_score = await score_confidence(
        _indicator(
            sources=[
                SourceRef(
                    source_id=first_source,
                    evidence_id=new_id("evd"),
                    observed_at=NOW,
                    method="threat.feed_record/v1",
                )
            ]
        ),
        registry=registry,
        config=config,
        now=NOW,
    )
    old_score = await score_confidence(
        _indicator(
            sources=[
                SourceRef(
                    source_id=first_source,
                    evidence_id=new_id("evd"),
                    observed_at=NOW - timedelta(days=20),
                    method="threat.feed_record/v1",
                )
            ]
        ),
        registry=registry,
        config=config,
        now=NOW,
    )

    assert score == pytest.approx(0.7956)
    assert repeat == score
    assert 0.0 <= score <= 1.0
    assert score > one_source_score
    assert one_source_score > old_score

    engine = ThreatFusionEngine(
        InMemoryObjectStore(registry=ObjectTypeRegistry(), mode="local"),
        config=config,
        source_registry=registry,
    )
    assert await engine.score_confidence(indicator, now=NOW) == pytest.approx(score)
    assert "TrustEngine" in (
        Path(__file__).resolve().parents[2] / "src" / "aqelyn" / "threat" / "confidence.py"
    ).read_text(encoding="utf-8")


def _indicator(*, sources: list[SourceRef]) -> ThreatIndicator:
    return ThreatIndicator(
        id=new_id("obj"),
        tenant_id=None,
        indicator_type="domain",
        value="evil.example",
        confidence=0.9,
        first_seen_at=NOW,
        last_seen_at=NOW,
        sources=sources,
    )
