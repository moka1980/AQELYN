"""PostgreSQL threat source registry (EA-0014 T2)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import asyncpg

from aqelyn.conventions import ActorRef, utc_now
from aqelyn.conventions.errors import StoreUnavailable
from aqelyn.threat.ddl import DDL
from aqelyn.threat.models import ThreatSource
from aqelyn.threat.registry import InMemoryThreatSourceRegistry, _source_key

_COLS = "source_id, reliability, meta, set_by, set_at, version"


def _to_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _row_to_source(row: asyncpg.Record) -> ThreatSource:
    data: dict[str, Any] = dict(row)
    data["meta"] = _json_value(data["meta"])
    data["set_by"] = _json_value(data["set_by"])
    return ThreatSource.model_validate(data)


class PostgresThreatSourceRegistry:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._default = InMemoryThreatSourceRegistry()

    @classmethod
    async def connect(cls, url: str) -> PostgresThreatSourceRegistry:
        try:
            pool = await asyncpg.create_pool(_to_dsn(url), min_size=1, max_size=5)
        except Exception as exc:
            raise StoreUnavailable(str(exc)) from exc
        assert pool is not None
        async with pool.acquire() as conn:
            await conn.execute(DDL)
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    async def get(self, source_id: str) -> ThreatSource:
        key = _source_key(source_id)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_COLS} FROM aq_threat_source WHERE source_id=$1", key
            )
        if row is None:
            return await self._default.get(key)
        return _row_to_source(row)

    async def set(
        self,
        source_id: str,
        *,
        reliability: float,
        meta: Mapping[str, Any],
        by: ActorRef,
    ) -> ThreatSource:
        stored = ThreatSource(
            source_id=_source_key(source_id),
            reliability=reliability,
            meta=dict(meta),
            set_by=by,
            set_at=utc_now(),
            version=1,
        )
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"INSERT INTO aq_threat_source ({_COLS}) VALUES ($1,$2,$3,$4,$5,$6) "
                "ON CONFLICT (source_id) DO UPDATE SET "
                "reliability=EXCLUDED.reliability, meta=EXCLUDED.meta, "
                "set_by=EXCLUDED.set_by, set_at=EXCLUDED.set_at, "
                "version=aq_threat_source.version + 1 "
                f"RETURNING {_COLS}",
                stored.source_id,
                stored.reliability,
                json.dumps(stored.meta),
                json.dumps(stored.set_by.model_dump(mode="json")),
                stored.set_at,
                stored.version,
            )
        assert row is not None
        return _row_to_source(row)

    async def list(self) -> list[ThreatSource]:
        default_entries = await self._default.list()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(f"SELECT {_COLS} FROM aq_threat_source ORDER BY source_id")
        stored = [_row_to_source(row) for row in rows]
        return [*default_entries, *stored]
