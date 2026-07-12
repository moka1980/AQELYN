"""In-memory Knowledge Graph over the EA-0002 ObjectStore (EA-0005 G2/G3)."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Sequence

from aqelyn.conventions.errors import GraphQueryInvalid, ObjectNotFound
from aqelyn.graph.graph import (
    DEFAULT_IMPACT_RELATION_TYPES,
    normalize_limits,
    require_node,
    validate_direction,
    validate_max_paths,
    validate_max_work,
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
            for adjacent_id, rel in await self._walk_edges(
                current_id,
                tenant_id=start.tenant_id,
                direction=normalized_direction,
                relation_types=rel_types,
            ):
                if adjacent_id in visited:
                    continue
                adjacent_node_ids = [*node_ids, adjacent_id]
                adjacent_edges = [*edges, _edge_view(rel)]
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
        max_work: int = 50_000,
    ) -> list[Path]:
        start = await self._visible_start(from_id)
        target = await self._visible_node(to_id, tenant_id=start.tenant_id)
        if target is None:
            return []
        normalized_direction = validate_direction(direction)
        rel_types = frozenset(relation_types) if relation_types is not None else None
        depth_limit = normalize_limits(max_depth=max_depth).max_depth
        path_limit = validate_max_paths(max_paths)
        work_limit = validate_max_work(max_work)
        if start.id == target.id:
            return [Path(node_ids=[start.id], edges=[], length=0)]

        found: list[Path] = []
        work_used = 0
        queue: deque[tuple[str, list[str], list[EdgeView]]] = deque([(start.id, [start.id], [])])
        while queue and len(found) < path_limit and work_used < work_limit:
            current_id, node_ids, edges = queue.popleft()
            work_used += 1
            if len(edges) >= depth_limit:
                continue
            for adjacent_id, rel in await self._walk_edges(
                current_id,
                tenant_id=start.tenant_id,
                direction=normalized_direction,
                relation_types=rel_types,
            ):
                if adjacent_id in node_ids:
                    continue
                adjacent_node_ids = [*node_ids, adjacent_id]
                adjacent_edges = [*edges, _edge_view(rel)]
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
        hits: dict[str, ImpactHit] = {}
        visited: set[str] = {start.id}
        queue: deque[tuple[str, list[str], list[EdgeView]]] = deque([(start.id, [start.id], [])])
        truncated = False

        while queue:
            current_id, node_ids, edges = queue.popleft()
            current_edges = await self._visible_edges(
                current_id,
                tenant_id=start.tenant_id,
                direction=normalized_direction,
                relation_types=rel_types,
            )
            if len(edges) >= limits.max_depth:
                if await self._has_unseen_neighbor(
                    current_id, current_edges.values(), normalized_direction, visited
                ):
                    truncated = True
                continue
            for rel in sorted(current_edges.values(), key=lambda edge: edge.id):
                for adjacent_id in _adjacent_ids(current_id, rel, normalized_direction):
                    if adjacent_id in visited:
                        continue
                    adjacent = await self._visible_node(adjacent_id, tenant_id=start.tenant_id)
                    if adjacent is None:
                        continue
                    if len(visited) >= limits.max_nodes:
                        truncated = True
                        continue
                    adjacent_node_ids = [*node_ids, adjacent.id]
                    adjacent_edges = [*edges, _edge_view(rel)]
                    path = Path(
                        node_ids=adjacent_node_ids,
                        edges=adjacent_edges,
                        length=len(adjacent_edges),
                    )
                    visited.add(adjacent.id)
                    hits[adjacent.id] = ImpactHit(node=_node_view(adjacent), via=path)
                    queue.append((adjacent.id, adjacent_node_ids, adjacent_edges))

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
        nodes: dict[str, NodeView] = {}
        edges: dict[str, EdgeView] = {}
        visited: set[str] = set()
        queue: deque[tuple[str, str | None, int]] = deque()
        truncated = False

        for seed in seeds:
            if seed.id in visited:
                continue
            if len(nodes) >= limits.max_nodes:
                truncated = True
                continue
            visited.add(seed.id)
            nodes[seed.id] = _node_view(seed)
            queue.append((seed.id, seed.tenant_id, 0))

        while queue:
            current_id, tenant_id, depth = queue.popleft()
            current_edges = await self._visible_edges(
                current_id,
                tenant_id=tenant_id,
                direction="both",
                relation_types=rel_types,
            )
            if depth >= limits.max_depth:
                if await self._has_unseen_neighbor(
                    current_id, current_edges.values(), "both", visited
                ):
                    truncated = True
                continue
            for rel in sorted(current_edges.values(), key=lambda edge: edge.id):
                edge_view = _edge_view(rel)
                for adjacent_id in _adjacent_ids(current_id, rel, "both"):
                    if adjacent_id in visited:
                        if rel.from_id in nodes and rel.to_id in nodes:
                            edges[edge_view.id] = edge_view
                        continue
                    adjacent = await self._visible_node(adjacent_id, tenant_id=tenant_id)
                    if adjacent is None:
                        continue
                    if len(nodes) >= limits.max_nodes:
                        truncated = True
                        continue
                    visited.add(adjacent.id)
                    nodes[adjacent.id] = _node_view(adjacent)
                    edges[edge_view.id] = edge_view
                    queue.append((adjacent.id, tenant_id, depth + 1))

        return Subgraph(
            nodes=[nodes[node_id] for node_id in sorted(nodes)],
            edges=[edges[edge_id] for edge_id in sorted(edges)],
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

    async def _walk_edges(
        self,
        current_id: str,
        *,
        tenant_id: str | None,
        direction: Direction,
        relation_types: frozenset[str] | None,
    ) -> list[tuple[str, AQRelationship]]:
        edges = await self._visible_edges(
            current_id,
            tenant_id=tenant_id,
            direction=direction,
            relation_types=relation_types,
        )
        result: list[tuple[str, AQRelationship]] = []
        for rel in sorted(edges.values(), key=lambda edge: edge.id):
            for adjacent_id in _adjacent_ids(current_id, rel, direction):
                result.append((adjacent_id, rel))
        return result


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
