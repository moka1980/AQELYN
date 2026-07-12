# EA-0005 — Knowledge Graph — Implementation Specification

**Realizes:** EA-0005 (supersedes the placeholder `archive/EA-0005/EA-0005_Master.md` for implementation)
**Depends on:** ADR-0001, CONVENTIONS, EA-0002 (objects + relationships), EA-0001 (registers as an `AQService`), EA-0004/Finding (results attach as evidence-backed context)
**Consumed by:** correlation/analysis engines (EA-0006+), the Finding pipeline (attach an explainable subgraph to a finding), UI graph views (EA-0059)
**Status:** Accepted
**Build milestone:** C-002 (see `C-002_Task_Bundle.md`)
**Definition of Ready:** see §12

---

## 1. Purpose

The Knowledge Graph answers *relationship* questions about everything AQELYN
tracks: what is connected to what, what depends on what, what breaks if this
fails, and how two things are related. It turns the flat object + relationship
data from EA-0002 into **traversable, analyzable, and explainable** structure —
so an engine can compute a blast radius, and a user can see *why* two things are
linked, with the evidence behind every hop.

It exists to serve the Charter promise for relationship-derived conclusions:
every path the graph reports must be **understandable** (plain nodes and edges)
and **provable** (each edge carries its provenance back to evidence).

## 2. Scope

**In scope:** neighbor lookup, bounded deterministic traversal / subgraph
extraction, shortest path and path enumeration, dependency and impact
("blast radius") analysis, correlation within K hops, explainable path output,
and the `KnowledgeGraph` interface with in-memory + PostgreSQL implementations
plus the `KnowledgeGraphService` (`AQService`).

**Out of scope:** owning node/edge storage (EA-0002 is the single source of
truth — see D1), graph *mutation* (objects/edges are written through the
`ObjectStore`), a custom query language (deferred — §14), and any ML/inference
reasoning (a later engine may consume this graph).

## 3. Design decisions

- **D1 — The graph is a read/analysis layer, not a second store.** Nodes are
  `aq_object` rows; edges are `aq_relationship` rows (EA-0002). The Knowledge
  Graph never duplicates them. This keeps one source of truth, preserves
  provenance, and honors ADR-0001's deferred decision to model the graph in
  PostgreSQL and only adopt a dedicated graph engine if query needs demand it.
- **D2 — All traversals are bounded and never hang.** Every operation takes
  `max_depth` and `max_nodes` limits (with hard caps). Hitting a limit returns a
  **truncated** result flagged `truncated=True` — never an error, never an
  unbounded walk.
- **D3 — Every edge in a result carries its provenance.** Each returned edge
  includes the relationship's `sources` (which reference evidence via EA-0004).
  This makes any path auditable and satisfies "how AQELYN knows" for
  graph-derived conclusions (D-critical for the Charter).
- **D4 — Deterministic results.** Given the same graph, every operation returns
  the same nodes/edges in the same order (stable sort by id). Required for
  reproducibility and audit.
- **D5 — Tenant-scoped and lifecycle-aware.** Traversal never crosses a tenant
  boundary and, by default, follows only `active`/`archived` nodes and `active`
  edges. Merged/deleted nodes are excluded unless explicitly requested.
- **D6 — Cycle-safe.** A visited-set guarantees termination on cyclic graphs;
  disconnected graphs are handled (empty results, not errors).
- **D7 — Two implementations, one contract.** `InMemoryKnowledgeGraph` (BFS over
  the `ObjectStore`) and `PostgresKnowledgeGraph` (recursive CTEs over
  `aq_relationship`) pass the same contract suite (portability, matches the
  foundation store pattern).

## 4. Ubiquitous language

| Term | Meaning |
|---|---|
| **Node** | An `AQObject` (EA-0002), referenced by id. |
| **Edge** | An `AQRelationship` (EA-0002): directed `from_id → to_id`, typed, provenance-carrying. |
| **Direction** | `out` follows `from→to`; `in` follows `to→from`; `both` treats edges as undirected. |
| **Subgraph** | A bounded set of nodes + edges reachable from a start under filters. |
| **Path** | An ordered, explainable sequence of edges linking two nodes. |
| **Impact / blast radius** | The set of nodes that (transitively) depend on a node — what is affected if it fails/changes. |
| **Correlation** | Nodes related to one or more seeds within K hops, optionally matching a predicate. |
| **Truncated** | A result cut short by `max_depth`/`max_nodes`; flagged, never silent. |

## 5. Result & query types

