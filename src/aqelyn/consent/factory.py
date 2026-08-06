"""Backend selection for consent + audit — memory for local/tests, Postgres for production."""

from __future__ import annotations

from dataclasses import dataclass

from aqelyn.consent.memory import InMemoryAuditLog, InMemoryConsentStore
from aqelyn.consent.store import AuditLog, ConsentStore
from aqelyn.conventions.errors import ConfigError


@dataclass
class ConsentStores:
    consent: ConsentStore
    audit: AuditLog
    _closable: object | None = None

    async def close(self) -> None:
        pool = self._closable
        if pool is not None:
            await pool.close()  # type: ignore[attr-defined]


async def build_consent_stores(*, backend: str, database_url: str | None = None) -> ConsentStores:
    if backend == "memory":
        return ConsentStores(consent=InMemoryConsentStore(), audit=InMemoryAuditLog())
    if backend == "postgres":
        if not database_url:
            raise ConfigError("postgres consent backend requires a database url")
        from aqelyn.consent.postgres import (
            PostgresAuditLog,
            PostgresConsentStore,
            connect_pool,
        )

        pool = await connect_pool(database_url)
        return ConsentStores(
            consent=PostgresConsentStore(pool),
            audit=PostgresAuditLog(pool),
            _closable=pool,
        )
    raise ConfigError(f"unknown consent backend: {backend}")
