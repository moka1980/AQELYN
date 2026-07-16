"""In-memory forecast stores (EA-0021 P2)."""

from __future__ import annotations

import copy
from datetime import datetime

from aqelyn.conventions import ActorRef, utc_now
from aqelyn.conventions.errors import (
    ForecastNotFound,
    OptimisticConcurrencyConflict,
    TenantScopeRequired,
)
from aqelyn.forecast.models import Forecast, Method, PredictionModel
from aqelyn.forecast.store import (
    validate_forecast_id,
    validate_inactive_prediction_model,
    validate_limit,
    validate_method,
    validate_model_id,
    validate_prediction_model,
    validate_promotion_actor,
    validate_promotion_evidence_id,
    validate_promotion_reason,
    validate_replayable_forecast,
    validate_tenant,
)


class InMemoryForecastStore:
    def __init__(self, *, mode: str = "local") -> None:
        self.mode = mode
        self._forecasts: dict[str, Forecast] = {}

    async def put(self, forecast: Forecast) -> Forecast:
        stored = validate_replayable_forecast(forecast)
        if stored.id in self._forecasts:
            raise OptimisticConcurrencyConflict(f"forecast already exists: {stored.id}")
        self._forecasts[stored.id] = stored.model_copy(deep=True)
        return copy.deepcopy(stored)

    async def get(self, forecast_id: str, *, tenant_id: str | None = None) -> Forecast | None:
        validate_forecast_id(forecast_id)
        tenant_id = validate_tenant(tenant_id)
        forecast = self._forecasts.get(forecast_id)
        if forecast is None or not self._visible(forecast.tenant_id, tenant_id):
            return None
        return copy.deepcopy(forecast)

    async def due_for_scoring(self, *, tenant_id: str | None, now: datetime) -> list[Forecast]:
        tenant_id = validate_tenant(tenant_id)
        rows = [
            copy.deepcopy(row)
            for row in self._forecasts.values()
            if self._visible(row.tenant_id, tenant_id)
            and row.outcome is None
            and row.resolves_at <= now
        ]
        rows.sort(key=lambda row: (row.resolves_at, row.id))
        return rows

    async def query(
        self, *, tenant_id: str | None, metric: str | None = None, limit: int = 100
    ) -> list[Forecast]:
        tenant_id = validate_tenant(tenant_id)
        validate_limit(limit)
        if self.mode == "enterprise" and tenant_id is None:
            raise TenantScopeRequired("forecast query must be tenant-scoped")
        rows = [
            copy.deepcopy(row)
            for row in self._forecasts.values()
            if self._visible(row.tenant_id, tenant_id) and (metric is None or row.metric == metric)
        ]
        rows.sort(key=lambda row: (row.issued_at, row.id))
        return rows[:limit]

    def _visible(self, row_tenant_id: str | None, requested_tenant_id: str | None) -> bool:
        if self.mode == "local" and row_tenant_id is not None:
            return False
        return requested_tenant_id is None or row_tenant_id == requested_tenant_id


class InMemoryPredictionModelStore:
    def __init__(self, *, mode: str = "local") -> None:
        self.mode = mode
        self._models: dict[str, PredictionModel] = {}
        self._by_version: dict[tuple[str | None, str, int], str] = {}

    async def put(self, model: PredictionModel) -> PredictionModel:
        stored = validate_inactive_prediction_model(model)
        key = (stored.tenant_id, stored.method, stored.version)
        if stored.id in self._models or key in self._by_version:
            raise OptimisticConcurrencyConflict(
                f"prediction model version already exists: {stored.method} v{stored.version}"
            )
        self._models[stored.id] = stored.model_copy(deep=True)
        self._by_version[key] = stored.id
        return copy.deepcopy(stored)

    async def get(self, model_id: str, *, tenant_id: str | None = None) -> PredictionModel | None:
        validate_model_id(model_id)
        tenant_id = validate_tenant(tenant_id)
        model = self._models.get(model_id)
        if model is None or not self._visible(model.tenant_id, tenant_id):
            return None
        return copy.deepcopy(model)

    async def active(self, method: Method, *, tenant_id: str | None = None) -> PredictionModel:
        method = validate_method(method)
        tenant_id = validate_tenant(tenant_id)
        if self.mode == "enterprise" and tenant_id is None:
            raise TenantScopeRequired("active prediction model must be tenant-scoped")
        candidates = [
            model
            for model in self._models.values()
            if self._visible(model.tenant_id, tenant_id) and model.method == method and model.active
        ]
        if not candidates:
            raise ForecastNotFound(f"active prediction model not found: {method}")
        selected = max(candidates, key=lambda model: model.version)
        return copy.deepcopy(selected)

    async def promote(
        self,
        model_id: str,
        *,
        by: ActorRef,
        reason: str,
        evidence_id: str,
        tenant_id: str | None = None,
    ) -> PredictionModel:
        validate_model_id(model_id)
        tenant_id = validate_tenant(tenant_id)
        by = validate_promotion_actor(by)
        validate_promotion_reason(reason)
        evidence_id = validate_promotion_evidence_id(evidence_id)
        existing = self._models.get(model_id)
        if existing is None or not self._visible(existing.tenant_id, tenant_id):
            raise ForecastNotFound(f"prediction model not found: {model_id}")
        for selected_id, model in list(self._models.items()):
            if model.tenant_id == existing.tenant_id and model.method == existing.method:
                self._models[selected_id] = model.model_copy(update={"active": False}, deep=True)
        promoted = existing.model_copy(
            update={
                "active": True,
                "promoted_by": by,
                "promoted_at": utc_now(),
                "evidence_id": evidence_id,
            },
            deep=True,
        )
        self._models[model_id] = validate_prediction_model(promoted)
        return copy.deepcopy(self._models[model_id])

    async def query(
        self, *, tenant_id: str | None, method: Method | None = None, limit: int = 100
    ) -> list[PredictionModel]:
        tenant_id = validate_tenant(tenant_id)
        validate_limit(limit)
        if self.mode == "enterprise" and tenant_id is None:
            raise TenantScopeRequired("prediction model query must be tenant-scoped")
        if method is not None:
            method = validate_method(method)
        rows = [
            copy.deepcopy(row)
            for row in self._models.values()
            if self._visible(row.tenant_id, tenant_id) and (method is None or row.method == method)
        ]
        rows.sort(key=lambda row: (row.method, row.version, row.id))
        return rows[:limit]

    def _visible(self, row_tenant_id: str | None, requested_tenant_id: str | None) -> bool:
        if self.mode == "local" and row_tenant_id is not None:
            return False
        return requested_tenant_id is None or row_tenant_id == requested_tenant_id