```
NodeView   = { id, object_type, display_name, tenant_id }
EdgeView   = { id, from_id, to_id, relation_type, confidence,
               sources: list[SourceRef] }        # provenance (D3), reuses EA-0002 SourceRef
Subgraph   = { nodes: list[NodeView], edges: list[EdgeView], truncated: bool }
Path       = { node_ids: list[str], edges: list[EdgeView], length: int }   # length = hop count
ImpactHit  = { node: NodeView, via: Path }        # each affected node + the path that establishes it
ImpactResult = { hits: list[ImpactHit], truncated: bool }

TraversalLimits = { max_depth: int = 6, max_nodes: int = 10_000 }   # hard caps: depth<=32, nodes<=100_000
```

`SourceRef` and lifecycle/tenant semantics are exactly as defined in EA-0002 /
CONVENTIONS. Default dependency relation types for impact analysis:
`{"depends_on", "runs_on", "member_of"}` (configurable per call).

## 6. Interfaces (Python 3.12)

```python
from typing import Protocol, Sequence

class KnowledgeGraph(Protocol):
    async def neighbors(
        self, node_id: str, *, direction: str = "both",
        relation_types: Sequence[str] | None = None,
    ) -> list[EdgeView]: ...

    async def subgraph(
        self, start_id: str, *, direction: str = "both",
        relation_types: Sequence[str] | None = None,
        max_depth: int = 6, max_nodes: int = 10_000,
    ) -> Subgraph: ...

    async def shortest_path(
        self, from_id: str, to_id: str, *, direction: str = "both",
        relation_types: Sequence[str] | None = None, max_depth: int = 6,
    ) -> Path | None: ...

    async def paths(
        self, from_id: str, to_id: str, *, direction: str = "both",
        relation_types: Sequence[str] | None = None,
        max_depth: int = 6, max_paths: int = 10,
    ) -> list[Path]: ...

    async def impact(
        self, node_id: str, *, direction: str = "in",
        relation_types: Sequence[str] | None = None,
        max_depth: int = 6, max_nodes: int = 10_000,
    ) -> ImpactResult: ...        # direction="in" = blast radius (who depends on me)

    async def correlate(
        self, seed_ids: Sequence[str], *, within_hops: int = 2,
        relation_types: Sequence[str] | None = None, max_nodes: int = 10_000,
    ) -> Subgraph: ...

    async def explain_path(self, path: Path) -> list[dict]: ...
    # one dict per hop: {from, to, relation_type, evidence_ids, source_methods} -> UI / finding context
```

`KnowledgeGraphService` wraps a `KnowledgeGraph` as an `AQService`
(name `"knowledge_graph"`, depends on the object store, exposes health).

## 7. Persistence / query strategy

- **No new tables.** The graph reads `aq_object` and `aq_relationship` (EA-0002).
- **In-memory:** BFS/DFS over `ObjectStore.relationships()` with a visited-set and
  the limits from §5. Node views come from `ObjectStore.get`.
- **PostgreSQL:** bounded traversal via a **recursive CTE** over `aq_relationship`
  joined to `aq_object`, e.g. (illustrative, `out` direction):

  ```sql
  WITH RECURSIVE walk(node_id, depth, path) AS (
    SELECT $1::text, 0, ARRAY[$1::text]
    UNION ALL
    SELECT r.to_id, w.depth + 1, w.path || r.to_id
    FROM walk w
    JOIN aq_relationship r ON r.from_id = w.node_id AND r.lifecycle_state = 'active'
    JOIN aq_object o ON o.id = r.to_id
    WHERE w.depth < $2                        -- max_depth
      AND NOT r.to_id = ANY(w.path)           -- cycle-safe (D6)
      AND o.lifecycle_state IN ('active','archived')
      AND o.tenant_id IS NOT DISTINCT FROM $3 -- tenant scope (D5)
  )
  SELECT * FROM walk LIMIT $4;                -- max_nodes; sets truncated if reached
  ```

  Direction `in` swaps `from_id`/`to_id`; `both` unions both.

## 8. Requirements

### Functional (testable)

