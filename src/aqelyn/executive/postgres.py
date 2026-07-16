"""PostgreSQL Executive Intelligence stores (EA-0022 X2)."""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.conventions.errors import (
    FrozenReportMutation,
    KPIDefinitionNotFound,
    OptimisticConcurrencyConflict,
    StoreUnavailable,
)
from aqelyn.executive.ddl import DDL
from aqelyn.executive.definitions import (
    validate_definition,
    validate_definition_key,
    validate_promotion_reason,
)
from aqelyn.executive.models import ExecutiveReport, KPIDefinition, validate_limit, validate_version
from aqelyn.executive.store import (
    validate_period,
    validate_query_limit,
    validate_report,
    validate_report_id,
    validate_tenant,
)

_DEFINITION_COLS = (
    "id, kpi_key, version, title, inputs, combinator, unit, thresholds, "
    "promoted_by, promoted_at, active"
)
_REPORT_COLS = (
    "id, tenant_id, title, version, period, sections, exceptions, approval_status, "
    "issued_at, issued_by, content_hash, frozen, scope, excludes"
)


def _to_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _connect(url: str) -> asyncpg.Pool:
    try:
        pool = await asyncpg.create_pool(_to_dsn(url), min_size=1, max_size=5)
    except Exception as exc:
        raise StoreUnavailable(str(exc)) from exc
    assert pool is not None
    async with pool.acquire() as conn:
        await conn.execute(DDL)
    return pool


class PostgresKPIDefinitionStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, url: str) -> PostgresKPIDefinitionStore:
        return cls(await _connect(url))

    async def close(self) -> None:
        await self._pool.close()

    async def propose(self, definition: KPIDefinition, *, by: ActorRef) -> KPIDefinition:
        _ = by
        stored = validate_definition(definition)
        async with self._pool.acquire() as conn, conn.transaction():
            version = await conn.fetchval(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM aq_kpi_definition WHERE kpi_key=$1",
                stored.key,
            )
            proposed = stored.model_copy(
                update={
                    "id": new_id("kdf"),
                    "version": version,
                    "active": False,
                    "promoted_by": None,
                    "promoted_at": None,
                },
                deep=True,
            )
            try:
                await conn.execute(
                    "INSERT INTO aq_kpi_definition "
                    "(id, kpi_key, version, title, inputs, combinator, unit, thresholds, "
                    "promoted_by, promoted_at, active) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
                    *_definition_args(proposed),
                )
            except asyncpg.UniqueViolationError as exc:
                raise OptimisticConcurrencyConflict(
                    f"kpi definition version already exists: {proposed.key} v{proposed.version}"
                ) from exc
        return proposed

    async def promote(
        self,
        key: str,
        version: int,
        *,
        by: ActorRef,
        reason: str,
    ) -> KPIDefinition:
        selected_key = validate_definition_key(key)
        selected_version = validate_version(version)
        validate_promotion_reason(reason)
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                f"SELECT {_DEFINITION_COLS} FROM aq_kpi_definition "
                "WHERE kpi_key=$1 AND version=$2 FOR UPDATE",
                selected_key,
                selected_version,
            )
            if row is None:
                raise KPIDefinitionNotFound(
                    f"kpi definition not found: {selected_key} v{selected_version}"
                )
            selected = _row_to_definition(row)
            promoted = selected.model_copy(
                update={"active": True, "promoted_by": by, "promoted_at": utc_now()},
                deep=True,
            )
            stored = validate_definition(promoted)
            await conn.execute(
                "UPDATE aq_kpi_definition SET promoted_by=$3, promoted_at=$4, active=true "
                "WHERE kpi_key=$1 AND version=$2",
                selected_key,
                selected_version,
                _dump_json_or_none(stored.promoted_by),
                stored.promoted_at,
            )
        return stored

    async def active(self, key: str) -> KPIDefinition:
        selected_key = validate_definition_key(key)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_DEFINITION_COLS} FROM aq_kpi_definition "
                "WHERE kpi_key=$1 AND active=true ORDER BY version DESC LIMIT 1",
                selected_key,
            )
        if row is None:
            raise KPIDefinitionNotFound(f"active kpi definition not found: {selected_key}")
        return _row_to_definition(row)

    async def get(self, key: str, version: int) -> KPIDefinition | None:
        selected_key = validate_definition_key(key)
        selected_version = validate_version(version)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_DEFINITION_COLS} FROM aq_kpi_definition WHERE kpi_key=$1 AND version=$2",
                selected_key,
                selected_version,
            )
        return None if row is None else _row_to_definition(row)

    async def versions(self, key: str, *, limit: int = 100) -> list[KPIDefinition]:
        selected_key = validate_definition_key(key)
        selected_limit = validate_limit(limit)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_DEFINITION_COLS} FROM aq_kpi_definition "
                "WHERE kpi_key=$1 ORDER BY version LIMIT $2",
                selected_key,
                selected_limit,
            )
        return [_row_to_definition(row) for row in rows]


