"""TR2 acceptance tests for Trust Engine evidence weighting."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from aqelyn.conventions import ActorRef, new_id
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord
from aqelyn.trust import (
    InMemorySourceReliabilityRegistry,
    SourceReliability,
    TrustConfig,
    TrustEngine,
)

SYS = ActorRef(actor_type="system", actor_id="trust-test")


def _evidence(
    *,
    evidence_id: str | None = None,
    source_id: str | None = None,
    evidence_type: str = "config.snapshot",
    method: str = "scanner",
    collected_at: datetime,
    confidence: float = 0.8,
) -> EvidenceRecord:
    return EvidenceRecord(
        id=evidence_id or new_id("evd"),
        evidence_type=evidence_type,
        schema_version=1,
        subject=Subject(object_ids=[new_id("obj")]),
        collected_at=collected_at,
        recorded_at=collected_at,
        collector=SYS,
        source_id=source_id or new_id("src"),
        method=method,
        content={"k": "v"},
        content_hash="sha256:test",
        confidence=confidence,
        seq=1,
        prev_hash=None,
        record_hash="sha256:record",
    )


async def test_trust_evidence_weight() -> None:
    now = datetime(2026, 7, 12, tzinfo=UTC)
    source_id = new_id("src")
    registry = InMemorySourceReliabilityRegistry()
    await registry.set(
        SourceReliability(
            key=source_id,
            weight=0.8,
            rationale="calibrated source",
            set_by=SYS,
            set_at=now,
        )
    )
    engine = TrustEngine(
        config=TrustConfig(
            type_weights={"config.snapshot": 0.5},
            half_life_days=90,
            recency_floor=0.1,
        ),
        registry=registry,
    )

    contribution = await engine.weigh_evidence(
        _evidence(source_id=source_id, collected_at=now, confidence=0.75),
        now=now,
    )

    assert contribution.evidence_id.startswith("evd_")
    assert contribution.source_reliability == 0.8
    assert contribution.type_weight == 0.5
    assert contribution.recency_factor == 1.0
    assert contribution.collector_confidence == 0.75
    assert contribution.age_days == 0.0
    assert contribution.weight == 0.8 * 0.5 * 1.0 * 0.75
    assert 0.0 <= contribution.weight <= 1.0


async def test_trust_recency_decay() -> None:
    now = datetime(2026, 7, 12, tzinfo=UTC)
    source_id = new_id("src")
    registry = InMemorySourceReliabilityRegistry()
    await registry.set(
        SourceReliability(
            key=source_id,
            weight=1.0,
            rationale="trusted source",
            set_by=SYS,
            set_at=now,
        )
    )
    engine = TrustEngine(
        config=TrustConfig(half_life_days=10, recency_floor=0.2),
        registry=registry,
    )
    recent = await engine.weigh_evidence(
        _evidence(source_id=source_id, collected_at=now),
        now=now,
    )
    one_half_life = await engine.weigh_evidence(
        _evidence(source_id=source_id, collected_at=now - timedelta(days=10)),
        now=now,
    )
    old = await engine.weigh_evidence(
        _evidence(source_id=source_id, collected_at=now - timedelta(days=100)),
        now=now,
    )

    assert recent.recency_factor == 1.0
    assert math.isclose(one_half_life.recency_factor, 0.5)
    assert old.recency_factor == 0.2
    assert recent.weight > one_half_life.weight > old.weight
    assert old.weight > 0.0
