"""PostgreSQL ExposureStore implementation (EA-0023 E2)."""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from aqelyn.conventions.errors import OptimisticConcurrencyConflict, StoreUnavailable
from aqelyn.exposure.ddl import DDL
from aqelyn.exposure.models import ExposureRecord, Reachability
from aqelyn.exposure.store import (
    validate_exposure,
    validate_exposure_id,
    validate_flagged_filter,
    validate_query_limit,
    validate_reachability_filter,
    validate_tenant,
)

_EXPOSURE_COLS = (
    "id, tenant_id, asset_ref, exposure_type, reachability, basis, score, confidence, "
    "impact_context, derivation, rationale, flagged, discovered_at, validated_at, status"
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


class PostgresExposureStore:
    def __init__(self, pool: asyncpg.Pool, *, mode: str = "local") -> None:
        self._pool = pool
        self.mode = mode

    @classmethod
    async def connect(cls, url: str, *, mode: str = "local") -> PostgresExposureStore:
        return cls(await _connect(url), mode=mode)

    async def close(self) -> None:
        await self._pool.close()

    async def put(self, exposure: ExposureRecord) -> ExposureRecord:
        stored = validate_exposure(exposure)
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO aq_exposure_record "
                    "(id, tenant_id, asset_ref, exposure_type, reachability, basis, score, "
                    "confidence, impact_context, derivation, rationale, flagged, discovered_at, "
                    "validated_at, status) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)",
                    *_exposure_args(stored),
                )
        except asyncpg.UniqueViolationError as exc:
            raise OptimisticConcurrencyConflict(f"exposure already exists: {stored.id}") from exc
        return stored

    async def get(self, exposure_id: str, *, tenant_id: str | None = None) -> ExposureRecord | None:
        validate_exposure_id(exposure_id)
        selected_tenant = validate_tenant(tenant_id)
        args: list[Any] = [exposure_id]
        clauses = ["id=$1"]
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if selected_tenant is not None:
            args.append(selected_tenant)
            clauses.append(f"tenant_id = ${len(args)}")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_EXPOSURE_COLS} FROM aq_exposure_record WHERE {' AND '.join(clauses)}",
                *args,
            )
        return None if row is None else _row_to_exposure(row)

    async def query(
        self,
        *,
        tenant_id: str | None,
        reachability: Reachability | None = None,
        flagged: bool | None = None,
        limit: int = 100,
    ) -> list[ExposureRecord]:
        selected_tenant = validate_tenant(tenant_id)
        selected_reachability = validate_reachability_filter(reachability)
        selected_flagged = validate_flagged_filter(flagged)
        selected_limit = validate_query_limit(limit)
        args: list[Any] = []
        clauses: list[str] = []
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if selected_tenant is not None:
            args.append(selected_tenant)
            clauses.append(f"tenant_id = ${len(args)}")
        if selected_reachability is not None:
            args.append(selected_reachability)
            clauses.append(f"reachability = ${len(args)}")
        if selected_flagged is not None:
            args.append(selected_flagged)
            clauses.append(f"flagged = ${len(args)}")
        args.append(selected_limit)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_EXPOSURE_COLS} FROM aq_exposure_record "
                f"{where}ORDER BY discovered_at, id LIMIT ${len(args)}",
                *args,
            )
        return [_row_to_exposure(row) for row in rows]


def _exposure_args(exposure: ExposureRecord) -> tuple[Any, ...]:
    return (
        exposure.id,
        exposure.tenant_id,
        json.dumps(exposure.asset_ref.model_dump(mode="json")),
        exposure.exposure_type,
        exposure.reachability,
        json.dumps([basis.model_dump(mode="json") for basis in exposure.basis]),
        exposure.score,
        exposure.confidence,
        _dump_json_or_none(exposure.impact_context),
        _dump_json_or_none(exposure.derivation),
        exposure.rationale,
        exposure.flagged,
        exposure.discovered_at,
        exposure.validated_at,
        exposure.status,
    )


def _row_to_exposure(row: asyncpg.Record) -> ExposureRecord:
    data: dict[str, Any] = dict(row)
    for key in ("asset_ref", "basis", "impact_context", "derivation"):
        data[key] = _json_value(data[key])
    return validate_exposure(ExposureRecord.model_validate(data))


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
