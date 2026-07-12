"""G4 acceptance tests for impact, correlation, and Postgres graph parity."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from aqelyn.conventions import ActorRef, new_id
from aqelyn.graph import ImpactResult, Subgraph
from aqelyn.objects import AQObject, AQRelationship, ObjectStore, SourceRef

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


async def _add_object(store: ObjectStore, display_name: str) -> AQObject:
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
    store: ObjectStore,
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


def _node_ids(result: Subgraph) -> set[str]:
    return {node.id for node in result.nodes}


def _edge_ids(result: Subgraph) -> set[str]:
    return {edge.id for edge in result.edges}


def _hit_by_node(result: ImpactResult) -> dict[str, Any]:
    return {hit.node.id: hit for hit in result.hits}


async def test_kg_impact_blast_radius(graph_harness: Any) -> None:
    store = graph_harness.object_store
    graph = graph_harness.graph
    database = await _add_object(store, "database")
    app = await _add_object(store, "app")
    api = await _add_object(store, "api")
    owner = await _add_object(store, "owner")
    app_database = await _add_relation(store, app, database, "depends_on", method="scanner")
    api_app = await _add_relation(store, api, app, "runs_on")
    owner_database = await _add_relation(store, owner, database, "owns")

    result = await graph.impact(database.id)
    limited = await graph.impact(database.id, max_depth=1)
    custom = await graph.impact(database.id, relation_types=("owns",))

    hits = _hit_by_node(result)
    assert set(hits) == {app.id, api.id}
    assert hits[app.id].via.node_ids == [database.id, app.id]
    assert [edge.id for edge in hits[app.id].via.edges] == [app_database.id]
    assert hits[app.id].via.edges[0].sources[0].method == "scanner"
    assert hits[api.id].via.node_ids == [database.id, app.id, api.id]
    assert [edge.id for edge in hits[api.id].via.edges] == [app_database.id, api_app.id]
    assert limited.truncated is True
    assert set(_hit_by_node(limited)) == {app.id}
    assert set(_hit_by_node(custom)) == {owner.id}
    assert custom.hits[0].via.edges[0].id == owner_database.id


async def test_kg_correlate(graph_harness: Any) -> None:
    store = graph_harness.object_store
    graph = graph_harness.graph
    a = await _add_object(store, "a")
    b = await _add_object(store, "b")
    c = await _add_object(store, "c")
    d = await _add_object(store, "d")
    disconnected = await _add_object(store, "x")
    ab = await _add_relation(store, a, b, "depends_on")
    bc = await _add_relation(store, b, c, "depends_on")
    await _add_relation(store, c, d, "runs_on")

    result = await graph.correlate([a.id, c.id], within_hops=1, relation_types=("depends_on",))
    limited = await graph.correlate([a.id], within_hops=2, max_nodes=2)

    assert result.truncated is False
    assert _node_ids(result) == {a.id, b.id, c.id}
    assert _edge_ids(result) == {ab.id, bc.id}
    assert disconnected.id not in _node_ids(result)
    assert d.id not in _node_ids(result)
    assert limited.truncated is True
    assert len(limited.nodes) == 2


async def test_kg_contract(graph_harness: Any) -> None:
    store = graph_harness.object_store
    graph = graph_harness.graph
    a = await _add_object(store, "a")
    b = await _add_object(store, "b")
    c = await _add_object(store, "c")
    ab = await _add_relation(store, a, b, "depends_on", method="contract")
    bc = await _add_relation(store, b, c, "runs_on")

    neighbors = await graph.neighbors(a.id, direction="out", relation_types=("depends_on",))
    subgraph = await graph.subgraph(a.id, direction="out", max_depth=1)
    shortest = await graph.shortest_path(a.id, c.id, direction="out")
    explanation = await graph.explain_path(shortest) if shortest is not None else []
    impact = await graph.impact(c.id)
    correlation = await graph.correlate([a.id], within_hops=2)

    assert [edge.id for edge in neighbors] == [ab.id]
    assert subgraph.truncated is True
    assert _node_ids(subgraph) == {a.id, b.id}
    assert shortest is not None
    assert shortest.node_ids == [a.id, b.id, c.id]
    assert [edge.id for edge in shortest.edges] == [ab.id, bc.id]
    assert explanation[0]["source_methods"] == ["contract"]
    assert set(_hit_by_node(impact)) == {a.id, b.id}
    assert _node_ids(correlation) == {a.id, b.id, c.id}
