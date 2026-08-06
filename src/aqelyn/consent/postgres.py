"""PostgreSQL consent and audit stores — the durable production backend (ECR-0117).

Both share one asyncpg pool. Every query is scoped by ``tenant_id``. The audit log offers only
``append`` and ``list`` — there is deliberately no UPDATE or DELETE, so a recorded event cannot
be altered or erased through this store.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import asyncpg

from aqelyn.consent.ddl import DDL
from aqelyn.consent.models import AuditAction, AuditEvent, ConsentRecord, ConsentScope
from aqelyn.conventions.errors import StoreUnavailable
from aqelyn.conventions.ids import new_id


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _to_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _row_to_consent(row: asyncpg.Record) -> ConsentRecord:
    return ConsentRecord.model_validate(
        {
            "id": row["id"],
            "tenant_id": row["tenant_id"],
            "account_id": row["account_id"],
            "scope": row["scope"],
            "text_version": row["text_version"],
            "granted_at": row["granted_at"],
            "revoked_at": row["revoked_at"],
        }
    )


def _row_to_event(row: asyncpg.Record) -> AuditEvent:
    return AuditEvent.model_validate(
        {
            "id": row["id"],
            "tenant_id": row["tenant_id"],
            "actor_account_id": row["actor_account_id"],
            "action": row["action"],
            "detail": row["detail"],
            "at": row["at"],
        }
    )


async def connect_pool(url: str) -> asyncpg.Pool:
    """Create the shared consent/audit pool and apply the DDL."""

    try:
        pool = await asyncpg.create_pool(_to_dsn(url), min_size=1, max_size=5)
    except Exception as exc:
        raise StoreUnavailable(str(exc)) from exc
    assert pool is not None
    async with pool.acquire() as conn:
        await conn.execute(DDL)
    return pool


class PostgresConsentStore:
    def __init__(self, pool: asyncpg.Pool, *, now: Callable[[], datetime] = _utcnow) -> None:
        self._pool = pool
        self._now = now

    async def record(
        self, *, tenant_id: str, account_id: str, scope: ConsentScope, text_version: str
    ) -> ConsentRecord:
        record = ConsentRecord(
            id=new_id("con"),
            tenant_id=tenant_id,
            account_id=account_id,
            scope=scope,
            text_version=text_version,
            granted_at=self._now(),
        )
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO aq_consent_record "
                "(id, tenant_id, account_id, scope, text_version, granted_at, revoked_at) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                record.id,
                record.tenant_id,
                record.account_id,
                record.scope,
                record.text_version,
                record.granted_at,
                record.revoked_at,
            )
        return record

    async def active(self, *, tenant_id: str, scope: ConsentScope) -> ConsentRecord | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM aq_consent_record "
                "WHERE tenant_id=$1 AND scope=$2 AND revoked_at IS NULL "
                "ORDER BY granted_at DESC LIMIT 1",
                tenant_id,
                scope,
            )
            return None if row is None else _row_to_consent(row)

    async def revoke(self, *, tenant_id: str, scope: ConsentScope) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE aq_consent_record SET revoked_at=$3 "
                "WHERE tenant_id=$1 AND scope=$2 AND revoked_at IS NULL",
                tenant_id,
                scope,
                self._now(),
            )


class PostgresAuditLog:
    def __init__(self, pool: asyncpg.Pool, *, now: Callable[[], datetime] = _utcnow) -> None:
        self._pool = pool
        self._now = now

    async def append(
        self, *, tenant_id: str, actor_account_id: str, action: AuditAction, detail: str
    ) -> AuditEvent:
        event = AuditEvent(
            id=new_id("aud"),
            tenant_id=tenant_id,
            actor_account_id=actor_account_id,
            action=action,
            detail=detail,
            at=self._now(),
        )
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO aq_audit_event "
                "(id, tenant_id, actor_account_id, action, detail, at) "
                "VALUES ($1, $2, $3, $4, $5, $6)",
                event.id,
                event.tenant_id,
                event.actor_account_id,
                event.action,
                event.detail,
                event.at,
            )
        return event

    async def list(self, *, tenant_id: str) -> list[AuditEvent]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM aq_audit_event WHERE tenant_id=$1 ORDER BY seq", tenant_id
            )
            return [_row_to_event(row) for row in rows]
