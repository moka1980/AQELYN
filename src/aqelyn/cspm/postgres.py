"""PostgreSQL CloudNormalizationStore implementation (EA-0028 Y2)."""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from aqelyn.conventions.errors import CrossTenantReference, StoreUnavailable
from aqelyn.cspm.ddl import DDL
from aqelyn.cspm.models import NormalizedCloudObject
from aqelyn.cspm.store import (
    validate_cloud_object,
    validate_cloud_object_id,
    validate_provider_filter,
    validate_query_limit,
    validate_tenant_scope,
)

_COLUMNS = (
    "object_id, object_type, tenant_id, provider, account, region, native_facts, "
    "field_provenance, conflicts, evidence_id, flagged"
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


class PostgresCloudNormalizationStore:
    def __init__(self, pool: asyncpg.Pool, *, mode: str = "local") -> None:
        self._pool = pool
        self.mode = mode

    @classmethod
    async def connect(
        cls,
        url: str,
        *,
        mode: str = "local",
    ) -> PostgresCloudNormalizationStore:
        return cls(await _connect(url), mode=mode)

    async def close(self) -> None:
        await self._pool.close()

    async def put(self, obj: NormalizedCloudObject) -> NormalizedCloudObject:
        stored = validate_cloud_object(obj)
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT tenant_id FROM aq_cloud_normalization WHERE object_id=$1 FOR UPDATE",
                stored.object_id,
            )
            if row is not None and row["tenant_id"] != stored.tenant_id:
                raise CrossTenantReference("normalized cloud object tenant_id cannot change")
            await conn.execute(
                f"INSERT INTO aq_cloud_normalization ({_COLUMNS}) VALUES "
                "($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) "
                "ON CONFLICT (object_id) DO UPDATE SET "
                "object_type=EXCLUDED.object_type, provider=EXCLUDED.provider, "
                "account=EXCLUDED.account, region=EXCLUDED.region, "
                "native_facts=EXCLUDED.native_facts, "
                "field_provenance=EXCLUDED.field_provenance, conflicts=EXCLUDED.conflicts, "
                "evidence_id=EXCLUDED.evidence_id, flagged=EXCLUDED.flagged",
                *_object_args(stored),
            )
        return stored.model_copy(deep=True)

    async def get(
        self,
        object_id: str,
        *,
        tenant_id: str | None,
    ) -> NormalizedCloudObject | None:
        selected_id = validate_cloud_object_id(object_id)
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        args: list[Any] = [selected_id]
        clauses = ["object_id=$1"]
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if selected_tenant is not None:
            args.append(selected_tenant)
            clauses.append(f"tenant_id = ${len(args)}")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_COLUMNS} FROM aq_cloud_normalization WHERE {' AND '.join(clauses)}",
                *args,
            )
        return None if row is None else _row_to_object(row)

    async def query(
        self,
        *,
        tenant_id: str | None,
        provider: str | None = None,
        limit: int = 1000,
    ) -> list[NormalizedCloudObject]:
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        selected_provider = validate_provider_filter(provider)
        selected_limit = validate_query_limit(limit)
        args: list[Any] = []
        clauses: list[str] = []
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if selected_tenant is not None:
            args.append(selected_tenant)
            clauses.append(f"tenant_id = ${len(args)}")
        if selected_provider is not None:
            args.append(selected_provider)
            clauses.append(f"provider = ${len(args)}")
        args.append(selected_limit)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_COLUMNS} FROM aq_cloud_normalization "
                f"{where}ORDER BY object_id LIMIT ${len(args)}",
                *args,
            )
        return [_row_to_object(row) for row in rows]


def _object_args(obj: NormalizedCloudObject) -> tuple[Any, ...]:
    return (
        obj.object_id,
        obj.object_type,
        obj.tenant_id,
        obj.provider,
        obj.account,
        obj.region,
        json.dumps(obj.native_facts),
        json.dumps(obj.field_provenance),
        json.dumps(obj.conflicts),
        obj.evidence_id,
        obj.flagged,
    )


def _row_to_object(row: asyncpg.Record) -> NormalizedCloudObject:
    data: dict[str, Any] = dict(row)
    for key in ("native_facts", "field_provenance", "conflicts"):
        data[key] = _json_value(data[key])
    return NormalizedCloudObject.model_validate(data)


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value
