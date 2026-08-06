"""Consent/audit test harness — the same contract on both backends (ECR-0117)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from aqelyn.consent.memory import InMemoryAuditLog, InMemoryConsentStore
from aqelyn.consent.store import AuditLog, ConsentStore

PG_URL = os.getenv("AQELYN_DATABASE_URL")


class Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now = self.now + delta


@dataclass
class ConsentHarness:
    consent: ConsentStore
    audit: AuditLog
    clock: Clock


@pytest.fixture(params=["inmemory", "postgres"], ids=["inmemory", "postgres"])
async def consent(request: pytest.FixtureRequest) -> AsyncIterator[ConsentHarness]:
    clock = Clock(datetime(2026, 1, 1, 12, 0, tzinfo=UTC))

    if request.param == "inmemory":
        yield ConsentHarness(
            consent=InMemoryConsentStore(now=clock),
            audit=InMemoryAuditLog(now=clock),
            clock=clock,
        )
        return

    if not PG_URL:
        pytest.skip("AQELYN_DATABASE_URL not set")

    from aqelyn.consent.postgres import (
        PostgresAuditLog,
        PostgresConsentStore,
        connect_pool,
    )

    pool = await connect_pool(PG_URL)
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE aq_consent_record, aq_audit_event")
    try:
        yield ConsentHarness(
            consent=PostgresConsentStore(pool, now=clock),
            audit=PostgresAuditLog(pool, now=clock),
            clock=clock,
        )
    finally:
        await pool.close()
