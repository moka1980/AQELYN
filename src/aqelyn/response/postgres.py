"""PostgreSQL Response Orchestration stores (EA-0018 R2)."""

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
from aqelyn.response.ddl import DDL
from aqelyn.response.models import AutomationTrigger, ResponseCampaign
from aqelyn.response.store import (
    normalize_campaign_status_filter,
    validate_campaign,
    validate_campaign_id,
    validate_positive,
    validate_tenant,
    validate_trigger,
    validate_trigger_id,
)

_CAMPAIGN_COLS = (
    "id, tenant_id, incident_id, source_finding_id, phases, status, created_by, "
    "created_at, updated_at, evidence_ids, version"
)
_TRIGGER_COLS = "id, tenant_id, name, condition, playbook_id, max_effect, enabled, version"


def _to_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _row_to_campaign(row: asyncpg.Record) -> ResponseCampaign:
    data: dict[str, Any] = dict(row)
    for key in ("phases", "created_by", "evidence_ids"):
        data[key] = _json_value(data[key])
    return ResponseCampaign.model_validate(data)


def _row_to_trigger(row: asyncpg.Record) -> AutomationTrigger:
    data: dict[str, Any] = dict(row)
    data["condition"] = _json_value(data["condition"])
    return AutomationTrigger.model_validate(data)


class PostgresCampaignStore:
    def __init__(self, pool: asyncpg.Pool, *, mode: str = "local") -> None:
        self._pool = pool
        self.mode = mode

    @classmethod
    async def connect(cls, url: str, **kw: Any) -> PostgresCampaignStore:
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

    async def upsert(self, campaign: ResponseCampaign) -> ResponseCampaign:
        stored = validate_campaign(campaign)
        if not stored.id:
            stored.id = new_id("rsp")
        validate_campaign_id(stored.id, field="id")
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                f"SELECT {_CAMPAIGN_COLS} FROM aq_response_campaign WHERE id=$1 FOR UPDATE",
                stored.id,
            )
            if row is None:
                created = stored.model_copy(update={"version": 1}, deep=True)
                await _insert_campaign(conn, created)
                return created

            existing = _row_to_campaign(row)
            if existing.tenant_id != stored.tenant_id:
                raise CrossTenantReference("campaign tenant_id cannot change")
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
            await _update_campaign(conn, updated)
            return updated

    async def get(
        self,
        campaign_id: str,
        *,
        tenant_id: str | None = None,
    ) -> ResponseCampaign | None:
        validate_campaign_id(campaign_id)
        tenant_id = validate_tenant(tenant_id)
        clauses = ["id = $1"]
        args: list[Any] = [campaign_id]
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if tenant_id is not None:
            args.append(tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_CAMPAIGN_COLS} FROM aq_response_campaign WHERE {' AND '.join(clauses)}",
                *args,
            )
        return None if row is None else _row_to_campaign(row)

    async def query(
        self,
        *,
        tenant_id: str | None,
        status: Sequence[str] | None = None,
        limit: int = 100,
    ) -> list[ResponseCampaign]:
        tenant_id = validate_tenant(tenant_id)
        statuses = normalize_campaign_status_filter(status)
        validate_positive(limit, field="limit")
        if self.mode == "enterprise" and tenant_id is None:
            raise TenantScopeRequired("campaign query must be tenant-scoped in enterprise mode")

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
            f"SELECT {_CAMPAIGN_COLS} FROM aq_response_campaign {where}"
            f"ORDER BY updated_at DESC, id LIMIT ${len(args)}"
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        return [_row_to_campaign(row) for row in rows]


