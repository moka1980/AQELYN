# EA-0025 — Cyber Asset Discovery & Inventory Intelligence Engine — Implementation Specification

**Realizes:** EA-0025 / IS-025 (supersedes the placeholder `archive/EA-0025/EA-0025_Master.md` for implementation)
**Depends on:** ADR-0001, CONVENTIONS, EA-0001 (`AQService`), **EA-0002 (relationship storage)**, **EA-0005 (traversal)**, **EA-0006 (source reliability + confidence)**, **EA-0012 (`classify()`, config)**, EA-0007 (mission), EA-0004 (evidence), EA-0008 (gated lifecycle decisions), EA-0009 (Policy)
**Consumed by:** EA-0023 (asset set), EA-0024 (coverage denominator), EA-0013/0022 (asset context) — `inventory()` is the authoritative answer to "which assets exist"
**Status:** Accepted
**Build milestone:** C-022 (see `C-022_Task_Bundle.md`)
**Definition of Ready:** see §9

---

## 0. Scope reconciliation

IS-025 establishes the **authoritative** answer to *"which assets exist"* — the
denominator twenty engines scope their work to. It is **not** a connector: the
master's Discovery API is `POST /discovery/start` under **Public APIs** — discovery
data is **handed in**, no agents/collectors/credentials/network (EA-0023 §0.1 holds
a seventh time). The largest duplication surface yet, all mapped:

| The question | Owner | Realization |
|---|---|---|
| How is an asset classified? | **EA-0012 `classify()`** | Cited, not re-implemented. |
| Where is relationship/config data stored? | **EA-0002** (`relationships()`) / **EA-0012** | Reused. |
| How are relationships traversed? | **EA-0005** (`paths()`) | Reused. |
| How reliable is a source? | **EA-0006** (source reliability) | Precedence authority (S2). |
| What does an asset cost? | **EA-0007** mission | Cited. |

| IS-025 component | Realization |
|---|---|
| Discovery Engine | **New (handed-in ingest)** — accepts posted-in discovery data. No scan/probe/connect (S6). |
| Asset Inventory Engine | **New** — the authoritative `inventory()` (S3/S4). |
| Asset Classification Engine | **Delegates EA-0012 `classify()`** — no second classifier. |
| Ownership Intelligence Engine | **New** — ownership was named in EA-0012 but never implemented. |
| Relationship Discovery Engine | **New inference**; storage is EA-0002, traversal is EA-0005. |
| Lifecycle Management Engine | **New** — absence ≠ decommission (S3). |
| Configuration Enrichment Engine | **Reuses EA-0012** config. |
| *(reuse)* Confidence | **EA-0006**. Evidence = **EA-0004**. |

Tenant-scoped, append-only, **no scanning** (handed-in), no new authorization surface.

## 1. The central problem: a shrinking inventory that looks like good news

Twenty engines scope their work to *"the assets."* If a broken feed silently
shrinks the inventory, the platform then reports **fully-covered, zero-exposure,
all-clean — of a smaller world.** Cascading blindness that looks like good news is
the worst failure this system can have. Five rules prevent it:

- **S1 — An asset is a source's report, evidence-backed.** Every `AssetRecord`
  names its `discovery_source`, carries EA-0006 `confidence`, and cites evidence.
  No record is authoritative without source lineage + validation metadata.
- **S2 — Reconciliation records conflicts; it does not smooth them.** Three sources
  disagreeing about a host is the *normal* case. Precedence resolves via **EA-0006
  source reliability** — **not** last-writer-wins, **not** source order. Every
  conflict stays **on the record**, with each candidate's value and reliability; a
  tie lands **unresolved and surfaced**, never silently picked.
- **S3 — Absence of evidence is not evidence of absence.** An asset that stops
  appearing in a feed becomes **`unreported`**, **never** `decommissioned`.
  Decommissioning requires **positive evidence** or an **attributed gated decision**
  (EA-0008). `sweep_unreported` **refuses to run when source health is unknown** —
  it will not mark assets unreported on the word of a feed that may itself be broken.
- **S4 — The denominator declares its own freshness.** `inventory()` carries its
  `as_of`/freshness so nobody can report *100% coverage of a stale world*. A
  **degraded store makes `inventory()` fail rather than shrink** — an empty or
  partial inventory is never returned as if complete.
- **S5 — Lifecycle is append-only and gated.** State transitions
  (provisioned→active→…→retired) are recorded append-only; **retirement is an
  attributed gated decision**, never inferred. The engine proposes; EA-0008 acts.
- **S6 — Discovery is handed-in.** No `scan()`/`probe()`/`connect()`/network — data
  is posted in (EA-0023 §0.1). Active collection, if ever added, is an EA-0008
  `scan.active` gated action consumed as stored data.

