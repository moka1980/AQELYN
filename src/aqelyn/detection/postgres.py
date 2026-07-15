"""PostgreSQL Threat Detection stores (EA-0017 D2)."""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from aqelyn.conventions import new_id
from aqelyn.conventions.errors import OptimisticConcurrencyConflict, StoreUnavailable
from aqelyn.detection.ddl import DDL
from aqelyn.detection.models import BehaviorProfile, DetectionRule
from aqelyn.detection.store import (
    normalize_enabled_only,
    validate_positive,
    validate_profile,
    validate_profile_id,
    validate_rule,
    validate_rule_id,
    validate_tenant,
)

_RULE_COLS = (
    "id, version, name, description, kind, condition, subject_type, technique_ids, "
    "severity, enabled, tenant_id"
)
_PROFILE_COLS = (
    "id, version, tenant_id, subject_ref, metric, window_days, baseline, computed_at, "
    "insufficient_data"
)


def _to_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _json_value(value: Any) -> Any:
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


def _row_to_rule(row: asyncpg.Record) -> DetectionRule:
    data: dict[str, Any] = dict(row)
    data["condition"] = _json_value(data["condition"])
    data["technique_ids"] = _json_value(data["technique_ids"])
    return DetectionRule.model_validate(data)


def _row_to_profile(row: asyncpg.Record) -> BehaviorProfile:
    data: dict[str, Any] = dict(row)
    data["baseline"] = _json_value(data["baseline"])
    return BehaviorProfile.model_validate(data)


class PostgresRuleStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, url: str) -> PostgresRuleStore:
        return cls(await _connect(url))

    async def close(self) -> None:
        await self._pool.close()

    async def put(self, rule: DetectionRule) -> DetectionRule:
        stored = validate_rule(rule)
        async with self._pool.acquire() as conn:
            try:
                await conn.execute(
                    f"INSERT INTO aq_detection_rule ({_RULE_COLS}) VALUES "
                    "($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
                    *_rule_args(stored),
                )
            except asyncpg.UniqueViolationError as exc:
                raise OptimisticConcurrencyConflict(
                    f"detection rule version already exists: {stored.id} v{stored.version}"
                ) from exc
        return stored

    async def get(self, rule_id: str, *, version: int | None = None) -> DetectionRule | None:
        validate_rule_id(rule_id)
        async with self._pool.acquire() as conn:
            if version is not None:
                validate_positive(version, field="version")
                row = await conn.fetchrow(
                    f"SELECT {_RULE_COLS} FROM aq_detection_rule WHERE id=$1 AND version=$2",
                    rule_id,
                    version,
                )
            else:
                row = await conn.fetchrow(
                    f"SELECT {_RULE_COLS} FROM aq_detection_rule "
                    "WHERE id=$1 ORDER BY version DESC LIMIT 1",
                    rule_id,
                )
        return None if row is None else _row_to_rule(row)

    async def list(
        self, *, tenant_id: str | None, enabled_only: bool = True
    ) -> list[DetectionRule]:
        tenant_id = validate_tenant(tenant_id)
        enabled_only = normalize_enabled_only(enabled_only)
        args: list[Any] = []
        clauses = ["tenant_id IS NULL"]
        if tenant_id is not None:
            args.append(tenant_id)
            clauses = ["(tenant_id IS NULL OR tenant_id = $1)"]
        if enabled_only:
            clauses.append("enabled = true")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT DISTINCT ON (id) {_RULE_COLS} FROM aq_detection_rule "
                f"WHERE {' AND '.join(clauses)} "
                "ORDER BY id, version DESC",
                *args,
            )
        rules = [_row_to_rule(row) for row in rows]
        rules.sort(key=lambda rule: (rule.tenant_id is not None, rule.tenant_id or "", rule.id))
        return rules


class PostgresProfileStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, url: str) -> PostgresProfileStore:
        return cls(await _connect(url))

    async def close(self) -> None:
        await self._pool.close()

    async def put(self, profile: BehaviorProfile) -> BehaviorProfile:
        incoming = validate_profile(profile)
        async with self._pool.acquire() as conn, conn.transaction():
            latest = await _latest_for_logical(
                conn,
                tenant_id=incoming.tenant_id,
                subject_ref=incoming.subject_ref,
                metric=incoming.metric,
                lock=True,
            )
            stored = incoming.model_copy(
                update={
                    "id": latest.id if latest is not None else incoming.id or new_id("prf"),
                    "version": 1 if latest is None else latest.version + 1,
                },
                deep=True,
            )
            try:
                await conn.execute(
                    f"INSERT INTO aq_behavior_profile ({_PROFILE_COLS}) VALUES "
                    "($1,$2,$3,$4,$5,$6,$7,$8,$9)",
                    *_profile_args(stored),
                )
            except asyncpg.UniqueViolationError as exc:
                raise OptimisticConcurrencyConflict(
                    f"profile version already exists: {stored.id} v{stored.version}"
                ) from exc
        return stored

    async def get(self, profile_id: str, *, version: int | None = None) -> BehaviorProfile | None:
        validate_profile_id(profile_id)
        async with self._pool.acquire() as conn:
            if version is not None:
                validate_positive(version, field="version")
                row = await conn.fetchrow(
                    f"SELECT {_PROFILE_COLS} FROM aq_behavior_profile WHERE id=$1 AND version=$2",
                    profile_id,
                    version,
                )
            else:
                row = await conn.fetchrow(
                    f"SELECT {_PROFILE_COLS} FROM aq_behavior_profile "
                    "WHERE id=$1 ORDER BY version DESC LIMIT 1",
                    profile_id,
                )
        return None if row is None else _row_to_profile(row)

    async def latest(
        self, *, subject_ref: str, metric: str, tenant_id: str | None
    ) -> BehaviorProfile | None:
        tenant_id = validate_tenant(tenant_id)
        async with self._pool.acquire() as conn:
            return await _latest_for_logical(
                conn,
                tenant_id=tenant_id,
                subject_ref=subject_ref,
                metric=metric,
                lock=False,
            )


async def _latest_for_logical(
    conn: asyncpg.Connection,
    *,
    tenant_id: str | None,
    subject_ref: str,
    metric: str,
    lock: bool,
) -> BehaviorProfile | None:
    suffix = " FOR UPDATE" if lock else ""
    row = await conn.fetchrow(
        f"SELECT {_PROFILE_COLS} FROM aq_behavior_profile "
        "WHERE tenant_id IS NOT DISTINCT FROM $1 AND subject_ref=$2 AND metric=$3 "
        f"ORDER BY version DESC LIMIT 1{suffix}",
        tenant_id,
        subject_ref,
        metric,
    )
    return None if row is None else _row_to_profile(row)


def _rule_args(rule: DetectionRule) -> tuple[Any, ...]:
    return (
        rule.id,
        rule.version,
        rule.name,
        rule.description,
        rule.kind,
        json.dumps(rule.condition.model_dump(mode="json", by_alias=True)),
        rule.subject_type,
        json.dumps(rule.technique_ids),
        rule.severity,
        rule.enabled,
        rule.tenant_id,
    )


def _profile_args(profile: BehaviorProfile) -> tuple[Any, ...]:
    return (
        profile.id,
        profile.version,
        profile.tenant_id,
        profile.subject_ref,
        profile.metric,
        profile.window_days,
        json.dumps(profile.baseline),
        profile.computed_at,
        profile.insufficient_data,
    )
