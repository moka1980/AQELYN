"""Identity test harness — the same contract, proven against both backends (ECR-0116).

Every test runs twice: once on the in-memory backend, once on Postgres (skipped when
``AQELYN_DATABASE_URL`` is unset). A single movable clock is injected into all three stores so
expiry is deterministic without real sleeping. This is the whole point of "no API change" —
the identical test body must pass on either backend.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from aqelyn.identity.memory import (
    InMemoryAccountStore,
    InMemoryInviteStore,
    InMemorySessionStore,
)
from aqelyn.identity.store import AccountStore, InviteStore, SessionStore

PG_URL = os.getenv("AQELYN_DATABASE_URL")

TENANT_A = "11111111-1111-4111-8111-111111111111"
TENANT_B = "22222222-2222-4222-8222-222222222222"


class Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now = self.now + delta


@dataclass
class IdentityHarness:
    accounts: AccountStore
    invites: InviteStore
    sessions: SessionStore
    clock: Clock


@pytest.fixture(params=["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def identity(request: pytest.FixtureRequest) -> AsyncIterator[IdentityHarness]:
    clock = Clock(datetime(2026, 1, 1, 12, 0, tzinfo=UTC))

    if request.param == "inmemory":
        accounts = InMemoryAccountStore(now=clock)
        yield IdentityHarness(
            accounts=accounts,
            invites=InMemoryInviteStore(accounts, now=clock),
            sessions=InMemorySessionStore(now=clock),
            clock=clock,
        )
        return

    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    from aqelyn.identity.postgres import (
        PostgresAccountStore,
        PostgresInviteStore,
        connect_pool,
    )

    pool = await connect_pool(PG_URL)
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_account, aq_invite")
    try:
        yield IdentityHarness(
            accounts=PostgresAccountStore(pool, now=clock),
            invites=PostgresInviteStore(pool, now=clock),
            sessions=InMemorySessionStore(now=clock),
            clock=clock,
        )
    finally:
        await pool.close()