## 2. Purpose

Every other engine asks *"which of the assets…?"* — and is only as right as the
inventory beneath it. This engine is that inventory: an **authoritative, evidence-
backed, freshness-declaring** record of what exists, reconciled honestly across
disagreeing sources, where an asset never vanishes because a feed went quiet. Its
value is that the whole platform can trust the denominator.

## 3. Design decisions

- **D1 — `AssetRecord` names its source + confidence.** `discovery_source`,
  `confidence` (EA-0006), `basis` (evidence), `lifecycle_state`; unrepresentable
  without a source + basis (S1).
- **D2 — Reconciliation is explicit.** `reconcile()` produces an `AssetRecord` whose
  `conflicts: list[FieldConflict]` records every disagreement (field, candidates
  with value + source + reliability, `resolved_by`/`unresolved`) (S2).
- **D3 — Lifecycle has an `unreported` state distinct from `decommissioned`** (S3).
  `mark_unreported` (bulk `sweep_unreported`) is separate from `decommission`, which
  requires positive evidence or an EA-0008 decision.
- **D4 — `inventory()` declares freshness and fails-closed** — `as_of`, per-source
  freshness, and `total`; a degraded store raises `InventoryUnavailable` (S4).
- **D5 — Classification delegates EA-0012 `classify()`; storage/traversal reuse
  EA-0002/EA-0005.** No second classifier, store, or traversal.
- **D6 — Registered as an `AQService`;** stores in-memory + Postgres; append-only.

## 4. Ubiquitous language

| Term | Meaning |
|---|---|
| **AssetRecord** | A source-attributed, evidence-backed asset (S1/D1). |
| **Reconciliation** | Conflict-recording merge across sources by EA-0006 reliability (S2/D2). |
| **`unreported`** | An asset a feed stopped reporting — *not* decommissioned (S3/D3). |
| **`inventory()`** | The authoritative, freshness-declaring asset set (S4/D4). |
| **Ownership** | Business/technical owner + custodian + accountability chain. |

## 5. Types

```
LifecycleState = "provisioned"|"active"|"modified"|"unreported"|"decommissioned"|"archived"

DiscoverySource = { source_id: str, reliability: float | null, health: "ok"|"degraded"|"unknown",
                    as_of: datetime }                                # EA-0006 reliability (S2)
AssetBasis  = { kind: "discovery"|"config"|"identity"|"relationship", ref: str,
                as_of: datetime, evidence_id: str | null }           # cited (S1)
FieldConflict = { field: str,
                  candidates: list[{ value: Any, source_id: str, reliability: float | null }],
                  resolved_by: str | null, unresolved: bool }        # every conflict on record (S2)

AssetRecord = { id, tenant_id, asset_type: str, discovery_source: str,   # source-named (S1)
                classification: str | null,                              # EA-0012 classify() (D5)
                owner: Ownership | null, lifecycle_state: LifecycleState,
                confidence: float, basis: list[AssetBasis],              # EA-0006 + evidence (S1)
                conflicts: list[FieldConflict],                          # S2/D2
                first_seen_at: datetime, last_reported_at: datetime,
                unreported_since: datetime | null }                      # S3
Ownership   = { business_owner: str | null, technical_owner: str | null,
                custodian: str | null, rationale: str, source_id: str }
AssetRelationship = { id, tenant_id, source_asset: str, target_asset: str,
                      relationship_type: str, confidence: float,
                      inferred_from: str, evidence_id: str | null }      # EA-0002 storage (D5)
InventoryReport = { assets: list[str], total: int, as_of: datetime,      # declares freshness (S4)
                    source_freshness: dict, degraded: bool }
InventoryConfig = { stale_after_days: int, min_source_health: str, max_relationship_work: int }
```

Reuses EA-0006 confidence, EA-0004 evidence, EA-0002 relationship storage, EA-0012
classification.

## 6. Interfaces (Python 3.12)

