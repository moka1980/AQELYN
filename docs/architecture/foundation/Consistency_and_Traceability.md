# Foundation — Consistency & Traceability Report

**Scope:** ADR-0001 + the six C-001 foundation specs (CONVENTIONS, EA-0002,
EA-0003, EA-0004, Finding model, EA-0001).
**Purpose:** prove the specs are internally consistent and that they trace back
to the Charter, before Codex begins C-001.
**Status:** pass, with two drift issues found and fixed (§2).

---

## 1. What was checked

Mechanical cross-spec consistency of: typed ID prefixes, the error taxonomy,
event-type names and their registration ownership, shared type definitions
(`ActorRef`, `Subject`, `SourceRef`, `BlobRef`, `HealthStatus`), tenancy
handling, hashing/canonicalization references, and cross-spec dependency
direction (no cycles, no forward references).

## 2. Issues found and fixed

| # | Issue | Resolution |
|---|---|---|
| C-1 | `aqelyn.evidence.recorded` and the three `aqelyn.finding.*` events were referenced by EA-0004/Finding but not explicitly *registered* by any spec; EA-0003's table read as the whole registry. | Added "Events registered by this spec" tables to EA-0004 (§5a) and Finding (§6a); clarified in EA-0003 §7 that the registry is extensible and each spec owns its types. |
| C-2 | `ActorRef` was defined identically in both EA-0002 and CONVENTIONS with no canonical source. | CONVENTIONS §6 marked canonical; EA-0002 now references it and must not redefine. |

Both were mechanical (no design change, no user judgment required).

## 3. Verified-consistent inventories

### 3.1 Typed ID prefixes (CONVENTIONS §1 is canonical)

`obj` (EA-0002), `rel` (EA-0002), `src` (EA-0002), `evt` (EA-0003),
`evd` (EA-0004), `pkg` (EA-0004), `fnd` (Finding), `svc` (EA-0001).
Every prefix used in any spec is declared in CONVENTIONS. ✔

### 3.2 Error taxonomy (CONVENTIONS §9 is canonical)

Every code named in a spec's "Error taxonomy (contributions)" section appears in
the CONVENTIONS table, and every CONVENTIONS row is owned by exactly one spec.
No duplicates, no orphans. ✔

### 3.3 Event types & ownership (post-fix)

| event_type | Registered by | Referenced by |
|---|---|---|
| `aqelyn.kernel.runtime_started` / `_stopped` | EA-0003 | EA-0001 |
| `aqelyn.object.created` / `updated` / `state_changed` / `merged` | EA-0003 | EA-0002, EA-0001 |
| `aqelyn.relationship.created` | EA-0003 | EA-0002 |
| `aqelyn.evidence.recorded` | EA-0004 | EA-0004 |
| `aqelyn.finding.raised` / `status_changed` / `regressed` | Finding | Finding |

Every referenced event now has exactly one registering spec. ✔

### 3.4 Shared types (single definition, reused)

| Type | Defined in | Reused by |
|---|---|---|
| `ActorRef` | CONVENTIONS §6 (canonical) | EA-0002, EA-0003, EA-0004, Finding, EA-0001 |
| `Subject` | EA-0003 | EA-0004, Finding |
| `SourceRef` | EA-0002 | EA-0004 (fills `evidence_id`) |
| `BlobRef` | EA-0004 | — |
| `HealthStatus` | EA-0001 | — |

No conflicting redefinitions remain. ✔

### 3.5 Dependency direction (acyclic)

```
CONVENTIONS → EA-0002 → EA-0003 → EA-0004 → Finding → EA-0001
```
No spec references a type or event owned by a spec later in this order except
the Kernel (EA-0001), which is intentionally last and wires all others. ✔

### 3.6 Cross-cutting invariants honored by every spec

- Tenancy: `tenant_id uuid | null`, NULL = local, cross-tenant refs rejected. ✔
- Timestamps: UTC RFC3339 µs. ✔
- Hashing: sha256 over CONVENTIONS §3 canonical JSON (EA-0004 packages/chain). ✔
- Append-only audit surfaces: `aq_object_history`, `aq_event_log`, `aq_evidence`,
  `aq_finding_audit`, `aq_evidence_custody`. ✔
- Two-implementation portability (in-memory + backing store), one contract suite,
  in every store spec. ✔

## 4. Charter → spec traceability

Each permanent Charter requirement is enforced by at least one spec, structurally
(rejected at write) where possible rather than by convention.

| Charter requirement | Enforced by | How |
|---|---|---|
| Evidence before opinion | EA-0004 + Finding | Findings require ≥1 evidence ref (`EvidenceRequired`); objects require ≥1 source (`MissingProvenance`). |
| "How AQELYN knows" is always answerable | EA-0002 → EA-0004 → Finding | object → source → evidence chain; Finding `how_determined` mandatory. |
| Tamper-evident proof for enterprise/gov | EA-0004 | immutable hash-chained evidence + offline-verifiable packages + custody log. |
| Understandable by non-expert | Finding | `title`, `what_happened`, `why_it_matters`, `risk_of_inaction` mandatory, plain-language. |
| Actionable by expert | Finding | `expert_details`, `affected_object_ids`, `remediation.steps`. |
| Expected outcome after remediation | Finding | `remediation.expected_outcome` mandatory. |
| Progressive detail (6 levels) | Finding §4 | one record serves all six levels. |
| Not just detect — explain/prove/prioritize/fix | Finding | required explanation + evidence + `severity_score` + `remediation`/`automation`. |
| Alert fatigue avoided | Finding | dedup by `dedup_key`; re-detection updates, not duplicates. |
| Full auditability & traceability | EA-0002/3/4 + Finding | append-only history/log/chain/audit on every mutation. |
| Privacy-first, local-first | CONVENTIONS + all | nullable tenancy; runs fully local (in-memory infra) per ADR-0001. |
| Same architecture, both modes | ADR-0001 + CONVENTIONS | local (NULL tenant, in-memory/self-host) and enterprise (tenant-scoped, Redis/Postgres) share one contract set. |
| Safe automation | Finding | `automation.eligibility` + `requires_approval` + `risk_note`. |

## 5. Residual notes (not blockers)

- Signing / external anchoring of evidence is a **reserved seam** (EA-0004 D4),
  not built in C-001. Deliberate.
- Source-priority attribute merge and per-attribute confidence are **deferred**
  (EA-0002 §20), to arrive with richer Evidence signals. Deliberate.
- Redis stream topology (single vs per-type) is a **wiring choice** left to
  EA-0001 implementation; it does not affect any contract or test.

## 6. Verdict

The foundation spec set is internally consistent and Charter-traceable. It is
ready to be **Accepted** and handed to Codex per the C-001 task bundle.
