# Engineering Change Request (ECR) Log

Records approved changes to **Accepted** module specs, so amendments happen
under change control rather than silent edits (per `START_HERE.md`).

| ECR | Against | Status | Summary |
|---|---|---|---|
| ECR-0001 | EA-0005 Knowledge Graph | Accepted | Add a `max_work` enumeration budget to `paths()`. |
| ECR-0002 | EA-0009 Policy Engine | Accepted | Harden condition attribute lookup against dunder traversal. |
| ECR-0003 | EA-0013 Risk Intelligence | Accepted | Tenant-qualify the correlated `Risk.id` to prevent a cross-tenant PK collision. |

---

## ECR-0001 — `paths()` enumeration work budget

**Raised by:** Claude Code (post-EA-0005 review).
**Severity:** non-blocking hardening.

**Problem.** EA-0005 traversals are bounded, but the bound was uneven. The
Postgres CTE traversals are limited by `LIMIT` (max_nodes) and depth. The
Python-side `paths()` enumeration was bounded only by `max_depth` and
`max_paths` — on a dense graph it could expand a very large number of partial
paths before collecting `max_paths` complete ones, so worst-case effort was not
explicitly capped. This violates the spirit of EA-0005 D2 ("bounded, never
hang").

**Resolution.** Add `max_work: int = 50_000` to `paths()` (§6). It caps the
number of nodes/partial-paths expanded during enumeration; on reaching it,
`paths()` returns the paths found so far rather than continuing. Hard cap
`max_work ≤ 1_000_000`. Captured as **FR-13** and **AC-15**
(`test_kg_paths_work_budget`).

**Impact.** Additive, backward-compatible (new keyword arg with a default).
Implemented via C-002 follow-up ticket **G3a**. No change to other methods or to
the contract of already-passing tests.

---

## ECR-0002 — Policy condition lookup dunder hardening

**Raised by:** Claude Code (post-P1 review).
**Severity:** defense-in-depth hardening.

**Problem.** EA-0009 P1 correctly avoids arbitrary code execution: the condition
interpreter is structured data and contains no `eval`/`exec`/dynamic import
path. However, its dotted attribute lookup used `getattr(current, part)` after a
non-dict hop. With untrusted policy attr-path segments, a path such as
`resource.type.__class__` could traverse Python object internals. This is not a
code-execution issue, but it is an avoidable information-leak surface.

**Resolution.** Attribute lookup is restricted to data mapping traversal only.
Any empty path segment or segment starting with `__` is treated as missing, and
non-mapping values stop traversal rather than calling `getattr`.

**Impact.** Backward-compatible for supported policy data because Decision
requests and compliance resources are dictionaries. Adds an acceptance test that
a dunder attr path yields no match.

---

## ECR-0003 — Tenant-qualify the correlated `Risk.id`

**Raised by:** Claude Code (post-R3 review, PR #52).
**Severity:** blocking correctness — tenant-isolation break.

**Problem.** R2 derived the correlated risk id as `risk:{correlation_key}`, and
`aq_risk.id` is the primary key. A `correlation_key` is caller-controllable and
can be shared across tenants — via an explicit `finding.correlation_id` or an
external `CorrelationSignal.correlation_key` taxonomy (e.g.
`"risk:internet-exposure"`). Two tenants sharing such a key minted the **same
PK**, so the second tenant's `upsert` matched the first tenant's row by id and
raised `CrossTenantReference` — one tenant's risk permanently blocked another
from registering its own. The `(tenant_id, correlation_key)` unique index was
correct; only the PK id lacked a tenant segment. Reproduced empirically during
review (identical id, `CrossTenantReference`). Finding-derived keys embed object
UUIDs and were already collision-free; the defect surfaced only for shared
explicit keys.

**Resolution.** Derive the id as `risk:{tenant_id or 'global'}:{key}`
(`_risk_id`). The tenant id is a UUID (or the literal `global`), so the
`:`-delimited prefix is unambiguous and two tenants sharing a `correlation_key`
now produce distinct ids. Dedupe/versioning semantics are unchanged (still keyed
on `(tenant_id, correlation_key)`).

**Impact.** Changes the format of correlated risk ids (no persisted risks exist
yet — R3 is the first persistence). Adds `test_risk_cross_tenant_correlation_key`
(both backends); updates the one R2 assertion that pinned the old id string.
