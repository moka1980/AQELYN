# EA-0002 — Universal Object Model (UOM) — Implementation Specification

**Realizes:** EA-0002 (supersedes the placeholder `archive/EA-0002/EA-0002_Master.md` for implementation)
**Depends on:** ADR-0001 (Runtime & Stack) — Python 3.12, PostgreSQL 16, modular monolith
**Consumed by:** EA-0003 (Events), EA-0004 (Evidence), EA-0005 (Knowledge Graph), Finding schema, and every asset/identity engine (EA-0052+)
**Status:** Accepted
**Definition of Ready:** see §16

---

## 1. Purpose

The Universal Object Model is AQELYN's canonical way of representing **every
real-world thing it tracks** — devices, identities, accounts, applications,
domains, certificates, services, and so on — plus the **relationships** between
them. It is the single spine that Events reference, that Evidence attaches to,
that Findings point at, and that the Knowledge Graph traverses.

One model serves both product modes (charter requirement): a **local-first**
single-user install and a **centrally governed enterprise** deployment, without
forking the architecture.

## 2. Scope

**In scope:** the object envelope, the typed identifier scheme, the type
registry (extensibility), the relationship (edge) model, provenance/source
linkage, identity resolution & merge, lifecycle states, tenancy scoping,
optimistic concurrency, the `ObjectStore` interface, and the PostgreSQL schema.

**Out of scope:** concrete asset type schemas (Device, Identity, etc. — defined
by their own EAs, registered against this model), the Knowledge Graph query
language (EA-0005), and any collection/scanning logic.

## 3. Ubiquitous language (glossary)

| Term | Meaning |
|---|---|
| **AQObject** | A single tracked entity (one device, one identity, …). The base envelope every object shares. |
| **object_type** | The kind of an object (e.g. `device`, `identity`). Registered in the type registry. |
| **Attributes** | Type-specific fields of an object, validated against the type's schema. |
| **AQRelationship** | A directed edge between two objects (e.g. identity `owns` account). A first-class record. |
| **Source / Provenance** | The record of *how AQELYN learned* a fact — a seam that links objects/attributes to Evidence (EA-0004). |
| **Natural key** | A stable real-world identifier used to match/dedup objects across sources (e.g. a device serial). |
| **Merge** | Collapsing two records found to be the same real-world entity into one surviving object. |
| **tenant_id** | Owning tenant. **NULL = local/single-tenant install.** Reserved for enterprise mode. |
| **Lifecycle state** | `active`, `archived`, `merged`, `deleted` (soft). Objects are never hard-deleted. |

## 4. Design decisions

- **D1 — Edges are first-class.** Relationships are stored as their own records
  (`AQRelationship`), not embedded, so the graph is queryable in PostgreSQL now
  and portable to a dedicated graph store later (EA-0005) without touching
  callers.
- **D2 — Local-first tenancy.** `tenant_id` exists on every object from day one
  but is **nullable**. A local install leaves it NULL; enterprise mode sets it.
  All queries scope by tenant (NULL-aware). No retrofit later.
- **D3 — Provenance is native.** Every object, and optionally every attribute,
  carries source references. This enforces the charter's "evidence before
  opinion" at the data layer: nothing is asserted without a traceable origin.
- **D4 — Soft delete + full history.** Objects transition lifecycle states and
  write an append-only history row on every change. Nothing is destroyed —
  required for government/enterprise auditability.
- **D5 — Optimistic concurrency.** A monotonic `version` integer guards updates;
  concurrent writers get a conflict, never a silent overwrite.
- **D6 — Typed, sortable identifiers.** See §5.
- **D7 — Extensible via a type registry, closed via validation.** New object
  types are added by registration + schema, never by loosening the base model.

## 5. Identifiers

- Internal primary key: **UUIDv7** (time-ordered), generated in the application
  (dependency: `uuid-utils`), stored natively as PostgreSQL `uuid`.
- Canonical external form: a **type-prefixed string** for readability, safety at
  API boundaries, and log grep-ability:

  ```
  {prefix}_{uuid-hex-without-dashes}
  e.g.  obj_0192f4c9e8a97b3c8f2144d7c0b3e5a1
  ```

| Family | Prefix |
|---|---|
| Object | `obj` |
| Relationship | `rel` |
| Source | `src` |
| Evidence (EA-0004) | `evd` |
| Event (EA-0003) | `evt` |
| Finding | `fnd` |