```python
from typing import Protocol, Sequence
from datetime import datetime

class AssetStore(Protocol):
    async def put(self, a: AssetRecord) -> AssetRecord: ...          # rejects: no source/basis
    async def get(self, asset_id: str, *, tenant_id: str | None) -> AssetRecord | None: ...
    async def query(self, *, tenant_id: str | None, lifecycle_state: LifecycleState | None = None,
                    limit: int = 100) -> list[AssetRecord]: ...

class InventoryEngine(Protocol):
    async def ingest(self, *, reports: Sequence[dict], source: DiscoverySource,
                     tenant_id: str | None) -> Sequence[AssetRecord]: ...   # handed-in (S6)
    async def reconcile(self, asset_id: str, *, tenant_id: str | None) -> AssetRecord: ...  # conflicts recorded (S2)
    async def inventory(self, *, tenant_id: str | None) -> InventoryReport: ...  # freshness; fail-closed (S4)
    async def mark_unreported(self, asset_id: str, *, tenant_id: str | None) -> AssetRecord: ...  # not decommission (S3)
    async def sweep_unreported(self, *, source: DiscoverySource, tenant_id: str | None) -> list[AssetRecord]: ...  # refuses if health unknown (S3)
    async def decommission(self, asset_id: str, *, by: "ActorRef", evidence_id: str | None,
                           tenant_id: str | None) -> AssetRecord: ...   # positive evidence / gated (S3/S5)
    async def infer_relationships(self, asset_id: str, *, tenant_id: str | None) -> list[AssetRelationship]: ...  # EA-0002/0005
    # NOTE: no scan()/probe()/connect() — discovery is handed in (S6).
```

`InventoryIntelligenceService` wraps engine + store as an `AQService`
(name `"inventory_engine"`, depends on assetconfig/objects/graph/trust/mission/
evidence; health reflects owner-read availability + config validity). It supplies
`inventory()` to EA-0023 (asset set) and EA-0024 (coverage denominator).

## 7. Computation (the reference model)

**Ingest.** Accept **handed-in** discovery `reports` with a `DiscoverySource`
(reliability + health + as_of). Build/refresh `AssetRecord`s: `discovery_source`,
`confidence` (EA-0006), cited `basis`; update `last_reported_at`. No scan (S6).

**Reconcile.** Across sources reporting the same asset, resolve each field by
**EA-0006 reliability**; record **every** disagreement in `conflicts` (candidates +
reliability); a tie → `unresolved=True` and surfaced (S2). Classification is
EA-0012 `classify()` (D5).

**Lifecycle.** An asset absent from a fresh, healthy source → `mark_unreported`
(`unreported_since`), **not** decommissioned (S3). `sweep_unreported` **refuses**
(`SourceHealthUnknown`) if the source's health is `unknown` — a broken feed cannot
retire assets. `decommission` requires positive evidence or an attributed EA-0008
decision (S3/S5). History append-only.

**inventory().** Return the authoritative set with `as_of` + per-source freshness +
`total`; if the store is degraded, **raise `InventoryUnavailable`** rather than
return a shrunken/stale set as complete (S4).

**Relationships.** `infer_relationships` writes `AssetRelationship`s via EA-0002
storage; traversal is EA-0005 `paths()` (bounded by `max_relationship_work`).

## 8. Requirements

### Functional (testable)

- **FR-1** An `AssetRecord` SHALL name a `discovery_source` and carry a non-empty `basis`; one without SHALL be rejected (S1/D1).
- **FR-2** Reconciliation SHALL record **every** field conflict with each candidate's value + `source_id` + reliability; a tie SHALL be `unresolved=True` and surfaced — never silently picked, never last-writer/order (S2/D2).
- **FR-3** Precedence SHALL resolve via EA-0006 source reliability; no second reliability model (S2).
- **FR-4** An asset absent from a source SHALL become `unreported` (with `unreported_since`), SHALL NOT become `decommissioned` (S3/D3).
- **FR-5** `sweep_unreported` SHALL refuse (`SourceHealthUnknown`) when the source's health is `unknown` (S3).
- **FR-6** `decommission` SHALL require positive evidence or an attributed EA-0008 decision; the engine SHALL NOT infer decommission from absence (S3/S5).
- **FR-7** `inventory()` SHALL carry `as_of` + per-source freshness; a degraded store SHALL raise `InventoryUnavailable` rather than return a partial set (S4/D4).
- **FR-8** Classification SHALL delegate EA-0012 `classify()`; relationship storage SHALL use EA-0002; traversal SHALL use EA-0005 — no duplicates (D5).
- **FR-9** `confidence` SHALL come from EA-0006; no second confidence model (S1).
- **FR-10** Discovery SHALL be handed-in; the engine SHALL expose no `scan`/`probe`/`connect`/network surface (S6).
- **FR-11** Lifecycle history SHALL be append-only; retirement SHALL be attributed/gated (S5).
- **FR-12** `AssetStore` in-memory and Postgres implementations SHALL each pass one contract suite.
- **FR-13** `InventoryIntelligenceService` SHALL register as an `AQService` with health reflecting dependency availability + config validity (EA-0001).

### Non-functional

- **NFR-1 (no silent shrink — structural)** a degraded store makes `inventory()` fail, not shrink; `sweep_unreported` refuses on unknown health — proven behaviourally per ECR-0007.
- **NFR-2 (conflicts preserved)** every reconciliation conflict is on the record; ties surfaced — proven by test.
- **NFR-3 (reuse, not rebuild)** classification delegates EA-0012, storage EA-0002, traversal EA-0005 — proven behaviourally (spies), no duplicate.
- **NFR-4 (bounded & typed)** traversal/queries bounded; `mypy --strict` + `ruff` clean.

