"""PostgreSQL Asset & Configuration Governance stores (EA-0012 A3)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import asyncpg

from aqelyn.assetconfig.ddl import DDL
from aqelyn.assetconfig.models import Baseline, DriftSnapshot
from aqelyn.assetconfig.store import (
    validate_baseline,
    validate_baseline_id,
    validate_positive,
    validate_snapshot,
    validate_snapshot_id,
    validate_tenant,
)
from aqelyn.conventions.errors import (
    CrossTenantReference,
    OptimisticConcurrencyConflict,
    StoreUnavailable,
)

_BASELINE_COLS = "id, name, asset_class, version, checks, tenant_id, set_by, set_at"
_SNAPSHOT_COLS = (
    "id, tenant_id, run_at, scope, baseline_ids, overall_score, asset_drifts, evidence_id"
)


def _to_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _row_to_baseline(row: asyncpg.Record) -> Baseline:
    data: dict[str, Any] = dict(row)
    data["checks"] = _json_value(data["checks"])
    data["set_by"] = _json_value(data["set_by"])
    return Baseline.model_validate(data)


def _row_to_snapshot(row: asyncpg.Record) -> DriftSnapshot:
    data: dict[str, Any] = dict(row)
    for key in ("scope", "baseline_ids", "asset_drifts"):
        data[key] = _json_value(data[key])
    return DriftSnapshot.model_validate(data)


async def _connect(url: str) -> asyncpg.Pool:
    try:
        pool = await asyncpg.create_pool(_to_dsn(url), min_size=1, max_size=5)
    except Exception as exc:
        raise StoreUnavailable(str(exc)) from exc
    assert pool is not None
    async with pool.acquire() as conn:
        await conn.execute(DDL)
    return pool


class PostgresBaselineStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, url: str) -> PostgresBaselineStore:
        return cls(await _connect(url))

    async def close(self) -> None:
        await self._pool.close()

    async def put(self, baseline: Baseline) -> Baseline:
        stored = validate_baseline(baseline)
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                f"SELECT {_BASELINE_COLS} FROM aq_acg_baseline WHERE id=$1 FOR UPDATE",
                stored.id,
            )
            if row is not None:
                existing = _row_to_baseline(row)
                if existing.tenant_id != stored.tenant_id:
                    raise CrossTenantReference("baseline tenant_id cannot change")
                await conn.execute(
                    "UPDATE aq_acg_baseline "
                    "SET name=$2, asset_class=$3, version=$4, checks=$5, "
                    "tenant_id=$6, set_by=$7, set_at=$8 "
                    "WHERE id=$1",
                    stored.id,
                    stored.name,
                    stored.asset_class,
                    stored.version,
                    json.dumps([check.model_dump(mode="json") for check in stored.checks]),
                    stored.tenant_id,
                    json.dumps(stored.set_by.model_dump(mode="json")),
                    stored.set_at,
                )
                return stored

            await conn.execute(
                f"INSERT INTO aq_acg_baseline ({_BASELINE_COLS}) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
                stored.id,
                stored.name,
                stored.asset_class,
                stored.version,
                json.dumps([check.model_dump(mode="json") for check in stored.checks]),
                stored.tenant_id,
                json.dumps(stored.set_by.model_dump(mode="json")),
                stored.set_at,
            )
        return stored

    async def get(self, baseline_id: str) -> Baseline | None:
        validate_baseline_id(baseline_id)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_BASELINE_COLS} FROM aq_acg_baseline WHERE id=$1",
                baseline_id,
            )
        return None if row is None else _row_to_baseline(row)

    async def list(
        self, *, tenant_id: str | None, asset_class: str | None = None
    ) -> list[Baseline]:
        tenant_id = validate_tenant(tenant_id)
        args: list[Any] = []
        if tenant_id is None:
            clauses = ["tenant_id IS NULL"]
        else:
            args.append(tenant_id)
            clauses = ["(tenant_id IS NULL OR tenant_id = $1)"]
        if asset_class is not None:
            args.append(asset_class)
            clauses.append(f"asset_class = ${len(args)}")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_BASELINE_COLS} FROM aq_acg_baseline "
                f"WHERE {' AND '.join(clauses)} "
                "ORDER BY (tenant_id IS NOT NULL), tenant_id, id",
                *args,
            )
        return [_row_to_baseline(row) for row in rows]


class PostgresDriftSnapshotStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, url: str) -> PostgresDriftSnapshotStore:
        return cls(await _connect(url))

    async def close(self) -> None:
        await self._pool.close()

    async def put(self, snapshot: DriftSnapshot) -> DriftSnapshot:
        stored = validate_snapshot(snapshot)
        async with self._pool.acquire() as conn:
            try:
                await conn.execute(
                    f"INSERT INTO aq_acg_drift_snapshot ({_SNAPSHOT_COLS}) VALUES "
                    "($1,$2,$3,$4,$5,$6,$7,$8)",
                    stored.id,
                    stored.tenant_id,
                    stored.run_at,
                    json.dumps(stored.scope),
                    json.dumps(stored.baseline_ids),
                    stored.overall_score,
                    json.dumps([drift.model_dump(mode="json") for drift in stored.asset_drifts]),
                    stored.evidence_id,
                )
            except asyncpg.UniqueViolationError as exc:
                raise OptimisticConcurrencyConflict(
                    f"snapshot already exists: {stored.id}"
                ) from exc
        return stored

    async def get(self, snapshot_id: str) -> DriftSnapshot | None:
        validate_snapshot_id(snapshot_id)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_SNAPSHOT_COLS} FROM aq_acg_drift_snapshot WHERE id=$1",
                snapshot_id,
            )
        return None if row is None else _row_to_snapshot(row)

    async def latest(self, *, tenant_id: str | None) -> DriftSnapshot | None:
        tenant_id = validate_tenant(tenant_id)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_SNAPSHOT_COLS} FROM aq_acg_drift_snapshot "
                "WHERE tenant_id IS NOT DISTINCT FROM $1 "
                "ORDER BY run_at DESC, id DESC LIMIT 1",
                tenant_id,
            )
        return None if row is None else _row_to_snapshot(row)

    async def history(
        self, *, tenant_id: str | None, since: datetime | None = None, limit: int = 100
    ) -> list[DriftSnapshot]:
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
                f"SELECT {_SNAPSHOT_COLS} FROM aq_acg_drift_snapshot "
                f"WHERE {' AND '.join(clauses)} "
                f"ORDER BY run_at, id LIMIT ${len(args)}",
                *args,
            )
        return [_row_to_snapshot(row) for row in rows]
