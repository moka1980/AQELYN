"""Trust Engine reference computations (EA-0006 TR2)."""

from __future__ import annotations

from datetime import UTC, datetime

from aqelyn.evidence import EvidenceRecord
from aqelyn.trust.models import EvidenceContribution, TrustConfig
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


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _clamp(value: float, *, low: float = 0.0, high: float = 1.0) -> float:
    return min(max(value, low), high)