## 9. Acceptance Criteria ↔ Tests (Definition of Ready)

| # | Criterion | Test (pytest id) |
|---|---|---|
| AC-1 | AssetRecord without source/basis rejected | `test_inv_source_basis_required` |
| AC-2 | Reconciliation records every conflict | `test_inv_reconcile_records_conflicts` |
| AC-3 | Tie → unresolved + surfaced, not picked | `test_inv_reconcile_tie_unresolved` |
| AC-4 | Precedence by EA-0006 reliability (not order) | `test_inv_reconcile_reliability_precedence` |
| AC-5 | Absent asset → unreported, not decommissioned | `test_inv_absence_not_decommission` |
| AC-6 | sweep_unreported refuses on unknown source health | `test_inv_sweep_refuses_unknown_health` |
| AC-7 | decommission requires evidence / gated decision | `test_inv_decommission_requires_evidence` |
| AC-8 | inventory() declares freshness (as_of + per-source) | `test_inv_inventory_declares_freshness` |
| AC-9 | Degraded store → inventory() fails, not shrinks | `test_inv_inventory_fails_not_shrinks` |
| AC-10 | Classification delegates EA-0012 classify() | `test_inv_classify_delegates_acg` |
| AC-11 | Relationship storage EA-0002; traversal EA-0005 | `test_inv_relationships_reuse` |
| AC-12 | Confidence from EA-0006 (no 2nd model) | `test_inv_confidence_from_trust` |
| AC-13 | No scan/probe/connect surface (structural) | `test_inv_no_scan_surface` |
| AC-14 | Lifecycle append-only; retirement gated | `test_inv_lifecycle_append_only` |
| AC-15 | Store passes one suite each backend | `test_inv_store_contract[...]` |
| AC-16 | Registers as AQService with health | `test_inv_service_health` |
| AC-17 | inventory() supplies EA-0023 asset set + EA-0024 coverage denominator | `test_inv_seams_wired` |

## 10. Error taxonomy (contributions)

`InventoryConfigInvalid`, `AssetBasisMissing`, `AssetNotFound`,
`InventoryUnavailable`, `SourceHealthUnknown`, `DecommissionRequiresEvidence`
(added to `conventions.errors` + CONVENTIONS §9). Reuses EA-0023 `ScanNotPermitted`,
`StoreUnavailable`, `TenantScopeRequired`.

## 11. Registered event types (owned by EA-0025)

`aqelyn.inventory.asset_discovered`, `aqelyn.inventory.asset_reconciled`,
`aqelyn.inventory.asset_unreported`, `aqelyn.inventory.lifecycle_changed`,
`aqelyn.inventory.relationship_updated` — via `register_inventory_events()`.

## 12. Failure handling

- Invalid config → `InventoryConfigInvalid` at construction.
- Store degraded → `inventory()` raises `InventoryUnavailable` — **never** a shrunken
  set returned as complete (S4). Overrides master §28.2 "previous inventory retained".
- Source health unknown → `sweep_unreported` raises `SourceHealthUnknown`; no asset
  is marked unreported on a possibly-broken feed (S3).
- Reconciliation tie → recorded `unresolved`, surfaced — never silently resolved (S2).
- `decommission` without evidence/decision → `DecommissionRequiresEvidence` (S3/S5).
- A request to scan → `ScanNotPermitted`; discovery is handed-in (S6).

## 13. Dependencies & consumers

- **Depends on:** EA-0012 (`classify()`/config), EA-0002 (relationships), EA-0005
  (traversal), EA-0006 (reliability/confidence), EA-0007 (mission), EA-0004
  (evidence), EA-0008 (gated lifecycle), EA-0009 (policy), EA-0001 `AQService`.
- **Consumed by:** **EA-0023** (asset set) and **EA-0024** (coverage denominator) —
  wired in C-022 **N6**; EA-0013/0022 (asset context).
- **Explicitly NOT:** a scanner, a second classifier/store/traversal, or an actor.

## 14. Resolved / deferred decisions

- **Absence ≠ decommission** (S3) — the most important rule: a shrinking inventory
  that looks like good news is the worst failure this system can have.
- **Reconciliation records conflicts** (S2) and **the denominator declares its
  freshness** (S4) — see **ECR-0014**.
- **`inventory()` closes the EA-0023/EA-0024 seams** (N6) — what those modules were
  missing was never network access; it was an authoritative "which assets exist".
- **Not the connector turn** — discovery is handed in; no ADR-0001 refresh.
