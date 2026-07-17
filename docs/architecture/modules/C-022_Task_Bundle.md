# C-022 Cyber Asset Discovery & Inventory Intelligence - Implementation Task Bundle

**Milestone:** C-022 (Cyber Asset Discovery & Inventory Intelligence, EA-0025)
**For:** Codex (implementer) / Claude Code (reviewer)
**Prerequisites:** EA-0024 merged & green; EA-0025 spec **Accepted**; **EA-0025 §0, §1 read first**; CONVENTIONS + EA-0002/0004/0005/0006/0007/0008/0012/0023/0024 read.
**Definition of Done:** every ticket's acceptance tests pass on in-memory **and** Postgres where a backing store is required; `ruff` clean; `mypy --strict` clean; **absence never decommissions; inventory() declares freshness and fails rather than shrinks; reconciliation records conflicts; no scan/probe/connect surface**; nothing outside the spec; `make check` green; Claude Code sign-off per ticket.

**Read EA-0025 §1 first.** Twenty engines scope their work to "the assets". A
silently shrinking inventory makes the platform report fully-covered, zero-exposure,
all-clean of a smaller world - the worst failure this system can have. Absence of
evidence is not evidence of absence. Discovery is handed-in, not scanned. If a
needed behavior is not in the spec, raise an ECR.

**Verification standard (ECR-0007):** invariants are structural and behavioural. For
this module: a degraded store makes `inventory()` fail (not shrink); `sweep_unreported`
refuses on unknown source health; every reconciliation conflict is on the record; no
public `scan`/`probe`/`connect` method exists. Do not substitute a grep for the proof.

## Target source layout

