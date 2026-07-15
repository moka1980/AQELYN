"""PostgreSQL Security Data Lake stores (EA-0019 L2)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import asyncpg

from aqelyn.conventions.errors import (
    OptimisticConcurrencyConflict,
    StoreUnavailable,
    TenantScopeRequired,
)
from aqelyn.lake.ddl import DDL
from aqelyn.lake.models import Dataset, Quarantine, TelemetryRecord
from aqelyn.lake.store import (
    normalize_retention_state_filter,
    validate_dataset,
    validate_dataset_name,
    validate_positive,
    validate_quarantine,
    validate_record,
    validate_record_id,
    validate_tenant,
)

_DATASET_COLS = (
    "name, tenant_id, schema, classifications, retention_policy_id, "
    "indexed_fields, set_by, set_at, version"
)
_RECORD_COLS = (
    "id, tenant_id, dataset, source_id, occurred_at, ingested_at, fields, raw_ref, "
    "schema_version, retention_state, legal_hold, evidence_id"
)
_QUARANTINE_COLS = "source_id, reason, received_at, raw_ref"


def _to_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _json_dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _row_to_dataset(row: asyncpg.Record) -> Dataset:
    data: dict[str, Any] = dict(row)
    data["schema"] = _json_value(data["schema"])
    data["classifications"] = _json_value(data["classifications"])
    data["indexed_fields"] = _json_value(data["indexed_fields"])
    data["set_by"] = _json_value(data["set_by"])
    return Dataset.model_validate(data)


def _row_to_record(row: asyncpg.Record) -> TelemetryRecord:
    data: dict[str, Any] = dict(row)
    data["fields"] = _json_value(data["fields"])
    data["raw_ref"] = _json_value(data["raw_ref"])
    return TelemetryRecord.model_validate(data)


def _row_to_quarantine(row: asyncpg.Record) -> Quarantine:
    data: dict[str, Any] = dict(row)
    data["raw_ref"] = _json_value(data["raw_ref"])
    return Quarantine.model_validate(data)


class PostgresDatasetCatalog:
    def __init__(self, pool: asyncpg.Pool, *, mode: str = "local") -> None:
        self._pool = pool
        self.mode = mode

    @classmethod
    async def connect(cls, url: str, **kw: Any) -> PostgresDatasetCatalog:
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

    async def register(self, dataset: Dataset) -> Dataset:
        stored = validate_dataset(dataset)
        data = stored.model_dump(mode="json", by_alias=True)
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO aq_lake_dataset (
                    name, tenant_id, schema, classifications, retention_policy_id,
                    indexed_fields, set_by, set_at, version
                )
                VALUES ($1,$2,$3::jsonb,$4::jsonb,$5,$6::jsonb,$7::jsonb,$8,$9)
                ON CONFLICT (COALESCE(tenant_id, ''), name) DO UPDATE SET
                    schema = EXCLUDED.schema,
                    classifications = EXCLUDED.classifications,
                    retention_policy_id = EXCLUDED.retention_policy_id,
                    indexed_fields = EXCLUDED.indexed_fields,
                    set_by = EXCLUDED.set_by,
                    set_at = EXCLUDED.set_at,
                    version = aq_lake_dataset.version + 1
                """,
                data["name"],
                data["tenant_id"],
                _json_dump(data["schema"]),
                _json_dump(data["classifications"]),
                data["retention_policy_id"],
                _json_dump(data["indexed_fields"]),
                _json_dump(data["set_by"]),
                stored.set_at,
                data["version"],
            )
        fetched = await self.get(stored.name, tenant_id=stored.tenant_id)
        assert fetched is not None
        return fetched

    async def get(self, name: str, *, tenant_id: str | None) -> Dataset | None:
        validate_dataset_name(name, field="name")
        tenant_id = validate_tenant(tenant_id)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_DATASET_COLS} FROM aq_lake_dataset "
                "WHERE tenant_id IS NOT DISTINCT FROM $1 AND name=$2",
                tenant_id,
                name,
            )
            if row is None and tenant_id is not None:
                row = await conn.fetchrow(
                    f"SELECT {_DATASET_COLS} FROM aq_lake_dataset "
                    "WHERE tenant_id IS NULL AND name=$1",
                    name,
                )
        return None if row is None else _row_to_dataset(row)

    async def list(self, *, tenant_id: str | None) -> list[Dataset]:
        tenant_id = validate_tenant(tenant_id)
        args: list[Any] = []
        clauses: list[str] = []
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        elif tenant_id is not None:
            args.append(tenant_id)
            clauses.append(f"(tenant_id IS NULL OR tenant_id = ${len(args)})")
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_DATASET_COLS} FROM aq_lake_dataset {where}"
                "ORDER BY COALESCE(tenant_id, ''), name",
                *args,
            )
        return [_row_to_dataset(row) for row in rows]


