"""Threat Intelligence Fusion engine (EA-0014 T1)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from aqelyn.conventions import ActorRef
from aqelyn.conventions.errors import MalformedFeedRecord
from aqelyn.graph import InMemoryKnowledgeGraph, KnowledgeGraph
from aqelyn.objects import ObjectQuery, ObjectStore
from aqelyn.threat.confidence import score_confidence
from aqelyn.threat.correlate import correlate
from aqelyn.threat.correlate import explain as explain_match
from aqelyn.threat.models import (
    FeedRecord,
    FusionConfig,
    MatchReport,
    QuarantinedFeedRecord,
    ThreatIndicator,
    ThreatMatch,
)
from aqelyn.threat.normalize import (
    ensure_threat_object_types,
    indicator_to_object,
    normalize_record,
    object_to_indicator,
    quarantine_time,
)
from aqelyn.threat.registry import InMemoryThreatSourceRegistry, ThreatSourceRegistry

_ACTOR = ActorRef(actor_type="system", actor_id="threat_fusion_engine")


class ThreatFusionEngine:
    def __init__(
        self,
        object_store: ObjectStore,
        *,
        config: FusionConfig | None = None,
        actor: ActorRef | None = None,
        source_registry: ThreatSourceRegistry | None = None,
        graph: KnowledgeGraph | None = None,
    ) -> None:
        self.object_store = object_store
        self.config = config or FusionConfig()
        self.actor = actor or _ACTOR
        self.source_registry = source_registry or InMemoryThreatSourceRegistry()
        self.graph = graph or InMemoryKnowledgeGraph(object_store)
        self._quarantine: list[QuarantinedFeedRecord] = []
        ensure_threat_object_types(object_store)

    @property
    def quarantine(self) -> tuple[QuarantinedFeedRecord, ...]:
        return tuple(self._quarantine)

    async def ingest(
        self,
        records: Sequence[FeedRecord],
        *,
        tenant_id: str | None,
    ) -> list[ThreatIndicator]:
        indicators: list[ThreatIndicator] = []
        for record in records:
            try:
                indicator = normalize_record(record, tenant_id=tenant_id, config=self.config)
            except MalformedFeedRecord as exc:
                if not self.config.quarantine_on_malformed:
                    raise
                self._quarantine.append(
                    QuarantinedFeedRecord(
                        record=record,
                        reason=exc.message,
                        quarantined_at=quarantine_time(),
                    )
                )
                continue
            saved = await self.object_store.upsert(indicator_to_object(indicator, by=self.actor))
            indicators.append(object_to_indicator(saved))
        return indicators

    def explain(self, item: ThreatIndicator | ThreatMatch) -> dict[str, object]:
        if isinstance(item, ThreatMatch):
            return explain_match(item)
        indicator = item
        return {
            "indicator_id": indicator.id,
            "indicator_type": indicator.indicator_type,
            "value": indicator.value,
            "confidence": indicator.confidence,
            "sources": [source.model_dump(mode="json") for source in indicator.sources],
            "reason": (
                "Indicator was normalized from handed-in feed data and cataloged by natural key."
            ),
        }

    async def score_confidence(
        self, indicator: ThreatIndicator, *, now: datetime | None = None
    ) -> float:
        return await score_confidence(
            indicator,
            registry=self.source_registry,
            config=self.config,
            now=now,
        )

    async def correlate(
        self,
        *,
        tenant_id: str | None,
        scope: ObjectQuery | None = None,
        now: datetime | None = None,
    ) -> MatchReport:
        return await correlate(
            object_store=self.object_store,
            graph=self.graph,
            tenant_id=tenant_id,
            scope=scope,
            config=self.config.correlation,
            min_match_confidence=self.config.min_match_confidence,
            now=now,
        )
