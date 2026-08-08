"""In-memory ObjectStore (EA-0002). Reference implementation + test double."""

from __future__ import annotations

import copy
from bisect import bisect_right, insort
from collections.abc import Callable
from typing import Any

from aqelyn.conventions import ActorRef, new_id, utc_now
from aqelyn.conventions.errors import (
    CrossTenantReference,
    MissingProvenance,
    ObjectNotFound,
    OptimisticConcurrencyConflict,
    SchemaValidationError,
    TenantScopeRequired,
)
from aqelyn.objects.models import AQObject, AQRelationship, NaturalKey, ObjectQuery
from aqelyn.objects.registry import ObjectTypeRegistry
from aqelyn.objects.store import (
    VALID_TRANSITIONS,
    ObjectEventSink,
    dedupe_sources,
    merge_attributes,
    validate_object_id,
)


class InMemoryObjectStore:
    def __init__(
        self,
        *,
        registry: ObjectTypeRegistry | None = None,
        mode: str = "local",
        event_sink: ObjectEventSink | None = None,
    ) -> None:
        self._objs: dict[str, AQObject] = {}
        self._object_ids: list[str] = []
        self._rels: dict[str, AQRelationship] = {}
        self._nk: dict[tuple[str | None, str, str], str] = {}
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._seq = 0
        self.registry = registry or ObjectTypeRegistry()
        self.mode = mode
        self._sink = event_sink

    # --- helpers ---
    def _write_history(self, obj: AQObject) -> None:
        self._seq += 1
        self._history.setdefault(obj.id, []).append(
            {
                "seq": self._seq,
                "version": obj.version,
                "snapshot": obj.model_dump(mode="json"),
                "changed_at": utc_now().isoformat(),
                "changed_by": obj.updated_by.model_dump(),
            }
        )

    async def _emit(
        self, event_type: str, obj: AQObject, actor: ActorRef, payload: dict[str, Any]
    ) -> None:
        if self._sink is not None:
            await self._sink.object_event(
                event_type,
                object_id=obj.id,
                tenant_id=obj.tenant_id,
                payload=payload,
                actor=actor,
            )

    def _nk_lookup(self, tenant: str | None, obj_type: str, keys: list[NaturalKey]) -> str | None:
        for k in keys:
            hit = self._nk.get((tenant, k.namespace, k.value))
            if hit is not None:
                existing = self._objs[hit]
                if existing.object_type == obj_type and existing.lifecycle_state in (
                    "active",
                    "archived",
                ):
                    return hit
        return None

    def _index_nk(self, obj: AQObject) -> None:
        for k in obj.natural_keys:
            self._nk[(obj.tenant_id, k.namespace, k.value)] = obj.id

    # --- interface ---
    async def get(self, object_id: str, *, resolve_merged: bool = True) -> AQObject | None:
        validate_object_id(object_id)
        obj = self._objs.get(object_id)
        if obj is None:
            return None
        if resolve_merged:
            seen = {obj.id}
            while obj.lifecycle_state == "merged" and obj.merged_into is not None:
                nxt = self._objs.get(obj.merged_into)
                if nxt is None or nxt.id in seen:
                    break
                seen.add(nxt.id)
                obj = nxt
        return copy.deepcopy(obj)

    async def upsert(self, obj: AQObject) -> AQObject:
        live, event_type, actor, payload, _undo = await self._upsert_quiet(obj)
        await self._emit(event_type, live, actor, payload)
        return copy.deepcopy(live)

    async def _upsert_quiet(
        self, obj: AQObject
    ) -> tuple[AQObject, str, ActorRef, dict[str, Any], Callable[[], None]]:
        """The upsert without its event, plus a precise undo of THIS write only (ECR-0124).

        An atomic composite defers the returned event until its whole unit succeeds and calls
        the undo if it does not — touching nothing but the one row this call wrote, so an
        unrelated concurrent write is never rolled back with it."""

        if not obj.sources:
            raise MissingProvenance("object requires at least one source")
        self.registry.validate(obj.object_type, obj.attributes)
        match_id = self._nk_lookup(obj.tenant_id, obj.object_type, obj.natural_keys)
        now = utc_now()
        if match_id is not None:
            existing = self._objs[match_id]
            before = copy.deepcopy(existing)
            existing.attributes = merge_attributes(existing.attributes, obj.attributes)
            existing.labels = {**existing.labels, **obj.labels}
            existing.sources = dedupe_sources([*existing.sources, *obj.sources])
            existing.last_seen_at = max(existing.last_seen_at, obj.last_seen_at)
            existing.display_name = obj.display_name or existing.display_name
            existing.version += 1
            existing.updated_at = now
            existing.updated_by = obj.updated_by
            self._index_nk(existing)
            self._write_history(existing)

            written_version = existing.version

            def _undo_update() -> None:
                current = self._objs.get(match_id)
                # Restore the pre-image ONLY if the row is exactly as this unit left it.
                # A concurrent writer who advanced it since must not be overwritten by a
                # rollback that isn't theirs (Codex re-review, 2026-08-08).
                if current is None or current.version != written_version:
                    return
                self._objs[match_id] = before
                history = self._history.get(match_id)
                if history:
                    history.pop()

            return (
                existing,
                "aqelyn.object.updated",
                existing.updated_by,
                {"changed_fields": ["*"]},
                _undo_update,
            )
        created = obj.model_copy(deep=True)
        if not created.id:
            created.id = new_id("obj")
        created.version = 1
        created.created_at = now
        created.updated_at = now
        self._objs[created.id] = created
        insort(self._object_ids, created.id)
        self._index_nk(created)
        self._write_history(created)
        created_id = created.id

        def _undo_create() -> None:
            current = self._objs.get(created_id)
            # Delete ONLY if nobody has built on the row since this unit created it; a
            # concurrent writer's update must survive our rollback (their data, not ours).
            if current is None or current.version != 1:
                return
            del self._objs[created_id]
            if created_id in self._object_ids:
                self._object_ids.remove(created_id)
            for key in created.natural_keys:
                nk_key = (created.tenant_id, key.namespace, key.value)
                if self._nk.get(nk_key) == created_id:
                    del self._nk[nk_key]
            self._history.pop(created_id, None)

        return (
            created,
            "aqelyn.object.created",
            created.created_by,
            {"object_type": created.object_type},
            _undo_create,
        )

    async def update(self, obj: AQObject, *, expected_version: int) -> AQObject:
        existing = self._objs.get(obj.id)
        if existing is None:
            raise ObjectNotFound(obj.id)
        if existing.version != expected_version:
            raise OptimisticConcurrencyConflict(
                f"expected v{expected_version}, found v{existing.version}"
            )
        updated = obj.model_copy(deep=True)
        updated.version = existing.version + 1
        updated.created_at = existing.created_at
        updated.updated_at = utc_now()
        self._objs[updated.id] = updated
        self._index_nk(updated)
        self._write_history(updated)
        await self._emit(
            "aqelyn.object.updated", updated, updated.updated_by, {"changed_fields": ["*"]}
        )
        return copy.deepcopy(updated)

    async def query(self, q: ObjectQuery) -> tuple[list[AQObject], str | None]:
        if self.mode == "enterprise" and q.tenant_id is None:
            raise TenantScopeRequired("query must be tenant-scoped in enterprise mode")
        selected: list[AQObject] = []
        start = 0 if q.cursor is None else bisect_right(self._object_ids, q.cursor)
        has_more = False
        for index in range(start, len(self._object_ids)):
            object_id = self._object_ids[index]
            obj = self._objs[object_id]
            if self.mode == "local" and obj.tenant_id is not None:
                continue
            if q.tenant_id is not None and obj.tenant_id != q.tenant_id:
                continue
            if obj.lifecycle_state not in q.include_states:
                continue
            if q.object_type is not None and obj.object_type != q.object_type:
                continue
            if q.exclude_object_types and obj.object_type in q.exclude_object_types:
                continue
            if q.labels and any(obj.labels.get(k) != v for k, v in q.labels.items()):
                continue
            if q.natural_key is not None and not any(
                nk.namespace == q.natural_key.namespace and nk.value == q.natural_key.value
                for nk in obj.natural_keys
            ):
                continue
            if len(selected) == q.limit:
                has_more = True
                break
            selected.append(obj)
        next_cursor = selected[-1].id if has_more and selected else None
        return [copy.deepcopy(obj) for obj in selected], next_cursor

    async def relate(self, rel: AQRelationship) -> AQRelationship:
        frm = self._objs.get(rel.from_id)
        to = self._objs.get(rel.to_id)
        if frm is None or to is None:
            raise ObjectNotFound("relationship endpoint missing")
        if frm.tenant_id != to.tenant_id:
            raise CrossTenantReference("relationship endpoints span tenants")
        created = rel.model_copy(deep=True)
        if not created.id:
            created.id = new_id("rel")
        created.tenant_id = frm.tenant_id
        self._rels[created.id] = created
        return copy.deepcopy(created)

    async def relationships(
        self, object_id: str, *, direction: str = "both", relation_type: str | None = None
    ) -> list[AQRelationship]:
        validate_object_id(object_id)
        out: list[AQRelationship] = []
        for rel in self._rels.values():
            if rel.lifecycle_state != "active":
                continue
            if relation_type is not None and rel.relation_type != relation_type:
                continue
            match = (direction in ("both", "out") and rel.from_id == object_id) or (
                direction in ("both", "in") and rel.to_id == object_id
            )
            if match:
                out.append(copy.deepcopy(rel))
        return out

    async def merge(self, survivor_id: str, duplicate_id: str, *, by: ActorRef) -> AQObject:
        validate_object_id(survivor_id, field="survivor_id")
        validate_object_id(duplicate_id, field="duplicate_id")
        survivor = self._objs.get(survivor_id)
        duplicate = self._objs.get(duplicate_id)
        if survivor is None or duplicate is None:
            raise ObjectNotFound("merge endpoint missing")
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
        self._index_nk(survivor)
        for rel in self._rels.values():
            if rel.from_id == duplicate_id:
                rel.from_id = survivor_id
            if rel.to_id == duplicate_id:
                rel.to_id = survivor_id
        duplicate.lifecycle_state = "merged"
        duplicate.merged_into = survivor_id
        duplicate.version += 1
        duplicate.updated_at = utc_now()
        duplicate.updated_by = by
        self._write_history(survivor)
        self._write_history(duplicate)
        await self._emit(
            "aqelyn.object.merged",
            survivor,
            by,
            {"survivor_id": survivor_id, "duplicate_id": duplicate_id},
        )
        return copy.deepcopy(survivor)

    async def set_state(
        self, object_id: str, state: str, *, by: ActorRef, expected_version: int
    ) -> AQObject:
        validate_object_id(object_id)
        obj = self._objs.get(object_id)
        if obj is None:
            raise ObjectNotFound(object_id)
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
        self._write_history(obj)
        await self._emit("aqelyn.object.state_changed", obj, by, {"from": prev, "to": state})
        return copy.deepcopy(obj)

    async def history(self, object_id: str) -> list[dict[str, Any]]:
        validate_object_id(object_id)
        return list(self._history.get(object_id, []))
