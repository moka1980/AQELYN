"""TR3 acceptance tests for Trust Engine assessment, decision, and explanation."""

from __future__ import annotations

from datetime import UTC, datetime

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
NOW = datetime(2026, 7, 12, tzinfo=UTC)


def _evidence(
    *,
    evidence_id: str | None = None,
    source_id: str | None = None,
    evidence_type: str = "config.snapshot",
    method: str = "scanner",
    confidence: float = 1.0,
) -> EvidenceRecord:
    return EvidenceRecord(
        id=evidence_id or new_id("evd"),
        evidence_type=evidence_type,
        schema_version=1,
        subject=Subject(object_ids=[new_id("obj")]),
        collected_at=NOW,
        recorded_at=NOW,
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


async def _engine_with_source(source_id: str, weight: float) -> TrustEngine:
    registry = InMemorySourceReliabilityRegistry()
    await registry.set(
        SourceReliability(
            key=source_id,
            weight=weight,
            rationale="calibrated source",
            set_by=SYS,
            set_at=NOW,
        )
    )
    return TrustEngine(registry=registry)


async def test_trust_deterministic() -> None:
    source_id = new_id("src")
    engine = await _engine_with_source(source_id, 0.7)
    evidence = [
        _evidence(evidence_id=new_id("evd"), source_id=source_id),
        _evidence(evidence_id=new_id("evd"), source_id=source_id, confidence=0.5),
    ]

    first = await engine.assess("claim:device", evidence, now=NOW)
    second = await engine.assess("claim:device", list(reversed(evidence)), now=NOW)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


async def test_trust_score_bounded() -> None:
    source_id = new_id("src")
    engine = await _engine_with_source(source_id, 1.0)

    assessment = await engine.assess(
        "claim:bounded",
        [_evidence(source_id=source_id, confidence=1.0) for _ in range(3)],
        now=NOW,
    )

    assert assessment.score == 1.0
    assert 0.0 <= assessment.score <= 1.0


async def test_trust_monotonic() -> None:
    source_id = new_id("src")
    engine = await _engine_with_source(source_id, 0.4)
    first = _evidence(source_id=source_id)
    second = _evidence(source_id=source_id)

    one = await engine.assess("claim:mono", [first], now=NOW)
    two = await engine.assess("claim:mono", [first, second], now=NOW)

    assert two.score >= one.score


async def test_trust_explainable() -> None:
    source_id = new_id("src")
    engine = await _engine_with_source(source_id, 0.6)
    evidence = _evidence(source_id=source_id)

    assessment = await engine.assess("claim:explain", [evidence], now=NOW)
    explanation = engine.explain(assessment)

    assert assessment.method == "noisy_or/v1"
    assert assessment.reason.startswith(f"{assessment.level} confidence:")
    assert assessment.contributions[0].evidence_id == evidence.id
    assert explanation == [
        {
            "evidence_id": evidence.id,
            "weight": assessment.contributions[0].weight,
            "source_reliability": 0.6,
            "type_weight": 1.0,
            "recency_factor": 1.0,
            "collector_confidence": 1.0,
            "age_days": 0.0,
            "method": "noisy_or/v1",
        }
    ]


async def test_trust_level_mapping() -> None:
    low_source = new_id("src")
    medium_source = new_id("src")
    high_source = new_id("src")
    registry = InMemorySourceReliabilityRegistry()
    for source_id, weight in ((low_source, 0.2), (medium_source, 0.5), (high_source, 0.8)):
        await registry.set(
            SourceReliability(
                key=source_id,
                weight=weight,
                rationale="level fixture",
                set_by=SYS,
                set_at=NOW,
            )
        )
    engine = TrustEngine(config=TrustConfig(), registry=registry)

    low = await engine.assess("claim:low", [_evidence(source_id=low_source)], now=NOW)
    medium = await engine.assess("claim:medium", [_evidence(source_id=medium_source)], now=NOW)
    high = await engine.assess("claim:high", [_evidence(source_id=high_source)], now=NOW)

    assert low.level == "low"
    assert medium.level == "medium"
    assert high.level == "high"


async def test_trust_no_side_effects() -> None:
    source_id = new_id("src")
    engine = await _engine_with_source(source_id, 0.7)
    evidence = _evidence(source_id=source_id)
    evidence_before = evidence.model_dump(mode="json")
    registry_before = [entry.model_dump(mode="json") for entry in await engine.registry.list()]

    await engine.assess("claim:pure", [evidence], now=NOW)

    assert evidence.model_dump(mode="json") == evidence_before
    assert [
        entry.model_dump(mode="json") for entry in await engine.registry.list()
    ] == registry_before


async def test_trust_decide() -> None:
    source_id = new_id("src")
    engine = await _engine_with_source(source_id, 0.8)
    assessment = await engine.assess("claim:decision", [_evidence(source_id=source_id)], now=NOW)

    passed = await engine.decide(assessment, threshold=0.7, action="auto_accept")
    failed = await engine.decide(assessment, threshold=0.9, action="auto_accept")

    assert passed.decision == "auto_accept"
    assert passed.score == assessment.score
    assert passed.threshold == 0.7
    assert "meets threshold" in passed.rationale
    assert failed.decision == "defer_auto_accept"
    assert "does not meet threshold" in failed.rationale


async def test_trust_no_evidence() -> None:
    engine = TrustEngine()

    assessment = await engine.assess("claim:empty", [], now=NOW)

    assert assessment.score == 0.0
    assert assessment.level == "low"
    assert assessment.no_evidence is True
    assert assessment.contributions == []
    assert assessment.reason == "low confidence: no evidence was provided."
