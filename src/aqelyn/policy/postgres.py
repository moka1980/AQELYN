"""PostgreSQL PolicyStore implementation (EA-0009 P3)."""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from aqelyn.conventions.errors import StoreUnavailable
from aqelyn.policy.ddl import DDL
from aqelyn.policy.models import Policy
from aqelyn.policy.store import validate_policy, validate_policy_id, validate_policy_tenant

_COLS = "id, version, name, description, tenant_id, rules, standard, set_by, set_at"


def _to_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _row_to_policy(row: asyncpg.Record) -> Policy:
    data: dict[str, Any] = dict(row)
    data["rules"] = _json_value(data["rules"])
    data["set_by"] = _json_value(data["set_by"])
    return Policy.model_validate(data)


class PostgresPolicyStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, url: str) -> PostgresPolicyStore:
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

    async def put(self, policy: Policy) -> Policy:
        stored = validate_policy(policy)
        async with self._pool.acquire() as conn:
            await conn.execute(
                f"INSERT INTO aq_policy ({_COLS}) VALUES "
                "($1,$2,$3,$4,$5,$6,$7,$8,$9) "
                "ON CONFLICT (id) DO UPDATE SET "
                "version=$2, name=$3, description=$4, tenant_id=$5, rules=$6, "
                "standard=$7, set_by=$8, set_at=$9",
                stored.id,
                stored.version,
                stored.name,
                stored.description,
                stored.tenant_id,
                json.dumps([rule.model_dump(mode="json") for rule in stored.rules]),
                stored.standard,
                json.dumps(stored.set_by.model_dump(mode="json")),
                stored.set_at,
            )
        return stored

    async def get(self, policy_id: str) -> Policy | None:
        validate_policy_id(policy_id)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(f"SELECT {_COLS} FROM aq_policy WHERE id=$1", policy_id)
        return None if row is None else _row_to_policy(row)

    async def list(self, *, tenant_id: str | None = None) -> list[Policy]:
        tenant_id = validate_policy_tenant(tenant_id)
        args: list[Any] = []
        if tenant_id is None:
            where = "WHERE tenant_id IS NULL"
        else:
            args.append(tenant_id)
            where = "WHERE tenant_id IS NULL OR tenant_id = $1"
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_COLS} FROM aq_policy {where} "
                "ORDER BY (tenant_id IS NOT NULL), tenant_id, id",
                *args,
            )
        return [_row_to_policy(row) for row in rows]
