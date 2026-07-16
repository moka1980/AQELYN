"""Predictive Analytics & Forecasting AQService wrapper and events (EA-0021 P6)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import EvidenceNotFound, ForecastConfigInvalid, StoreUnavailable
from aqelyn.events.registry import EventTypeRegistry
from aqelyn.evidence import EvidenceStore
from aqelyn.forecast.engine import ForecastingEngine
from aqelyn.forecast.models import ForecastConfig
from aqelyn.forecast.store import ForecastStore, PredictionModelStore
from aqelyn.forecast.trend import MetricObservation
from aqelyn.kernel.service import HealthStatus
from aqelyn.trust.models import TrustConfig

if TYPE_CHECKING:
    from aqelyn.lake.service import DataLakeService
    from aqelyn.risk.engine import RiskIntelligenceEngine

FORECAST_EVENTS: dict[str, int] = {
    "aqelyn.forecast.generated": 1,
    "aqelyn.forecast.scored": 1,
    "aqelyn.forecast.trend_detected": 1,
}


def register_forecast_events(registry: EventTypeRegistry) -> None:
    for event_type, schema_version in FORECAST_EVENTS.items():
        registry.register(event_type, schema_version, None)


class EmptyMetricHistorySource:
    async def history(
        self,
        *,
        metric: str,
        window_days: int,
        tenant_id: str | None,
    ) -> Sequence[MetricObservation]:
        _ = metric, window_days, tenant_id
        return []


class EmptyActualValueSource:
    async def actual(
        self,
        *,
        metric: str,
        at: datetime,
        tenant_id: str | None,
    ) -> MetricObservation | None:
        _ = metric, at, tenant_id
        return None


class ForecastingService:
    def __init__(
        self,
        engine: ForecastingEngine,
        *,
        forecast_store: ForecastStore,
        model_store: PredictionModelStore,
        evidence_store: EvidenceStore,
        lake_service: DataLakeService | None,
        risk_engine: RiskIntelligenceEngine | None,
        close_forecast_store: Callable[[], Awaitable[None]] | None = None,
        close_model_store: Callable[[], Awaitable[None]] | None = None,
        dependencies: Sequence[str] = ("datalake_engine", "trust_engine", "risk_engine"),
        critical: bool = True,
    ) -> None:
        self.engine = engine
        self.forecast_store = forecast_store
        self.model_store = model_store
        self.evidence_store = evidence_store
        self.lake_service = lake_service
        self.risk_engine = risk_engine
        self._close_forecast_store = close_forecast_store
        self._close_model_store = close_model_store
        self._dependencies = tuple(dependencies)
        self._critical = critical
        self._started = False

    @property
    def name(self) -> str:
        return "forecast_engine"

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
            if self._close_forecast_store is not None:
                await self._close_forecast_store()
        finally:
            self._started = False

    async def health(self) -> HealthStatus:
        dependencies: dict[str, str] = {}
        try:
            self._check_config()
            await self._check_forecast_store()
            dependencies["forecast_store"] = "healthy"
            await self._check_model_store()
            dependencies["model_store"] = "healthy"
            await self._check_evidence_store()
            dependencies["evidence_store"] = "healthy"
            await self._check_trust_engine()
            dependencies["trust_engine"] = "healthy"
            self._check_lake_service()
            dependencies["lake_service"] = "healthy"
            self._check_risk_engine()
            dependencies["risk_engine"] = "healthy"
            self._check_history_source()
            dependencies["history_source"] = "healthy"
            self._check_actual_source()
            dependencies["actual_source"] = "healthy"
            self._check_evidence_recorder()
            dependencies["evidence_recorder"] = "healthy"
        except ForecastConfigInvalid as exc:
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
        await self._check_forecast_store()
        await self._check_model_store()
        await self._check_evidence_store()
        await self._check_trust_engine()
        self._check_lake_service()
        self._check_risk_engine()
        self._check_history_source()
        self._check_actual_source()
        self._check_evidence_recorder()

    def _check_config(self) -> None:
        ForecastConfig.model_validate(self.engine.config.model_dump(mode="json"))

    async def _check_forecast_store(self) -> None:
        try:
            await self.forecast_store.get(new_id("fct"), tenant_id=None)
        except Exception as exc:
            raise StoreUnavailable(f"forecast store unavailable: {exc}") from exc

    async def _check_model_store(self) -> None:
        try:
            await self.model_store.get(new_id("pdm"), tenant_id=None)
        except Exception as exc:
            raise StoreUnavailable(f"forecast model store unavailable: {exc}") from exc

    async def _check_evidence_store(self) -> None:
        try:
            await self.evidence_store.verify(new_id("evd"))
        except EvidenceNotFound:
            return
        except Exception as exc:
            raise StoreUnavailable(f"forecast evidence store unavailable: {exc}") from exc

    async def _check_trust_engine(self) -> None:
        trust_engine = self.engine.trust_engine
        if trust_engine is None:
            raise StoreUnavailable("forecast trust engine unavailable")
        config = getattr(trust_engine, "config", None)
        registry = getattr(trust_engine, "registry", None)
        try:
            if config is not None:
                TrustConfig.model_validate(config.model_dump(mode="json"))
            if registry is not None:
                await registry.get()
        except Exception as exc:
            raise StoreUnavailable(f"forecast trust engine unavailable: {exc}") from exc

    def _check_lake_service(self) -> None:
        if self.lake_service is None:
            raise StoreUnavailable("forecast lake service unavailable")

    def _check_risk_engine(self) -> None:
        if self.risk_engine is None:
            raise StoreUnavailable("forecast risk engine unavailable")

    def _check_history_source(self) -> None:
        if not callable(getattr(self.engine.history_source, "history", None)):
            raise StoreUnavailable("forecast history source unavailable")

    def _check_actual_source(self) -> None:
        if not callable(getattr(self.engine.actual_source, "actual", None)):
            raise StoreUnavailable("forecast actual source unavailable")

    def _check_evidence_recorder(self) -> None:
        if not callable(getattr(self.engine.evidence_recorder, "add", None)):
            raise StoreUnavailable("forecast evidence recorder unavailable")
