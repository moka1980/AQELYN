"""PostgreSQL RunStore implementation (EA-0008 W2)."""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from aqelyn.conventions import new_id, utc_now
from aqelyn.conventions.errors import (
    CrossTenantReference,
    OptimisticConcurrencyConflict,
    RunNotFound,
    StoreUnavailable,
    TenantScopeRequired,
)
from aqelyn.workflow.ddl import DDL
from aqelyn.workflow.models import Run
from aqelyn.workflow.store import validate_positive, validate_run_id

_COLS = (
    "id, playbook_id, playbook_version, tenant_id, status, source_finding_id, "
    "results, approvals, created_by, created_at, updated_at, version"
)


def _to_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _row_to_run(row: asyncpg.Record) -> Run:
    data: dict[str, Any] = dict(row)
    for key in ("results", "approvals", "created_by"):
        data[key] = _json_value(data[key])
    return Run.model_validate(data)


class PostgresRunStore:
    def __init__(self, pool: asyncpg.Pool, *, mode: str = "local") -> None:
        self._pool = pool
        self.mode = mode

    @classmethod
    async def connect(cls, url: str, **kw: Any) -> PostgresRunStore:
        try:
            pool = await asyncpg.create_pool(_to_dsn(url), min_size=1, max_size=5)
        except Exception as exc:
            raise StoreUnavailable(str(exc)) from exc
        assert pool is not None
        async with pool.acquire() as conn:
            await conn.execute(DDL)
        return cls(pool, **kw)

    async def close(self) -> None:
        await self._pool.close()

    async def create(self, run: Run) -> Run:
        created = run.model_copy(deep=True)
        if not created.id:
            created.id = new_id("run")
        validate_run_id(created.id, field="id")
        now = utc_now()
        created.version = 1
        created.created_at = now
        created.updated_at = now
        async with self._pool.acquire() as conn:
            try:
                await conn.execute(
                    f"INSERT INTO aq_workflow_run ({_COLS}) VALUES "
                    "($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)",
                    created.id,
                    created.playbook_id,
                    created.playbook_version,
                    created.tenant_id,
                    created.status,
                    created.source_finding_id,
                    json.dumps([result.model_dump(mode="json") for result in created.results]),
                    json.dumps(
                        [approval.model_dump(mode="json") for approval in created.approvals]
                    ),
                    json.dumps(created.created_by.model_dump()),
                    created.created_at,
                    created.updated_at,
                    created.version,
                )
            except asyncpg.UniqueViolationError as exc:
                raise OptimisticConcurrencyConflict(f"run already exists: {created.id}") from exc
        return created

    async def get(self, run_id: str, *, tenant_id: str | None = None) -> Run | None:
        validate_run_id(run_id)
        clauses = ["id = $1"]
        args: list[Any] = [run_id]
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if tenant_id is not None:
            args.append(tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_COLS} FROM aq_workflow_run WHERE {' AND '.join(clauses)}",
                *args,
            )
        return None if row is None else _row_to_run(row)

    async def update(self, run: Run, *, expected_version: int) -> Run:
        validate_positive(expected_version, field="expected_version")
        validate_run_id(run.id, field="id")
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                f"SELECT {_COLS} FROM aq_workflow_run WHERE id=$1 FOR UPDATE",
                run.id,
            )
            if row is None:
                raise RunNotFound(run.id)
            existing = _row_to_run(row)
            if existing.tenant_id != run.tenant_id:
                raise CrossTenantReference("run tenant_id cannot change")
            if existing.version != expected_version:
                raise OptimisticConcurrencyConflict(
                    f"expected v{expected_version}, found v{existing.version}"
                )
            updated = run.model_copy(
                update={
                    "version": existing.version + 1,
                    "created_at": existing.created_at,
                    "updated_at": max(utc_now(), existing.updated_at),
                },
                deep=True,
            )
            await conn.execute(
                "UPDATE aq_workflow_run SET status=$2, results=$3, approvals=$4, "
                "updated_at=$5, version=$6 WHERE id=$1",
                updated.id,
                updated.status,
                json.dumps([result.model_dump(mode="json") for result in updated.results]),
                json.dumps([approval.model_dump(mode="json") for approval in updated.approvals]),
                updated.updated_at,
                updated.version,
            )
            return updated

    async def list(self, *, tenant_id: str | None = None, limit: int = 100) -> list[Run]:
        validate_positive(limit, field="limit")
        if self.mode == "enterprise" and tenant_id is None:
            raise TenantScopeRequired("run list must be tenant-scoped in enterprise mode")
        clauses: list[str] = []
        args: list[Any] = []
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if tenant_id is not None:
            args.append(tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")
        args.append(limit)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        sql = f"SELECT {_COLS} FROM aq_workflow_run {where}ORDER BY id LIMIT ${len(args)}"
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        return [_row_to_run(row) for row in rows]
