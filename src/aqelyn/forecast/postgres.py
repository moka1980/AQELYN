"""PostgreSQL forecast stores (EA-0021 P2)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import asyncpg

from aqelyn.conventions import ActorRef, utc_now
from aqelyn.conventions.errors import (
    ForecastNotFound,
    OptimisticConcurrencyConflict,
    StoreUnavailable,
    TenantScopeRequired,
)
from aqelyn.forecast.ddl import DDL
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

_FORECAST_COLS = (
    "id, tenant_id, metric, subject_ref, method, model_version, horizon_days, "
    "issued_at, resolves_at, point, interval, confidence, basis, derivation, "
    "advisory, statement, outcome"
)
_MODEL_COLS = (
    "id, tenant_id, method, params, version, promoted_by, promoted_at, active, evidence_id"
)


def _to_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _connect(url: str) -> asyncpg.Pool:
    try:
        pool = await asyncpg.create_pool(_to_dsn(url), min_size=1, max_size=5)
    except Exception as exc:
        raise StoreUnavailable(str(exc)) from exc
    assert pool is not None
    async with pool.acquire() as conn:
        await conn.execute(DDL)
    return pool


class PostgresForecastStore:
    def __init__(self, pool: asyncpg.Pool, *, mode: str = "local") -> None:
        self._pool = pool
        self.mode = mode

    @classmethod
    async def connect(cls, url: str, *, mode: str = "local") -> PostgresForecastStore:
        return cls(await _connect(url), mode=mode)

    async def close(self) -> None:
        await self._pool.close()

    async def put(self, forecast: Forecast) -> Forecast:
        stored = validate_replayable_forecast(forecast)
        async with self._pool.acquire() as conn:
            try:
                await conn.execute(
                    f"INSERT INTO aq_forecast ({_FORECAST_COLS}) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)",
                    *_forecast_args(stored),
                )
            except asyncpg.UniqueViolationError as exc:
                raise OptimisticConcurrencyConflict(
                    f"forecast already exists: {stored.id}"
                ) from exc
        return stored

    async def get(self, forecast_id: str, *, tenant_id: str | None = None) -> Forecast | None:
        validate_forecast_id(forecast_id)
        tenant_id = validate_tenant(tenant_id)
        clauses = ["id=$1"]
        args: list[Any] = [forecast_id]
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if tenant_id is not None:
            args.append(tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_FORECAST_COLS} FROM aq_forecast WHERE {' AND '.join(clauses)}",
                *args,
            )
        return None if row is None else _row_to_forecast(row)

    async def due_for_scoring(self, *, tenant_id: str | None, now: datetime) -> list[Forecast]:
        tenant_id = validate_tenant(tenant_id)
        args: list[Any] = [now]
        clauses = ["outcome IS NULL", "resolves_at <= $1"]
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if tenant_id is not None:
            args.append(tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_FORECAST_COLS} FROM aq_forecast "
                f"WHERE {' AND '.join(clauses)} ORDER BY resolves_at, id",
                *args,
            )
        return [_row_to_forecast(row) for row in rows]

    async def query(
        self, *, tenant_id: str | None, metric: str | None = None, limit: int = 100
    ) -> list[Forecast]:
        tenant_id = validate_tenant(tenant_id)
        validate_limit(limit)
        if self.mode == "enterprise" and tenant_id is None:
            raise TenantScopeRequired("forecast query must be tenant-scoped")
        args: list[Any] = []
        clauses: list[str] = []
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if tenant_id is not None:
            args.append(tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")
        if metric is not None:
            args.append(metric)
            clauses.append(f"metric = ${len(args)}")
        args.append(limit)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_FORECAST_COLS} FROM aq_forecast "
                f"{where}ORDER BY issued_at, id LIMIT ${len(args)}",
                *args,
            )
        return [_row_to_forecast(row) for row in rows]


class PostgresPredictionModelStore:
    def __init__(self, pool: asyncpg.Pool, *, mode: str = "local") -> None:
        self._pool = pool
        self.mode = mode

    @classmethod
    async def connect(cls, url: str, *, mode: str = "local") -> PostgresPredictionModelStore:
        return cls(await _connect(url), mode=mode)

    async def close(self) -> None:
        await self._pool.close()

    async def put(self, model: PredictionModel) -> PredictionModel:
        stored = validate_inactive_prediction_model(model)
        async with self._pool.acquire() as conn:
            try:
                await conn.execute(
                    "INSERT INTO aq_prediction_model "
                    "(id, tenant_key, tenant_id, method, params, version, promoted_by, "
                    "promoted_at, active, evidence_id) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
                    stored.id,
                    _tenant_key(stored.tenant_id),
                    stored.tenant_id,
                    stored.method,
                    json.dumps(stored.params),
                    stored.version,
                    _dump_json_or_none(stored.promoted_by),
                    stored.promoted_at,
                    stored.active,
                    stored.evidence_id,
                )
            except asyncpg.UniqueViolationError as exc:
                raise OptimisticConcurrencyConflict(
                    f"prediction model version already exists: {stored.method} v{stored.version}"
                ) from exc
        return stored

    async def get(self, model_id: str, *, tenant_id: str | None = None) -> PredictionModel | None:
        validate_model_id(model_id)
        tenant_id = validate_tenant(tenant_id)
        clauses = ["id=$1"]
        args: list[Any] = [model_id]
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if tenant_id is not None:
            args.append(tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_MODEL_COLS} FROM aq_prediction_model WHERE {' AND '.join(clauses)}",
                *args,
            )
        return None if row is None else _row_to_model(row)

    async def active(self, method: Method, *, tenant_id: str | None = None) -> PredictionModel:
        method = validate_method(method)
        tenant_id = validate_tenant(tenant_id)
        if self.mode == "enterprise" and tenant_id is None:
            raise TenantScopeRequired("active prediction model must be tenant-scoped")
        clauses = ["method=$1", "active=true"]
        args: list[Any] = [method]
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if tenant_id is not None:
            args.append(tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_MODEL_COLS} FROM aq_prediction_model "
                f"WHERE {' AND '.join(clauses)} ORDER BY version DESC LIMIT 1",
                *args,
            )
        if row is None:
            raise ForecastNotFound(f"active prediction model not found: {method}")
        return _row_to_model(row)

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
        async with self._pool.acquire() as conn, conn.transaction():
            clauses = ["id=$1"]
            args: list[Any] = [model_id]
            if self.mode == "local":
                clauses.append("tenant_id IS NULL")
            if tenant_id is not None:
                args.append(tenant_id)
                clauses.append(f"tenant_id = ${len(args)}")
            row = await conn.fetchrow(
                f"SELECT {_MODEL_COLS} FROM aq_prediction_model "
                f"WHERE {' AND '.join(clauses)} FOR UPDATE",
                *args,
            )
            if row is None:
                raise ForecastNotFound(f"prediction model not found: {model_id}")
            selected = _row_to_model(row)
            promoted = selected.model_copy(
                update={
                    "active": True,
                    "promoted_by": by,
                    "promoted_at": utc_now(),
                    "evidence_id": evidence_id,
                },
                deep=True,
            )
            stored = validate_prediction_model(promoted)
            await conn.execute(
                "UPDATE aq_prediction_model SET active=false WHERE tenant_key=$1 AND method=$2",
                _tenant_key(stored.tenant_id),
                stored.method,
            )
            await conn.execute(
                "UPDATE aq_prediction_model SET promoted_by=$2, promoted_at=$3, "
                "active=true, evidence_id=$4 WHERE id=$1",
                stored.id,
                _dump_json_or_none(stored.promoted_by),
                stored.promoted_at,
                stored.evidence_id,
            )
        return stored

    async def query(
        self, *, tenant_id: str | None, method: Method | None = None, limit: int = 100
    ) -> list[PredictionModel]:
        tenant_id = validate_tenant(tenant_id)
        validate_limit(limit)
        if self.mode == "enterprise" and tenant_id is None:
            raise TenantScopeRequired("prediction model query must be tenant-scoped")
        args: list[Any] = []
        clauses: list[str] = []
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if tenant_id is not None:
            args.append(tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")
        if method is not None:
            args.append(validate_method(method))
            clauses.append(f"method = ${len(args)}")
        args.append(limit)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_MODEL_COLS} FROM aq_prediction_model "
                f"{where}ORDER BY method, version, id LIMIT ${len(args)}",
                *args,
            )
        return [_row_to_model(row) for row in rows]


def _forecast_args(forecast: Forecast) -> tuple[Any, ...]:
    return (
        forecast.id,
        forecast.tenant_id,
        forecast.metric,
        forecast.subject_ref,
        forecast.method,
        forecast.model_version,
        forecast.horizon_days,
        forecast.issued_at,
        forecast.resolves_at,
        forecast.point,
        json.dumps(forecast.interval.model_dump(mode="json")),
        forecast.confidence,
        json.dumps([basis.model_dump(mode="json") for basis in forecast.basis]),
        json.dumps(forecast.derivation.model_dump(mode="json")),
        forecast.advisory,
        forecast.statement,
        None if forecast.outcome is None else json.dumps(forecast.outcome.model_dump(mode="json")),
    )


def _row_to_forecast(row: asyncpg.Record) -> Forecast:
    data: dict[str, Any] = dict(row)
    for key in ("interval", "basis", "derivation", "outcome"):
        data[key] = _json_value(data[key])
    return Forecast.model_validate(data)


def _row_to_model(row: asyncpg.Record) -> PredictionModel:
    data: dict[str, Any] = dict(row)
    data["params"] = _json_value(data["params"])
    data["promoted_by"] = _json_value(data["promoted_by"])
    return PredictionModel.model_validate(data)


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


def _dump_json_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return json.dumps(value.model_dump(mode="json"))
    return json.dumps(value)


def _tenant_key(tenant_id: str | None) -> str:
    return tenant_id or ""
