"""PostgreSQL Risk Intelligence stores (EA-0013 R3)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import asyncpg

from aqelyn.conventions.errors import (
    CrossTenantReference,
    OptimisticConcurrencyConflict,
    StoreUnavailable,
)
from aqelyn.risk.ddl import DDL
from aqelyn.risk.models import Risk, RiskSnapshot
from aqelyn.risk.store import (
    normalize_band_filter,
    normalize_lifecycle_filter,
    validate_positive,
    validate_risk,
    validate_risk_id,
    validate_snapshot,
    validate_snapshot_id,
    validate_tenant,
)

_RISK_COLS = (
    "id, tenant_id, correlation_key, title, category, likelihood, impact, score, band, "
    "signals, affected_object_ids, top_mission_id, lifecycle, treatment, treatment_note, "
    "treated_by, reason, factors, first_seen_at, last_scored_at, version"
)
_SNAPSHOT_COLS = "id, tenant_id, run_at, total, band_counts, top_risks, overall_exposure"


def _to_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


async def _connect(url: str) -> asyncpg.Pool:
    try:
        pool = await asyncpg.create_pool(_to_dsn(url), min_size=1, max_size=5)
    except Exception as exc:
        raise StoreUnavailable(str(exc)) from exc
    assert pool is not None
    async with pool.acquire() as conn:
        await conn.execute(DDL)
    return pool


def _row_to_risk(row: asyncpg.Record) -> Risk:
    data: dict[str, Any] = dict(row)
    for key in ("signals", "affected_object_ids", "treated_by", "factors"):
        data[key] = _json_value(data[key])
    return Risk.model_validate(data)


def _row_to_snapshot(row: asyncpg.Record) -> RiskSnapshot:
    data: dict[str, Any] = dict(row)
    for key in ("band_counts", "top_risks"):
        data[key] = _json_value(data[key])
    return RiskSnapshot.model_validate(data)


class PostgresRiskStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, url: str) -> PostgresRiskStore:
        return cls(await _connect(url))

    async def close(self) -> None:
        await self._pool.close()

    async def upsert(self, risk: Risk) -> Risk:
        stored = validate_risk(risk)
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                f"SELECT {_RISK_COLS} FROM aq_risk "
                "WHERE id=$1 OR (tenant_id IS NOT DISTINCT FROM $2 AND correlation_key=$3) "
                "ORDER BY CASE WHEN id=$1 THEN 0 ELSE 1 END "
                "LIMIT 1 FOR UPDATE",
                stored.id,
                stored.tenant_id,
                stored.correlation_key,
            )
            if row is None:
                created = stored.model_copy(update={"version": 1}, deep=True)
                await _insert_risk(conn, created)
                return created

            existing = _row_to_risk(row)
            if (existing.tenant_id, existing.correlation_key) != (
                stored.tenant_id,
                stored.correlation_key,
            ):
                raise CrossTenantReference("risk tenant_id/correlation_key cannot change")
            validate_positive(stored.version, field="version")
            if existing.version != stored.version:
                raise OptimisticConcurrencyConflict(
                    f"expected v{stored.version}, found v{existing.version}"
                )
            updated = stored.model_copy(
                update={
                    "id": existing.id,
                    "first_seen_at": existing.first_seen_at,
                    "version": existing.version + 1,
                },
                deep=True,
            )
            await _update_risk(conn, updated)
            return updated

    async def get(self, risk_id: str) -> Risk | None:
        validate_risk_id(risk_id)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(f"SELECT {_RISK_COLS} FROM aq_risk WHERE id=$1", risk_id)
        return None if row is None else _row_to_risk(row)

    async def query(
        self,
        *,
        tenant_id: str | None,
        band: Sequence[str] | None = None,
        lifecycle: Sequence[str] | None = None,
        limit: int = 100,
    ) -> list[Risk]:
        tenant_id = validate_tenant(tenant_id)
        bands = normalize_band_filter(band)
        lifecycles = normalize_lifecycle_filter(lifecycle)
        validate_positive(limit, field="limit")
        args: list[Any] = [tenant_id]
        clauses = ["tenant_id IS NOT DISTINCT FROM $1"]
        if bands is not None:
            args.append(list(bands))
            clauses.append(f"band = ANY(${len(args)}::text[])")
        if lifecycles is not None:
            args.append(list(lifecycles))
            clauses.append(f"lifecycle = ANY(${len(args)}::text[])")
        args.append(limit)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_RISK_COLS} FROM aq_risk "
                f"WHERE {' AND '.join(clauses)} "
                f"ORDER BY score DESC, id LIMIT ${len(args)}",
                *args,
            )
        return [_row_to_risk(row) for row in rows]


class PostgresRiskSnapshotStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, url: str) -> PostgresRiskSnapshotStore:
        return cls(await _connect(url))

    async def close(self) -> None:
        await self._pool.close()

    async def put(self, snapshot: RiskSnapshot) -> RiskSnapshot:
        stored = validate_snapshot(snapshot)
        async with self._pool.acquire() as conn:
            try:
                await conn.execute(
                    f"INSERT INTO aq_risk_snapshot ({_SNAPSHOT_COLS}) VALUES "
                    "($1,$2,$3,$4,$5,$6,$7)",
                    stored.id,
                    stored.tenant_id,
                    stored.run_at,
                    stored.total,
                    json.dumps(stored.band_counts),
                    json.dumps(stored.top_risks),
                    stored.overall_exposure,
                )
            except asyncpg.UniqueViolationError as exc:
                raise OptimisticConcurrencyConflict(
                    f"snapshot already exists: {stored.id}"
                ) from exc
        return stored

    async def get(self, snapshot_id: str) -> RiskSnapshot | None:
        validate_snapshot_id(snapshot_id)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_SNAPSHOT_COLS} FROM aq_risk_snapshot WHERE id=$1",
                snapshot_id,
            )
        return None if row is None else _row_to_snapshot(row)

    async def latest(self, *, tenant_id: str | None) -> RiskSnapshot | None:
        tenant_id = validate_tenant(tenant_id)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_SNAPSHOT_COLS} FROM aq_risk_snapshot "
                "WHERE tenant_id IS NOT DISTINCT FROM $1 "
                "ORDER BY run_at DESC, id DESC LIMIT 1",
                tenant_id,
            )
        return None if row is None else _row_to_snapshot(row)

    async def history(
        self, *, tenant_id: str | None, since: datetime | None = None, limit: int = 100
    ) -> list[RiskSnapshot]:
        tenant_id = validate_tenant(tenant_id)
        validate_positive(limit, field="limit")
        args: list[Any] = [tenant_id]
        clauses = ["tenant_id IS NOT DISTINCT FROM $1"]
        if since is not None:
            args.append(since)
            clauses.append(f"run_at >= ${len(args)}")
        args.append(limit)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_SNAPSHOT_COLS} FROM aq_risk_snapshot "
                f"WHERE {' AND '.join(clauses)} "
                f"ORDER BY run_at, id LIMIT ${len(args)}",
                *args,
            )
        return [_row_to_snapshot(row) for row in rows]


async def _insert_risk(conn: asyncpg.Connection, risk: Risk) -> None:
    try:
        await conn.execute(
            f"INSERT INTO aq_risk ({_RISK_COLS}) VALUES "
            "($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21)",
            *_risk_args(risk),
        )
    except asyncpg.UniqueViolationError as exc:
        raise OptimisticConcurrencyConflict(f"risk already exists: {risk.id}") from exc


async def _update_risk(conn: asyncpg.Connection, risk: Risk) -> None:
    await conn.execute(
        "UPDATE aq_risk SET "
        "tenant_id=$2, correlation_key=$3, title=$4, category=$5, likelihood=$6, "
        "impact=$7, score=$8, band=$9, signals=$10, affected_object_ids=$11, "
        "top_mission_id=$12, lifecycle=$13, treatment=$14, treatment_note=$15, "
        "treated_by=$16, reason=$17, factors=$18, first_seen_at=$19, "
        "last_scored_at=$20, version=$21 "
        "WHERE id=$1",
        *_risk_args(risk),
    )


def _risk_args(risk: Risk) -> tuple[Any, ...]:
    return (
        risk.id,
        risk.tenant_id,
        risk.correlation_key,
        risk.title,
        risk.category,
        risk.likelihood,
        risk.impact,
        risk.score,
        risk.band,
        json.dumps([signal.model_dump(mode="json") for signal in risk.signals]),
        json.dumps(risk.affected_object_ids),
        risk.top_mission_id,
        risk.lifecycle,
        risk.treatment,
        risk.treatment_note,
        None if risk.treated_by is None else json.dumps(risk.treated_by.model_dump(mode="json")),
        risk.reason,
        json.dumps(risk.factors),
        risk.first_seen_at,
        risk.last_scored_at,
        risk.version,
    )
