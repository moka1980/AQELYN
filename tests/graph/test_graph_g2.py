"""G2 acceptance tests for the in-memory Knowledge Graph traversal core."""

from datetime import UTC, datetime

from aqelyn.conventions import ActorRef, new_id
from aqelyn.graph import InMemoryKnowledgeGraph, Subgraph
from aqelyn.objects import AQObject, AQRelationship, InMemoryObjectStore, SourceRef

SYS = ActorRef(actor_type="system", actor_id="graph-test")
TENANT_A = "018f0000-0000-7000-8000-000000000001"
TENANT_B = "018f0000-0000-7000-8000-000000000002"


def _now() -> datetime:
    return datetime.now(UTC)


def _source(method: str) -> SourceRef:
    return SourceRef(
        source_id=new_id("src"),
        evidence_id=new_id("evd"),
        observed_at=_now(),
        method=method,
    )


async def _add_object(
    store: InMemoryObjectStore, display_name: str, *, tenant_id: str | None = None
) -> AQObject:
    now = _now()
    return await store.upsert(
        AQObject(
            id="",
            object_type="generic",
            schema_version=1,
            tenant_id=tenant_id,
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


def _node_ids(result: Subgraph) -> list[str]:
    return [node.id for node in result.nodes]


def _edge_ids(result: Subgraph) -> list[str]:
    return [edge.id for edge in result.edges]


async def test_kg_neighbors_filtered() -> None:
    store = InMemoryObjectStore()
    graph = InMemoryKnowledgeGraph(store)
    a = await _add_object(store, "a")
    b = await _add_object(store, "b")
    c = await _add_object(store, "c")
    ab = await _add_relation(store, a, b, "depends_on")
    ca = await _add_relation(store, c, a, "runs_on")

    out_depends = await graph.neighbors(a.id, direction="out", relation_types=("depends_on",))
    incoming = await graph.neighbors(a.id, direction="in")

    assert [edge.id for edge in out_depends] == [ab.id]
    assert [edge.id for edge in incoming] == [ca.id]


async def test_kg_subgraph_bounded_truncation() -> None:
    store = InMemoryObjectStore()
    graph = InMemoryKnowledgeGraph(store)
    a = await _add_object(store, "a")
    b = await _add_object(store, "b")
    c = await _add_object(store, "c")
    ab = await _add_relation(store, a, b, "depends_on")
    await _add_relation(store, b, c, "depends_on")

    result = await graph.subgraph(a.id, direction="out", max_depth=1)

    assert result.truncated is True
    assert _node_ids(result) == sorted([a.id, b.id])
    assert _edge_ids(result) == [ab.id]
    assert c.id not in _node_ids(result)


async def test_kg_edges_carry_provenance() -> None:
    store = InMemoryObjectStore()
    graph = InMemoryKnowledgeGraph(store)
    a = await _add_object(store, "a")
    b = await _add_object(store, "b")
    ab = await _add_relation(store, a, b, "depends_on", method="scanner")

    edges = await graph.neighbors(a.id, direction="out")

    assert [edge.id for edge in edges] == [ab.id]
    assert len(edges[0].sources) == 1
    assert edges[0].sources[0].evidence_id is not None
    assert edges[0].sources[0].method == "scanner"


async def test_kg_tenant_isolation() -> None:
    store = InMemoryObjectStore(mode="enterprise")
    graph = InMemoryKnowledgeGraph(store)
    a = await _add_object(store, "a", tenant_id=TENANT_A)
    b = await _add_object(store, "b", tenant_id=TENANT_A)
    x = await _add_object(store, "x", tenant_id=TENANT_B)
    ab = await _add_relation(store, a, b, "depends_on")
    now = _now()
    cross_tenant = AQRelationship(
        id=new_id("rel"),
        tenant_id=TENANT_A,
        from_id=a.id,
        to_id=x.id,
        relation_type="depends_on",
        sources=[_source("bad-cross-tenant-row")],
        created_at=now,
        updated_at=now,
        created_by=SYS,
        updated_by=SYS,
    )
    store._rels[cross_tenant.id] = cross_tenant

    result = await graph.subgraph(a.id, direction="out", max_depth=2)

    assert _node_ids(result) == sorted([a.id, b.id])
    assert _edge_ids(result) == [ab.id]
    assert x.id not in _node_ids(result)
    assert cross_tenant.id not in _edge_ids(result)


async def test_kg_excludes_inactive() -> None:
    store = InMemoryObjectStore()
    graph = InMemoryKnowledgeGraph(store)
    a = await _add_object(store, "a")
    deleted = await _add_object(store, "deleted")
    active = await _add_object(store, "active")
    await _add_relation(store, a, deleted, "depends_on")
    inactive_edge = await _add_relation(store, a, active, "runs_on")
    await store.set_state(deleted.id, "deleted", by=SYS, expected_version=deleted.version)
    store._rels[inactive_edge.id].lifecycle_state = "deleted"

    assert await graph.neighbors(a.id, direction="out") == []


async def test_kg_deterministic() -> None:
    store = InMemoryObjectStore()
    graph = InMemoryKnowledgeGraph(store)
    a = await _add_object(store, "a")
    b = await _add_object(store, "b")
    c = await _add_object(store, "c")
    await _add_relation(store, a, c, "runs_on")
    await _add_relation(store, a, b, "depends_on")

    first = await graph.subgraph(a.id, direction="out")
    second = await graph.subgraph(a.id, direction="out")

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert _node_ids(first) == sorted(_node_ids(first))
    assert _edge_ids(first) == sorted(_edge_ids(first))


async def test_kg_cycle_safe() -> None:
    store = InMemoryObjectStore()
    graph = InMemoryKnowledgeGraph(store)
    a = await _add_object(store, "a")
    b = await _add_object(store, "b")
    c = await _add_object(store, "c")
    ab = await _add_relation(store, a, b, "depends_on")
    bc = await _add_relation(store, b, c, "depends_on")
    ca = await _add_relation(store, c, a, "depends_on")

    result = await graph.subgraph(a.id, direction="out", max_depth=6)

    assert result.truncated is False
    assert _node_ids(result) == sorted([a.id, b.id, c.id])
    assert _edge_ids(result) == sorted([ab.id, bc.id, ca.id])
