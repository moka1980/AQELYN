"""G3a acceptance tests for ECR-0001 paths() work budgeting."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from aqelyn.conventions import ActorRef, new_id
from aqelyn.conventions.errors import GraphQueryInvalid
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


async def test_kg_paths_work_budget(graph_harness: Any) -> None:
    store = graph_harness.object_store
    graph = graph_harness.graph
    start = await _add_object(store, "start")
    target = await _add_object(store, "target")
    direct = await _add_relation(store, start, target, "depends_on", method="direct")
    mids = [await _add_object(store, f"mid-{idx}") for idx in range(5)]
    leaves = [await _add_object(store, f"leaf-{idx}") for idx in range(5)]

    for mid in mids:
        await _add_relation(store, start, mid, "depends_on")
    for mid in mids:
        for leaf in leaves:
            await _add_relation(store, mid, leaf, "depends_on")
    for leaf in leaves:
        await _add_relation(store, leaf, target, "depends_on")

    with pytest.raises(GraphQueryInvalid, match="max_work"):
        await graph.paths(start.id, target.id, direction="out", max_work=0)

    budgeted = await graph.paths(
        start.id,
        target.id,
        direction="out",
        max_depth=3,
        max_paths=20,
        max_work=1,
    )
    full = await graph.paths(
        start.id,
        target.id,
        direction="out",
        max_depth=3,
        max_paths=20,
        max_work=1_000,
    )

    assert len(budgeted) == 1
    assert budgeted[0].node_ids == [start.id, target.id]
    assert [edge.id for edge in budgeted[0].edges] == [direct.id]
    assert len(full) > len(budgeted)
    assert full[0].node_ids == budgeted[0].node_ids