class PostgresTelemetryRecordStore:
    def __init__(self, pool: asyncpg.Pool, *, mode: str = "local") -> None:
        self._pool = pool
        self.mode = mode

    @classmethod
    async def connect(cls, url: str, **kw: Any) -> PostgresTelemetryRecordStore:
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

    async def append(self, record: TelemetryRecord) -> TelemetryRecord:
        stored = validate_record(record)
        validate_record_id(stored.id, field="id")
        data = stored.model_dump(mode="json")
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO aq_lake_record (
                        id, tenant_id, dataset, source_id, occurred_at, ingested_at,
                        fields, raw_ref, schema_version, retention_state, legal_hold,
                        evidence_id
                    )
                    VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,$9,$10,$11,$12)
                    """,
                    data["id"],
                    data["tenant_id"],
                    data["dataset"],
                    data["source_id"],
                    stored.occurred_at,
                    stored.ingested_at,
                    _json_dump(data["fields"]),
                    None if data["raw_ref"] is None else _json_dump(data["raw_ref"]),
                    data["schema_version"],
                    data["retention_state"],
                    data["legal_hold"],
                    data["evidence_id"],
                )
        except asyncpg.UniqueViolationError as exc:
            raise OptimisticConcurrencyConflict(
                f"telemetry record already exists: {stored.id}"
            ) from exc
        return stored

    async def get(
        self,
        record_id: str,
        *,
        tenant_id: str | None = None,
    ) -> TelemetryRecord | None:
        validate_record_id(record_id)
        tenant_id = validate_tenant(tenant_id)
        clauses = ["id = $1"]
        args: list[Any] = [record_id]
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if tenant_id is not None:
            args.append(tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_RECORD_COLS} FROM aq_lake_record WHERE {' AND '.join(clauses)}",
                *args,
            )
        return None if row is None else _row_to_record(row)

    async def query(
        self,
        *,
        dataset: str,
        tenant_id: str | None,
        limit: int = 100,
        retention_state: Sequence[str] | None = None,
    ) -> list[TelemetryRecord]:
        validate_dataset_name(dataset)
        tenant_id = validate_tenant(tenant_id)
        validate_positive(limit, field="limit")
        states = normalize_retention_state_filter(retention_state)
        if self.mode == "enterprise" and tenant_id is None:
            raise TenantScopeRequired("lake record query must be tenant-scoped")
        args: list[Any] = [dataset]
        clauses = ["dataset = $1"]
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if tenant_id is not None:
            args.append(tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")
        if states is not None:
            args.append(list(states))
            clauses.append(f"retention_state = ANY(${len(args)}::text[])")
        args.append(limit)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_RECORD_COLS} FROM aq_lake_record WHERE {' AND '.join(clauses)} "
                f"ORDER BY occurred_at, id LIMIT ${len(args)}",
                *args,
            )
        return [_row_to_record(row) for row in rows]

    async def quarantine(self, item: Quarantine, *, tenant_id: str | None) -> Quarantine:
        tenant_id = validate_tenant(tenant_id)
        stored = validate_quarantine(item)
        data = stored.model_dump(mode="json")
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO aq_lake_quarantine (tenant_id, source_id, reason, received_at, raw_ref)
                VALUES ($1,$2,$3,$4,$5::jsonb)
                """,
                tenant_id,
                data["source_id"],
                data["reason"],
                stored.received_at,
                None if data["raw_ref"] is None else _json_dump(data["raw_ref"]),
            )
        return stored

    async def list_quarantine(
        self,
        *,
        tenant_id: str | None,
        limit: int = 100,
    ) -> list[Quarantine]:
        tenant_id = validate_tenant(tenant_id)
        validate_positive(limit, field="limit")
        if self.mode == "enterprise" and tenant_id is None:
            raise TenantScopeRequired("lake quarantine query must be tenant-scoped")
        args: list[Any] = []
        clauses: list[str] = []
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if tenant_id is not None:
            args.append(tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")
        args.append(limit)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_QUARANTINE_COLS} FROM aq_lake_quarantine {where}"
                f"ORDER BY received_at, seq LIMIT ${len(args)}",
                *args,
            )
        return [_row_to_quarantine(row) for row in rows]