class PostgresReportStore:
    def __init__(self, pool: asyncpg.Pool, *, mode: str = "local") -> None:
        self._pool = pool
        self.mode = mode

    @classmethod
    async def connect(cls, url: str, *, mode: str = "local") -> PostgresReportStore:
        return cls(await _connect(url), mode=mode)

    async def close(self) -> None:
        await self._pool.close()

    async def put(self, report: ExecutiveReport) -> ExecutiveReport:
        stored = validate_report(report)
        async with self._pool.acquire() as conn, conn.transaction():
            existing = await conn.fetchrow(
                f"SELECT {_REPORT_COLS} FROM aq_executive_report WHERE id=$1 FOR UPDATE",
                stored.id,
            )
            if existing is not None and _row_to_report(existing).frozen:
                raise FrozenReportMutation(f"frozen report cannot be mutated: {stored.id}")
            if existing is None:
                try:
                    await conn.execute(
                        "INSERT INTO aq_executive_report "
                        "(id, tenant_id, title, version, period, sections, exceptions, "
                        "approval_status, issued_at, issued_by, content_hash, frozen, scope, "
                        "excludes) "
                        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)",
                        *_report_args(stored),
                    )
                except asyncpg.UniqueViolationError as exc:
                    raise OptimisticConcurrencyConflict(
                        f"report already exists: {stored.id}"
                    ) from exc
            else:
                await conn.execute(
                    "UPDATE aq_executive_report SET tenant_id=$2, title=$3, version=$4, "
                    "period=$5, sections=$6, exceptions=$7, approval_status=$8, "
                    "issued_at=$9, issued_by=$10, content_hash=$11, frozen=$12, "
                    "scope=$13, excludes=$14 WHERE id=$1",
                    *_report_args(stored),
                )
        return stored

    async def get(self, report_id: str, *, tenant_id: str | None = None) -> ExecutiveReport | None:
        validate_report_id(report_id)
        tenant_id = validate_tenant(tenant_id)
        args: list[Any] = [report_id]
        clauses = ["id=$1"]
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if tenant_id is not None:
            args.append(tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_REPORT_COLS} FROM aq_executive_report WHERE {' AND '.join(clauses)}",
                *args,
            )
        return None if row is None else _row_to_report(row)

    async def query(
        self, *, tenant_id: str | None, period: str | None = None, limit: int = 100
    ) -> list[ExecutiveReport]:
        tenant_id = validate_tenant(tenant_id)
        period = validate_period(period)
        validate_query_limit(limit)
        args: list[Any] = []
        clauses: list[str] = []
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if tenant_id is not None:
            args.append(tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")
        if period is not None:
            args.append(period)
            clauses.append(f"period = ${len(args)}")
        args.append(limit)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_REPORT_COLS} FROM aq_executive_report "
                f"{where}ORDER BY period, id LIMIT ${len(args)}",
                *args,
            )
        return [_row_to_report(row) for row in rows]


def _definition_args(definition: KPIDefinition) -> tuple[Any, ...]:
    return (
        definition.id,
        definition.key,
        definition.version,
        definition.title,
        json.dumps([item.model_dump(mode="json") for item in definition.inputs]),
        definition.combinator,
        definition.unit,
        json.dumps(definition.thresholds),
        _dump_json_or_none(definition.promoted_by),
        definition.promoted_at,
        definition.active,
    )


def _report_args(report: ExecutiveReport) -> tuple[Any, ...]:
    return (
        report.id,
        report.tenant_id,
        report.title,
        report.version,
        report.period,
        json.dumps([section.model_dump(mode="json") for section in report.sections]),
        json.dumps([figure.model_dump(mode="json") for figure in report.exceptions]),
        report.approval_status,
        report.issued_at,
        _dump_json_or_none(report.issued_by),
        report.content_hash,
        report.frozen,
        json.dumps(report.scope),
        json.dumps([exclude.model_dump(mode="json") for exclude in report.excludes]),
    )


def _row_to_definition(row: asyncpg.Record) -> KPIDefinition:
    data: dict[str, Any] = dict(row)
    data["key"] = data.pop("kpi_key")
    for key in ("inputs", "thresholds", "promoted_by"):
        data[key] = _json_value(data[key])
    data["thresholds"] = dict(
        sorted(data["thresholds"].items(), key=lambda item: float(item[1]), reverse=True)
    )
    return KPIDefinition.model_validate(data)


def _row_to_report(row: asyncpg.Record) -> ExecutiveReport:
    data: dict[str, Any] = dict(row)
    for key in ("sections", "exceptions", "issued_by", "scope", "excludes"):
        data[key] = _json_value(data[key])
    return ExecutiveReport.model_validate(data)


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


def _dump_json_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return json.dumps(value.model_dump(mode="json"))
    return json.dumps(value)
