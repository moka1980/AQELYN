"""PostgreSQL append-only DSPM store (EA-0031 P2)."""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from aqelyn.conventions.errors import (
    CrossTenantReference,
    OptimisticConcurrencyConflict,
    StoreUnavailable,
)
from aqelyn.dspm.ddl import DDL
from aqelyn.dspm.models import (
    AssetClassificationStatus,
    Classification,
    DataAsset,
    DataExposure,
    DataPostureAssessment,
)
from aqelyn.dspm.store import (
    validate_assessment,
    validate_asset,
    validate_asset_id,
    validate_classification_filter,
    validate_exposure,
    validate_query_cursor,
    validate_query_limit,
    validate_status_filter,
    validate_store_id,
    validate_tenant_scope,
)


def _to_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _connect(url: str) -> asyncpg.Pool:
    try:
        pool = await asyncpg.create_pool(_to_dsn(url), min_size=1, max_size=5)
    except Exception as exc:
        raise StoreUnavailable(str(exc)) from exc
    if pool is None:
        raise StoreUnavailable("asyncpg did not return a connection pool")
    async with pool.acquire() as conn:
        await conn.execute(DDL)
    return pool


class PostgresDSPMStore:
    def __init__(self, pool: asyncpg.Pool, *, mode: str = "local") -> None:
        self._pool = pool
        self.mode = mode

    @classmethod
    async def connect(cls, url: str, *, mode: str = "local") -> PostgresDSPMStore:
        return cls(await _connect(url), mode=mode)

    async def close(self) -> None:
        await self._pool.close()

    async def put_asset(self, asset: DataAsset) -> DataAsset:
        stored = validate_asset(asset)
        async with self._pool.acquire() as conn, conn.transaction():
            latest = await conn.fetchrow(
                "SELECT tenant_id, version, payload FROM aq_dspm_asset "
                "WHERE id=$1 ORDER BY version DESC LIMIT 1 FOR UPDATE",
                stored.id,
            )
            if latest is not None:
                if latest["tenant_id"] != stored.tenant_id:
                    raise CrossTenantReference("data asset tenant_id cannot change")
                expected = int(latest["version"]) + 1
                if stored.version != expected:
                    raise OptimisticConcurrencyConflict(
                        f"data asset {stored.id} expected version {expected}"
                    )
                current = _asset_from_payload(latest["payload"])
                if (
                    stored.store_id != current.store_id
                    or stored.object_id != current.object_id
                    or stored.inventory_ref != current.inventory_ref
                ):
                    raise OptimisticConcurrencyConflict("data asset identity cannot change")
            elif stored.version != 1:
                raise OptimisticConcurrencyConflict("new data asset must start at version 1")
            await _ensure_asset_key(conn, stored)
            try:
                await conn.execute(
                    "INSERT INTO aq_dspm_asset "
                    "(id, version, tenant_id, store_id, store_type, classification, "
                    "classification_status, flagged, payload) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)",
                    stored.id,
                    stored.version,
                    stored.tenant_id,
                    stored.store_id,
                    stored.store_type,
                    stored.max_known_sensitivity,
                    stored.classification_status,
                    stored.flagged,
                    json.dumps(stored.model_dump(mode="json")),
                )
            except asyncpg.UniqueViolationError as exc:
                raise OptimisticConcurrencyConflict(
                    f"data asset version already exists: {stored.id} v{stored.version}"
                ) from exc
        return stored.model_copy(deep=True)

    async def get_asset(
        self,
        asset_id: str,
        *,
        tenant_id: str | None,
    ) -> DataAsset | None:
        selected_id = validate_asset_id(asset_id)
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        args: list[Any] = [selected_id]
        clauses = ["id=$1"]
        self._tenant_clauses(clauses, args, selected_tenant)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT payload FROM aq_dspm_asset "
                f"WHERE {' AND '.join(clauses)} ORDER BY version DESC LIMIT 1",
                *args,
            )
        return None if row is None else _asset_from_payload(row["payload"])

    async def get_asset_by_store_id(
        self,
        store_id: str,
        *,
        tenant_id: str | None,
    ) -> DataAsset | None:
        selected_store = validate_store_id(store_id)
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        args: list[Any] = [selected_store]
        clauses = ["store_id=$1"]
        self._tenant_clauses(clauses, args, selected_tenant)
        async with self._pool.acquire() as conn:
            key_row = await conn.fetchrow(
                f"SELECT asset_id FROM aq_dspm_asset_key WHERE {' AND '.join(clauses)}",
                *args,
            )
            if key_row is None:
                return None
            row = await conn.fetchrow(
                "SELECT payload FROM aq_dspm_asset WHERE id=$1 ORDER BY version DESC LIMIT 1",
                key_row["asset_id"],
            )
        return None if row is None else _asset_from_payload(row["payload"])

    async def put_exposure(self, exposure: DataExposure) -> DataExposure:
        stored = validate_exposure(exposure)
        await self._insert_immutable(
            "aq_dspm_exposure",
            stored.id,
            stored.tenant_id,
            stored.model_dump(mode="json"),
            label="data exposure",
        )
        return stored.model_copy(deep=True)

    async def put_assessment(
        self,
        assessment: DataPostureAssessment,
    ) -> DataPostureAssessment:
        stored = validate_assessment(assessment)
        await self._insert_immutable(
            "aq_dspm_assessment",
            stored.id,
            stored.tenant_id,
            stored.model_dump(mode="json"),
            label="data assessment",
        )
        return stored.model_copy(deep=True)

    async def query_assets(
        self,
        *,
        tenant_id: str | None,
        classification: Classification | None = None,
        status: AssetClassificationStatus | None = None,
        flagged: bool | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[list[DataAsset], str | None]:
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        selected_classification = validate_classification_filter(classification)
        selected_status = validate_status_filter(status)
        selected_limit = validate_query_limit(limit)
        selected_cursor = validate_query_cursor(cursor)

        args: list[Any] = []
        inner: list[str] = []
        self._tenant_clauses(inner, args, selected_tenant)
        outer: list[str] = []
        if selected_classification is not None:
            args.append(selected_classification)
            outer.append(f"classification = ${len(args)}")
        if selected_status is not None:
            args.append(selected_status)
            outer.append(f"classification_status = ${len(args)}")
        if flagged is not None:
            args.append(flagged)
            outer.append(f"flagged = ${len(args)}")
        if selected_cursor is not None:
            args.append(selected_cursor)
            outer.append(f"id > ${len(args)}")
        args.append(selected_limit + 1)
        inner_where = f"WHERE {' AND '.join(inner)}" if inner else ""
        outer_where = f"WHERE {' AND '.join(outer)}" if outer else ""
        async with self._pool.acquire() as conn:
            rows = list(
                await conn.fetch(
                    "WITH latest AS ("
                    "SELECT DISTINCT ON (id) id, classification, classification_status, "
                    "flagged, payload FROM aq_dspm_asset "
                    f"{inner_where} ORDER BY id, version DESC"
                    ") SELECT id, payload FROM latest "
                    f"{outer_where} ORDER BY id LIMIT ${len(args)}",
                    *args,
                )
            )
        has_more = len(rows) > selected_limit
        page = rows[:selected_limit]
        next_cursor = str(page[-1]["id"]) if has_more else None
        return [_asset_from_payload(row["payload"]) for row in page], next_cursor

    async def _insert_immutable(
        self,
        table: str,
        record_id: str,
        tenant_id: str | None,
        payload: dict[str, object],
        *,
        label: str,
    ) -> None:
        async with self._pool.acquire() as conn:
            try:
                await conn.execute(
                    f"INSERT INTO {table} (id, tenant_id, payload) VALUES ($1,$2,$3)",
                    record_id,
                    tenant_id,
                    json.dumps(payload),
                )
            except asyncpg.UniqueViolationError as exc:
                row = await conn.fetchrow(f"SELECT tenant_id FROM {table} WHERE id=$1", record_id)
                if row is not None and row["tenant_id"] != tenant_id:
                    raise CrossTenantReference(f"{label} tenant_id cannot change") from exc
                raise OptimisticConcurrencyConflict(f"{label} already exists: {record_id}") from exc

    def _tenant_clauses(
        self,
        clauses: list[str],
        args: list[Any],
        tenant_id: str | None,
    ) -> None:
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if tenant_id is not None:
            args.append(tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")


def _asset_from_payload(value: Any) -> DataAsset:
    if isinstance(value, str):
        value = json.loads(value)
    return DataAsset.model_validate(value)


async def _ensure_asset_key(conn: asyncpg.Connection, asset: DataAsset) -> None:
    by_asset = await conn.fetchrow(
        "SELECT tenant_id, store_id FROM aq_dspm_asset_key WHERE asset_id=$1 FOR UPDATE",
        asset.id,
    )
    if by_asset is not None:
        if by_asset["tenant_id"] != asset.tenant_id or by_asset["store_id"] != asset.store_id:
            raise OptimisticConcurrencyConflict("data asset identity cannot change")
        return
    try:
        await conn.execute(
            "INSERT INTO aq_dspm_asset_key (tenant_key, tenant_id, store_id, asset_id) "
            "VALUES ($1,$2,$3,$4)",
            "" if asset.tenant_id is None else asset.tenant_id,
            asset.tenant_id,
            asset.store_id,
            asset.id,
        )
    except asyncpg.UniqueViolationError as exc:
        raise OptimisticConcurrencyConflict(
            f"store_id already belongs to another data asset: {asset.store_id}"
        ) from exc