class PostgresTriggerStore:
    def __init__(self, pool: asyncpg.Pool, *, mode: str = "local") -> None:
        self._pool = pool
        self.mode = mode

    @classmethod
    async def connect(cls, url: str, **kw: Any) -> PostgresTriggerStore:
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

    async def put(self, trigger: AutomationTrigger) -> AutomationTrigger:
        stored = validate_trigger(trigger)
        if not stored.id:
            stored.id = new_id("trg")
        validate_trigger_id(stored.id, field="id")
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                f"SELECT {_TRIGGER_COLS} FROM aq_response_trigger WHERE id=$1 FOR UPDATE",
                stored.id,
            )
            if row is None:
                created = stored.model_copy(update={"version": 1}, deep=True)
                await _insert_trigger(conn, created)
                return created

            existing = _row_to_trigger(row)
            if existing.tenant_id != stored.tenant_id:
                raise CrossTenantReference("trigger tenant_id cannot change")
            validate_positive(stored.version, field="version")
            if existing.version != stored.version:
                raise OptimisticConcurrencyConflict(
                    f"expected v{stored.version}, found v{existing.version}"
                )
            updated = stored.model_copy(update={"version": existing.version + 1}, deep=True)
            await _update_trigger(conn, updated)
            return updated

    async def list(
        self,
        *,
        tenant_id: str | None,
        enabled_only: bool = True,
    ) -> list[AutomationTrigger]:
        tenant_id = validate_tenant(tenant_id)
        if self.mode == "enterprise" and tenant_id is None:
            raise TenantScopeRequired("trigger list must be tenant-scoped in enterprise mode")
        args: list[Any] = []
        clauses: list[str] = []
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if tenant_id is not None:
            args.append(tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")
        if enabled_only:
            clauses.append("enabled = true")
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_TRIGGER_COLS} FROM aq_response_trigger {where}ORDER BY id",
                *args,
            )
        return [_row_to_trigger(row) for row in rows]


async def _insert_campaign(conn: asyncpg.Connection, campaign: ResponseCampaign) -> None:
    try:
        await conn.execute(
            f"INSERT INTO aq_response_campaign ({_CAMPAIGN_COLS}) VALUES "
            "($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
            *_campaign_args(campaign),
        )
    except asyncpg.UniqueViolationError as exc:
        raise OptimisticConcurrencyConflict(f"campaign already exists: {campaign.id}") from exc


async def _update_campaign(conn: asyncpg.Connection, campaign: ResponseCampaign) -> None:
    await conn.execute(
        "UPDATE aq_response_campaign SET tenant_id=$2, incident_id=$3, source_finding_id=$4, "
        "phases=$5, status=$6, created_by=$7, created_at=$8, updated_at=$9, evidence_ids=$10, "
        "version=$11 WHERE id=$1",
        *_campaign_args(campaign),
    )


async def _insert_trigger(conn: asyncpg.Connection, trigger: AutomationTrigger) -> None:
    try:
        await conn.execute(
            f"INSERT INTO aq_response_trigger ({_TRIGGER_COLS}) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
            *_trigger_args(trigger),
        )
    except asyncpg.UniqueViolationError as exc:
        raise OptimisticConcurrencyConflict(f"trigger already exists: {trigger.id}") from exc


async def _update_trigger(conn: asyncpg.Connection, trigger: AutomationTrigger) -> None:
    await conn.execute(
        "UPDATE aq_response_trigger SET tenant_id=$2, name=$3, condition=$4, playbook_id=$5, "
        "max_effect=$6, enabled=$7, version=$8 WHERE id=$1",
        *_trigger_args(trigger),
    )


def _campaign_args(campaign: ResponseCampaign) -> tuple[Any, ...]:
    return (
        campaign.id,
        campaign.tenant_id,
        campaign.incident_id,
        campaign.source_finding_id,
        json.dumps([phase.model_dump(mode="json") for phase in campaign.phases]),
        campaign.status,
        json.dumps(campaign.created_by.model_dump()),
        campaign.created_at,
        campaign.updated_at,
        json.dumps(campaign.evidence_ids),
        campaign.version,
    )


def _trigger_args(trigger: AutomationTrigger) -> tuple[Any, ...]:
    return (
        trigger.id,
        trigger.tenant_id,
        trigger.name,
        json.dumps(trigger.condition.model_dump(mode="json", by_alias=True, exclude_none=True)),
        trigger.playbook_id,
        trigger.max_effect,
        trigger.enabled,
        trigger.version,
    )
