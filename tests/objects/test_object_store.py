"""T2 acceptance tests for EA-0002 (§16). Run against in-memory and Postgres."""

from datetime import UTC, datetime
from typing import Any

import pytest

from aqelyn.conventions import ActorRef, new_id, parse_id
from aqelyn.conventions.errors import (
    CrossTenantReference,
    MissingProvenance,
    OptimisticConcurrencyConflict,
    SchemaValidationError,
    TenantScopeRequired,
    UnknownObjectType,
)
from aqelyn.objects import (
    AQObject,
    AQRelationship,
    InMemoryObjectStore,
    NaturalKey,
    ObjectQuery,
    ObjectTypeRegistry,
    SourceRef,
)

SYS = ActorRef(actor_type="system", actor_id="test")


def _obj(**kw: Any) -> AQObject:
    now = datetime.now(UTC)
    base: dict[str, Any] = {
        "id": "",
        "object_type": "generic",
        "schema_version": 1,
        "display_name": "thing",
        "sources": [SourceRef(source_id=new_id("src"), observed_at=now, method="test")],
        "first_seen_at": now,
        "last_seen_at": now,
        "created_at": now,
        "updated_at": now,
        "created_by": SYS,
        "updated_by": SYS,
    }
    base.update(kw)
    return AQObject(**base)


async def test_uom_id_assigned_and_immutable(object_store: Any) -> None:
    saved = await object_store.upsert(_obj())
    assert saved.id.startswith("obj_")
    again = await object_store.get(saved.id)
    assert again is not None
    assert again.id == saved.id


async def test_uom_persisted_ids_are_typed(object_store: Any) -> None:
    saved = await object_store.upsert(_obj())
    assert parse_id(saved.id)[0] == "obj"
    assert all(parse_id(source.source_id)[0] == "src" for source in saved.sources)


async def test_uom_malformed_typed_id_rejected() -> None:
    now = datetime.now(UTC)
    with pytest.raises(SchemaValidationError):
        SourceRef(source_id="src_not-a-uuid", observed_at=now, method="test")


async def test_uom_non_uuid_tenant_rejected() -> None:
    with pytest.raises(SchemaValidationError):
        _obj(tenant_id="not-a-uuid")


async def test_uom_unknown_object_type_rejected(object_store: Any) -> None:
    with pytest.raises(UnknownObjectType):
        await object_store.upsert(_obj(object_type="nope"))


async def test_uom_attributes_validated(object_store: Any) -> None:
    with pytest.raises(SchemaValidationError):
        await object_store.upsert(_obj(object_type="device", attributes={}))
    ok = await object_store.upsert(_obj(object_type="device", attributes={"hostname": "h1"}))
    assert ok.attributes["hostname"] == "h1"


async def test_uom_upsert_dedup_by_natural_key(object_store: Any) -> None:
    nk = [NaturalKey(namespace="device.serial", value="C02X")]
    a = await object_store.upsert(_obj(natural_keys=nk, attributes={"a": 1}))
    b = await object_store.upsert(_obj(natural_keys=nk, attributes={"b": 2}))
    assert a.id == b.id
    assert b.version == 2
    assert b.attributes == {"a": 1, "b": 2}


async def test_uom_optimistic_conflict(object_store: Any) -> None:
    saved = await object_store.upsert(_obj())
    saved.display_name = "renamed"
    await object_store.update(saved, expected_version=1)
    with pytest.raises(OptimisticConcurrencyConflict):
        await object_store.update(saved, expected_version=1)


async def test_uom_requires_provenance(object_store: Any) -> None:
    with pytest.raises(MissingProvenance):
        await object_store.upsert(_obj(sources=[]))


async def test_uom_soft_delete_and_history(object_store: Any) -> None:
    saved = await object_store.upsert(_obj())
    deleted = await object_store.set_state(
        saved.id, "deleted", by=SYS, expected_version=saved.version
    )
    assert deleted.lifecycle_state == "deleted"
    hist = await object_store.history(saved.id)
    assert len(hist) >= 2  # create + delete


async def test_uom_merge_survivor_redirect(object_store: Any) -> None:
    a = await object_store.upsert(_obj(display_name="survivor"))
    b = await object_store.upsert(_obj(display_name="dupe"))
    c = await object_store.upsert(_obj(display_name="other"))
    await object_store.relate(
        AQRelationship(
            id="",
            from_id=b.id,
            to_id=c.id,
            relation_type="owns",
            created_at=a.created_at,
            updated_at=a.created_at,
            created_by=SYS,
            updated_by=SYS,
        )
    )
    await object_store.merge(a.id, b.id, by=SYS)
    resolved = await object_store.get(b.id)
    assert resolved is not None
    assert resolved.id == a.id  # redirect
    rels = await object_store.relationships(a.id, direction="out")
    assert any(r.to_id == c.id for r in rels)  # re-pointed


async def test_uom_tenant_scoping(object_store: Any) -> None:
    await object_store.upsert(_obj())
    rows, _ = await object_store.query(ObjectQuery())
    assert len(rows) >= 1  # local mode returns NULL-tenant objects


async def test_uom_enterprise_requires_scope() -> None:
    store = InMemoryObjectStore(registry=ObjectTypeRegistry(), mode="enterprise")
    with pytest.raises(TenantScopeRequired):
        await store.query(ObjectQuery())


async def test_uom_history_append_only(object_store: Any) -> None:
    saved = await object_store.upsert(_obj())
    h1 = await object_store.history(saved.id)
    saved.display_name = "x"
    await object_store.update(saved, expected_version=saved.version)
    h2 = await object_store.history(saved.id)
    assert len(h2) == len(h1) + 1
    assert h2[: len(h1)] == h1  # earlier rows unchanged (append-only)


async def test_uom_cross_tenant_edge_rejected() -> None:
    store = InMemoryObjectStore(registry=ObjectTypeRegistry(), mode="enterprise")
    a = await store.upsert(_obj(tenant_id="018f0000-0000-7000-8000-000000000001"))
    b = await store.upsert(_obj(tenant_id="018f0000-0000-7000-8000-000000000002"))
    with pytest.raises(CrossTenantReference):
        await store.relate(
            AQRelationship(
                id="",
                from_id=a.id,
                to_id=b.id,
                relation_type="owns",
                created_at=a.created_at,
                updated_at=a.created_at,
                created_by=SYS,
                updated_by=SYS,
            )
        )
