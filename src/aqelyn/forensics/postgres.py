"""PostgreSQL Digital Forensics artifact store (EA-0016 F2)."""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from aqelyn.conventions.errors import (
    CrossTenantReference,
    OptimisticConcurrencyConflict,
    StoreUnavailable,
)
from aqelyn.forensics.ddl import DDL
from aqelyn.forensics.models import Artifact
from aqelyn.forensics.store import (
    materialize_artifact_id,
    validate_artifact,
    validate_artifact_id,
    validate_case_id,
    validate_tenant,
)

_ARTIFACT_COLS = (
    "id, tenant_id, artifact_type, acquisition_id, object_id, evidence_id, metadata, "
    "linked_asset_ids, first_seen_at, case_id"
)


def _to_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _row_to_artifact(row: asyncpg.Record) -> Artifact:
    data: dict[str, Any] = dict(row)
    data["metadata"] = _json_value(data["metadata"])
    data["linked_asset_ids"] = _json_value(data["linked_asset_ids"])
    return Artifact.model_validate(data)


class PostgresArtifactStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, url: str) -> PostgresArtifactStore:
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

    async def put(self, artifact: Artifact) -> Artifact:
        stored = validate_artifact(materialize_artifact_id(artifact))
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                f"SELECT {_ARTIFACT_COLS} FROM aq_forensics_artifact WHERE id=$1 FOR UPDATE",
                stored.id,
            )
            if row is None:
                await _insert(conn, stored)
                return stored

            existing = _row_to_artifact(row)
            if existing.tenant_id != stored.tenant_id:
                raise CrossTenantReference("artifact tenant_id cannot change")
            await _update(conn, stored)
            return stored

    async def get(self, artifact_id: str) -> Artifact | None:
        validate_artifact_id(artifact_id)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_ARTIFACT_COLS} FROM aq_forensics_artifact WHERE id=$1",
                artifact_id,
            )
        return None if row is None else _row_to_artifact(row)

    async def list(self, *, tenant_id: str | None, case_id: str | None = None) -> list[Artifact]:
        tenant_id = validate_tenant(tenant_id)
        case_id = validate_case_id(case_id)
        args: list[Any] = [tenant_id]
        clauses = ["tenant_id IS NOT DISTINCT FROM $1"]
        if case_id is not None:
            args.append(case_id)
            clauses.append(f"case_id = ${len(args)}")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_ARTIFACT_COLS} FROM aq_forensics_artifact "
                f"WHERE {' AND '.join(clauses)} "
                "ORDER BY first_seen_at, id",
                *args,
            )
        return [_row_to_artifact(row) for row in rows]


async def _insert(conn: asyncpg.Connection, artifact: Artifact) -> None:
    try:
        await conn.execute(
            f"INSERT INTO aq_forensics_artifact ({_ARTIFACT_COLS}) VALUES "
            "($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
            *_artifact_args(artifact),
        )
    except asyncpg.UniqueViolationError as exc:
        raise OptimisticConcurrencyConflict(f"artifact already exists: {artifact.id}") from exc


async def _update(conn: asyncpg.Connection, artifact: Artifact) -> None:
    await conn.execute(
        "UPDATE aq_forensics_artifact SET "
        "tenant_id=$2, artifact_type=$3, acquisition_id=$4, object_id=$5, evidence_id=$6, "
        "metadata=$7, linked_asset_ids=$8, first_seen_at=$9, case_id=$10 "
        "WHERE id=$1",
        *_artifact_args(artifact),
    )


def _artifact_args(artifact: Artifact) -> tuple[Any, ...]:
    data = artifact.model_dump(mode="json")
    return (
        artifact.id,
        artifact.tenant_id,
        artifact.artifact_type,
        artifact.acquisition_id,
        artifact.object_id,
        artifact.evidence_id,
        json.dumps(data["metadata"]),
        json.dumps(data["linked_asset_ids"]),
        artifact.first_seen_at,
        artifact.case_id,
    )
