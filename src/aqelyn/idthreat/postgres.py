"""PostgreSQL append-only IdentityDetectionStore (EA-0027 I3)."""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from aqelyn.conventions.errors import (
    CrossTenantReference,
    IdentityNotFound,
    OptimisticConcurrencyConflict,
    StoreUnavailable,
)
from aqelyn.idthreat.ddl import DDL
from aqelyn.idthreat.models import (
    DetectionType,
    IdentityDetection,
    IdentityReview,
    IdThreatConfig,
)
from aqelyn.idthreat.store import (
    validate_detection,
    validate_detection_id,
    validate_detection_type_filter,
    validate_limit,
    validate_new_detection,
    validate_review,
    validate_subject_filter,
    validate_tenant,
)

_COLUMNS = (
    "id, tenant_id, subject_ref, detection_type, statement, corroboration, confidence, "
    "basis, derivation, profile_ref, entitlement_refs, status, detected_at"
)
_SELECT_COLUMNS = (
    "d.id, d.tenant_id, d.subject_ref, d.detection_type, d.statement, d.corroboration, "
    "d.confidence, d.basis, d.derivation, d.profile_ref, d.entitlement_refs, "
    "CASE WHEN r.detection_id IS NULL THEN d.status ELSE 'reviewed' END AS status, "
    "d.detected_at"
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


class PostgresIdentityDetectionStore:
    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        config: IdThreatConfig,
        mode: str = "local",
    ) -> None:
        self._pool = pool
        self.config = config
        self.mode = mode

    @classmethod
    async def connect(
        cls,
        url: str,
        *,
        config: IdThreatConfig,
        mode: str = "local",
    ) -> PostgresIdentityDetectionStore:
        return cls(await _connect(url), config=config, mode=mode)

    async def close(self) -> None:
        await self._pool.close()

    async def put(self, detection: IdentityDetection) -> IdentityDetection:
        stored = validate_new_detection(detection, config=self.config)
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT tenant_id FROM aq_identity_detection WHERE id=$1 FOR UPDATE",
                stored.id,
            )
            if row is not None:
                if row["tenant_id"] != stored.tenant_id:
                    raise CrossTenantReference("identity detection tenant_id cannot change")
                raise OptimisticConcurrencyConflict("identity detections are append-only")
            try:
                await conn.execute(
                    f"INSERT INTO aq_identity_detection ({_COLUMNS}) VALUES "
                    "($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)",
                    *_detection_args(stored),
                )
            except asyncpg.UniqueViolationError as exc:
                raise OptimisticConcurrencyConflict("identity detections are append-only") from exc
        return stored.model_copy(deep=True)

    async def get(
        self,
        detection_id: str,
        *,
        tenant_id: str | None,
    ) -> IdentityDetection | None:
        validate_detection_id(detection_id)
        selected_tenant = validate_tenant(tenant_id)
        args: list[Any] = [detection_id]
        clauses = ["d.id=$1"]
        if self.mode == "local":
            clauses.append("d.tenant_id IS NULL")
        if selected_tenant is not None:
            args.append(selected_tenant)
            clauses.append(f"d.tenant_id = ${len(args)}")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_SELECT_COLUMNS} FROM aq_identity_detection d "
                "LEFT JOIN aq_identity_review r ON r.detection_id=d.id "
                f"WHERE {' AND '.join(clauses)}",
                *args,
            )
        if row is None:
            return None
        return validate_detection(_row_to_detection(row), config=self.config)

    async def query(
        self,
        *,
        tenant_id: str | None,
        subject_ref: str | None = None,
        detection_type: DetectionType | None = None,
        limit: int = 100,
    ) -> list[IdentityDetection]:
        selected_tenant = validate_tenant(tenant_id)
        selected_subject = validate_subject_filter(subject_ref)
        selected_type = validate_detection_type_filter(detection_type)
        selected_limit = validate_limit(limit)
        args: list[Any] = []
        clauses: list[str] = []
        if self.mode == "local":
            clauses.append("d.tenant_id IS NULL")
        if selected_tenant is not None:
            args.append(selected_tenant)
            clauses.append(f"d.tenant_id = ${len(args)}")
        if selected_subject is not None:
            args.append(selected_subject)
            clauses.append(f"d.subject_ref = ${len(args)}")
        if selected_type is not None:
            args.append(selected_type)
            clauses.append(f"d.detection_type = ${len(args)}")
        args.append(selected_limit)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_SELECT_COLUMNS} FROM aq_identity_detection d "
                "LEFT JOIN aq_identity_review r ON r.detection_id=d.id "
                f"{where}ORDER BY d.detected_at, d.id LIMIT ${len(args)}",
                *args,
            )
        return [validate_detection(_row_to_detection(row), config=self.config) for row in rows]

    async def record_review(self, review: IdentityReview) -> IdentityReview:
        stored = validate_review(review)
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT tenant_id FROM aq_identity_detection WHERE id=$1 FOR SHARE",
                stored.detection_id,
            )
            if row is None:
                raise IdentityNotFound(stored.detection_id)
            if row["tenant_id"] != stored.tenant_id:
                raise CrossTenantReference("identity review tenant does not match detection")
            try:
                await conn.execute(
                    "INSERT INTO aq_identity_review "
                    "(detection_id, tenant_id, outcome, reviewed_by, reviewed_at, evidence_id) "
                    "VALUES ($1,$2,$3,$4,$5,$6)",
                    stored.detection_id,
                    stored.tenant_id,
                    stored.outcome,
                    json.dumps(stored.reviewed_by.model_dump(mode="json")),
                    stored.reviewed_at,
                    stored.evidence_id,
                )
            except asyncpg.UniqueViolationError as exc:
                raise OptimisticConcurrencyConflict(
                    "identity detection is already reviewed"
                ) from exc
        return stored.model_copy(deep=True)

    async def review_for(
        self,
        detection_id: str,
        *,
        tenant_id: str | None,
    ) -> IdentityReview | None:
        validate_detection_id(detection_id)
        selected_tenant = validate_tenant(tenant_id)
        args: list[Any] = [detection_id]
        clauses = ["detection_id=$1"]
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if selected_tenant is not None:
            args.append(selected_tenant)
            clauses.append(f"tenant_id = ${len(args)}")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT detection_id, tenant_id, outcome, reviewed_by, reviewed_at, evidence_id "
                f"FROM aq_identity_review WHERE {' AND '.join(clauses)}",
                *args,
            )
        return None if row is None else _row_to_review(row)


def _detection_args(detection: IdentityDetection) -> tuple[Any, ...]:
    return (
        detection.id,
        detection.tenant_id,
        detection.subject_ref,
        detection.detection_type,
        detection.statement,
        json.dumps([item.model_dump(mode="json") for item in detection.corroboration]),
        detection.confidence,
        json.dumps([item.model_dump(mode="json") for item in detection.basis]),
        json.dumps(detection.derivation.model_dump(mode="json")),
        detection.profile_ref,
        json.dumps(detection.entitlement_refs),
        detection.status,
        detection.detected_at,
    )


def _row_to_detection(row: asyncpg.Record) -> IdentityDetection:
    data: dict[str, Any] = dict(row)
    for key in ("corroboration", "basis", "derivation", "entitlement_refs"):
        data[key] = _json_value(data[key])
    return IdentityDetection.model_validate(data)


def _row_to_review(row: asyncpg.Record) -> IdentityReview:
    data: dict[str, Any] = dict(row)
    data["reviewed_by"] = _json_value(data["reviewed_by"])
    return IdentityReview.model_validate(data)


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value