- IDs are **immutable** once assigned. Merges preserve both IDs (survivor +
  merged-from list), never rewrite them.

## 6. The canonical object envelope

Every AQObject has these fields regardless of type:

| Field | Type | Req | Description |
|---|---|---|---|
| `id` | ID (`obj_…`) | yes | Immutable primary identifier (§5). |
| `object_type` | string | yes | Registered type key (e.g. `device`). |
| `schema_version` | int | yes | Version of this object_type's attribute schema. |
| `tenant_id` | UUID \| null | no | Owning tenant; **NULL in local mode** (D2). |
| `display_name` | string | yes | Human-readable label (charter: understandable output). |
| `attributes` | object (JSONB) | yes | Type-specific fields, validated by the type's schema. |
| `labels` | map<string,string> | no | Free-form key/value tags for grouping/filtering. |
| `natural_keys` | list<NaturalKey> | no | Stable identifiers for matching/dedup (§9). |
| `sources` | list<SourceRef> | yes | Provenance — how AQELYN knows this object (§8). Min 1. |
| `confidence` | float 0..1 | yes | Confidence the object exists/is correct. |
| `lifecycle_state` | enum | yes | `active` \| `archived` \| `merged` \| `deleted`. |
| `merged_into` | ID \| null | no | If `merged`, the survivor object id. |
| `version` | int | yes | Optimistic-concurrency counter, starts at 1 (D5). |
| `first_seen_at` | timestamp (UTC) | yes | When first observed. |
| `last_seen_at` | timestamp (UTC) | yes | When most recently observed. |
| `created_at` | timestamp (UTC) | yes | Row creation. |
| `updated_at` | timestamp (UTC) | yes | Last modification. |
| `created_by` | ActorRef | yes | Who/what created it (system, connector, user). |
| `updated_by` | ActorRef | yes | Who/what last changed it. |

All timestamps are UTC, RFC 3339, microsecond precision (convention, §Conventions spec).

### Supporting structures

```
NaturalKey   = { namespace: string, value: string }      # e.g. {"device.serial", "C02X…"}
SourceRef    = { source_id: ID(src_…), evidence_id: ID(evd_…) | null,
                 observed_at: timestamp, method: string }  # method e.g. "connector:intune"
ActorRef     = { actor_type: "system"|"connector"|"user"|"agent", actor_id: string }
             # canonical definition lives in CONVENTIONS §6; do not redefine
```

## 7. Object types & the type registry

- An `ObjectType` is registered with: `key` (e.g. `device`), `schema_version`,
  a JSON Schema for its `attributes`, its permitted `natural_keys` namespaces,
  and a `human_label`.
- The base envelope validates first; then `attributes` validate against the
  registered JSON Schema for `(object_type, schema_version)`.
- **Foundation ships exactly one built-in type: `generic`** (freeform
  attributes), enough for the C-001 walking skeleton. Real types (device,
  identity, …) arrive in their own EAs and register here.
- Unknown `object_type` on write → rejected with `UnknownObjectType` (§14).

## 8. Provenance / source model (evidence seam)

- Every object carries ≥1 `SourceRef`. A `Source` record (`src_…`) describes an
  origin (a connector run, a scan, a manual entry).
- `SourceRef.evidence_id` is **nullable in C-001** (Evidence Engine lands in
  EA-0004); once EA-0004 exists, sources SHOULD carry an `evidence_id`.
- This is the data-layer contract that lets a Finding later answer "how AQELYN
  knows" by walking object → source → evidence.

## 9. Identity resolution & merge

- On upsert, the store attempts to match an incoming object to an existing one
  by `(tenant_id, object_type, natural_key)` exact match.
- Match → update the existing object (merge attributes by last-writer-wins per
  field, union of `sources`, `max(last_seen_at)`), bump `version`.
- No match → create new.
- Explicit **merge(survivor_id, duplicate_id)**: sets duplicate
  `lifecycle_state=merged`, `merged_into=survivor_id`, re-points its
  relationships to the survivor, unions sources/natural_keys. Both ids remain
  resolvable; resolving a merged id returns the survivor (with a redirect flag).

## 10. Lifecycle

