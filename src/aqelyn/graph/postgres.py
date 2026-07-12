"""PostgreSQL Knowledge Graph over EA-0002 tables (EA-0005 G4)."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import asyncpg

from aqelyn.conventions.errors import GraphQueryInvalid, ObjectNotFound, StoreUnavailable
from aqelyn.graph.graph import (
    DEFAULT_IMPACT_RELATION_TYPES,
    normalize_limits,
    validate_direction,
    validate_max_paths,
    validate_within_hops,
)
from aqelyn.graph.models import (
    Direction,
    EdgeView,
    ImpactHit,
    ImpactResult,
    NodeView,
    Path,
    Subgraph,
)
from aqelyn.objects.ddl import DDL
from aqelyn.objects.store import validate_object_id

VISIBLE_NODE_STATES = ("active", "archived")
_NODE_COLS = "id, object_type, display_name, tenant_id, lifecycle_state"
_EDGE_COLS = "id, from_id, to_id, relation_type, confidence, sources"
_REL_EDGE_COLS = "r.id, r.from_id, r.to_id, r.relation_type, r.confidence, r.sources"


@dataclass(frozen=True)
class _WalkRow:
    node_id: str
    depth: int
    node_ids: list[str]
    edge_ids: list[str]


def _to_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _node_view(row: asyncpg.Record) -> NodeView:
    return NodeView(
        id=str(row["id"]),
        object_type=str(row["object_type"]),
        display_name=str(row["display_name"]),
        tenant_id=row["tenant_id"],
    )


def _edge_view(row: asyncpg.Record) -> EdgeView:
    return EdgeView(
        id=str(row["id"]),
        from_id=str(row["from_id"]),
        to_id=str(row["to_id"]),
        relation_type=str(row["relation_type"]),
        confidence=float(row["confidence"]),
        sources=_json_value(row["sources"]),
    )


def _walk_row(row: asyncpg.Record) -> _WalkRow:
    return _WalkRow(
        node_id=str(row["node_id"]),
        depth=int(row["depth"]),
        node_ids=[str(item) for item in row["path_node_ids"]],
        edge_ids=[str(item) for item in row["edge_ids"]],
    )


def _adjacent_ids(current_id: str, edge: EdgeView, direction: Direction) -> list[str]:
    adjacent: list[str] = []
    if direction in ("out", "both") and edge.from_id == current_id:
        adjacent.append(edge.to_id)
    if direction in ("in", "both") and edge.to_id == current_id and edge.from_id not in adjacent:
        adjacent.append(edge.from_id)
    return adjacent


class PostgresKnowledgeGraph:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, url: str) -> PostgresKnowledgeGraph:
        try:
            pool = await asyncpg.create_pool(_to_dsn(url), min_size=1, max_size=5)
        except Exception as exc:
            raise StoreUnavailable(str(exc)) from exc
        assert pool is not None
        async with pool.acquire() as conn:
            await conn.execute(DDL)
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    async def neighbors(
        self,
        node_id: str,
        *,
        direction: str = "both",
        relation_types: Sequence[str] | None = None,
    ) -> list[EdgeView]:
        start = await self._visible_start(node_id)
        normalized_direction = validate_direction(direction)
        rel_types = frozenset(relation_types) if relation_types is not None else None
        edges = await self._visible_edges(
            start.id,
            tenant_id=start.tenant_id,
            direction=normalized_direction,
            relation_types=rel_types,
        )
        return [edges[edge_id] for edge_id in sorted(edges)]

    async def subgraph(
        self,
        start_id: str,
        *,
        direction: str = "both",
        relation_types: Sequence[str] | None = None,
        max_depth: int = 6,
        max_nodes: int = 10_000,
    ) -> Subgraph:
        start = await self._visible_start(start_id)
        normalized_direction = validate_direction(direction)
        rel_types = frozenset(relation_types) if relation_types is not None else None
        limits = normalize_limits(max_depth=max_depth, max_nodes=max_nodes)
        rows, truncated = await self._recursive_walk(
            [start.id],
            tenant_id=start.tenant_id,
            direction=normalized_direction,
            relation_types=rel_types,
            max_depth=limits.max_depth,
            max_nodes=limits.max_nodes,
        )
        node_ids = sorted({row.node_id for row in rows})
        depths = _min_depths(rows)
        edge_ids = await self._subgraph_edge_ids(
            node_ids,
            source_ids=[node_id for node_id, depth in depths.items() if depth < limits.max_depth],
            tenant_id=start.tenant_id,
            direction=normalized_direction,
            relation_types=rel_types,
        )
        node_views = await self._node_views(node_ids)
        edge_views = await self._edge_views(edge_ids)
        return Subgraph(
            nodes=[node_views[node_id] for node_id in sorted(node_views)],
            edges=[edge_views[edge_id] for edge_id in sorted(edge_views)],
            truncated=truncated,
        )

    async def shortest_path(
        self,
        from_id: str,
        to_id: str,
        *,
        direction: str = "both",
        relation_types: Sequence[str] | None = None,
        max_depth: int = 6,
    ) -> Path | None:
        start = await self._visible_start(from_id)
        target = await self._visible_node(to_id, tenant_id=start.tenant_id)
        if target is None:
            return None
        normalized_direction = validate_direction(direction)
        rel_types = frozenset(relation_types) if relation_types is not None else None
        depth_limit = normalize_limits(max_depth=max_depth).max_depth
        if start.id == target.id:
            return Path(node_ids=[start.id], edges=[], length=0)

        queue: deque[tuple[str, list[str], list[EdgeView]]] = deque([(start.id, [start.id], [])])
        visited: set[str] = {start.id}
        while queue:
            current_id, node_ids, edges = queue.popleft()
            if len(edges) >= depth_limit:
                continue
            for adjacent_id, edge in await self._walk_edges(
                current_id,
                tenant_id=start.tenant_id,
                direction=normalized_direction,
                relation_types=rel_types,
            ):
                if adjacent_id in visited:
                    continue
                adjacent_node_ids = [*node_ids, adjacent_id]
                adjacent_edges = [*edges, edge]
                if adjacent_id == target.id:
                    return Path(
                        node_ids=adjacent_node_ids,
                        edges=adjacent_edges,
                        length=len(adjacent_edges),
                    )
                visited.add(adjacent_id)
                queue.append((adjacent_id, adjacent_node_ids, adjacent_edges))
        return None

    async def paths(
        self,
        from_id: str,
        to_id: str,
        *,
        direction: str = "both",
        relation_types: Sequence[str] | None = None,
        max_depth: int = 6,
        max_paths: int = 10,
    ) -> list[Path]:
        start = await self._visible_start(from_id)
        target = await self._visible_node(to_id, tenant_id=start.tenant_id)
        if target is None:
            return []
        normalized_direction = validate_direction(direction)
        rel_types = frozenset(relation_types) if relation_types is not None else None
        depth_limit = normalize_limits(max_depth=max_depth).max_depth
        path_limit = validate_max_paths(max_paths)
        if start.id == target.id:
            return [Path(node_ids=[start.id], edges=[], length=0)]

        found: list[Path] = []
        queue: deque[tuple[str, list[str], list[EdgeView]]] = deque([(start.id, [start.id], [])])
        while queue and len(found) < path_limit:
            current_id, node_ids, edges = queue.popleft()
            if len(edges) >= depth_limit:
                continue
            for adjacent_id, edge in await self._walk_edges(
                current_id,
                tenant_id=start.tenant_id,
                direction=normalized_direction,
                relation_types=rel_types,
            ):
                if adjacent_id in node_ids:
                    continue
                adjacent_node_ids = [*node_ids, adjacent_id]
                adjacent_edges = [*edges, edge]
                if adjacent_id == target.id:
                    found.append(
                        Path(
                            node_ids=adjacent_node_ids,
                            edges=adjacent_edges,
                            length=len(adjacent_edges),
                        )
                    )
                    if len(found) >= path_limit:
                        break
                    continue
                queue.append((adjacent_id, adjacent_node_ids, adjacent_edges))
        return found

    async def impact(
        self,
        node_id: str,
        *,
        direction: str = "in",
        relation_types: Sequence[str] | None = None,
        max_depth: int = 6,
        max_nodes: int = 10_000,
    ) -> ImpactResult:
        start = await self._visible_start(node_id)
        normalized_direction = validate_direction(direction)
        rel_types = (
            DEFAULT_IMPACT_RELATION_TYPES if relation_types is None else frozenset(relation_types)
        )
        limits = normalize_limits(max_depth=max_depth, max_nodes=max_nodes)
        rows, truncated = await self._recursive_walk(
            [start.id],
            tenant_id=start.tenant_id,
            direction=normalized_direction,
            relation_types=rel_types,
            max_depth=limits.max_depth,
            max_nodes=limits.max_nodes,
        )
        node_views = await self._node_views([row.node_id for row in rows])
        edge_views = await self._edge_views(
            sorted({edge_id for row in rows for edge_id in row.edge_ids})
        )
        hits: dict[str, ImpactHit] = {}
        for row in rows:
            if row.node_id == start.id or row.node_id in hits:
                continue
            path_edges = [edge_views[edge_id] for edge_id in row.edge_ids]
            hits[row.node_id] = ImpactHit(
                node=node_views[row.node_id],
                via=Path(node_ids=row.node_ids, edges=path_edges, length=len(path_edges)),
            )
        return ImpactResult(
            hits=[hits[node_id] for node_id in sorted(hits)],
            truncated=truncated,
        )

    async def correlate(
        self,
        seed_ids: Sequence[str],
        *,
        within_hops: int = 2,
        relation_types: Sequence[str] | None = None,
        max_nodes: int = 10_000,
    ) -> Subgraph:
        if not seed_ids:
            raise GraphQueryInvalid("seed_ids must not be empty")
        depth_limit = validate_within_hops(within_hops)
        limits = normalize_limits(max_depth=depth_limit, max_nodes=max_nodes)
        rel_types = frozenset(relation_types) if relation_types is not None else None
        seeds = sorted(
            [await self._visible_start(seed_id) for seed_id in seed_ids],
            key=lambda node: node.id,
        )
        rows: list[_WalkRow] = []
        truncated = False
        seeds_by_tenant: dict[str | None, list[str]] = {}
        for seed in seeds:
            seeds_by_tenant.setdefault(seed.tenant_id, []).append(seed.id)
        for tenant_id, tenant_seed_ids in seeds_by_tenant.items():
            tenant_rows, tenant_truncated = await self._recursive_walk(
                tenant_seed_ids,
                tenant_id=tenant_id,
                direction="both",
                relation_types=rel_types,
                max_depth=limits.max_depth,
                max_nodes=limits.max_nodes,
            )
            truncated = truncated or tenant_truncated
            rows.extend(tenant_rows)

        tenant_by_node: dict[str, str | None] = {}
        for seed in seeds:
            for row in rows:
                if row.node_ids[0] == seed.id:
                    tenant_by_node[row.node_id] = seed.tenant_id
        node_ids: list[str] = []
        seen_nodes: set[str] = set()
        for node_id in sorted({row.node_id for row in rows}):
            if len(node_ids) >= limits.max_nodes:
                truncated = True
                break
            if node_id not in seen_nodes:
                seen_nodes.add(node_id)
                node_ids.append(node_id)

        node_views = await self._node_views(node_ids)
        edge_ids: set[str] = set()
        for seed in seeds:
            tenant_rows = [row for row in rows if tenant_by_node.get(row.node_id) == seed.tenant_id]
            tenant_nodes = [row.node_id for row in tenant_rows if row.node_id in node_views]
            depths = _min_depths([row for row in tenant_rows if row.node_id in node_views])
            edge_ids.update(
                await self._subgraph_edge_ids(
                    tenant_nodes,
                    source_ids=[
                        node_id for node_id, depth in depths.items() if depth < limits.max_depth
                    ],
                    tenant_id=seed.tenant_id,
                    direction="both",
                    relation_types=rel_types,
                )
            )
        edge_views = await self._edge_views(sorted(edge_ids))
        return Subgraph(
            nodes=[node_views[node_id] for node_id in sorted(node_views)],
            edges=[edge_views[edge_id] for edge_id in sorted(edge_views)],
            truncated=truncated,
        )

    async def explain_path(self, path: Path) -> list[dict[str, object]]:
        if path.length != len(path.edges) or len(path.node_ids) != len(path.edges) + 1:
            raise GraphQueryInvalid("path node/edge counts are inconsistent")
        explanation: list[dict[str, object]] = []
        for index, edge in enumerate(path.edges):
            explanation.append(
                {
                    "from": path.node_ids[index],
                    "to": path.node_ids[index + 1],
                    "relation_type": edge.relation_type,
                    "evidence_ids": [
                        source.evidence_id
                        for source in edge.sources
                        if source.evidence_id is not None
                    ],
                    "source_ids": [source.source_id for source in edge.sources],
                    "source_methods": [source.method for source in edge.sources],
                }
            )
        return explanation

    async def _visible_start(self, node_id: str) -> NodeView:
        validate_object_id(node_id, field="node_id")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(f"SELECT {_NODE_COLS} FROM aq_object WHERE id=$1", node_id)
        if row is None or row["lifecycle_state"] not in VISIBLE_NODE_STATES:
            raise ObjectNotFound(node_id)
        return _node_view(row)

    async def _visible_node(self, node_id: str, *, tenant_id: str | None) -> NodeView | None:
        validate_object_id(node_id, field="node_id")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_NODE_COLS} FROM aq_object "
                "WHERE id=$1 AND lifecycle_state = ANY($2::text[]) "
                "AND tenant_id IS NOT DISTINCT FROM $3",
                node_id,
                list(VISIBLE_NODE_STATES),
                tenant_id,
            )
        if row is None:
            return None
        return _node_view(row)

    async def _node_views(self, node_ids: Sequence[str]) -> dict[str, NodeView]:
        if not node_ids:
            return {}
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_NODE_COLS} FROM aq_object WHERE id = ANY($1::text[]) "
                "AND lifecycle_state = ANY($2::text[])",
                list(node_ids),
                list(VISIBLE_NODE_STATES),
            )
        return {view.id: view for view in (_node_view(row) for row in rows)}

    async def _edge_views(self, edge_ids: Sequence[str]) -> dict[str, EdgeView]:
        if not edge_ids:
            return {}
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT {_EDGE_COLS} FROM aq_relationship WHERE id = ANY($1::text[]) "
                "AND lifecycle_state = 'active' ORDER BY id",
                list(edge_ids),
            )
        return {view.id: view for view in (_edge_view(row) for row in rows)}

    async def _visible_edges(
        self,
        node_id: str,
        *,
        tenant_id: str | None,
        direction: Direction,
        relation_types: frozenset[str] | None,
    ) -> dict[str, EdgeView]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT {_REL_EDGE_COLS}
                FROM aq_relationship r
                JOIN aq_object from_obj ON from_obj.id = r.from_id
                JOIN aq_object to_obj ON to_obj.id = r.to_id
                WHERE r.lifecycle_state = 'active'
                  AND r.tenant_id IS NOT DISTINCT FROM $2
                  AND from_obj.tenant_id IS NOT DISTINCT FROM $2
                  AND to_obj.tenant_id IS NOT DISTINCT FROM $2
                  AND from_obj.lifecycle_state = ANY($3::text[])
                  AND to_obj.lifecycle_state = ANY($3::text[])
                  AND (
                    ($4::text = 'out' AND r.from_id = $1)
                    OR ($4::text = 'in' AND r.to_id = $1)
                    OR ($4::text = 'both' AND (r.from_id = $1 OR r.to_id = $1))
                  )
                  AND ($5::text[] IS NULL OR r.relation_type = ANY($5::text[]))
                ORDER BY r.id
                """,
                node_id,
                tenant_id,
                list(VISIBLE_NODE_STATES),
                direction,
                _relation_type_list(relation_types),
            )
        return {view.id: view for view in (_edge_view(row) for row in rows)}

    async def _walk_edges(
        self,
        current_id: str,
        *,
        tenant_id: str | None,
        direction: Direction,
        relation_types: frozenset[str] | None,
    ) -> list[tuple[str, EdgeView]]:
        edges = await self._visible_edges(
            current_id,
            tenant_id=tenant_id,
            direction=direction,
            relation_types=relation_types,
        )
        result: list[tuple[str, EdgeView]] = []
        for edge in (edges[edge_id] for edge_id in sorted(edges)):
            for adjacent_id in _adjacent_ids(current_id, edge, direction):
                result.append((adjacent_id, edge))
        return result

    async def _recursive_walk(
        self,
        start_ids: Sequence[str],
        *,
        tenant_id: str | None,
        direction: Direction,
        relation_types: frozenset[str] | None,
        max_depth: int,
        max_nodes: int,
    ) -> tuple[list[_WalkRow], bool]:
        row_limit = max_nodes + 1
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH RECURSIVE walk(node_id, depth, path_node_ids, edge_ids) AS (
                    SELECT seed.node_id, 0, ARRAY[seed.node_id]::text[], ARRAY[]::text[]
                    FROM unnest($1::text[]) AS seed(node_id)
                    UNION ALL
                    SELECT step.next_id,
                           walk.depth + 1,
                           walk.path_node_ids || step.next_id,
                           walk.edge_ids || r.id
                    FROM walk
                    JOIN aq_relationship r ON r.lifecycle_state = 'active'
                    JOIN aq_object from_obj ON from_obj.id = r.from_id
                    JOIN aq_object to_obj ON to_obj.id = r.to_id
                    CROSS JOIN LATERAL (
                        SELECT CASE
                            WHEN $2::text = 'out' THEN r.to_id
                            WHEN $2::text = 'in' THEN r.from_id
                            WHEN r.from_id = walk.node_id THEN r.to_id
                            ELSE r.from_id
                        END AS next_id
                    ) AS step
                    WHERE walk.depth < $4
                      AND r.tenant_id IS NOT DISTINCT FROM $3
                      AND from_obj.tenant_id IS NOT DISTINCT FROM $3
                      AND to_obj.tenant_id IS NOT DISTINCT FROM $3
                      AND from_obj.lifecycle_state = ANY($7::text[])
                      AND to_obj.lifecycle_state = ANY($7::text[])
                      AND (
                        ($2::text = 'out' AND r.from_id = walk.node_id)
                        OR ($2::text = 'in' AND r.to_id = walk.node_id)
                        OR (
                            $2::text = 'both'
                            AND (r.from_id = walk.node_id OR r.to_id = walk.node_id)
                        )
                      )
                      AND ($5::text[] IS NULL OR r.relation_type = ANY($5::text[]))
                      AND step.next_id <> ALL(walk.path_node_ids)
                )
                SELECT node_id, depth, path_node_ids, edge_ids
                FROM walk
                ORDER BY depth, path_node_ids, edge_ids
                LIMIT $6
                """,
                list(start_ids),
                direction,
                tenant_id,
                max_depth,
                _relation_type_list(relation_types),
                row_limit,
                list(VISIBLE_NODE_STATES),
            )
        walk_rows = [_walk_row(row) for row in rows]
        truncated = len(walk_rows) > max_nodes
        walk_rows = walk_rows[:max_nodes]
        visited = {row.node_id for row in walk_rows}
        for row in walk_rows:
            if row.depth >= max_depth and await self._has_unseen_neighbor(
                row.node_id,
                tenant_id=tenant_id,
                direction=direction,
                relation_types=relation_types,
                visited=visited,
            ):
                truncated = True
        return walk_rows, truncated

    async def _has_unseen_neighbor(
        self,
        current_id: str,
        *,
        tenant_id: str | None,
        direction: Direction,
        relation_types: frozenset[str] | None,
        visited: set[str],
    ) -> bool:
        edges = await self._visible_edges(
            current_id,
            tenant_id=tenant_id,
            direction=direction,
            relation_types=relation_types,
        )
        for edge in edges.values():
            for adjacent_id in _adjacent_ids(current_id, edge, direction):
                if adjacent_id not in visited:
                    return True
        return False

    async def _subgraph_edge_ids(
        self,
        node_ids: Sequence[str],
        *,
        source_ids: Sequence[str],
        tenant_id: str | None,
        direction: Direction,
        relation_types: frozenset[str] | None,
    ) -> list[str]:
        if not node_ids or not source_ids:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT r.id
                FROM aq_relationship r
                JOIN aq_object from_obj ON from_obj.id = r.from_id
                JOIN aq_object to_obj ON to_obj.id = r.to_id
                WHERE r.lifecycle_state = 'active'
                  AND r.tenant_id IS NOT DISTINCT FROM $3
                  AND from_obj.tenant_id IS NOT DISTINCT FROM $3
                  AND to_obj.tenant_id IS NOT DISTINCT FROM $3
                  AND from_obj.lifecycle_state = ANY($6::text[])
                  AND to_obj.lifecycle_state = ANY($6::text[])
                  AND r.from_id = ANY($1::text[])
                  AND r.to_id = ANY($1::text[])
                  AND (
                    ($4::text = 'out' AND r.from_id = ANY($2::text[]))
                    OR ($4::text = 'in' AND r.to_id = ANY($2::text[]))
                    OR (
                        $4::text = 'both'
                        AND (r.from_id = ANY($2::text[]) OR r.to_id = ANY($2::text[]))
                    )
                  )
                  AND ($5::text[] IS NULL OR r.relation_type = ANY($5::text[]))
                ORDER BY r.id
                """,
                list(node_ids),
                list(source_ids),
                tenant_id,
                direction,
                _relation_type_list(relation_types),
                list(VISIBLE_NODE_STATES),
            )
        return [str(row["id"]) for row in rows]


def _relation_type_list(relation_types: frozenset[str] | None) -> list[str] | None:
    if relation_types is None:
        return None
    return sorted(relation_types)


def _min_depths(rows: Sequence[_WalkRow]) -> dict[str, int]:
    depths: dict[str, int] = {}
    for row in rows:
        previous = depths.get(row.node_id)
        if previous is None or row.depth < previous:
            depths[row.node_id] = row.depth
    return depths
