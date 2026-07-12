"""G3 acceptance tests for Knowledge Graph paths and explainability."""

from datetime import UTC, datetime

from aqelyn.conventions import ActorRef, new_id
from aqelyn.graph import InMemoryKnowledgeGraph
from aqelyn.objects import AQObject, AQRelationship, InMemoryObjectStore, SourceRef

SYS = ActorRef(actor_type="system", actor_id="graph-test")


def _now() -> datetime:
    return datetime.now(UTC)


def _source(method: str) -> SourceRef:
    return SourceRef(
        source_id=new_id("src"),
        evidence_id=new_id("evd"),
        observed_at=_now(),
        method=method,
    )


async def _add_object(store: InMemoryObjectStore, display_name: str) -> AQObject:
    now = _now()
    return await store.upsert(
        AQObject(
            id="",
            object_type="generic",
            schema_version=1,
            display_name=display_name,
            sources=[_source(f"object:{display_name}")],
            first_seen_at=now,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
            created_by=SYS,
            updated_by=SYS,
        )
    )


async def _add_relation(
    store: InMemoryObjectStore,
    from_obj: AQObject,
    to_obj: AQObject,
    relation_type: str,
    *,
    method: str | None = None,
) -> AQRelationship:
    now = _now()
    return await store.relate(
        AQRelationship(
            id="",
            from_id=from_obj.id,
            to_id=to_obj.id,
            relation_type=relation_type,
            sources=[_source(method or relation_type)],
            created_at=now,
            updated_at=now,
            created_by=SYS,
            updated_by=SYS,
        )
    )


async def test_kg_shortest_path() -> None:
    store = InMemoryObjectStore()
    graph = InMemoryKnowledgeGraph(store)
    a = await _add_object(store, "a")
    b = await _add_object(store, "b")
    c = await _add_object(store, "c")
    d = await _add_object(store, "d")
    e = await _add_object(store, "e")
    ab = await _add_relation(store, a, b, "depends_on")
    bd = await _add_relation(store, b, d, "runs_on")
    await _add_relation(store, a, c, "depends_on")
    await _add_relation(store, c, e, "runs_on")
    await _add_relation(store, e, d, "member_of")

    shortest = await graph.shortest_path(a.id, d.id, direction="out")
    all_paths = await graph.paths(a.id, d.id, direction="out", max_depth=4)
    filtered = await graph.shortest_path(a.id, d.id, direction="out", relation_types=("member_of",))

    assert shortest is not None
    assert shortest.node_ids == [a.id, b.id, d.id]
    assert [edge.id for edge in shortest.edges] == [ab.id, bd.id]
    assert shortest.length == 2
    assert [path.length for path in all_paths] == [2, 3]
    assert filtered is None


async def test_kg_explain_path() -> None:
    store = InMemoryObjectStore()
    graph = InMemoryKnowledgeGraph(store)
    a = await _add_object(store, "a")
    b = await _add_object(store, "b")
    ab = await _add_relation(store, a, b, "depends_on", method="scanner")

    path = await graph.shortest_path(a.id, b.id, direction="out")

    assert path is not None
    explanation = await graph.explain_path(path)
    assert explanation == [
        {
            "from": a.id,
            "to": b.id,
            "relation_type": "depends_on",
            "evidence_ids": [ab.sources[0].evidence_id],
            "source_ids": [ab.sources[0].source_id],
            "source_methods": ["scanner"],
        }
    ]
