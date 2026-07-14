"""Threat Intelligence Fusion engine (EA-0014 T1)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from aqelyn.conventions import ActorRef
from aqelyn.conventions.errors import MalformedFeedRecord
from aqelyn.objects import ObjectStore
from aqelyn.threat.confidence import score_confidence
from aqelyn.threat.models import FeedRecord, FusionConfig, QuarantinedFeedRecord, ThreatIndicator
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
    ) -> None:
        self.object_store = object_store
        self.config = config or FusionConfig()
        self.actor = actor or _ACTOR
        self.source_registry = source_registry or InMemoryThreatSourceRegistry()
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

    def explain(self, indicator: ThreatIndicator) -> dict[str, object]:
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