- **FR-1** `neighbors` SHALL return active edges adjacent to a node filtered by direction and `relation_types`, excluding edges to merged/deleted nodes.
- **FR-2** `subgraph` SHALL perform a bounded, cycle-safe BFS to `max_depth`/`max_nodes` and set `truncated=True` iff a limit was hit (D2, D6).
- **FR-3** `shortest_path` SHALL return a minimal-hop `Path` (or `None`); the path's edges SHALL be ordered from `from_id` to `to_id`.
- **FR-4** Every `EdgeView` returned SHALL carry the relationship's `sources` (provenance, D3).
- **FR-5** All operations SHALL be tenant-scoped and SHALL NOT return cross-tenant nodes or edges (D5).
- **FR-6** `impact(direction="in")` SHALL return every node that transitively depends on the target (over `relation_types`), each with the establishing `Path`; bounded + `truncated` flagged.
- **FR-7** `correlate` SHALL return the deduped set of nodes within `within_hops` of any seed, as a `Subgraph`.
- **FR-8** By default all operations SHALL follow only `active`/`archived` nodes and `active` edges.
- **FR-9** Results SHALL be deterministic: identical graph → identical nodes/edges in identical (id-sorted) order (D4).
- **FR-10** `explain_path` SHALL yield, per hop, the relation type plus the evidence/source references behind that edge (Charter "how AQELYN knows").
- **FR-11** Invalid parameters (`max_depth < 1`, `within_hops < 1`, unknown direction) SHALL raise `GraphQueryInvalid`; an unknown start node SHALL raise `ObjectNotFound`.
- **FR-12** `KnowledgeGraphService` SHALL register as an `AQService` with health/readiness reflecting object-store availability (EA-0001).

### Non-functional (initial targets)

- **NFR-1 (bounded)** No operation is unbounded; hard caps `max_depth ≤ 32`, `max_nodes ≤ 100_000` are enforced regardless of caller input.
- **NFR-2 (latency)** `neighbors` p95 < 10 ms; a depth-4 `subgraph` over ≤ 10k reachable nodes p95 < 150 ms on M-tier hardware.
- **NFR-3 (portability & typing)** in-memory and PostgreSQL implementations pass one contract suite; `mypy --strict` + `ruff` clean.
- **NFR-4 (determinism)** repeated identical queries return byte-identical serialized results.

## 9. Acceptance Criteria ↔ Tests (Definition of Ready)

| # | Criterion | Test (pytest id) |
|---|---|---|
| AC-1 | Neighbors filtered by direction + type | `test_kg_neighbors_filtered` |
| AC-2 | Bounded BFS sets truncated at limits | `test_kg_subgraph_bounded_truncation` |
| AC-3 | Shortest path is minimal-hop, ordered | `test_kg_shortest_path` |
| AC-4 | Every edge carries provenance | `test_kg_edges_carry_provenance` |
| AC-5 | Tenant isolation on traversal | `test_kg_tenant_isolation` |
| AC-6 | Impact returns blast radius with paths | `test_kg_impact_blast_radius` |
| AC-7 | Correlate returns deduped k-hop set | `test_kg_correlate` |
| AC-8 | Merged/deleted excluded by default | `test_kg_excludes_inactive` |
| AC-9 | Deterministic ordering | `test_kg_deterministic` |
| AC-10 | explain_path yields per-hop evidence | `test_kg_explain_path` |
| AC-11 | Invalid params / unknown node rejected | `test_kg_invalid_params` |
| AC-12 | In-memory & Postgres pass one suite | `test_kg_contract[inmemory]` / `[postgres]` |
| AC-13 | Cycle-safe termination | `test_kg_cycle_safe` |
| AC-14 | Registers as AQService with health | `test_kg_service_health` |

## 10. Error taxonomy (contributions)

`GraphQueryInvalid` (bad traversal parameters). Reuses `ObjectNotFound` (EA-0002)
for unknown start nodes. Both recorded in CONVENTIONS §9 when this spec lands.

## 11. Failure handling

- Object store unavailable → surface `StoreUnavailable`; the service reports
  `degraded`/`unavailable` via `AQService.health` (EA-0001); no partial silent
  result.
- Limit reached → truncated result (never error, never hang).
- Missing node mid-traversal (deleted concurrently) → skipped, not fatal;
  traversal continues deterministically.

## 12. Dependencies & consumers

- **Depends on:** EA-0002 `ObjectStore` (`relationships`, `get`) or a Postgres
  pool; EA-0001 `AQService`; CONVENTIONS.
- **Consumed by:** analysis/correlation engines (EA-0006+); the Finding pipeline
  (attach `affected_object_ids` + an explainable subgraph so a finding can show
  *why* assets are related and prove it); EA-0059 UI graph views.

## 13. Resolved / deferred decisions

- **No dedicated graph database in EA-0005.** PostgreSQL recursive CTEs over
  `aq_relationship` are sufficient at foundation scale (ADR-0001 deferred item).
  If real workloads exceed this, a dedicated graph engine gets its own ADR — the
  `KnowledgeGraph` interface is designed so that swap changes no callers.
- **No query language yet.** The typed methods in §6 cover foundation needs; a
  declarative graph query surface is deferred to a later EA.
- **Bounded-and-truncated over erroring** on large traversals is accepted and
  binding.
