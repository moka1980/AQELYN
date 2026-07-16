"""PostgreSQL decision stores (EA-0020 E2)."""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.conventions.errors import (
    ModelVersionNotFound,
    OptimisticConcurrencyConflict,
    StoreUnavailable,
    TenantScopeRequired,
)
from aqelyn.decision.ddl import DDL
from aqelyn.decision.models import ModelVersion, Recommendation
from aqelyn.decision.store import (
    validate_limit,
    validate_model_version,
    validate_model_version_number,
    validate_promotion_reason,
    validate_recommendation,
    validate_recommendation_id,
    validate_tenant,
)

_REC_COLS = (
    "id, tenant_id, subject_ref, statement, action_hint, confidence, derivation, "
    "advisory, created_at"
)
_MODEL_COLS = "tenant_id, version, params, promoted_by, promoted_at, active, evidence_id"


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


class PostgresRecommendationStore:
    def __init__(self, pool: asyncpg.Pool, *, mode: str = "local") -> None:
        self._pool = pool
        self.mode = mode

    @classmethod
    async def connect(cls, url: str, *, mode: str = "local") -> PostgresRecommendationStore:
        return cls(await _connect(url), mode=mode)

    async def close(self) -> None:
        await self._pool.close()

    async def put(self, recommendation: Recommendation) -> Recommendation:
        stored = validate_recommendation(recommendation)
        async with self._pool.acquire() as conn:
            try:
                await conn.execute(
                    f"INSERT INTO aq_decision_recommendation ({_REC_COLS}) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)",
                    *_recommendation_args(stored),
                )
            except asyncpg.UniqueViolationError as exc:
                raise OptimisticConcurrencyConflict(
                    f"recommendation already exists: {stored.id}"
                ) from exc
        return stored

    async def get(
        self, recommendation_id: str, *, tenant_id: str | None = None
    ) -> Recommendation | None:
        validate_recommendation_id(recommendation_id)
        tenant_id = validate_tenant(tenant_id)
        clauses = ["id=$1"]
        args: list[Any] = [recommendation_id]
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if tenant_id is not None:
            args.append(tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_REC_COLS} FROM aq_decision_recommendation WHERE {' AND '.join(clauses)}",
                *args,
            )
        return None if row is None else _row_to_recommendation(row)

    async def query(
        self, *, tenant_id: str | None = None, limit: int = 100
    ) -> list[Recommendation]:
        tenant_id = validate_tenant(tenant_id)
        validate_limit(limit)
        if self.mode == "enterprise" and tenant_id is None:
            raise TenantScopeRequired("recommendation query must be tenant-scoped")
        clauses: list[str] = []
        args: list[Any] = []
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if tenant_id is not None:
            args.append(tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")
        args.append(limit)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_REC_COLS} FROM aq_decision_recommendation "
                f"{where}ORDER BY created_at, id LIMIT ${len(args)}",
                *args,
            )
        return [_row_to_recommendation(row) for row in rows]


