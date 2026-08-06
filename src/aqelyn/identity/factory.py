"""Backend selection for identity — memory for local/tests, Postgres for durable production.

Mirrors the platform's ``backend`` switch (``memory`` | ``postgres``). Sessions are in-memory in
both backends: they are ephemeral by design (a restart requires re-login), so they do not live in
Postgres. Accounts and invites share one pool in the Postgres backend.
"""

from __future__ import annotations

from dataclasses import dataclass

from aqelyn.conventions.errors import ConfigError
from aqelyn.identity.memory import (
    InMemoryAccountStore,
    InMemoryInviteStore,
    InMemorySessionStore,
)
from aqelyn.identity.store import AccountStore, InviteStore, SessionStore


@dataclass
class IdentityStores:
    accounts: AccountStore
    invites: InviteStore
    sessions: SessionStore
    _closable: object | None = None

    async def close(self) -> None:
        pool = self._closable
        if pool is not None:
            await pool.close()  # type: ignore[attr-defined]


async def build_identity_stores(*, backend: str, database_url: str | None = None) -> IdentityStores:
    sessions = InMemorySessionStore()
    if backend == "memory":
        accounts = InMemoryAccountStore()
        return IdentityStores(
            accounts=accounts,
            invites=InMemoryInviteStore(accounts),
            sessions=sessions,
        )
    if backend == "postgres":
        if not database_url:
            raise ConfigError("postgres identity backend requires a database url")
        from aqelyn.identity.postgres import (
            PostgresAccountStore,
            PostgresInviteStore,
            connect_pool,
        )

        pool = await connect_pool(database_url)
        return IdentityStores(
            accounts=PostgresAccountStore(pool),
            invites=PostgresInviteStore(pool),
            sessions=sessions,
            _closable=pool,
        )
    raise ConfigError(f"unknown identity backend: {backend}")
