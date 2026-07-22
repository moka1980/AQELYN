"""PostgreSQL append-only ISPM store (EA-0033 G2)."""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from aqelyn.conventions.errors import (
    CrossTenantReference,
    ISPMConfigInvalid,
    StoreUnavailable,
)
from aqelyn.ispm.ddl import DDL
from aqelyn.ispm.models import NormalizedIdentity, NormalizedIdentityKind
from aqelyn.ispm.store import (
    validate_cursor,
    validate_external_id,
    validate_identity,
    validate_identity_kind,
    validate_limit,
    validate_object_id,
    validate_provider,
    validate_tenant_scope,
    validate_write_tenant,
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


class PostgresISPMStore:
    def __init__(self, pool: asyncpg.Pool, *, mode: str = "local") -> None:
        self._pool = pool
        self.mode = mode

    @classmethod
    async def connect(cls, url: str, *, mode: str = "local") -> PostgresISPMStore:
        return cls(await _connect(url), mode=mode)

    async def close(self) -> None:
        await self._pool.close()

    async def upsert_identity(self, identity: NormalizedIdentity) -> NormalizedIdentity:
        stored = validate_identity(identity)
        validate_write_tenant(stored.tenant_id, mode=self.mode)
        payload = stored.model_dump(mode="json")
        async with self._pool.acquire() as conn, conn.transaction():
            mapped = await conn.fetchrow(
                "SELECT id FROM aq_ispm_identity_key "
                "WHERE tenant_id IS NOT DISTINCT FROM $1 AND provider=$2 AND external_id=$3",
                stored.tenant_id,
                stored.provider,
                stored.external_id,
            )
            if mapped is not None and str(mapped["id"]) != stored.object_id:
                raise ISPMConfigInvalid("normalized identity key cannot change object_id")
            id_row = await conn.fetchrow(
                "SELECT tenant_id, provider, external_id FROM aq_ispm_identity_key WHERE id=$1",
                stored.object_id,
            )
            if id_row is not None:
                if id_row["tenant_id"] != stored.tenant_id:
                    raise CrossTenantReference("normalized identity tenant_id cannot change")
                if (
                    str(id_row["provider"]) != stored.provider
                    or str(id_row["external_id"]) != stored.external_id
                ):
                    raise ISPMConfigInvalid(
                        "normalized identity object_id cannot change identity key"
                    )
            else:
                try:
                    await conn.execute(
                        "INSERT INTO aq_ispm_identity_key "
                        "(id, tenant_id, provider, external_id) VALUES ($1,$2,$3,$4)",
                        stored.object_id,
                        stored.tenant_id,
                        stored.provider,
                        stored.external_id,
                    )
                except asyncpg.UniqueViolationError as exc:
                    raise ISPMConfigInvalid(
                        "normalized identity key already belongs to another object"
                    ) from exc
            latest = await conn.fetchrow(
                "SELECT record FROM aq_ispm_identity_revision "
                "WHERE id=$1 ORDER BY revision DESC LIMIT 1",
                stored.object_id,
            )
            if latest is not None:
                current = _identity_from_payload(latest["record"])
                if current.model_dump(mode="json") == payload:
                    return current
            await conn.execute(
                "INSERT INTO aq_ispm_identity_revision "
                "(id, tenant_id, provider, identity_kind, record) VALUES ($1,$2,$3,$4,$5)",
                stored.object_id,
                stored.tenant_id,
                stored.provider,
                stored.identity_kind,
                json.dumps(payload),
            )
        return stored.model_copy(deep=True)

    async def get_identity(
        self,
        object_id: str,
        *,
        tenant_id: str | None,
    ) -> NormalizedIdentity | None:
        selected_id = validate_object_id(object_id)
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        args: list[Any] = [selected_id]
        clauses = ["id=$1"]
        self._tenant_clauses(clauses, args, selected_tenant)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT record FROM aq_ispm_identity_revision "
                f"WHERE {' AND '.join(clauses)} ORDER BY revision DESC LIMIT 1",
                *args,
            )
        return None if row is None else _identity_from_payload(row["record"])

    async def get_identity_by_external(
        self,
        provider: str,
        external_id: str,
        *,
        tenant_id: str | None,
    ) -> NormalizedIdentity | None:
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        selected_provider = validate_provider(provider)
        if selected_provider is None:
            raise ISPMConfigInvalid("provider must not be empty")
        selected_external = validate_external_id(external_id)
        args: list[Any] = [selected_provider, selected_external]
        clauses = ["provider=$1", "external_id=$2"]
        self._tenant_clauses(clauses, args, selected_tenant)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT id FROM aq_ispm_identity_key WHERE {' AND '.join(clauses)}",
                *args,
            )
            if row is None:
                return None
            revision = await conn.fetchrow(
                "SELECT record FROM aq_ispm_identity_revision "
                "WHERE id=$1 ORDER BY revision DESC LIMIT 1",
                row["id"],
            )
        return None if revision is None else _identity_from_payload(revision["record"])

    async def query_identities(
        self,
        *,
        tenant_id: str | None,
        provider: str | None = None,
        identity_kind: NormalizedIdentityKind | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> tuple[list[NormalizedIdentity], str | None]:
        selected_tenant = validate_tenant_scope(tenant_id, mode=self.mode)
        selected_provider = validate_provider(provider)
        selected_kind = validate_identity_kind(identity_kind)
        selected_cursor = validate_cursor(cursor)
        selected_limit = validate_limit(limit)
        args: list[Any] = []
        inner: list[str] = []
        self._tenant_clauses(inner, args, selected_tenant)
        outer: list[str] = []
        if selected_provider is not None:
            args.append(selected_provider)
            outer.append(f"provider=${len(args)}")
        if selected_kind is not None:
            args.append(selected_kind)
            outer.append(f"identity_kind=${len(args)}")
        if selected_cursor is not None:
            args.append(selected_cursor)
            outer.append(f"id>${len(args)}")
        args.append(selected_limit + 1)
        inner_where = f"WHERE {' AND '.join(inner)}" if inner else ""
        outer_where = f"WHERE {' AND '.join(outer)}" if outer else ""
        async with self._pool.acquire() as conn:
            rows = list(
                await conn.fetch(
                    "WITH latest AS ("
                    "SELECT DISTINCT ON (id) id, provider, identity_kind, record "
                    "FROM aq_ispm_identity_revision "
                    f"{inner_where} ORDER BY id, revision DESC"
                    ") SELECT id, record FROM latest "
                    f"{outer_where} ORDER BY id LIMIT ${len(args)}",
                    *args,
                )
            )
        has_more = len(rows) > selected_limit
        page = rows[:selected_limit]
        next_cursor = str(page[-1]["id"]) if has_more else None
        return [_identity_from_payload(row["record"]) for row in page], next_cursor

    def _tenant_clauses(
        self,
        clauses: list[str],
        args: list[Any],
        tenant_id: str | None,
    ) -> None:
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        else:
            args.append(tenant_id)
            clauses.append(f"tenant_id=${len(args)}")


def _identity_from_payload(payload: object) -> NormalizedIdentity:
    if isinstance(payload, str):
        payload = json.loads(payload)
    return NormalizedIdentity.model_validate(payload)
