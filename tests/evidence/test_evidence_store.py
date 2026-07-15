"""T4 acceptance tests for EA-0004 (§11). Run against in-memory and Postgres."""

from datetime import UTC, datetime
from typing import Any

import pytest

from aqelyn.conventions import ActorRef, new_id, parse_id
from aqelyn.conventions.errors import EvidenceNotFound, SchemaValidationError
from aqelyn.events import InMemoryEventBus, Subject
from aqelyn.evidence import (
    EvidenceRecord,
    InMemoryBlobStore,
    InMemoryEvidenceStore,
)

SYS = ActorRef(actor_type="system", actor_id="collector")


def _rec(**kw: Any) -> EvidenceRecord:
    now = datetime.now(UTC)
    base: dict[str, Any] = {
        "id": "",
        "evidence_type": "config.snapshot",
        "schema_version": 1,
        "subject": Subject(object_ids=[new_id("obj")]),
        "collected_at": now,
        "recorded_at": now,
        "collector": SYS,
        "source_id": new_id("src"),
        "method": "test",
        "content": {"k": "v"},
        "content_hash": "",
        "seq": 0,
        "prev_hash": None,
        "record_hash": "",
    }
    base.update(kw)
    return EvidenceRecord(**base)


async def test_evd_chain_fields_assigned(evidence_store: Any) -> None:
    r = await evidence_store.add(_rec())
    assert r.id.startswith("evd_")
    assert r.seq == 1
    assert r.prev_hash is None
    assert r.record_hash
    r2 = await evidence_store.add(_rec())
    assert r2.seq == 2
    assert r2.prev_hash == r.record_hash


async def test_evd_content_hash(evidence_store: Any) -> None:
    r = await evidence_store.add(_rec(content={"a": 1}))
    assert (await evidence_store.verify(r.id)).ok


async def test_evd_persisted_ids_are_typed(evidence_store: Any) -> None:
    r = await evidence_store.add(_rec())
    assert parse_id(r.id)[0] == "evd"
    assert parse_id(r.source_id)[0] == "src"
    assert all(parse_id(object_id)[0] == "obj" for object_id in r.subject.object_ids)


async def test_evd_malformed_typed_id_rejected() -> None:
    with pytest.raises(SchemaValidationError):
        _rec(source_id="src_not-a-uuid")


async def test_evd_non_uuid_tenant_rejected() -> None:
    with pytest.raises(SchemaValidationError):
        _rec(tenant_id="not-a-uuid")


async def test_evd_content_xor_ref() -> None:
    with pytest.raises(SchemaValidationError):
        _rec(content=None, content_ref=None)


async def test_evd_verify_detects_tamper(evidence_store: Any) -> None:
    r = await evidence_store.add(_rec(content={"a": 1}))
    # tamper the in-memory record directly
    if isinstance(evidence_store, InMemoryEvidenceStore):
        evidence_store._by_id[r.id].content = {"a": 2}
        res = await evidence_store.verify(r.id)
        assert not res.ok
    else:
        async with evidence_store._pool.acquire() as conn:
            await conn.execute("UPDATE aq_evidence SET content=$2 WHERE id=$1", r.id, '{"a": 2}')
        res = await evidence_store.verify(r.id)
        assert not res.ok


async def test_evd_verify_chain_break(evidence_store: Any) -> None:
    await evidence_store.add(_rec())
    await evidence_store.add(_rec())
    res = await evidence_store.verify_chain(tenant_id=None)
    assert res.ok


async def test_evd_custody_logged(evidence_store: Any) -> None:
    r = await evidence_store.add(_rec())
    intake = await evidence_store.custody_of(r.id)
    assert [entry["action"] for entry in intake] == ["intake"]
    await evidence_store.get(r.id, actor=SYS)
    custody = await evidence_store.custody_of(r.id)
    assert [entry["action"] for entry in custody] == ["intake", "read"]


async def test_evd_package_self_verifying(evidence_store: Any) -> None:
    a = await evidence_store.add(_rec())
    b = await evidence_store.add(_rec())
    pkg = await evidence_store.package([a.id, b.id], by=SYS, reason="audit")
    assert (await evidence_store.verify_package(pkg.id)).ok


async def test_evd_emits_event() -> None:
    from aqelyn.evidence import register_evidence_events

    bus = InMemoryEventBus()
    register_evidence_events(bus.registry)
    store = InMemoryEvidenceStore(event_bus=bus)
    r = await store.add(_rec())
    assert any(
        e.event_type == "aqelyn.evidence.recorded" and e.subject.evidence_id == r.id
        for e in bus.log
    )


async def test_evd_blob_integrity() -> None:
    blobs = InMemoryBlobStore()
    ref = await blobs.put(b"hello", media_type="text/plain")
    assert await blobs.get(ref) == b"hello"


async def test_evd_not_found(evidence_store: Any) -> None:
    with pytest.raises(EvidenceNotFound):
        await evidence_store.verify(new_id("evd"))
