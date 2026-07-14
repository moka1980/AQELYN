"""Threat confidence scoring backed by the Trust Engine (EA-0014 T2)."""

from __future__ import annotations

from datetime import datetime

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.events import Subject
from aqelyn.evidence import EvidenceRecord
from aqelyn.threat.models import FusionConfig, ThreatIndicator
from aqelyn.threat.registry import ThreatSourceRegistry
from aqelyn.trust import (
    InMemorySourceReliabilityRegistry,
    SourceReliability,
    TrustConfig,
    TrustEngine,
)

_ACTOR = ActorRef(actor_type="system", actor_id="threat_fusion_engine")
_EVIDENCE_TYPE = "threat.indicator/v1"


async def score_confidence(
    indicator: ThreatIndicator,
    *,
    registry: ThreatSourceRegistry,
    config: FusionConfig | None = None,
    now: datetime | None = None,
) -> float:
    selected_config = config or FusionConfig()
    trust_registry = InMemorySourceReliabilityRegistry(
        default_reliability=0.5,
        default_set_by=_ACTOR,
        default_set_at=now,
    )
    evidence: list[EvidenceRecord] = []
    for source in sorted(indicator.sources, key=lambda item: item.source_id):
        threat_source = await registry.get(source.source_id)
        await trust_registry.set(
            SourceReliability(
                key=source.source_id,
                weight=threat_source.reliability,
                rationale=str(threat_source.meta.get("rationale", "threat source reliability")),
                set_by=threat_source.set_by,
                set_at=threat_source.set_at,
                version=threat_source.version,
            )
        )
        evidence.append(
            _source_to_evidence(
                indicator,
                source_id=source.source_id,
                method=source.method,
                observed_at=source.observed_at,
                evidence_id=source.evidence_id,
            )
        )
    trust_engine = TrustEngine(
        config=TrustConfig(
            type_weights={_EVIDENCE_TYPE: 1.0},
            half_life_days=selected_config.recency_half_life_days,
        ),
        registry=trust_registry,
    )
    subject_ref = indicator.id or f"{indicator.indicator_type}:{indicator.value}"
    assessment = await trust_engine.assess(subject_ref, evidence, now=now)
    return assessment.score


def _source_to_evidence(
    indicator: ThreatIndicator,
    *,
    source_id: str,
    method: str,
    observed_at: datetime,
    evidence_id: str | None,
) -> EvidenceRecord:
    recorded_at = utc_now()
    object_ids = [indicator.id] if indicator.id else []
    return EvidenceRecord(
        id=evidence_id or new_id("evd"),
        tenant_id=indicator.tenant_id,
        evidence_type=_EVIDENCE_TYPE,
        schema_version=1,
        subject=Subject(object_ids=object_ids),
        collected_at=observed_at,
        recorded_at=recorded_at,
        collector=_ACTOR,
        source_id=source_id,
        method=method,
        content={
            "indicator_type": indicator.indicator_type,
            "value": indicator.value,
            "confidence": indicator.confidence,
        },
        content_hash="synthetic-threat-confidence-input",
        confidence=indicator.confidence,
        labels={"module": "EA-0014", "kind": "threat_confidence"},
        seq=0,
        prev_hash=None,
        record_hash="synthetic-threat-confidence-input",
    )
