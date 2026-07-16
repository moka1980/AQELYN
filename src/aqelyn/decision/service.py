"""Decision Intelligence AQService wrapper and events (EA-0020 E5)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import DecisionConfigInvalid, EvidenceNotFound, StoreUnavailable
from aqelyn.decision.models import ClaimRef, DecisionConfig
from aqelyn.decision.recommend import DecisionIntelligenceEngine
from aqelyn.decision.store import ModelVersionStore, RecommendationStore
from aqelyn.events.registry import EventTypeRegistry
from aqelyn.evidence import EvidenceStore
from aqelyn.kernel.service import HealthStatus
from aqelyn.trust.models import TrustConfig

DECISION_EVENTS: dict[str, int] = {
    "aqelyn.decision.recommendation_generated": 1,
    "aqelyn.decision.decision_recorded": 1,
    "aqelyn.decision.model_promoted": 1,
}


def register_decision_events(registry: EventTypeRegistry) -> None:
    for event_type, schema_version in DECISION_EVENTS.items():
        registry.register(event_type, schema_version, None)


class EmptyDecisionClaimSource:
    async def claims_for(self, *, subject_ref: str, tenant_id: str | None) -> Sequence[ClaimRef]:
        return []


class DecisionIntelligenceService:
    def __init__(
        self,
        engine: DecisionIntelligenceEngine,
        *,
        recommendation_store: RecommendationStore,
        model_store: ModelVersionStore,
        evidence_store: EvidenceStore,
        close_recommendation_store: Callable[[], Awaitable[None]] | None = None,
        close_model_store: Callable[[], Awaitable[None]] | None = None,
        dependencies: Sequence[str] = (
            "trust_engine",
            "mission_engine",
            "risk_engine",
            "soc_engine",
            "workflow_engine",
        ),
        critical: bool = True,
    ) -> None:
        self.engine = engine
        self.recommendation_store = recommendation_store
        self.model_store = model_store
        self.evidence_store = evidence_store
        self._close_recommendation_store = close_recommendation_store
        self._close_model_store = close_model_store
        self._dependencies = tuple(dependencies)
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return "decision_engine"

    @property
    def dependencies(self) -> Sequence[str]:
        return self._dependencies

    @property
    def critical(self) -> bool:
        return self._critical

    async def start(self) -> None:
        await self._check_available()
        self._started = True

    async def stop(self) -> None:
        try:
            if self._close_model_store is not None:
                await self._close_model_store()
            if self._close_recommendation_store is not None:
                await self._close_recommendation_store()
        finally:
            self._started = False

    async def health(self) -> HealthStatus:
        dependencies: dict[str, str] = {}
        try:
            self._check_config()
            await self._check_recommendation_store()
            dependencies["recommendation_store"] = "healthy"
            await self._check_model_store()
            dependencies["model_store"] = "healthy"
            await self._check_evidence_store()
            dependencies["evidence_store"] = "healthy"
            await self._check_trust_engine()
            dependencies["trust_engine"] = "healthy"
            self._check_workflow_engine()
            dependencies["workflow_engine"] = "healthy"
            self._check_claim_source()
            dependencies["claim_source"] = "healthy"
        except DecisionConfigInvalid as exc:
            return HealthStatus(
                status="unavailable",
                ready=False,
                detail=exc.message,
                dependencies=dependencies,
            )
        except StoreUnavailable as exc:
            return HealthStatus(
                status="unavailable",
                ready=False,
                detail=exc.message,
                dependencies=dependencies,
            )
        except Exception as exc:
            return HealthStatus(
                status="unavailable",
                ready=False,
                detail=str(exc),
                dependencies=dependencies,
            )

        if not self._started:
            return HealthStatus(
                status="degraded",
                ready=False,
                detail="service not started",
                dependencies=dependencies,
            )
        return HealthStatus(status="healthy", ready=True, dependencies=dependencies)

    async def _check_available(self) -> None:
        self._check_config()
        await self._check_recommendation_store()
        await self._check_model_store()
        await self._check_evidence_store()
        await self._check_trust_engine()
        self._check_workflow_engine()
        self._check_claim_source()

    def _check_config(self) -> None:
        DecisionConfig.model_validate(self.engine.config.model_dump(mode="json"))

    async def _check_recommendation_store(self) -> None:
        try:
            await self.recommendation_store.get(new_id("rec"))
        except Exception as exc:
            raise StoreUnavailable(f"decision recommendation store unavailable: {exc}") from exc

    async def _check_model_store(self) -> None:
        try:
            await self.model_store.get(1)
        except Exception as exc:
            raise StoreUnavailable(f"decision model store unavailable: {exc}") from exc

    async def _check_evidence_store(self) -> None:
        try:
            await self.evidence_store.verify(new_id("evd"))
        except EvidenceNotFound:
            return
        except Exception as exc:
            raise StoreUnavailable(f"decision evidence store unavailable: {exc}") from exc

    async def _check_trust_engine(self) -> None:
        trust_engine = self.engine.trust_engine
        if trust_engine is None:
            raise StoreUnavailable("decision trust engine unavailable")
        config = getattr(trust_engine, "config", None)
        registry = getattr(trust_engine, "registry", None)
        try:
            if config is not None:
                TrustConfig.model_validate(config.model_dump(mode="json"))
            if registry is not None:
                await registry.get()
        except Exception as exc:
            raise StoreUnavailable(f"decision trust engine unavailable: {exc}") from exc

    def _check_workflow_engine(self) -> None:
        if self.engine.workflow_engine is None:
            raise StoreUnavailable("decision workflow engine unavailable")

    def _check_claim_source(self) -> None:
        if self.engine.claim_source is None:
            raise StoreUnavailable("decision claim source unavailable")
