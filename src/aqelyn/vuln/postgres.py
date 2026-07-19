"""PostgreSQL VulnerabilityStore implementation (EA-0024 V2)."""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from aqelyn.conventions.errors import CrossTenantReference, StoreUnavailable
from aqelyn.vuln.ddl import DDL
from aqelyn.vuln.models import DispositionKind, VulnerabilityRecord
from aqelyn.vuln.store import (
    validate_asset_ref_filter,
    validate_cve_filter,
    validate_disposition_filter,
    validate_query_limit,
    validate_tenant,
    validate_vulnerability,
    validate_vulnerability_id,
)

_VULN_COLS = (
    "id, tenant_id, cve_id, scanner, asset_ref, severity, cvss, epss, confidence, "
    "basis, disposition, discovered_at, status"
)


def _to_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


async def _connect(url: str) -> asyncpg.Pool:
    try:
        pool = await asyncpg.create_pool(_to_dsn(url), min_size=1, max_size=5)
    except Exception as exc:
        raise StoreUnavailable(str(exc)) from exc
    assert pool is not None
    async with pool.acquire() as conn:
        await conn.execute(DDL)
    return pool


class PostgresVulnerabilityStore:
    def __init__(self, pool: asyncpg.Pool, *, mode: str = "local") -> None:
        self._pool = pool
        self.mode = mode

    @classmethod
    async def connect(cls, url: str, *, mode: str = "local") -> PostgresVulnerabilityStore:
        return cls(await _connect(url), mode=mode)

    async def close(self) -> None:
        await self._pool.close()

    async def put(self, vulnerability: VulnerabilityRecord) -> VulnerabilityRecord:
        stored = validate_vulnerability(vulnerability)
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                f"SELECT {_VULN_COLS} FROM aq_vuln_record WHERE id=$1 FOR UPDATE",
                stored.id,
            )
            if row is not None:
                existing = _row_to_vulnerability(row)
                if existing.tenant_id != stored.tenant_id:
                    raise CrossTenantReference("vulnerability tenant_id cannot change")
                await _update_vulnerability(conn, stored)
            else:
                await _insert_vulnerability(conn, stored)
            await _history(conn, stored)
        return stored

    async def get(
        self, vulnerability_id: str, *, tenant_id: str | None = None
    ) -> VulnerabilityRecord | None:
        validate_vulnerability_id(vulnerability_id)
        selected_tenant = validate_tenant(tenant_id)
        args: list[Any] = [vulnerability_id]
        clauses = ["id=$1"]
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if selected_tenant is not None:
            args.append(selected_tenant)
            clauses.append(f"tenant_id = ${len(args)}")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_VULN_COLS} FROM aq_vuln_record WHERE {' AND '.join(clauses)}",
                *args,
            )
        return None if row is None else _row_to_vulnerability(row)

    async def query(
        self,
        *,
        tenant_id: str | None,
        cve_id: str | None = None,
        asset_ref_id: str | None = None,
        disposition: DispositionKind | None = None,
        limit: int = 100,
    ) -> list[VulnerabilityRecord]:
        selected_tenant = validate_tenant(tenant_id)
        selected_cve_id = validate_cve_filter(cve_id)
        selected_asset_ref_id = validate_asset_ref_filter(asset_ref_id)
        selected_disposition = validate_disposition_filter(disposition)
        selected_limit = validate_query_limit(limit)
        args: list[Any] = []
        clauses: list[str] = []
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if selected_tenant is not None:
            args.append(selected_tenant)
            clauses.append(f"tenant_id = ${len(args)}")
        if selected_cve_id is not None:
            args.append(selected_cve_id)
            clauses.append(f"cve_id = ${len(args)}")
        if selected_asset_ref_id is not None:
            args.append(selected_asset_ref_id)
            clauses.append(f"asset_ref->>'ref_id' = ${len(args)}")
        if selected_disposition is not None:
            args.append(selected_disposition)
            clauses.append(f"disposition->>'kind' = ${len(args)}")
        args.append(selected_limit)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_VULN_COLS} FROM aq_vuln_record "
                f"{where}ORDER BY discovered_at, id LIMIT ${len(args)}",
                *args,
            )
        return [_row_to_vulnerability(row) for row in rows]

    async def history(self, vulnerability_id: str) -> list[dict[str, Any]]:
        validate_vulnerability_id(vulnerability_id)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT seq, vulnerability_id, snapshot, changed_at "
                "FROM aq_vuln_history WHERE vulnerability_id=$1 ORDER BY seq",
                vulnerability_id,
            )
        return [_history_row(row) for row in rows]


async def _insert_vulnerability(
    conn: asyncpg.Connection, vulnerability: VulnerabilityRecord
) -> None:
    await conn.execute(
        f"INSERT INTO aq_vuln_record ({_VULN_COLS}) VALUES "
        "($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)",
        *_vulnerability_args(vulnerability),
    )


async def _update_vulnerability(
    conn: asyncpg.Connection, vulnerability: VulnerabilityRecord
) -> None:
    await conn.execute(
        "UPDATE aq_vuln_record SET "
        "tenant_id=$2, cve_id=$3, scanner=$4, asset_ref=$5, severity=$6, cvss=$7, "
        "epss=$8, confidence=$9, basis=$10, disposition=$11, discovered_at=$12, "
        "status=$13 WHERE id=$1",
        *_vulnerability_args(vulnerability),
    )


async def _history(conn: asyncpg.Connection, vulnerability: VulnerabilityRecord) -> None:
    await conn.execute(
        "INSERT INTO aq_vuln_history (vulnerability_id, snapshot) VALUES ($1,$2)",
        vulnerability.id,
        json.dumps(vulnerability.model_dump(mode="json")),
    )


def _vulnerability_args(vulnerability: VulnerabilityRecord) -> tuple[Any, ...]:
    return (
        vulnerability.id,
        vulnerability.tenant_id,
        vulnerability.cve_id,
        vulnerability.scanner,
        json.dumps(vulnerability.asset_ref.model_dump(mode="json")),
        vulnerability.severity,
        json.dumps(vulnerability.cvss.model_dump(mode="json")),
        _dump_json_or_none(vulnerability.epss),
        vulnerability.confidence,
        json.dumps([basis.model_dump(mode="json") for basis in vulnerability.basis]),
        _dump_json_or_none(vulnerability.disposition),
        vulnerability.discovered_at,
        vulnerability.status,
    )


def _row_to_vulnerability(row: asyncpg.Record) -> VulnerabilityRecord:
    data: dict[str, Any] = dict(row)
    for key in ("asset_ref", "cvss", "epss", "basis", "disposition"):
        data[key] = _json_value(data[key])
    return VulnerabilityRecord.model_validate(data)


def _history_row(row: asyncpg.Record) -> dict[str, Any]:
    data: dict[str, Any] = dict(row)
    data["snapshot"] = _json_value(data["snapshot"])
    return data


def _dump_json_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return json.dumps(value.model_dump(mode="json"))
    return json.dumps(value)
