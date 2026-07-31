"""Postgres write shape for GC-004 backend-divergence control."""

from __future__ import annotations

from typing import Protocol

DDL = "CREATE TABLE aq_gc004_control (id text, ddl_only text, postgres_only text)"


class Connection(Protocol):
    async def execute(self, query: str, *args: object) -> str: ...


class PostgresControlStore:
    async def put(self, conn: Connection, identifier: str, value: str) -> None:
        await conn.execute(
            "INSERT INTO aq_gc004_control (id, postgres_only) VALUES ($1, $2)",
            identifier,
            value,
        )
