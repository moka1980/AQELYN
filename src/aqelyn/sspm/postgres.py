"""PostgreSQL SaaSNormalizationStore implementation (EA-0029 Z2)."""

from __future__ import annotations

import json
from typing import Any, Literal

import asyncpg

from aqelyn.conventions.errors import CrossTenantReference, StoreUnavailable
from aqelyn.sspm.ddl import DDL
from aqelyn.sspm.models import NormalizedSaaSObject, OverScopedStatus, SaaSIntegration
from aqelyn.sspm.store import (
    validate_object_id,
    validate_over_scoped_filter,
    validate_provider_filter,
    validate_query_cursor,
    validate_query_limit,
    validate_saas_integration,
    validate_saas_object,
    validate_tenant_scope,
)

_OBJECT_COLUMNS = (
    "object_id, tenant_id, object_type, provider, provider_tenant, native_facts, "
    "field_provenance, conflicts, evidence_id, flagged"
)
_INTEGRATION_COLUMNS = (
    "object_id, tenant_id, integration_id, grantor_ref, grantor_kind, third_party_app, "
    "third_party_external, scopes, over_scoped, reachable_object_ids, reach_status, "
    "known_surface_ref, claim_confidence, evidence_id, observed_at, reason"
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


class PostgresSaaSNormalizationStore:
    def __init__(self, pool: asyncpg.Pool, *, mode: str = "local") -> None:
        self._pool = pool
        self.mode = mode

    @classmethod
    async def connect(
        cls,
        url: str,
        *,
        mode: str = "local",
    ) -> PostgresSaaSNormalizationStore:
        return cls(await _connect(url), mode=mode)

    async def close(self) -> None:
        await self._pool.close()

    async def put(self, obj: NormalizedSaaSObject) -> NormalizedSaaSObject:
        stored = validate_saas_object(obj)
        async with self._pool.acquire() as conn, conn.transaction():
            await _guard_tenant(conn, "aq_saas_normalization", stored.object_id, stored.tenant_id)
            await conn.execute(
                f"INSERT INTO aq_saas_normalization ({_OBJECT_COLUMNS}) VALUES "
                "($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) "
                "ON CONFLICT (object_id) DO UPDATE SET "
                "object_type=EXCLUDED.object_type, provider=EXCLUDED.provider, "
                "provider_tenant=EXCLUDED.provider_tenant, native_facts=EXCLUDED.native_facts, "
                "field_provenance=EXCLUDED.field_provenance, conflicts=EXCLUDED.conflicts, "
                "evidence_id=EXCLUDED.evidence_id, flagged=EXCLUDED.flagged",
                *_object_args(stored),
            )
        return stored.model_copy(deep=True)

    async def put_integration(self, integration: SaaSIntegration) -> SaaSIntegration:
        stored = validate_saas_integration(integration)
        async with self._pool.acquire() as conn, conn.transaction():
            await _guard_tenant(conn, "aq_saas_integration", stored.object_id, stored.tenant_id)
            await conn.execute(
                f"INSERT INTO aq_saas_integration ({_INTEGRATION_COLUMNS}) VALUES "
                "($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16) "
                "ON CONFLICT (object_id) DO UPDATE SET "
                "integration_id=EXCLUDED.integration_id, grantor_ref=EXCLUDED.grantor_ref, "
                "grantor_kind=EXCLUDED.grantor_kind, third_party_app=EXCLUDED.third_party_app, "
                "third_party_external=EXCLUDED.third_party_external, scopes=EXCLUDED.scopes, "
                "over_scoped=EXCLUDED.over_scoped, "
                "reachable_object_ids=EXCLUDED.reachable_object_ids, "
                "reach_status=EXCLUDED.reach_status, "
                "known_surface_ref=EXCLUDED.known_surface_ref, "
                "claim_confidence=EXCLUDED.claim_confidence, evidence_id=EXCLUDED.evidence_id, "
                "observed_at=EXCLUDED.observed_at, reason=EXCLUDED.reason",
                *_integration_args(stored),
            )
        return stored.model_copy(deep=True)

    async def get(
        self,
        object_id: str,
        *,
        tenant_id: str | None,
    ) -> NormalizedSaaSObject | None:
        row = await self._get_row(
            "aq_saas_normalization",
            _OBJECT_COLUMNS,
            object_id,
            tenant_id=tenant_id,
        )
        return None if row is None else _row_to_object(row)

    async def get_integration(
        self,
        object_id: str,
        *,
        tenant_id: str | None,
    ) -> SaaSIntegration | None:
        row = await self._get_row(
            "aq_saas_integration",
            _INTEGRATION_COLUMNS,
            object_id,
            tenant_id=tenant_id,
        )
        return None if row is None else _row_to_integration(row)

    async def query(
        self,
        *,
        tenant_id: str | None,
        provider: str | None = None,
        limit: int = 1000,
        cursor: str | None = None,
    ) -> tuple[list[NormalizedSaaSObject], str | None]:
        rows, next_cursor = await self._query_rows(
            "aq_saas_normalization",
            _OBJECT_COLUMNS,
            tenant_id=tenant_id,
            filter_column="provider",
            filter_value=validate_provider_filter(provider),
            limit=limit,
            cursor=cursor,
        )
        return [_row_to_object(row) for row in rows], next_cursor

    async def query_integrations(
        self,
        *,
        tenant_id: str | None,
        over_scoped: OverScopedStatus | None = None,
        limit: int = 1000,
        cursor: str | None = None,
    ) -> tuple[list[SaaSIntegration], str | None]:
        rows, next_cursor = await self._query_rows(
            "aq_saas_integration",
            _INTEGRATION_COLUMNS,
            tenant_id=tenant_id,
            filter_column="over_scoped",
            filter_value=validate_over_scoped_filter(over_scoped),
            limit=limit,
            cursor=cursor,
        )
        return [_row_to_integration(row) for row in rows], next_cursor

    async def _get_row(
        self,
        table: Literal["aq_saas_normalization", "aq_saas_integration"],
        columns: str,
        object_id: str,
        *,
        tenant_id: str | None,
    ) -> asyncpg.Record | None:
        selected_id = validate_object_id(object_id)
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        args: list[Any] = [selected_id]
        clauses = ["object_id=$1"]
        _add_tenant_clause(clauses, args, mode=self.mode, tenant_id=selected_tenant)
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(
                f"SELECT {columns} FROM {table} WHERE {' AND '.join(clauses)}",
                *args,
            )

    async def _query_rows(
        self,
        table: Literal["aq_saas_normalization", "aq_saas_integration"],
        columns: str,
        *,
        tenant_id: str | None,
        filter_column: Literal["provider", "over_scoped"],
        filter_value: str | None,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[asyncpg.Record], str | None]:
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        selected_limit = validate_query_limit(limit)
        selected_cursor = validate_query_cursor(cursor)
        args: list[Any] = []
        clauses: list[str] = []
        _add_tenant_clause(clauses, args, mode=self.mode, tenant_id=selected_tenant)
        if filter_value is not None:
            args.append(filter_value)
            clauses.append(f"{filter_column} = ${len(args)}")
        if selected_cursor is not None:
            args.append(selected_cursor)
            clauses.append(f"object_id > ${len(args)}")
        args.append(selected_limit + 1)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        async with self._pool.acquire() as conn:
            rows = list(
                await conn.fetch(
                    f"SELECT {columns} FROM {table} {where}ORDER BY object_id LIMIT ${len(args)}",
                    *args,
                )
            )
        has_more = len(rows) > selected_limit
        page = rows[:selected_limit]
        next_cursor = str(page[-1]["object_id"]) if has_more else None
        return page, next_cursor


def _add_tenant_clause(
    clauses: list[str],
    args: list[Any],
    *,
    mode: str,
    tenant_id: str | None,
) -> None:
    if mode == "local":
        clauses.append("tenant_id IS NULL")
    if tenant_id is not None:
        args.append(tenant_id)
        clauses.append(f"tenant_id = ${len(args)}")


async def _guard_tenant(
    conn: asyncpg.Connection,
    table: Literal["aq_saas_normalization", "aq_saas_integration"],
    object_id: str,
    tenant_id: str | None,
) -> None:
    row = await conn.fetchrow(
        f"SELECT tenant_id FROM {table} WHERE object_id=$1 FOR UPDATE",
        object_id,
    )
    if row is not None and row["tenant_id"] != tenant_id:
        raise CrossTenantReference("SaaS record tenant_id cannot change")


def _object_args(obj: NormalizedSaaSObject) -> tuple[Any, ...]:
    return (
        obj.object_id,
        obj.tenant_id,
        obj.object_type,
        obj.provider,
        obj.tenant,
        json.dumps(obj.native_facts),
        json.dumps(obj.field_provenance),
        json.dumps(obj.conflicts),
        obj.evidence_id,
        obj.flagged,
    )


def _integration_args(integration: SaaSIntegration) -> tuple[Any, ...]:
    return (
        integration.object_id,
        integration.tenant_id,
        integration.integration_id,
        integration.grantor_ref,
        integration.grantor_kind,
        integration.third_party_app,
        integration.third_party_external,
        json.dumps(integration.scopes),
        integration.over_scoped,
        json.dumps(integration.reachable_object_ids),
        integration.reach_status,
        integration.known_surface_ref,
        integration.claim_confidence,
        integration.evidence_id,
        integration.observed_at,
        integration.reason,
    )


def _row_to_object(row: asyncpg.Record) -> NormalizedSaaSObject:
    data: dict[str, Any] = dict(row)
    data["tenant"] = data.pop("provider_tenant")
    for key in ("native_facts", "field_provenance", "conflicts"):
        data[key] = _json_value(data[key])
    return NormalizedSaaSObject.model_validate(data)


def _row_to_integration(row: asyncpg.Record) -> SaaSIntegration:
    data: dict[str, Any] = dict(row)
    for key in ("scopes", "reachable_object_ids"):
        data[key] = _json_value(data[key])
    return SaaSIntegration.model_validate(data)


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value
