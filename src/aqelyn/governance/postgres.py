"""PostgreSQL SnapshotStore implementation (EA-0010 G3)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import asyncpg

from aqelyn.conventions.errors import OptimisticConcurrencyConflict, StoreUnavailable
from aqelyn.governance.ddl import DDL
from aqelyn.governance.models import ComplianceSnapshot
from aqelyn.governance.store import (
    validate_positive,
    validate_snapshot,
    validate_snapshot_id,
    validate_snapshot_tenant,
)

_COLS = (
    "id, tenant_id, run_at, scope, overall_score, control_results, framework_scores, evidence_id"
)


def _to_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _row_to_snapshot(row: asyncpg.Record) -> ComplianceSnapshot:
    data: dict[str, Any] = dict(row)
    for key in ("scope", "control_results", "framework_scores"):
        data[key] = _json_value(data[key])
    return ComplianceSnapshot.model_validate(data)


class PostgresSnapshotStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, url: str) -> PostgresSnapshotStore:
        try:
            pool = await asyncpg.create_pool(_to_dsn(url), min_size=1, max_size=5)
        except Exception as exc:
            raise StoreUnavailable(str(exc)) from exc
        assert pool is not None
        async with pool.acquire() as conn:
            await conn.execute(DDL)
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    async def put(self, snapshot: ComplianceSnapshot) -> ComplianceSnapshot:
        stored = validate_snapshot(snapshot)
        async with self._pool.acquire() as conn:
            try:
                await conn.execute(
                    f"INSERT INTO aq_compliance_snapshot ({_COLS}) VALUES "
                    "($1,$2,$3,$4,$5,$6,$7,$8)",
                    stored.id,
                    stored.tenant_id,
                    stored.run_at,
                    json.dumps(stored.scope),
                    stored.overall_score,
                    json.dumps(
                        [result.model_dump(mode="json") for result in stored.control_results]
                    ),
                    json.dumps(stored.framework_scores),
                    stored.evidence_id,
                )
            except asyncpg.UniqueViolationError as exc:
                raise OptimisticConcurrencyConflict(
                    f"snapshot already exists: {stored.id}"
                ) from exc
        return stored

    async def get(self, snapshot_id: str) -> ComplianceSnapshot | None:
        validate_snapshot_id(snapshot_id)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_COLS} FROM aq_compliance_snapshot WHERE id=$1",
                snapshot_id,
            )
        return None if row is None else _row_to_snapshot(row)

    async def latest(self, *, tenant_id: str | None) -> ComplianceSnapshot | None:
        tenant_id = validate_snapshot_tenant(tenant_id)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_COLS} FROM aq_compliance_snapshot "
                "WHERE tenant_id IS NOT DISTINCT FROM $1 "
                "ORDER BY run_at DESC, id DESC LIMIT 1",
                tenant_id,
            )
        return None if row is None else _row_to_snapshot(row)

    async def history(
        self, *, tenant_id: str | None, since: datetime | None = None, limit: int = 100
    ) -> list[ComplianceSnapshot]:
        tenant_id = validate_snapshot_tenant(tenant_id)
        validate_positive(limit, field="limit")
        args: list[Any] = [tenant_id]
        clauses = ["tenant_id IS NOT DISTINCT FROM $1"]
        if since is not None:
            args.append(since)
            clauses.append(f"run_at >= ${len(args)}")
        args.append(limit)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_COLS} FROM aq_compliance_snapshot "
                f"WHERE {' AND '.join(clauses)} "
                f"ORDER BY run_at, id LIMIT ${len(args)}",
                *args,
            )
        return [_row_to_snapshot(row) for row in rows]
