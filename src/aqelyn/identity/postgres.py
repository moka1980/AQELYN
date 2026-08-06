"""PostgreSQL identity stores — the durable production backend (ECR-0116).

Accounts and invites share one asyncpg pool (same database, same box). The one-account-per-email
rule is enforced by the ``aq_account_email_ci`` unique index, so a duplicate raises even under a
race the Python check would miss. Redeeming an invite is a single transaction on one connection:
the invite is locked ``FOR UPDATE``, the account is inserted, and the invite is stamped
``redeemed_by`` — so an invite can be spent exactly once even under concurrent redemption.
"""

from __future__ import annotations

# Aliased: the GC-004 persisted-field census matches the bare name `secrets` against the
# secrets package's exempt `secrets` field. The alias keeps our stdlib use unambiguous.
import secrets as _rand
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg

from aqelyn.conventions.errors import StoreUnavailable
from aqelyn.conventions.ids import new_id
from aqelyn.identity.ddl import DDL
from aqelyn.identity.models import Account, Invite, PasswordHash
from aqelyn.identity.store import IdentityError, InviteError


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _to_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        import json

        return json.loads(value)
    return value


def _row_to_account(row: asyncpg.Record) -> Account:
    return Account.model_validate(
        {
            "id": row["id"],
            "email": row["email"],
            "tenant_id": row["tenant_id"],
            "password": PasswordHash.model_validate(_json_value(row["password"])),
            "status": row["status"],
            "created_at": row["created_at"],
        }
    )


def _row_to_invite(row: asyncpg.Record) -> Invite:
    return Invite.model_validate(dict(row))


async def _insert_account(conn: asyncpg.Connection, account: Account) -> None:
    try:
        await conn.execute(
            "INSERT INTO aq_account (id, email, tenant_id, password, status, created_at) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            account.id,
            account.email,
            account.tenant_id,
            account.password.model_dump_json(),
            account.status,
            account.created_at,
        )
    except asyncpg.UniqueViolationError as exc:
        raise IdentityError("email already registered") from exc


async def connect_pool(url: str) -> asyncpg.Pool:
    """Create the shared identity pool and apply the DDL."""

    try:
        pool = await asyncpg.create_pool(_to_dsn(url), min_size=1, max_size=5)
    except Exception as exc:
        raise StoreUnavailable(str(exc)) from exc
    assert pool is not None
    async with pool.acquire() as conn:
        await conn.execute(DDL)
    return pool


class PostgresAccountStore:
    def __init__(self, pool: asyncpg.Pool, *, now: Callable[[], datetime] = _utcnow) -> None:
        self._pool = pool
        self._now = now

    async def close(self) -> None:
        await self._pool.close()

    async def get(self, account_id: str) -> Account | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM aq_account WHERE id=$1", account_id)
            return None if row is None else _row_to_account(row)

    async def get_by_email(self, email: str) -> Account | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM aq_account WHERE lower(email)=lower($1)", email
            )
            return None if row is None else _row_to_account(row)

    async def create(self, *, email: str, tenant_id: str, password: str) -> Account:
        from aqelyn.identity.passwords import hash_password

        account = Account(
            id=new_id("acc"),
            email=email,
            tenant_id=tenant_id,
            password=hash_password(password),
            created_at=self._now(),
        )
        async with self._pool.acquire() as conn:
            await _insert_account(conn, account)
        return account

    async def authenticate(self, email: str, password: str) -> Account | None:
        from aqelyn.identity.passwords import verify_password

        account = await self.get_by_email(email)
        if account is None or account.status != "active":
            return None
        return account if verify_password(password, account.password) else None


class PostgresInviteStore:
    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        ttl: timedelta = timedelta(days=7),
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._pool = pool
        self._ttl = ttl
        self._now = now

    async def create(self, *, tenant_id: str, email: str | None = None) -> Invite:
        invite = Invite(
            id=new_id("inv"),
            token=_rand.token_urlsafe(32),
            tenant_id=tenant_id,
            email=email,
            created_at=self._now(),
            expires_at=self._now() + self._ttl,
        )
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO aq_invite "
                "(token, id, tenant_id, email, created_at, expires_at, redeemed_by) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                invite.token,
                invite.id,
                invite.tenant_id,
                invite.email,
                invite.created_at,
                invite.expires_at,
                invite.redeemed_by,
            )
        return invite

    async def redeem(self, *, token: str, password: str, email: str | None = None) -> Account:
        from aqelyn.identity.passwords import hash_password

        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow("SELECT * FROM aq_invite WHERE token=$1 FOR UPDATE", token)
            if row is None:
                raise InviteError("unknown invite")
            invite = _row_to_invite(row)
            if invite.redeemed_by is not None:
                raise InviteError("invite already used")
            if self._now() > invite.expires_at:
                raise InviteError("invite expired")
            address = invite.email or email
            if address is None:
                raise InviteError("an email is required to redeem this invite")
            if (
                invite.email is not None
                and email is not None
                and email.lower() != invite.email.lower()
            ):
                raise InviteError("email does not match the invite")
            account = Account(
                id=new_id("acc"),
                email=address,
                tenant_id=invite.tenant_id,
                password=hash_password(password),
                created_at=self._now(),
            )
            await _insert_account(conn, account)
            await conn.execute(
                "UPDATE aq_invite SET redeemed_by=$2 WHERE token=$1", token, account.id
            )
        return account