```
src/aqelyn/inventory/
|-- __init__.py       # exports engine, service, stores, types, register_inventory_events
|-- models.py         # DiscoverySource, AssetBasis, FieldConflict, AssetRecord, Ownership,
|                     #   AssetRelationship, InventoryReport, InventoryConfig (N1)
|-- engine.py         # ingest/reconcile (N2), lifecycle/inventory (N3),
|                     #   classify/ownership/relationships (N4)
|-- store.py          # AssetStore protocol + validators (N2)
|-- memory.py         # in-memory store (N2)
|-- postgres.py       # Postgres store + DDL (N2)
`-- service.py        # InventoryIntelligenceService(AQService) + register_inventory_events (N5)
tests/inventory/      # acceptance suite (in-memory + Postgres)
```

Suggested id prefixes (register in CONVENTIONS §9): `ast` (asset_record),
`arl` (asset_relationship).

---

## N1 - Types, config, taxonomy & no-scan surface

**Spec:** §1 (S1/S6), §5, §8 FR-1/9/10, §10.
**Deliverables:** the models; `AssetRecord` requires `discovery_source` + non-empty
`basis` and carries EA-0006 `confidence`; `LifecycleState` includes **both
`unreported` and `decommissioned`** as distinct states; `FieldConflict` with
`unresolved`; `InventoryConfig`; error codes (`InventoryConfigInvalid`,
`AssetBasisMissing`, `AssetNotFound`, `InventoryUnavailable`, `SourceHealthUnknown`,
`DecommissionRequiresEvidence`) in `conventions.errors` + CONVENTIONS §9. **No public
`scan`/`probe`/`connect` method or socket/network dependency.**
**Acceptance:** `test_inv_source_basis_required`, `test_inv_no_scan_surface`,
`test_inv_config_invalid`.

## N2 - AssetStore + handed-in ingest + reconciliation

**Spec:** §6, §7 ingest/reconcile, FR-1/2/3/12, S2.
**Deliverables:** `AssetStore` protocol, in-memory + Postgres stores + DDL; contract
suite; tenant scoping; append-only history; `ingest` accepts **handed-in** reports
with a `DiscoverySource`; `reconcile` resolves each field by **EA-0006 source
reliability** (not last-writer, not source order), **records every conflict** with
each candidate's value + source + reliability, and marks ties `unresolved=True` +
surfaced.
**Depends on:** N1.
**Acceptance:** `test_inv_store_contract[inmemory]`, `test_inv_store_contract[postgres]`,
`test_inv_reconcile_records_conflicts`, `test_inv_reconcile_tie_unresolved`,
`test_inv_reconcile_reliability_precedence`, `test_inv_confidence_from_trust`.

## N3 - Lifecycle (absence != decommission) + inventory() (freshness or fail)

**Spec:** §1 (S3/S4/S5), §7 lifecycle/inventory, FR-4/5/6/7/11, NFR-1.
**Deliverables:** `mark_unreported`/`sweep_unreported` set `unreported` +
`unreported_since` and are **separate from** `decommission`; `sweep_unreported`
**refuses** (`SourceHealthUnknown`) when source health is `unknown`; `decommission`
requires positive evidence or an attributed EA-0008 decision (`DecommissionRequires
Evidence` otherwise); lifecycle history append-only; `inventory()` returns `as_of` +
per-source freshness + `total`, and a **degraded store raises `InventoryUnavailable`
rather than returning a partial/shrunken set**.
**Depends on:** N2.
**Acceptance:** `test_inv_absence_not_decommission`, `test_inv_sweep_refuses_unknown_health`,
`test_inv_decommission_requires_evidence`, `test_inv_inventory_declares_freshness`,
`test_inv_inventory_fails_not_shrinks`, `test_inv_lifecycle_append_only`.

## N4 - Classification, ownership & relationship inference (reuse)

**Spec:** §1, §7 relationships, FR-8, NFR-3.
**Deliverables:** classification **delegates EA-0012 `classify()`** (no second
classifier); ownership intelligence (business/technical/custodian + rationale +
source); `infer_relationships` writes `AssetRelationship`s via **EA-0002** storage and
traverses via **EA-0005** `paths()` (bounded by `max_relationship_work`). No duplicate
classifier/store/traversal.
**Depends on:** N3.
**Acceptance:** `test_inv_classify_delegates_acg`, `test_inv_relationships_reuse`.

## N5 - Service + events

**Spec:** FR-13, §11.
**Deliverables:** `InventoryIntelligenceService` (`AQService`, name
`"inventory_engine"`) + `register_inventory_events`; in-memory and Postgres
kernel-factory wiring using the established `TYPE_CHECKING` + in-function import
pattern; health reflects owner-read availability + config validity.
**Depends on:** N4.
**Acceptance:** `test_inv_service_health`.

## N6 - Close the seams: wire inventory() to EA-0023 and EA-0024

**Spec:** §0, §13; **ECR-0013**, **ECR-0014**.
**Deliverables:** wire EA-0025 `inventory()` as **EA-0023's asset set** (the
`KnownSurfaceSource` the exposure engine was missing) **and EA-0024's coverage
denominator** (replacing the refusing default from ECR-0013 with a real
inventory-backed `CoverageReport` whose `unscanned` = inventory minus scanned, and
which fails-closed when `inventory()` is unavailable). Both wired in the kernel
factory. This closes the two deferred seams and ECR-0013's coverage gap with an
authoritative denominator.
**Depends on:** N5.
**Acceptance:** `test_inv_seams_wired` (exposure derives its asset set from
`inventory()`; vulnerability coverage's `unscanned` reflects inventory minus scanned;
a degraded `inventory()` makes coverage refuse, not report clean).

---

## Review protocol (Claude Code) - the denominator must be trustworthy

Per ticket, confirm the normal DoD **and**, with extra scrutiny:
1. **Absence != decommission.** An asset that stops appearing becomes `unreported`,
   never `decommissioned`; decommission needs positive evidence or a gated decision.
2. **No silent shrink.** A degraded store makes `inventory()` **fail**, not return a
   smaller set; `sweep_unreported` **refuses** on unknown source health.
3. **Freshness declared.** `inventory()` carries `as_of` + per-source freshness - no
   reporting 100% coverage of a stale world.
4. **Conflicts recorded, not smoothed.** Every reconciliation disagreement is on the
   record with candidate values + EA-0006 reliability; ties are `unresolved` +
   surfaced; precedence is reliability, never last-writer or source order.
5. **Reuse, not rebuild.** Classification delegates EA-0012; relationship storage is
   EA-0002; traversal is EA-0005; confidence is EA-0006. No duplicates.
6. **Handed-in, not scanned.** No scan/probe/connect surface; discovery data is posted
   in (structural + behavioural, per ECR-0007).
7. **Seams closed (N6).** Exposure's asset set and vulnerability's coverage denominator
   both come from `inventory()`; a degraded `inventory()` makes coverage refuse (not
   report clean) - the ECR-0013 fix, done right.
8. **Service import discipline.** The service ticket must avoid the R5/T5 circular
   import trap: `TYPE_CHECKING` imports plus in-function runtime imports.

Merge only on green review; then **report back to the owner** before the next module.