```
        create
          │
          ▼
      ┌────────┐  archive   ┌──────────┐
      │ active │──────────▶ │ archived │
      └────────┘◀────────── └──────────┘  restore
        │    │  merge(→survivor)
   soft │    └────────────▶  merged   (terminal; redirects to survivor)
 delete ▼
     deleted   (terminal; retained for audit)
```

Only `active`/`archived` objects appear in default queries. `merged`/`deleted`
are excluded unless explicitly requested (audit/history views).

## 11. Tenancy & scoping rules

- Local mode: `tenant_id = NULL` everywhere; all queries implicitly scope to
  NULL.
- Enterprise mode: every object has a non-null `tenant_id`; every query MUST be
  scoped to one tenant (or an explicit cross-tenant admin scope). The store
  rejects unscoped queries in enterprise mode (`TenantScopeRequired`).
- No object may reference an object in another tenant (relationships are
  intra-tenant). Enforced at write.

## 12. Concurrency & versioning

- Update calls pass `expected_version`. If it doesn't match the stored
  `version`, the store raises `OptimisticConcurrencyConflict` — the caller
  re-reads and retries. `version` increments by 1 on every successful mutation.

## 13. Interfaces (Python 3.12)

Pydantic v2 models mirror §6. The store is a `Protocol` so C-001 can ship an
in-memory implementation and swap PostgreSQL in without changing callers
(ADR-0001 D3/D6 pattern).

```python
from typing import Protocol, Sequence
from datetime import datetime
from pydantic import BaseModel, Field

class NaturalKey(BaseModel):
    namespace: str
    value: str

class SourceRef(BaseModel):
    source_id: str
    evidence_id: str | None = None
    observed_at: datetime
    method: str

class ActorRef(BaseModel):
    actor_type: str            # "system" | "connector" | "user" | "agent"
    actor_id: str

class AQObject(BaseModel):
    id: str
    object_type: str
    schema_version: int
    tenant_id: str | None = None
    display_name: str
    attributes: dict = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)
    natural_keys: list[NaturalKey] = Field(default_factory=list)
    sources: list[SourceRef]
    confidence: float = 1.0
    lifecycle_state: str = "active"
    merged_into: str | None = None
    version: int = 1
    first_seen_at: datetime
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime
    created_by: ActorRef
    updated_by: ActorRef

class AQRelationship(BaseModel):
    id: str
    tenant_id: str | None = None
    from_id: str
    to_id: str
    relation_type: str         # e.g. "owns", "runs_on", "member_of"
    attributes: dict = Field(default_factory=dict)
    sources: list[SourceRef]
    confidence: float = 1.0
    lifecycle_state: str = "active"
    version: int = 1
    created_at: datetime
    updated_at: datetime
    created_by: ActorRef
    updated_by: ActorRef

class ObjectQuery(BaseModel):
    tenant_id: str | None = None
    object_type: str | None = None
    labels: dict[str, str] | None = None
    natural_key: NaturalKey | None = None
    include_states: Sequence[str] = ("active", "archived")
    limit: int = 100
    cursor: str | None = None

class ObjectStore(Protocol):
    async def get(self, object_id: str, *, resolve_merged: bool = True) -> AQObject | None: ...
    async def upsert(self, obj: AQObject) -> AQObject: ...            # match/merge per §9
    async def update(self, obj: AQObject, *, expected_version: int) -> AQObject: ...  # §12
    async def query(self, q: ObjectQuery) -> tuple[list[AQObject], str | None]: ...   # (rows, next_cursor)
    async def relate(self, rel: AQRelationship) -> AQRelationship: ...
    async def relationships(self, object_id: str, *, direction: str = "both",
                            relation_type: str | None = None) -> list[AQRelationship]: ...
    async def merge(self, survivor_id: str, duplicate_id: str, *, by: ActorRef) -> AQObject: ...
    async def set_state(self, object_id: str, state: str, *, by: ActorRef,
                        expected_version: int) -> AQObject: ...
    async def history(self, object_id: str) -> list[dict]: ...        # append-only audit rows
```

## 14. Persistence (PostgreSQL 16)

