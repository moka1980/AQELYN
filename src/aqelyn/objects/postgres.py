"""PostgreSQL ObjectStore (EA-0002 §14).

Load-modify-write inside a row-locked transaction so semantics match the
in-memory reference exactly (both pass the same contract suite).
"""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.conventions.errors import (
    CrossTenantReference,
    MissingProvenance,
    ObjectNotFound,
    OptimisticConcurrencyConflict,
    SchemaValidationError,
    StoreUnavailable,
    TenantScopeRequired,
)
from aqelyn.objects.ddl import DDL
from aqelyn.objects.models import AQObject, AQRelationship, NaturalKey, ObjectQuery
from aqelyn.objects.registry import ObjectTypeRegistry
from aqelyn.objects.store import (
    VALID_TRANSITIONS,
    ObjectEventSink,
    dedupe_sources,
    merge_attributes,
    validate_object_id,
)

_COLS = (
    "id, object_type, schema_version, tenant_id, display_name, attributes, labels, "
    "natural_keys, sources, confidence, lifecycle_state, merged_into, version, "
    "first_seen_at, last_seen_at, created_at, updated_at, created_by, updated_by"
)


def _to_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _row_to_obj(row: asyncpg.Record) -> AQObject:
    d = dict(row)
    for jkey in ("attributes", "labels", "natural_keys", "sources", "created_by", "updated_by"):
        if isinstance(d[jkey], str):
            d[jkey] = json.loads(d[jkey])
    return AQObject.model_validate(d)


