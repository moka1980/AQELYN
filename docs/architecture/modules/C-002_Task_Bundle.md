# C-002 Knowledge Graph — Implementation Task Bundle

**Milestone:** C-002 (Knowledge Graph, EA-0005)
**For:** Codex (implementer) · Claude Code (reviewer)
**Prerequisites:** C-001 foundation merged & green; EA-0005 spec **Accepted**; CONVENTIONS + EA-0002 read.
**Definition of Done:** every ticket's acceptance tests pass on in-memory **and** Postgres; `ruff` clean; `mypy --strict` clean; nothing outside the spec; `make check` green; Claude Code sign-off per ticket.

---

## How to use this bundle

Build tickets **in order** (G1 → G5). Each names its spec section and the exact
`pytest` ids from EA-0005 §9. The graph is a **read/analysis layer over
EA-0002** — do not add node/edge storage. If a needed behavior isn't in the
spec, raise an Engineering Change Request.

## Target source layout

```
src/aqelyn/graph/
├── __init__.py       # exports KnowledgeGraph, service, types
├── models.py         # NodeView, EdgeView, Subgraph, Path, ImpactResult, TraversalLimits (G1)
├── graph.py          # KnowledgeGraph protocol + shared bounds/validation (G1)
├── memory.py         # InMemoryKnowledgeGraph over ObjectStore (G2/G3/G4)
├── postgres.py       # PostgresKnowledgeGraph via recursive CTEs (G2/G3/G4)
└── service.py        # KnowledgeGraphService(AQService) (G5)
tests/graph/          # shared contract suite parametrized [inmemory, postgres]
```

---

## G1 — Types, protocol, and bounds

**Spec:** §5, §6, §3 (D2/D4), §10.
**Deliverables:** the result/query models; the `KnowledgeGraph` protocol;
parameter validation (`GraphQueryInvalid` on `max_depth<1`, `within_hops<1`,
unknown direction); hard-cap enforcement (`max_depth ≤ 32`, `max_nodes ≤
100_000`); the `GraphQueryInvalid` error added to `conventions.errors` +
CONVENTIONS §9.
**Depends on:** C-001 (EA-0002 models, conventions).
**Acceptance:** `test_kg_invalid_params`.

## G2 — In-memory traversal core

**Spec:** §7 (in-memory), FR-1/2/4/5/8/9, D3/D5/D6.
**Deliverables:** `InMemoryKnowledgeGraph(object_store)` with `neighbors` and
`subgraph` (bounded, cycle-safe, deterministic, provenance-carrying,
tenant-scoped, lifecycle-aware).
**Depends on:** G1.
**Acceptance:** `test_kg_neighbors_filtered`, `test_kg_subgraph_bounded_truncation`,
`test_kg_edges_carry_provenance`, `test_kg_tenant_isolation`,
`test_kg_excludes_inactive`, `test_kg_deterministic`, `test_kg_cycle_safe`.

## G3 — Paths & explainability

**Spec:** FR-3, FR-10.
**Deliverables:** `shortest_path`, `paths`, and `explain_path` (per-hop relation
type + evidence/source refs).
**Depends on:** G2.
**Acceptance:** `test_kg_shortest_path`, `test_kg_explain_path`.

## G4 — Impact, correlation & Postgres implementation

**Spec:** FR-6, FR-7; §7 (Postgres recursive CTE).
**Deliverables:** `impact` (blast radius) and `correlate`; the full
`PostgresKnowledgeGraph` implementing the same interface via recursive CTEs;
both implementations wired into one parametrized contract suite.
**Depends on:** G3.
**Acceptance:** `test_kg_impact_blast_radius`, `test_kg_correlate`,
`test_kg_contract[inmemory]`, `test_kg_contract[postgres]`.

## G5 — KnowledgeGraphService (AQService)

**Spec:** FR-12, §11.
**Deliverables:** `KnowledgeGraphService` registering as an `AQService`
(name `"knowledge_graph"`, depends on the object store), health/readiness
reflecting store availability; wired into the kernel factory.
**Depends on:** G4.
**Acceptance:** `test_kg_service_health`.

---

## Review protocol (Claude Code)

Per ticket, confirm: (1) each named acceptance test exists and passes on
in-memory **and** Postgres where specified; (2) no node/edge storage was added —
the graph reads EA-0002 only; (3) every returned edge carries provenance;
(4) all traversals are bounded (no unbounded walk, no hang) and tenant-scoped;
(5) results are deterministic; (6) `ruff` + `mypy --strict` clean; interfaces
match the spec exactly. Merge only on green review; then **report back to the
owner** before the next module.
