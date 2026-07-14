"""T1 acceptance tests for Threat Intelligence Fusion normalization."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import (
    ALL_ERROR_CODES,
    MalformedFeedRecord,
    ThreatConfigInvalid,
)
from aqelyn.objects import InMemoryObjectStore, NaturalKey, ObjectQuery, ObjectStore
from aqelyn.objects.postgres import PostgresObjectStore
from aqelyn.objects.registry import ObjectTypeRegistry
from aqelyn.threat import FeedRecord, FusionConfig, ThreatFusionEngine
from aqelyn.threat.models import THREAT_INDICATOR_OBJECT_TYPE

PG_URL = os.getenv("AQELYN_DATABASE_URL")
NOW = datetime(2026, 7, 14, 16, 0, tzinfo=UTC)


@dataclass
class ThreatHarness:
    kind: str
    object_store: ObjectStore


@pytest.fixture(params=["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def threat_harness(request: pytest.FixtureRequest) -> AsyncIterator[ThreatHarness]:
    if request.param == "inmemory":
        yield ThreatHarness(
            kind="inmemory",
            object_store=InMemoryObjectStore(registry=ObjectTypeRegistry(), mode="local"),
        )
        return
    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    store = await PostgresObjectStore.connect(
        PG_URL,
        registry=ObjectTypeRegistry(),
        mode="local",
    )
    async with store._pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE aq_relationship, aq_object_natural_key, aq_object_history, aq_object "
            "RESTART IDENTITY"
        )
    try:
        yield ThreatHarness(kind="postgres", object_store=store)
    finally:
        await store.close()


def _record(
    *,
    source_id: str | None = None,
    evidence_id: str | None = None,
    raw: dict[str, Any] | None = None,
) -> FeedRecord:
    return FeedRecord(
        source_id=source_id or new_id("src"),
        evidence_id=evidence_id or new_id("evd"),
        received_at=NOW,
        raw=raw or {"type": "domain", "value": "Example.COM.", "ttps": ["T1046"]},
    )


def _threat_source_text() -> str:
    root = Path(__file__).resolve().parents[2] / "src" / "aqelyn" / "threat"
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(root.glob("*.py")))


async def test_tif_ingest_no_fetch(threat_harness: ThreatHarness) -> None:
    source = new_id("src")
    evidence = new_id("evd")
    engine = ThreatFusionEngine(
        threat_harness.object_store,
        config=FusionConfig(source_reliability={source: 0.8}),
    )

    indicators = await engine.ingest(
        [
            _record(
                source_id=source,
                evidence_id=evidence,
                raw={"type": "domain_name", "value": "Example.COM.", "confidence": 0.9},
            )
        ],
        tenant_id=None,
    )

    [indicator] = indicators
    assert indicator.indicator_type == "domain"
    assert indicator.value == "example.com"
    assert indicator.confidence == 0.9
    assert indicator.sources[0].source_id == source
    assert indicator.sources[0].evidence_id == evidence

    stored = await threat_harness.object_store.get(indicator.id)
    assert stored is not None
    assert stored.object_type == THREAT_INDICATOR_OBJECT_TYPE
    assert stored.natural_keys == [
        NaturalKey(namespace="threat_indicator.domain", value="example.com")
    ]

    threat_source = _threat_source_text()
    for forbidden in (
        "socket",
        "requests",
        "urllib",
        "httpx",
        "aiohttp",
        "ftplib",
        "paramiko",
        "boto3",
        "os.environ",
        "getenv",
    ):
        assert forbidden not in threat_source


async def test_tif_quarantine_malformed(threat_harness: ThreatHarness) -> None:
    engine = ThreatFusionEngine(threat_harness.object_store)

    indicators = await engine.ingest([_record(raw={"type": "domain"})], tenant_id=None)

    assert indicators == []
    [quarantined] = engine.quarantine
    assert "missing required field" in quarantined.reason
    rows, _ = await threat_harness.object_store.query(
        ObjectQuery(object_type=THREAT_INDICATOR_OBJECT_TYPE)
    )
    assert rows == []

    strict_engine = ThreatFusionEngine(
        threat_harness.object_store,
        config=FusionConfig(quarantine_on_malformed=False),
    )
    with pytest.raises(MalformedFeedRecord):
        await strict_engine.ingest([_record(raw={"type": "domain"})], tenant_id=None)


async def test_tif_dedupe_indicators(threat_harness: ThreatHarness) -> None:
    first_source = new_id("src")
    second_source = new_id("src")
    engine = ThreatFusionEngine(threat_harness.object_store)

    indicators = await engine.ingest(
        [
            _record(source_id=first_source, raw={"indicator_type": "domain", "value": "evil.test"}),
            _record(source_id=second_source, raw={"kind": "fqdn", "observable": "EVIL.TEST."}),
        ],
        tenant_id=None,
    )

    assert len(indicators) == 2
    assert indicators[0].id == indicators[1].id
    assert len(indicators[1].sources) == 2
    rows, _ = await threat_harness.object_store.query(
        ObjectQuery(
            object_type=THREAT_INDICATOR_OBJECT_TYPE,
            natural_key=NaturalKey(namespace="threat_indicator.domain", value="evil.test"),
        )
    )
    [stored] = rows
    assert stored.id == indicators[0].id
    assert stored.version == 2
    assert sorted(source.source_id for source in stored.sources) == sorted(
        [first_source, second_source]
    )


def test_tif_config_invalid() -> None:
    source_id = new_id("src")

    with pytest.raises(ThreatConfigInvalid, match="min_match_confidence"):
        FusionConfig(min_match_confidence=1.01)
    with pytest.raises(ThreatConfigInvalid, match="recency_half_life_days"):
        FusionConfig(recency_half_life_days=0.0)
    with pytest.raises(ThreatConfigInvalid, match="source_reliability"):
        FusionConfig(source_reliability={source_id: -0.1})

    assert "ThreatConfigInvalid" in ALL_ERROR_CODES
    assert "ThreatSourceNotFound" in ALL_ERROR_CODES
    assert "MalformedFeedRecord" in ALL_ERROR_CODES