class PostgresObjectStore:
    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        registry: ObjectTypeRegistry | None = None,
        mode: str = "local",
        event_sink: ObjectEventSink | None = None,
    ) -> None:
        self._pool = pool
        self.registry = registry or ObjectTypeRegistry()
        self.mode = mode
        self._sink = event_sink

    @classmethod
    async def connect(cls, url: str, **kw: Any) -> PostgresObjectStore:
        try:
            pool = await asyncpg.create_pool(_to_dsn(url), min_size=1, max_size=5)
        except Exception as exc:  # normalize connection failure
            raise StoreUnavailable(str(exc)) from exc
        assert pool is not None
        async with pool.acquire() as conn:
            await conn.execute(DDL)
        return cls(pool, **kw)

    async def close(self) -> None:
        await self._pool.close()

    # --- persistence helpers ---
    async def _insert(self, conn: asyncpg.Connection, o: AQObject) -> None:
        await conn.execute(
            f"INSERT INTO aq_object ({_COLS}) VALUES "
            "($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)",
            o.id,
            o.object_type,
            o.schema_version,
            o.tenant_id,
            o.display_name,
            json.dumps(o.attributes),
            json.dumps(o.labels),
            json.dumps([nk.model_dump() for nk in o.natural_keys]),
            json.dumps([s.model_dump(mode="json") for s in o.sources]),
            o.confidence,
            o.lifecycle_state,
            o.merged_into,
            o.version,
            o.first_seen_at,
            o.last_seen_at,
            o.created_at,
            o.updated_at,
            json.dumps(o.created_by.model_dump()),
            json.dumps(o.updated_by.model_dump()),
        )
        await self._reindex_nk(conn, o)
        await self._history(conn, o)

    async def _save(self, conn: asyncpg.Connection, o: AQObject) -> None:
        await conn.execute(
            "UPDATE aq_object SET attributes=$2, labels=$3, natural_keys=$4, sources=$5, "
            "display_name=$6, confidence=$7, lifecycle_state=$8, merged_into=$9, version=$10, "
            "last_seen_at=$11, updated_at=$12, updated_by=$13 WHERE id=$1",
            o.id,
            json.dumps(o.attributes),
            json.dumps(o.labels),
            json.dumps([nk.model_dump() for nk in o.natural_keys]),
            json.dumps([s.model_dump(mode="json") for s in o.sources]),
            o.display_name,
            o.confidence,
            o.lifecycle_state,
            o.merged_into,
            o.version,
            o.last_seen_at,
            o.updated_at,
            json.dumps(o.updated_by.model_dump()),
        )
        await self._reindex_nk(conn, o)
        await self._history(conn, o)

    async def _reindex_nk(self, conn: asyncpg.Connection, o: AQObject) -> None:
        await conn.execute("DELETE FROM aq_object_natural_key WHERE object_id=$1", o.id)
        for nk in o.natural_keys:
            await conn.execute(
                "INSERT INTO aq_object_natural_key (object_id, tenant_id, namespace, value) "
                "VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
                o.id,
                o.tenant_id,
                nk.namespace,
                nk.value,
            )

    async def _history(self, conn: asyncpg.Connection, o: AQObject) -> None:
        await conn.execute(
            "INSERT INTO aq_object_history (object_id, version, snapshot, changed_by) "
            "VALUES ($1,$2,$3,$4)",
            o.id,
            o.version,
            json.dumps(o.model_dump(mode="json")),
            json.dumps(o.updated_by.model_dump()),
        )

    async def _emit(
        self, event_type: str, o: AQObject, actor: ActorRef, payload: dict[str, Any]
    ) -> None:
        if self._sink is not None:
            await self._sink.object_event(
                event_type, object_id=o.id, tenant_id=o.tenant_id, payload=payload, actor=actor
            )

    async def _find_by_nk(
        self, conn: asyncpg.Connection, tenant: str | None, otype: str, keys: list[NaturalKey]
    ) -> str | None:
        for k in keys:
            row = await conn.fetchrow(
                "SELECT nk.object_id FROM aq_object_natural_key nk JOIN aq_object o "
                "ON o.id = nk.object_id WHERE nk.tenant_id IS NOT DISTINCT FROM $1 "
                "AND nk.namespace=$2 AND nk.value=$3 AND o.object_type=$4 "
                "AND o.lifecycle_state IN ('active','archived')",
                tenant,
                k.namespace,
                k.value,
                otype,
            )
            if row is not None:
                return str(row["object_id"])
        return None

    # --- interface ---
    async def get(self, object_id: str, *, resolve_merged: bool = True) -> AQObject | None:
        validate_object_id(object_id)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(f"SELECT {_COLS} FROM aq_object WHERE id=$1", object_id)
            if row is None:
                return None
            obj = _row_to_obj(row)
            seen = {obj.id}
            while resolve_merged and obj.lifecycle_state == "merged" and obj.merged_into:
                nxt = await conn.fetchrow(
                    f"SELECT {_COLS} FROM aq_object WHERE id=$1", obj.merged_into
                )
                if nxt is None:
                    break
                obj = _row_to_obj(nxt)
                if obj.id in seen:
                    break
                seen.add(obj.id)
            return obj

    async def upsert(self, obj: AQObject) -> AQObject:
        if not obj.sources:
            raise MissingProvenance("object requires at least one source")
        self.registry.validate(obj.object_type, obj.attributes)
        now = utc_now()
        async with self._pool.acquire() as conn, conn.transaction():
            match_id = await self._find_by_nk(
                conn, obj.tenant_id, obj.object_type, obj.natural_keys
            )
            if match_id is not None:
                row = await conn.fetchrow(
                    f"SELECT {_COLS} FROM aq_object WHERE id=$1 FOR UPDATE", match_id
                )
                assert row is not None
                existing = _row_to_obj(row)
                existing.attributes = merge_attributes(existing.attributes, obj.attributes)
                existing.labels = {**existing.labels, **obj.labels}
                existing.sources = dedupe_sources([*existing.sources, *obj.sources])
                existing.last_seen_at = max(existing.last_seen_at, obj.last_seen_at)
                existing.display_name = obj.display_name or existing.display_name
                existing.version += 1
                existing.updated_at = now
                existing.updated_by = obj.updated_by
                await self._save(conn, existing)
                await self._emit(
                    "aqelyn.object.updated",
                    existing,
                    existing.updated_by,
                    {"changed_fields": ["*"]},
                )
                return existing
            created = obj.model_copy(deep=True)
            if not created.id:
                created.id = new_id("obj")
            created.version = 1
            created.created_at = now
            created.updated_at = now
            await self._insert(conn, created)
            await self._emit(
                "aqelyn.object.created",
                created,
                created.created_by,
                {"object_type": created.object_type},
            )
            return created

    async def update(self, obj: AQObject, *, expected_version: int) -> AQObject:
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                f"SELECT {_COLS} FROM aq_object WHERE id=$1 FOR UPDATE", obj.id
            )
            if row is None:
                raise ObjectNotFound(obj.id)
            existing = _row_to_obj(row)
            if existing.version != expected_version:
                raise OptimisticConcurrencyConflict(
                    f"expected v{expected_version}, found v{existing.version}"
                )
            updated = obj.model_copy(deep=True)
            updated.version = existing.version + 1
            updated.created_at = existing.created_at
            updated.updated_at = utc_now()
            await self._save(conn, updated)
            await self._emit(
                "aqelyn.object.updated", updated, updated.updated_by, {"changed_fields": ["*"]}
            )
            return updated

    async def query(self, q: ObjectQuery) -> tuple[list[AQObject], str | None]:
        if self.mode == "enterprise" and q.tenant_id is None:
            raise TenantScopeRequired("query must be tenant-scoped in enterprise mode")
        clauses = ["lifecycle_state = ANY($1::text[])"]
        args: list[Any] = [list(q.include_states)]
        if self.mode == "local":
            clauses.append("tenant_id IS NULL")
        if q.tenant_id is not None:
            args.append(q.tenant_id)
            clauses.append(f"tenant_id = ${len(args)}")
        if q.object_type is not None:
            args.append(q.object_type)
            clauses.append(f"object_type = ${len(args)}")
        if q.exclude_object_types:
            args.append(list(q.exclude_object_types))
            clauses.append(f"object_type <> ALL(${len(args)}::text[])")
        args.append(q.limit)
        sql = (
            f"SELECT {_COLS} FROM aq_object WHERE {' AND '.join(clauses)} "
            f"ORDER BY id LIMIT ${len(args)}"
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        out = [_row_to_obj(r) for r in rows]
        if q.labels:
            out = [o for o in out if all(o.labels.get(k) == v for k, v in q.labels.items())]
        if q.natural_key is not None:
            nk = q.natural_key
            out = [
                o
                for o in out
                if any(k.namespace == nk.namespace and k.value == nk.value for k in o.natural_keys)
            ]
        return out, None

    async def relate(self, rel: AQRelationship) -> AQRelationship:
        async with self._pool.acquire() as conn, conn.transaction():
            frm = await conn.fetchrow("SELECT tenant_id FROM aq_object WHERE id=$1", rel.from_id)
            to = await conn.fetchrow("SELECT tenant_id FROM aq_object WHERE id=$1", rel.to_id)
            if frm is None or to is None:
                raise ObjectNotFound("relationship endpoint missing")
            if frm["tenant_id"] != to["tenant_id"]:
                raise CrossTenantReference("relationship endpoints span tenants")
            created = rel.model_copy(deep=True)
            if not created.id:
                created.id = new_id("rel")
            created.tenant_id = frm["tenant_id"]
            await conn.execute(
                "INSERT INTO aq_relationship (id, tenant_id, from_id, to_id, relation_type, "
                "attributes, sources, confidence, lifecycle_state, version, created_at, "
                "updated_at, created_by, updated_by) VALUES "
                "($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)",
                created.id,
                created.tenant_id,
                created.from_id,
                created.to_id,
                created.relation_type,
                json.dumps(created.attributes),
                json.dumps([s.model_dump(mode="json") for s in created.sources]),
                created.confidence,
                created.lifecycle_state,
                created.version,
                created.created_at,
                created.updated_at,
                json.dumps(created.created_by.model_dump()),
                json.dumps(created.updated_by.model_dump()),
            )
            return created

    async def relationships(
        self, object_id: str, *, direction: str = "both", relation_type: str | None = None
    ) -> list[AQRelationship]:
        validate_object_id(object_id)
        clauses = ["lifecycle_state = 'active'"]
        args: list[Any] = []
        if direction == "out":
            args.append(object_id)
            clauses.append(f"from_id = ${len(args)}")
        elif direction == "in":
            args.append(object_id)
            clauses.append(f"to_id = ${len(args)}")
        else:
            args.append(object_id)
            clauses.append(f"(from_id = ${len(args)} OR to_id = ${len(args)})")
        if relation_type is not None:
            args.append(relation_type)
            clauses.append(f"relation_type = ${len(args)}")
        sql = f"SELECT * FROM aq_relationship WHERE {' AND '.join(clauses)}"
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        result: list[AQRelationship] = []
        for r in rows:
            d = dict(r)
            for jkey in ("attributes", "sources", "created_by", "updated_by"):
                if isinstance(d[jkey], str):
                    d[jkey] = json.loads(d[jkey])
            result.append(AQRelationship.model_validate(d))
        return result

    async def merge(self, survivor_id: str, duplicate_id: str, *, by: ActorRef) -> AQObject:
        validate_object_id(survivor_id, field="survivor_id")
        validate_object_id(duplicate_id, field="duplicate_id")
        async with self._pool.acquire() as conn, conn.transaction():
            srow = await conn.fetchrow(
                f"SELECT {_COLS} FROM aq_object WHERE id=$1 FOR UPDATE", survivor_id
            )
            drow = await conn.fetchrow(
                f"SELECT {_COLS} FROM aq_object WHERE id=$1 FOR UPDATE", duplicate_id
            )
            if srow is None or drow is None:
                raise ObjectNotFound("merge endpoint missing")
            survivor = _row_to_obj(srow)
            duplicate = _row_to_obj(drow)
            if survivor.tenant_id != duplicate.tenant_id:
                raise CrossTenantReference("merge across tenants")
            survivor.sources = dedupe_sources([*survivor.sources, *duplicate.sources])
            existing_nk = {(nk.namespace, nk.value) for nk in survivor.natural_keys}
            for nk in duplicate.natural_keys:
                if (nk.namespace, nk.value) not in existing_nk:
                    survivor.natural_keys.append(nk)
            survivor.version += 1
            survivor.updated_at = utc_now()
            survivor.updated_by = by
            duplicate.lifecycle_state = "merged"
            duplicate.merged_into = survivor_id
            duplicate.version += 1
            duplicate.updated_at = utc_now()
            duplicate.updated_by = by
            await conn.execute(
                "UPDATE aq_relationship SET from_id=$1 WHERE from_id=$2", survivor_id, duplicate_id
            )
            await conn.execute(
                "UPDATE aq_relationship SET to_id=$1 WHERE to_id=$2", survivor_id, duplicate_id
            )
            await self._save(conn, survivor)
            await self._save(conn, duplicate)
            await self._emit(
                "aqelyn.object.merged",
                survivor,
                by,
                {"survivor_id": survivor_id, "duplicate_id": duplicate_id},
            )
            return survivor

    async def set_state(
        self, object_id: str, state: str, *, by: ActorRef, expected_version: int
    ) -> AQObject:
        validate_object_id(object_id)
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                f"SELECT {_COLS} FROM aq_object WHERE id=$1 FOR UPDATE", object_id
            )
            if row is None:
                raise ObjectNotFound(object_id)
            obj = _row_to_obj(row)
            if obj.version != expected_version:
                raise OptimisticConcurrencyConflict(
                    f"expected v{expected_version}, found v{obj.version}"
                )
            if state not in VALID_TRANSITIONS.get(obj.lifecycle_state, set()):
                raise SchemaValidationError(f"illegal transition {obj.lifecycle_state} -> {state}")
            prev = obj.lifecycle_state
            obj.lifecycle_state = state  # type: ignore[assignment]
            obj.version += 1
            obj.updated_at = utc_now()
            obj.updated_by = by
            await self._save(conn, obj)
            await self._emit("aqelyn.object.state_changed", obj, by, {"from": prev, "to": state})
            return obj

    async def history(self, object_id: str) -> list[dict[str, Any]]:
        validate_object_id(object_id)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT seq, version, snapshot, changed_at, changed_by FROM aq_object_history "
                "WHERE object_id=$1 ORDER BY seq",
                object_id,
            )
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            for jkey in ("snapshot", "changed_by"):
                if isinstance(d[jkey], str):
                    d[jkey] = json.loads(d[jkey])
            d["changed_at"] = d["changed_at"].isoformat()
            out.append(d)
        return out