```sql
CREATE TABLE aq_object (
    id              uuid PRIMARY KEY,               -- UUIDv7
    object_type     text        NOT NULL,
    schema_version  int         NOT NULL,
    tenant_id       uuid        NULL,               -- NULL = local mode (D2)
    display_name    text        NOT NULL,
    attributes      jsonb       NOT NULL DEFAULT '{}',
    labels          jsonb       NOT NULL DEFAULT '{}',
    confidence      double precision NOT NULL DEFAULT 1.0
                    CHECK (confidence >= 0 AND confidence <= 1),
    lifecycle_state text        NOT NULL DEFAULT 'active'
                    CHECK (lifecycle_state IN ('active','archived','merged','deleted')),
    merged_into     uuid        NULL REFERENCES aq_object(id),
    version         int         NOT NULL DEFAULT 1,
    first_seen_at   timestamptz NOT NULL,
    last_seen_at    timestamptz NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    created_by      jsonb       NOT NULL,
    updated_by      jsonb       NOT NULL
);
CREATE INDEX ix_object_tenant_type ON aq_object (tenant_id, object_type)
    WHERE lifecycle_state IN ('active','archived');
CREATE INDEX ix_object_labels ON aq_object USING gin (labels);
CREATE INDEX ix_object_attrs  ON aq_object USING gin (attributes);

CREATE TABLE aq_object_natural_key (
    object_id   uuid  NOT NULL REFERENCES aq_object(id),
    tenant_id   uuid  NULL,
    namespace   text  NOT NULL,
    value       text  NOT NULL,
    PRIMARY KEY (object_id, namespace, value)
);
-- Dedup seam (§9): one live object per natural key per tenant/type.
CREATE UNIQUE INDEX uq_natural_key_live
    ON aq_object_natural_key (tenant_id, namespace, value);

CREATE TABLE aq_object_source (
    id          uuid PRIMARY KEY,
    object_id   uuid  NOT NULL REFERENCES aq_object(id),
    source_id   uuid  NOT NULL,
    evidence_id uuid  NULL,                         -- filled once EA-0004 exists
    observed_at timestamptz NOT NULL,
    method      text  NOT NULL
);

CREATE TABLE aq_relationship (
    id              uuid PRIMARY KEY,
    tenant_id       uuid NULL,
    from_id         uuid NOT NULL REFERENCES aq_object(id),
    to_id           uuid NOT NULL REFERENCES aq_object(id),
    relation_type   text NOT NULL,
    attributes      jsonb NOT NULL DEFAULT '{}',
    confidence      double precision NOT NULL DEFAULT 1.0,
    lifecycle_state text NOT NULL DEFAULT 'active',
    version         int  NOT NULL DEFAULT 1,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    created_by      jsonb NOT NULL,
    updated_by      jsonb NOT NULL
);
CREATE INDEX ix_rel_from ON aq_relationship (from_id, relation_type);
CREATE INDEX ix_rel_to   ON aq_relationship (to_id, relation_type);

-- Append-only audit history (D4): one row per mutation.
CREATE TABLE aq_object_history (
    seq         bigserial PRIMARY KEY,
    object_id   uuid NOT NULL,
    version     int  NOT NULL,
    snapshot    jsonb NOT NULL,          -- full object state after the change
    changed_at  timestamptz NOT NULL DEFAULT now(),
    changed_by  jsonb NOT NULL
);
CREATE INDEX ix_history_object ON aq_object_history (object_id, version);
```

## 15. Requirements

### Functional (testable — replaces the placeholder "capability N")

- **FR-1** The store SHALL assign an immutable UUIDv7 id, rendered externally as `obj_<hex>`, to every new object.
- **FR-2** The store SHALL reject writes whose `object_type` is not registered (`UnknownObjectType`).
- **FR-3** The store SHALL validate `attributes` against the registered JSON Schema for `(object_type, schema_version)`.
- **FR-4** On `upsert`, the store SHALL match on `(tenant_id, object_type, natural_key)` and update-in-place when matched, else create (§9).
- **FR-5** `update`/`set_state` SHALL enforce `expected_version` and raise `OptimisticConcurrencyConflict` on mismatch (§12).
- **FR-6** Every object SHALL carry ≥1 `SourceRef`; writes with none SHALL be rejected (`MissingProvenance`).
- **FR-7** The store SHALL never hard-delete; `delete` performs a soft state transition and writes history (§10, D4).
- **FR-8** `merge` SHALL make the duplicate resolvable to the survivor and re-point the duplicate's relationships (§9).
- **FR-9** In enterprise mode the store SHALL reject unscoped queries (`TenantScopeRequired`); in local mode it SHALL scope to `tenant_id IS NULL`.
- **FR-10** Every mutation SHALL append one `aq_object_history` row capturing the post-change snapshot, version, actor, and time.
- **FR-11** `relationships()` SHALL return edges by direction and optional `relation_type`, excluding non-active edges by default.
- **FR-12** Cross-tenant relationships SHALL be rejected at write.

