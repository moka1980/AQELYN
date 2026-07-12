"""Knowledge Graph protocol and shared validation (EA-0005 §6, §10)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, cast, runtime_checkable

from aqelyn.conventions.errors import GraphQueryInvalid, ObjectNotFound
from aqelyn.graph.models import Direction, EdgeView, ImpactResult, Path, Subgraph, TraversalLimits
from aqelyn.objects.models import AQObject
from aqelyn.objects.store import ObjectStore, validate_object_id

MAX_DEPTH = 32
MAX_NODES = 100_000
MAX_WORK = 1_000_000
VALID_DIRECTIONS: frozenset[str] = frozenset(("out", "in", "both"))
DEFAULT_IMPACT_RELATION_TYPES: frozenset[str] = frozenset(("depends_on", "runs_on", "member_of"))


@runtime_checkable
class KnowledgeGraph(Protocol):
    async def neighbors(
        self,
        node_id: str,
        *,
        direction: str = "both",
        relation_types: Sequence[str] | None = None,
    ) -> list[EdgeView]: ...

    async def subgraph(
        self,
        start_id: str,
        *,
        direction: str = "both",
        relation_types: Sequence[str] | None = None,
        max_depth: int = 6,
        max_nodes: int = 10_000,
    ) -> Subgraph: ...

    async def shortest_path(
        self,
        from_id: str,
        to_id: str,
        *,
        direction: str = "both",
        relation_types: Sequence[str] | None = None,
        max_depth: int = 6,
    ) -> Path | None: ...

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
    ) -> list[Path]: ...

    async def impact(
        self,
        node_id: str,
        *,
        direction: str = "in",
        relation_types: Sequence[str] | None = None,
        max_depth: int = 6,
        max_nodes: int = 10_000,
    ) -> ImpactResult: ...

    async def correlate(
        self,
        seed_ids: Sequence[str],
        *,
        within_hops: int = 2,
        relation_types: Sequence[str] | None = None,
        max_nodes: int = 10_000,
    ) -> Subgraph: ...

    async def explain_path(self, path: Path) -> list[dict[str, object]]: ...


def validate_direction(direction: str) -> Direction:
    if direction not in VALID_DIRECTIONS:
        raise GraphQueryInvalid(f"unknown graph direction: {direction!r}")
    return cast(Direction, direction)


def normalize_limits(max_depth: int = 6, max_nodes: int = 10_000) -> TraversalLimits:
    if max_depth < 1:
        raise GraphQueryInvalid("max_depth must be >= 1")
    if max_nodes < 1:
        raise GraphQueryInvalid("max_nodes must be >= 1")
    return TraversalLimits(
        max_depth=min(max_depth, MAX_DEPTH),
        max_nodes=min(max_nodes, MAX_NODES),
    )


def validate_within_hops(within_hops: int) -> int:
    if within_hops < 1:
        raise GraphQueryInvalid("within_hops must be >= 1")
    return min(within_hops, MAX_DEPTH)


def validate_max_paths(max_paths: int) -> int:
    if max_paths < 1:
        raise GraphQueryInvalid("max_paths must be >= 1")
    return max_paths


def validate_max_work(max_work: int) -> int:
    if max_work < 1:
        raise GraphQueryInvalid("max_work must be >= 1")
    return min(max_work, MAX_WORK)


async def require_node(object_store: ObjectStore, node_id: str) -> AQObject:
    validate_object_id(node_id, field="node_id")
    obj = await object_store.get(node_id, resolve_merged=False)
    if obj is None:
        raise ObjectNotFound(node_id)
    return obj
