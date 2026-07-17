"""PostgreSQL AssetStore implementation (EA-0025 N2)."""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from aqelyn.conventions.errors import CrossTenantReference, StoreUnavailable
from aqelyn.inventory.ddl import DDL
from aqelyn.inventory.models import AssetRecord, LifecycleState
from aqelyn.inventory.store import (
    validate_asset,
    validate_asset_id,
    validate_lifecycle_filter,
    validate_query_limit,
    validate_tenant,
)

_ASSET_COLS = (
    "id, tenant_id, asset_type, discovery_source, classification, owner, lifecycle_state, "
    "confidence, basis, conflicts, first_seen_at, last_reported_at, unreported_since"
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


class PostgresAssetStore:
    def __init__(self, pool: asyncpg.Pool, *, mode: str = "local") -> None:
        self._pool = pool
        self.mode = mode

    @classmethod
    async def connect(cls, url: str, *, mode: str = "local") -> PostgresAssetStore:
        return cls(await _connect(url), mode=mode)

    async def close(self) -> None:
        await self._pool.close()

    async def put(self, asset: AssetRecord) -> AssetRecord:
        stored = validate_asset(asset)
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                f"SELECT {_ASSET_COLS} FROM aq_inventory_asset WHERE id=$1 FOR UPDATE",
                stored.id,
            )
            if row is not None:
                existing = _row_to_asset(row)
                if existing.tenant_id != stored.tenant_id:
                    raise CrossTenantReference("asset tenant_id cannot change")
                await _update_asset(conn, stored)
            else:
                await _insert_asset(conn, stored)
            await _history(conn, stored)
        return stored

    async def get(self, asset_id: str, *, tenant_id: str | None = None) -> AssetRecord | None:
        validate_asset_id(asset_id)
        selected_tenant = validate_tenant(tenant_id)
        args: list[Any] = [asset_id]
        clauses = ["id=$1"]
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if selected_tenant is not None:
            args.append(selected_tenant)
            clauses.append(f"tenant_id = ${len(args)}")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_ASSET_COLS} FROM aq_inventory_asset WHERE {' AND '.join(clauses)}",
                *args,
            )
        return None if row is None else _row_to_asset(row)

    async def query(
        self,
        *,
        tenant_id: str | None,
        lifecycle_state: LifecycleState | None = None,
        limit: int = 100,
    ) -> list[AssetRecord]:
        selected_tenant = validate_tenant(tenant_id)
        selected_lifecycle = validate_lifecycle_filter(lifecycle_state)
        selected_limit = validate_query_limit(limit)
        args: list[Any] = []
        clauses: list[str] = []
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if selected_tenant is not None:
            args.append(selected_tenant)
            clauses.append(f"tenant_id = ${len(args)}")
        if selected_lifecycle is not None:
            args.append(selected_lifecycle)
            clauses.append(f"lifecycle_state = ${len(args)}")
        args.append(selected_limit)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_ASSET_COLS} FROM aq_inventory_asset "
                f"{where}ORDER BY first_seen_at, id LIMIT ${len(args)}",
                *args,
            )
        return [_row_to_asset(row) for row in rows]

    async def history(self, asset_id: str) -> list[dict[str, Any]]:
        validate_asset_id(asset_id)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT seq, asset_id, snapshot, changed_at "
                "FROM aq_inventory_asset_history WHERE asset_id=$1 ORDER BY seq",
                asset_id,
            )
        return [_history_row(row) for row in rows]


async def _insert_asset(conn: asyncpg.Connection, asset: AssetRecord) -> None:
    await conn.execute(
        f"INSERT INTO aq_inventory_asset ({_ASSET_COLS}) VALUES "
        "($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)",
        *_asset_args(asset),
    )


async def _update_asset(conn: asyncpg.Connection, asset: AssetRecord) -> None:
    await conn.execute(
        "UPDATE aq_inventory_asset SET "
        "tenant_id=$2, asset_type=$3, discovery_source=$4, classification=$5, owner=$6, "
        "lifecycle_state=$7, confidence=$8, basis=$9, conflicts=$10, first_seen_at=$11, "
        "last_reported_at=$12, unreported_since=$13 WHERE id=$1",
        *_asset_args(asset),
    )


async def _history(conn: asyncpg.Connection, asset: AssetRecord) -> None:
    await conn.execute(
        "INSERT INTO aq_inventory_asset_history (asset_id, snapshot) VALUES ($1,$2)",
        asset.id,
        json.dumps(asset.model_dump(mode="json")),
    )


def _asset_args(asset: AssetRecord) -> tuple[Any, ...]:
    return (
        asset.id,
        asset.tenant_id,
        asset.asset_type,
        asset.discovery_source,
        asset.classification,
        _dump_json_or_none(asset.owner),
        asset.lifecycle_state,
        asset.confidence,
        json.dumps([basis.model_dump(mode="json") for basis in asset.basis]),
        json.dumps([conflict.model_dump(mode="json") for conflict in asset.conflicts]),
        asset.first_seen_at,
        asset.last_reported_at,
        asset.unreported_since,
    )


def _row_to_asset(row: asyncpg.Record) -> AssetRecord:
    data: dict[str, Any] = dict(row)
    for key in ("owner", "basis", "conflicts"):
        data[key] = _json_value(data[key])
    return AssetRecord.model_validate(data)


def _history_row(row: asyncpg.Record) -> dict[str, Any]:
    data: dict[str, Any] = dict(row)
    data["snapshot"] = _json_value(data["snapshot"])
    return data


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