### Non-functional (initial targets — validated by the C-001 skeleton, then confirmed on M-tier hardware)

- **NFR-1 (latency)** point `get` by id p95 < 5 ms; `upsert` p95 < 15 ms (excluding network), at 1M objects/tenant.
- **NFR-2 (scale)** correctness maintained to ≥ 10M objects and ≥ 30M relationships per tenant on an 8 GB host.
- **NFR-3 (integrity)** history is append-only; no code path updates or deletes `aq_object_history`.
- **NFR-4 (portability)** no PostgreSQL-only feature leaks above the store interface; the in-memory store passes the identical contract test suite.
- **NFR-5 (typing)** all modules pass `mypy --strict` and `ruff` (EA-0058).

## 16. Acceptance Criteria ↔ Tests (Definition of Ready)

This spec is "Ready" for Codex when a reviewer (Claude Code) can map each item
below to a named test. Each acceptance criterion becomes ≥1 test.

| # | Acceptance criterion | Test (pytest id) |
|---|---|---|
| AC-1 | New object gets an immutable `obj_` id | `test_uom_id_assigned_and_immutable` |
| AC-2 | Unregistered type rejected | `test_uom_unknown_object_type_rejected` |
| AC-3 | Attribute schema validation enforced | `test_uom_attributes_validated` |
| AC-4 | Upsert matches on natural key and updates in place | `test_uom_upsert_dedup_by_natural_key` |
| AC-5 | Version conflict raised on stale update | `test_uom_optimistic_conflict` |
| AC-6 | Object with no source rejected | `test_uom_requires_provenance` |
| AC-7 | Soft delete keeps row + writes history | `test_uom_soft_delete_and_history` |
| AC-8 | Merge redirects id and re-points edges | `test_uom_merge_survivor_redirect` |
| AC-9 | Local mode scopes to NULL tenant; enterprise rejects unscoped | `test_uom_tenant_scoping` |
| AC-10 | Every mutation appends exactly one history row | `test_uom_history_append_only` |
| AC-11 | In-memory and PostgreSQL stores pass the same contract suite | `test_uom_store_contract[inmemory]` / `[postgres]` |
| AC-12 | Cross-tenant relationship rejected | `test_uom_cross_tenant_edge_rejected` |

## 17. Error taxonomy (this spec's contributions)

`UnknownObjectType`, `SchemaValidationError`, `MissingProvenance`,
`OptimisticConcurrencyConflict`, `TenantScopeRequired`, `CrossTenantReference`,
`ObjectNotFound`. (Full platform taxonomy lives in the Conventions spec.)

## 18. Failure handling

- Validation failures → typed error above, no partial write (single transaction
  per mutation).
- Concurrency conflict → caller re-reads and retries; store never overwrites.
- Store unavailable → surface `StoreUnavailable`; the Kernel (EA-0001) reports
  degraded state; no silent data loss.

## 19. Dependencies & consumers

- **Depends on:** ADR-0001; `uuid-utils`, `pydantic>=2`, `asyncpg`/SQLAlchemy
  (implementation choice left to EA-0001 wiring, must stay behind the store
  interface).
- **Consumed by:** EA-0003 events reference `object_id`; EA-0004 evidence fills
  `SourceRef.evidence_id`; EA-0005 graph traverses `aq_relationship`; the
  Finding schema references affected objects by id.

## 20. Resolved decisions (previously open)

1. **Attribute merge policy (FR-4): last-writer-wins per field**, for now.
   Source-priority merging (a trusted connector overrides a lower-confidence
   guess) is deferred to a later revision once Evidence (EA-0004) provides
   per-source trust. No schema change is required to add it later — it changes
   only the merge function, behind the store interface.
2. **Confidence semantics: a single scalar per object**, for now. Per-attribute
   confidence is deferred to arrive with EA-0004 (Evidence), which supplies the
   per-source signal it depends on. The `confidence` field stays; per-attribute
   confidence will be additive, not a breaking change.

Both decisions are approved and binding for C-001. Revisiting either requires a
spec revision under change control.
