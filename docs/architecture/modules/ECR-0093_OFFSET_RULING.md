# ECR-0093 — The Offset Routes: Correction of Record, Named Exemptions, One Cursor Contract

**Status:** Accepted
**From:** claude.ai (spec author), from Claude Code's brief verified at `main @d42b4e3`
**Date:** 2026-08-03
**Number:** 0093 per rule 1, re-checked against `ECR-LOG.md` in the implementation branch.

---

## 1. R1 — Correction of record, first and unconditionally

**The offset pair named in three prior ECRs is wrong.** `/api/v1/findings` does not use
offset and never has — it has been keyset since ECR-0088 (`_findings` calls
`service.query(tenant_id, limit, cursor)` and touches neither `_page_request` nor `_page`).
The two offset routes are **`/api/v1/inventory`** and **`/api/v1/vulnerabilities`** — the
only two `_page_request` call sites in the file. The claim was wrong when first written, not
overtaken by events.

This ECR corrects **ECR-0090 §4, ECR-0091 §5, and ECR-0092 §3**, each stating: route pair
corrected to inventory + vulnerabilities; findings needs no migration; **the ECR-0092 §3
ruling survives in substance** — FR-003 is surface-wide, no collection route keeps offset
silently — with only its applicable set changed. The §6 method note carries the cause: a
citation can be precisely right and still point at the wrong thing.

## 2. Findings of record

1. **Both offset routes are report slicers, not row-streams.** Inventory pages
   `report.assets` from a per-request `InventoryReport`; vulnerabilities pages
   `assessment.priorities` from a per-request `VulnerabilityAssessment`. Both reports carry
   ECR-0034 `degraded` plus freshness/coverage metadata, both routes emit it, and `_page`
   enforces `SURFACE_WORK_BUDGET` and rejects `offset > len(items)`.
2. **The offset cursor was the strictly stronger contract.** It bound
   `{"offset","path","tenant_id"}` and rejected any path/tenant mismatch. The findings
   keyset cursor (`severity_score|finding_id`) had no such binding: not a leak
   (`WHERE tenant_id=$1` held), but a foreign cursor was silently accepted and resumed at an
   arbitrary position.
3. **Findings' keyset was not index-backed for the surface's own query shape.** The prior
   ordering-relevant index, `ix_finding_status_sev_id (tenant_id, status,
   severity_score DESC, id)`, has `status` in the middle; the surface route never sets
   `status`, so the index could not supply `ORDER BY severity_score DESC, id`. The SQL's
   explicit `ORDER BY` kept results **correct**; index backing and static-guard pinnability
   were missing.

## 3. Requirements and resolution

**R2 — Named exemption for both offset routes.** What these routes page is a derived report
recomputed per request under an ECR-0034 budget, not a durable row set. A cursor into snapshot
N has no defined meaning in snapshot N+1 — a keyset would encode a resume point into an object
that no longer exists, and offset has the identical flaw. The exemption is therefore named
rather than disguised as a migration:

- the exemption's grounds stay **visible in the payload**: `degraded`, `as_of` /
  `generated_at`, and freshness/coverage fields remain emitted; tests guard that property;
- if either engine's report is re-pointed at a durable store row-stream, that redesign gets
  its own ECR and the exemption lapses;
- both routes are explicitly exempt from keyset, retain offset deliberately, and remain
  replay-guarded by the scoped cursor binding.

**R3 — One cursor contract on the surface.** The `path` + `tenant_id` binding remains on the
offset routes and now wraps findings' store-owned opaque cursor as
`{"path","tenant_id","inner"}`. The findings store cursor format is untouched. Cross-route
and cross-tenant replay is rejected with a clean HTTP 400 in both directions.

**R4 — Findings gets the covering index: `(tenant_id, severity_score DESC, id ASC)`.**
Findings is the surface's highest-volume route; the composite already exists in the SQL; and,
unlike secrets, no structural obstacle prevents an index. One index, no table-shape change,
joins the DDL. ECR-0090's static guard now pins its name, table and per-column direction. This
is the arc's first DDL change and persists no new field, so GC-004 gains no census member.

**R5 — No weakening.** The 14-mutation matrix of ECR-0090/0091/0092 remains in force.

**R6 — Cursor breakage policy.** The surface is loopback-only, read-only and single-operator;
there is no external cursor contract or deprecation window. Previously issued findings cursors
break. Unparseable or wrong-scope cursors raise `SurfaceRequestInvalid` and return the defined
HTTP 400, never a 500 and never a silent reset.

## 4. Behavioural witness status for findings — honest, not assumed

The static guard pins the findings index agreement. Whether findings' existing behavioural
ordering witnesses meet the ECR-0090/0091 standard has not been measured in this implementation.
The reviewer runs both deletion mutations and records the result. A green mutation is a finding
for a follow-up ECR, not something this ECR silently repairs.

## 5. Carried constraints

Reads-only, loopback, no new dependency, GC-002/GC-003 untouched. ECR-0034 `degraded` ·
ECR-0061 exhaust-or-refuse · ECR-0062 keyset (unchanged at the store layer) · rule 33 · all
prior method notes.

## 6. Method note carried into the record

**A citation can be precisely right and still point at the wrong thing.** The offset
machinery's line numbers were correct every time they were cited — which is exactly why the
sentence wrapped around them survived three ECRs. When naming which callers use a mechanism,
grep the call sites; do not infer them from proximity. The line number that survives review is
not the same as the claim that survives review.

## 7. Outcome

ECR-0093 ships the three prior-record corrections, named snapshot exemptions with visible
honesty metadata, one scope-bound surface cursor contract, and the findings covering index plus
static conformance check. Claude Code reviews the 14-mutation matrix, the new controls, and the
§4 findings deletion probes before merge.