class PostgresModelVersionStore:
    def __init__(self, pool: asyncpg.Pool, *, mode: str = "local") -> None:
        self._pool = pool
        self.mode = mode

    @classmethod
    async def connect(cls, url: str, *, mode: str = "local") -> PostgresModelVersionStore:
        return cls(await _connect(url), mode=mode)

    async def close(self) -> None:
        await self._pool.close()

    async def put(
        self, model_version: ModelVersion, *, tenant_id: str | None = None
    ) -> ModelVersion:
        tenant_id = validate_tenant(tenant_id)
        stored = validate_model_version(model_version)
        async with self._pool.acquire() as conn, conn.transaction():
            try:
                if stored.active:
                    await conn.execute(
                        "UPDATE aq_decision_model_version SET active=false WHERE tenant_key=$1",
                        _tenant_key(tenant_id),
                    )
                await conn.execute(
                    "INSERT INTO aq_decision_model_version "
                    "(tenant_key, tenant_id, version, params, promoted_by, promoted_at, "
                    "active, evidence_id) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
                    _tenant_key(tenant_id),
                    tenant_id,
                    stored.version,
                    json.dumps(stored.params),
                    _dump_json_or_none(stored.promoted_by),
                    stored.promoted_at,
                    stored.active,
                    stored.evidence_id,
                )
            except asyncpg.UniqueViolationError as exc:
                raise OptimisticConcurrencyConflict(
                    f"model version already exists: {stored.version}"
                ) from exc
        return stored

    async def get(self, version: int, *, tenant_id: str | None = None) -> ModelVersion | None:
        version = validate_model_version_number(version)
        tenant_id = validate_tenant(tenant_id)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_MODEL_COLS} FROM aq_decision_model_version "
                "WHERE tenant_key=$1 AND version=$2",
                _tenant_key(tenant_id),
                version,
            )
        return None if row is None else _row_to_model(row)

    async def active(self, *, tenant_id: str | None = None) -> ModelVersion:
        tenant_id = validate_tenant(tenant_id)
        if self.mode == "enterprise" and tenant_id is None:
            raise TenantScopeRequired("active model version must be tenant-scoped")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_MODEL_COLS} FROM aq_decision_model_version "
                "WHERE tenant_key=$1 AND active=true ORDER BY version DESC LIMIT 1",
                _tenant_key(tenant_id),
            )
        if row is None:
            raise ModelVersionNotFound("no active model version")
        return _row_to_model(row)

    async def promote(
        self,
        version: int,
        *,
        by: ActorRef,
        reason: str,
        tenant_id: str | None = None,
        evidence_id: str | None = None,
    ) -> ModelVersion:
        version = validate_model_version_number(version)
        tenant_id = validate_tenant(tenant_id)
        validate_promotion_reason(reason)
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                f"SELECT {_MODEL_COLS} FROM aq_decision_model_version "
                "WHERE tenant_key=$1 AND version=$2 FOR UPDATE",
                _tenant_key(tenant_id),
                version,
            )
            if row is None:
                raise ModelVersionNotFound(f"model version not found: {version}")
            promoted = _row_to_model(row).model_copy(
                update={
                    "active": True,
                    "promoted_by": by,
                    "promoted_at": utc_now(),
                    "evidence_id": evidence_id or new_id("evd"),
                },
                deep=True,
            )
            stored = validate_model_version(promoted)
            await conn.execute(
                "UPDATE aq_decision_model_version SET active=false WHERE tenant_key=$1",
                _tenant_key(tenant_id),
            )
            await conn.execute(
                "UPDATE aq_decision_model_version SET promoted_by=$3, promoted_at=$4, "
                "active=true, evidence_id=$5 WHERE tenant_key=$1 AND version=$2",
                _tenant_key(tenant_id),
                version,
                _dump_json_or_none(stored.promoted_by),
                stored.promoted_at,
                stored.evidence_id,
            )
            return stored


def _recommendation_args(recommendation: Recommendation) -> tuple[Any, ...]:
    return (
        recommendation.id,
        recommendation.tenant_id,
        recommendation.subject_ref,
        recommendation.statement,
        None if recommendation.action_hint is None else json.dumps(recommendation.action_hint),
        recommendation.confidence,
        json.dumps(recommendation.derivation.model_dump(mode="json")),
        recommendation.advisory,
        recommendation.created_at,
    )


def _row_to_recommendation(row: asyncpg.Record) -> Recommendation:
    data: dict[str, Any] = dict(row)
    data["action_hint"] = _json_value(data["action_hint"])
    data["derivation"] = _json_value(data["derivation"])
    return Recommendation.model_validate(data)


def _row_to_model(row: asyncpg.Record) -> ModelVersion:
    data: dict[str, Any] = dict(row)
    data["params"] = _json_value(data["params"])
    data["promoted_by"] = _json_value(data["promoted_by"])
    data.pop("tenant_id", None)
    return ModelVersion.model_validate(data)


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


def _tenant_key(tenant_id: str | None) -> str:
    return tenant_id or ""
