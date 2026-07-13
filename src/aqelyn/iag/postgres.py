"""PostgreSQL CertificationStore implementation (EA-0011 I3)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import asyncpg

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import (
    CertificationNotFound,
    CrossTenantReference,
    OptimisticConcurrencyConflict,
    StoreUnavailable,
    TenantScopeRequired,
)
from aqelyn.iag.ddl import DDL
from aqelyn.iag.models import Certification
from aqelyn.iag.store import (
    normalize_status_filter,
    validate_certification,
    validate_certification_id,
    validate_positive,
)

_COLS = "id, tenant_id, name, scope, status, items, created_by, created_at, due_at, version"


def _to_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _row_to_cert(row: asyncpg.Record) -> Certification:
    data: dict[str, Any] = dict(row)
    for key in ("scope", "items", "created_by"):
        data[key] = _json_value(data[key])
    return Certification.model_validate(data)


class PostgresCertificationStore:
    def __init__(self, pool: asyncpg.Pool, *, mode: str = "local") -> None:
        self._pool = pool
        self.mode = mode

    @classmethod
    async def connect(cls, url: str, **kw: Any) -> PostgresCertificationStore:
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

    async def put(
        self,
        cert: Certification,
        *,
        expected_version: int | None = None,
    ) -> Certification:
        stored = validate_certification(_materialize_ids(cert))
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                f"SELECT {_COLS} FROM aq_iag_certification WHERE id=$1 FOR UPDATE",
                stored.id,
            )
            if row is None:
                if expected_version is not None:
                    raise CertificationNotFound(stored.id)
                created = stored.model_copy(update={"version": 1}, deep=True)
                await _insert(conn, created)
                return created

            existing = _row_to_cert(row)
            expected = expected_version if expected_version is not None else stored.version
            validate_positive(expected, field="expected_version")
            if existing.tenant_id != stored.tenant_id:
                raise CrossTenantReference("certification tenant_id cannot change")
            if existing.version != expected:
                raise OptimisticConcurrencyConflict(
                    f"expected v{expected}, found v{existing.version}"
                )
            updated = stored.model_copy(
                update={
                    "version": existing.version + 1,
                    "created_by": existing.created_by,
                    "created_at": existing.created_at,
                },
                deep=True,
            )
            await conn.execute(
                "UPDATE aq_iag_certification "
                "SET name=$2, scope=$3, status=$4, items=$5, created_by=$6, "
                "created_at=$7, due_at=$8, version=$9 "
                "WHERE id=$1",
                updated.id,
                updated.name,
                json.dumps(updated.scope),
                updated.status,
                json.dumps([item.model_dump(mode="json") for item in updated.items]),
                json.dumps(updated.created_by.model_dump()),
                updated.created_at,
                updated.due_at,
                updated.version,
            )
            return updated

    async def get(self, cert_id: str) -> Certification | None:
        validate_certification_id(cert_id)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_COLS} FROM aq_iag_certification WHERE id=$1",
                cert_id,
            )
        return None if row is None else _row_to_cert(row)

    async def list(
        self,
        *,
        tenant_id: str | None,
        status: Sequence[str] | None = None,
    ) -> list[Certification]:
        if self.mode == "enterprise" and tenant_id is None:
            raise TenantScopeRequired("certification list must be tenant-scoped in enterprise mode")
        statuses = normalize_status_filter(status)
        clauses: list[str] = []
        args: list[Any] = []
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if tenant_id is not None:
            args.append(tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")
        if statuses is not None:
            args.append(list(statuses))
            clauses.append(f"status = ANY(${len(args)}::text[])")
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_COLS} FROM aq_iag_certification {where}ORDER BY id",
                *args,
            )
        return [_row_to_cert(row) for row in rows]


async def _insert(conn: asyncpg.Connection, cert: Certification) -> None:
    try:
        await conn.execute(
            f"INSERT INTO aq_iag_certification ({_COLS}) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
            cert.id,
            cert.tenant_id,
            cert.name,
            json.dumps(cert.scope),
            cert.status,
            json.dumps([item.model_dump(mode="json") for item in cert.items]),
            json.dumps(cert.created_by.model_dump()),
            cert.created_at,
            cert.due_at,
            cert.version,
        )
    except asyncpg.UniqueViolationError as exc:
        raise OptimisticConcurrencyConflict(f"certification already exists: {cert.id}") from exc


def _materialize_ids(cert: Certification) -> Certification:
    items = [
        item if item.id else item.model_copy(update={"id": new_id("rvi")}) for item in cert.items
    ]
    return cert.model_copy(update={"id": cert.id or new_id("cert"), "items": items}, deep=True)
