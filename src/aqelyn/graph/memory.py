"""In-memory Knowledge Graph over the EA-0002 ObjectStore (EA-0005 G2)."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Sequence

from aqelyn.conventions.errors import ObjectNotFound
from aqelyn.graph.graph import normalize_limits, require_node, validate_direction
from aqelyn.graph.models import Direction, EdgeView, NodeView, Subgraph
from aqelyn.objects.models import AQObject, AQRelationship
from aqelyn.objects.store import ObjectStore

VISIBLE_NODE_STATES = frozenset(("active", "archived"))


class InMemoryKnowledgeGraph:
    def __init__(self, object_store: ObjectStore) -> None:
        self._objects = object_store

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
        return [_edge_view(edge) for edge in sorted(edges.values(), key=lambda edge: edge.id)]

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
        nodes: dict[str, NodeView] = {start.id: _node_view(start)}
        edges: dict[str, EdgeView] = {}
        visited: set[str] = {start.id}
        queue: deque[tuple[str, int]] = deque([(start.id, 0)])
        truncated = False

        while queue:
            current_id, depth = queue.popleft()
            current_edges = await self._visible_edges(
                current_id,
                tenant_id=start.tenant_id,
                direction=normalized_direction,
                relation_types=rel_types,
            )
            if depth >= limits.max_depth:
                if await self._has_unseen_neighbor(
                    current_id, current_edges.values(), normalized_direction, visited
                ):
                    truncated = True
                continue
            for rel in sorted(current_edges.values(), key=lambda edge: edge.id):
                edge_view = _edge_view(rel)
                for adjacent_id in _adjacent_ids(current_id, rel, normalized_direction):
                    if adjacent_id in visited:
                        if rel.from_id in nodes and rel.to_id in nodes:
                            edges[edge_view.id] = edge_view
                        continue
                    adjacent = await self._visible_node(adjacent_id, tenant_id=start.tenant_id)
                    if adjacent is None:
                        continue
                    if len(nodes) >= limits.max_nodes:
                        truncated = True
                        continue
                    visited.add(adjacent.id)
                    nodes[adjacent.id] = _node_view(adjacent)
                    edges[edge_view.id] = edge_view
                    queue.append((adjacent.id, depth + 1))

        return Subgraph(
            nodes=[nodes[node_id] for node_id in sorted(nodes)],
            edges=[edges[edge_id] for edge_id in sorted(edges)],
            truncated=truncated,
        )

    async def _visible_start(self, node_id: str) -> AQObject:
        node = await require_node(self._objects, node_id)
        if node.lifecycle_state not in VISIBLE_NODE_STATES:
            raise ObjectNotFound(node_id)
        return node

    async def _visible_node(self, node_id: str, *, tenant_id: str | None) -> AQObject | None:
        node = await self._objects.get(node_id, resolve_merged=False)
        if node is None:
            return None
        if node.lifecycle_state not in VISIBLE_NODE_STATES:
            return None
        if node.tenant_id != tenant_id:
            return None
        return node

    async def _visible_edges(
        self,
        node_id: str,
        *,
        tenant_id: str | None,
        direction: Direction,
        relation_types: frozenset[str] | None,
    ) -> dict[str, AQRelationship]:
        result: dict[str, AQRelationship] = {}
        for rel in await self._objects.relationships(node_id, direction=direction):
            if relation_types is not None and rel.relation_type not in relation_types:
                continue
            if rel.lifecycle_state != "active":
                continue
            if rel.tenant_id != tenant_id:
                continue
            if not await self._edge_endpoints_visible(rel, tenant_id=tenant_id):
                continue
            result[rel.id] = rel
        return result

    async def _edge_endpoints_visible(self, rel: AQRelationship, *, tenant_id: str | None) -> bool:
        from_node = await self._visible_node(rel.from_id, tenant_id=tenant_id)
        to_node = await self._visible_node(rel.to_id, tenant_id=tenant_id)
        return from_node is not None and to_node is not None

    async def _has_unseen_neighbor(
        self,
        current_id: str,
        edges: Iterable[AQRelationship],
        direction: Direction,
        visited: set[str],
    ) -> bool:
        for rel in edges:
            for adjacent_id in _adjacent_ids(current_id, rel, direction):
                if adjacent_id not in visited:
                    return True
        return False


def _node_view(obj: AQObject) -> NodeView:
    return NodeView(
        id=obj.id,
        object_type=obj.object_type,
        display_name=obj.display_name,
        tenant_id=obj.tenant_id,
    )


def _edge_view(rel: AQRelationship) -> EdgeView:
    return EdgeView(
        id=rel.id,
        from_id=rel.from_id,
        to_id=rel.to_id,
        relation_type=rel.relation_type,
        confidence=rel.confidence,
        sources=list(rel.sources),
    )


def _adjacent_ids(current_id: str, rel: AQRelationship, direction: Direction) -> list[str]:
    adjacent: list[str] = []
    if direction in ("out", "both") and rel.from_id == current_id:
        adjacent.append(rel.to_id)
    if direction in ("in", "both") and rel.to_id == current_id and rel.from_id not in adjacent:
        adjacent.append(rel.from_id)
    return adjacent
