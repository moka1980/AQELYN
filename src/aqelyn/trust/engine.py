"""Trust Engine reference computations (EA-0006 TR2)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, datetime

from aqelyn.evidence import EvidenceRecord
from aqelyn.trust.models import (
    Decision,
    EvidenceContribution,
    TrustAssessment,
    TrustConfig,
    TrustLevel,
)
from aqelyn.trust.registry import InMemorySourceReliabilityRegistry, SourceReliabilityRegistry

SECONDS_PER_DAY = 86_400.0


class TrustEngine:
    def __init__(
        self,
        *,
        config: TrustConfig | None = None,
        registry: SourceReliabilityRegistry | None = None,
    ) -> None:
        self.config = config or TrustConfig()
        self.registry = registry or InMemorySourceReliabilityRegistry(
            default_reliability=self.config.default_reliability
        )

    async def weigh_evidence(
        self, evidence: EvidenceRecord, *, now: datetime | None = None
    ) -> EvidenceContribution:
        computed_at = _as_utc(now or datetime.now(UTC))
        collected_at = _as_utc(evidence.collected_at)
        age_days = max((computed_at - collected_at).total_seconds() / SECONDS_PER_DAY, 0.0)
        source_reliability = (
            await self.registry.get(source_id=evidence.source_id, method=evidence.method)
        ).weight
        type_weight = self.config.type_weights.get(evidence.evidence_type, 1.0)
        recency_factor = _clamp(
            0.5 ** (age_days / self.config.half_life_days),
            low=self.config.recency_floor,
            high=1.0,
        )
        collector_confidence = _clamp(evidence.confidence)
        weight = _clamp(source_reliability * type_weight * recency_factor * collector_confidence)
        return EvidenceContribution(
            evidence_id=evidence.id,
            weight=weight,
            source_reliability=source_reliability,
            type_weight=type_weight,
            recency_factor=recency_factor,
            collector_confidence=collector_confidence,
            age_days=age_days,
        )

    async def assess(
        self,
        subject_ref: str,
        evidence: Sequence[EvidenceRecord],
        *,
        now: datetime | None = None,
    ) -> TrustAssessment:
        computed_at = _as_utc(now or datetime.now(UTC))
        ordered_evidence = sorted(evidence, key=lambda item: item.id)
        contributions = [
            await self.weigh_evidence(record, now=computed_at) for record in ordered_evidence
        ]
        if not contributions:
            return TrustAssessment(
                subject_ref=subject_ref,
                score=0.0,
                level="low",
                method="noisy_or/v1",
                contributions=[],
                reason="low confidence: no evidence was provided.",
                no_evidence=True,
                computed_at=computed_at,
            )
        score = _clamp(1.0 - math.prod(1.0 - contribution.weight for contribution in contributions))
        level = _level(score, self.config)
        return TrustAssessment(
            subject_ref=subject_ref,
            score=score,
            level=level,
            method="noisy_or/v1",
            contributions=contributions,
            reason=_reason(level, contributions),
            no_evidence=False,
            computed_at=computed_at,
        )

    async def decide(
        self, assessment: TrustAssessment, *, threshold: float, action: str
    ) -> Decision:
        passed = assessment.score >= threshold
        decision = action if passed else f"defer_{action}"
        comparison = "meets" if passed else "does not meet"
        return Decision(
            decision=decision,
            score=assessment.score,
            threshold=threshold,
            rationale=(
                f"{assessment.level} confidence score {assessment.score:.3f} "
                f"{comparison} threshold {threshold:.3f} for {action}."
            ),
        )

    def explain(self, assessment: TrustAssessment) -> list[dict[str, object]]:
        return [
            {
                "evidence_id": contribution.evidence_id,
                "weight": contribution.weight,
                "source_reliability": contribution.source_reliability,
                "type_weight": contribution.type_weight,
                "recency_factor": contribution.recency_factor,
                "collector_confidence": contribution.collector_confidence,
                "age_days": contribution.age_days,
                "method": assessment.method,
            }
            for contribution in assessment.contributions
        ]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _clamp(value: float, *, low: float = 0.0, high: float = 1.0) -> float:
    return min(max(value, low), high)


def _level(score: float, config: TrustConfig) -> TrustLevel:
    if score < config.thresholds.low:
        return "low"
    if score < config.thresholds.high:
        return "medium"
    return "high"


def _reason(level: TrustLevel, contributions: Sequence[EvidenceContribution]) -> str:
    count = len(contributions)
    total = "record" if count == 1 else "records"
    strongest = max(contributions, key=lambda contribution: contribution.weight)
    return (
        f"{level} confidence: {count} evidence {total} assessed; "
        f"strongest contribution {strongest.evidence_id} weighs {strongest.weight:.3f}."
    )
