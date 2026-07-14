"""PostgreSQL SOCStore implementation (EA-0015 S2)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import asyncpg

from aqelyn.conventions import new_id, utc_now
from aqelyn.conventions.errors import (
    CrossTenantReference,
    OptimisticConcurrencyConflict,
    StoreUnavailable,
    TenantScopeRequired,
)
from aqelyn.soc.ddl import DDL
from aqelyn.soc.models import Alert, Incident
from aqelyn.soc.store import (
    normalize_status_filter,
    validate_alert,
    validate_alert_id,
    validate_incident,
    validate_incident_id,
    validate_positive,
    validate_tenant,
)

_ALERT_COLS = (
    "id, tenant_id, source_kind, source_ref, evidence_id, severity, state, "
    "correlation_key, created_at, version"
)
_INCIDENT_COLS = (
    "id, tenant_id, title, status, priority, alert_ids, affected_object_ids, "
    "top_mission_id, risk_score, assignee, timeline, created_by, created_at, updated_at, version"
)


def _to_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _row_to_alert(row: asyncpg.Record) -> Alert:
    return Alert.model_validate(dict(row))


def _row_to_incident(row: asyncpg.Record) -> Incident:
    data: dict[str, Any] = dict(row)
    for key in ("alert_ids", "affected_object_ids", "assignee", "timeline", "created_by"):
        data[key] = _json_value(data[key])
    return Incident.model_validate(data)


class PostgresSOCStore:
    def __init__(self, pool: asyncpg.Pool, *, mode: str = "local") -> None:
        self._pool = pool
        self.mode = mode

    @classmethod
    async def connect(cls, url: str, **kw: Any) -> PostgresSOCStore:
        try:
            pool = await asyncpg.create_pool(_to_dsn(url), min_size=1, max_size=5)
        except Exception as exc:
            raise StoreUnavailable(str(exc)) from exc
        assert pool is not None
        async with pool.acquire() as conn:
            await conn.execute(DDL)
        return cls(pool, **kw)

    async def close(self) -> None:
        await self._pool.close()

    async def upsert_alert(self, alert: Alert) -> Alert:
        stored = validate_alert(alert)
        if not stored.id:
            stored.id = new_id("alt")
        validate_alert_id(stored.id, field="id")
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                f"SELECT {_ALERT_COLS} FROM aq_soc_alert "
                "WHERE id=$1 OR (tenant_id IS NOT DISTINCT FROM $2 AND source_ref=$3) "
                "ORDER BY CASE WHEN id=$1 THEN 0 ELSE 1 END "
                "LIMIT 1 FOR UPDATE",
                stored.id,
                stored.tenant_id,
                stored.source_ref,
            )
            if row is None:
                created = stored.model_copy(update={"version": 1}, deep=True)
                await _insert_alert(conn, created)
                return created

            existing = _row_to_alert(row)
            if (existing.tenant_id, existing.source_ref) != (stored.tenant_id, stored.source_ref):
                raise CrossTenantReference("alert tenant_id/source_ref cannot change")
            updated = stored.model_copy(
                update={
                    "id": existing.id,
                    "created_at": existing.created_at,
                    "version": existing.version + 1,
                },
                deep=True,
            )
            await _update_alert(conn, updated)
            return updated

    async def upsert_incident(self, incident: Incident) -> Incident:
        stored = validate_incident(incident)
        if not stored.id:
            stored.id = new_id("inc")
        validate_incident_id(stored.id, field="id")
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                f"SELECT {_INCIDENT_COLS} FROM aq_soc_incident WHERE id=$1 FOR UPDATE",
                stored.id,
            )
            if row is None:
                created = stored.model_copy(update={"version": 1}, deep=True)
                await _insert_incident(conn, created)
                return created

            existing = _row_to_incident(row)
            if existing.tenant_id != stored.tenant_id:
                raise CrossTenantReference("incident tenant_id cannot change")
            validate_positive(stored.version, field="version")
            if existing.version != stored.version:
                raise OptimisticConcurrencyConflict(
                    f"expected v{stored.version}, found v{existing.version}"
                )
            updated = stored.model_copy(
                update={
                    "created_at": existing.created_at,
                    "updated_at": max(utc_now(), existing.updated_at, stored.updated_at),
                    "version": existing.version + 1,
                },
                deep=True,
            )
            await _update_incident(conn, updated)
            return updated

    async def get_incident(
        self,
        incident_id: str,
        *,
        tenant_id: str | None = None,
    ) -> Incident | None:
        validate_incident_id(incident_id)
        tenant_id = validate_tenant(tenant_id)
        clauses = ["id = $1"]
        args: list[Any] = [incident_id]
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if tenant_id is not None:
            args.append(tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_INCIDENT_COLS} FROM aq_soc_incident WHERE {' AND '.join(clauses)}",
                *args,
            )
        return None if row is None else _row_to_incident(row)

    async def query_incidents(
        self,
        *,
        tenant_id: str | None,
        status: Sequence[str] | None = None,
        limit: int = 100,
    ) -> list[Incident]:
        tenant_id = validate_tenant(tenant_id)
        statuses = normalize_status_filter(status)
        validate_positive(limit, field="limit")
        if self.mode == "enterprise" and tenant_id is None:
            raise TenantScopeRequired("incident query must be tenant-scoped in enterprise mode")

        args: list[Any] = []
        clauses: list[str] = []
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if tenant_id is not None:
            args.append(tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")
        if statuses is not None:
            args.append(list(statuses))
            clauses.append(f"status = ANY(${len(args)}::text[])")
        args.append(limit)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        sql = (
            f"SELECT {_INCIDENT_COLS} FROM aq_soc_incident {where}"
            f"ORDER BY priority DESC, updated_at DESC, id LIMIT ${len(args)}"
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        return [_row_to_incident(row) for row in rows]


async def _insert_alert(conn: asyncpg.Connection, alert: Alert) -> None:
    try:
        await conn.execute(
            f"INSERT INTO aq_soc_alert ({_ALERT_COLS}) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
            *_alert_args(alert),
        )
    except asyncpg.UniqueViolationError as exc:
        raise OptimisticConcurrencyConflict(f"alert already exists: {alert.id}") from exc


async def _update_alert(conn: asyncpg.Connection, alert: Alert) -> None:
    await conn.execute(
        "UPDATE aq_soc_alert SET tenant_id=$2, source_kind=$3, source_ref=$4, "
        "evidence_id=$5, severity=$6, state=$7, correlation_key=$8, created_at=$9, "
        "version=$10 WHERE id=$1",
        *_alert_args(alert),
    )


async def _insert_incident(conn: asyncpg.Connection, incident: Incident) -> None:
    try:
        await conn.execute(
            f"INSERT INTO aq_soc_incident ({_INCIDENT_COLS}) VALUES "
            "($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)",
            *_incident_args(incident),
        )
    except asyncpg.UniqueViolationError as exc:
        raise OptimisticConcurrencyConflict(f"incident already exists: {incident.id}") from exc


async def _update_incident(conn: asyncpg.Connection, incident: Incident) -> None:
    await conn.execute(
        "UPDATE aq_soc_incident SET tenant_id=$2, title=$3, status=$4, priority=$5, "
        "alert_ids=$6, affected_object_ids=$7, top_mission_id=$8, risk_score=$9, "
        "assignee=$10, timeline=$11, created_by=$12, created_at=$13, updated_at=$14, "
        "version=$15 WHERE id=$1",
        *_incident_args(incident),
    )


def _alert_args(alert: Alert) -> tuple[Any, ...]:
    return (
        alert.id,
        alert.tenant_id,
        alert.source_kind,
        alert.source_ref,
        alert.evidence_id,
        alert.severity,
        alert.state,
        alert.correlation_key,
        alert.created_at,
        alert.version,
    )


def _incident_args(incident: Incident) -> tuple[Any, ...]:
    return (
        incident.id,
        incident.tenant_id,
        incident.title,
        incident.status,
        incident.priority,
        json.dumps(incident.alert_ids),
        json.dumps(incident.affected_object_ids),
        incident.top_mission_id,
        incident.risk_score,
        None if incident.assignee is None else json.dumps(incident.assignee.model_dump()),
        json.dumps([entry.model_dump(mode="json") for entry in incident.timeline]),
        json.dumps(incident.created_by.model_dump()),
        incident.created_at,
        incident.updated_at,
        incident.version,
    )
