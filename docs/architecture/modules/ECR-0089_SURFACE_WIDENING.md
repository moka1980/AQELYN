# ECR-0089 — Widening the Surface (read seams, first four capabilities, one data path)

**Status:** Accepted
**From:** claude.ai (spec author), from Claude Code's widening brief verified at `main @f601c69`
**Date:** 2026-08-02
**Number:** 0089 per rule 1, re-checked against `ECR-LOG.md` in the implementation branch.

---

## 1. Findings of record

1. **There is no uniform read seam.** The 30 registered services split three ways: 15 expose
   their API as methods on the service; 13 expose only `start/stop/health` with the real API
   behind `.engine` (or `.graph`); 3 are infrastructure with no read API (`datalake_engine`,
   `event_bus`, `object_store`). Any spec assuming one shape is wrong for roughly half the
   platform. This ECR settles the seam as an architectural decision, not an implementation
   accident.
2. **`reporting/` still bypasses the kernel entirely** — zero kernel/`get_service` references
   across all four modules. The platform has two user-facing paths with no shared data path.
3. **`explain` exists on 11 services** and the product principle is *Explain Before You
   Recommend*. A surface that shows scores without derivations contradicts the product's own
   first principle.

## 2. Decision 1 — the seam: read services in the owning packages

**Adopted: generalise `FindingReadService`** (the ECR-0088 precedent). For each capability
the surface exposes, the owning domain package provides a dedicated read service, registered
with the kernel. The surface never traverses `service.engine`.

**The `*ReadService` contract, normative and checkable:**

- **Read-only by construction:** the class exposes no public method that mutates state — no
  `ingest`, `raise_*`, `propose_*`, `decommission`, `transition`, `assign`, `treat`, or any
  method whose name or effect is a write. Reviewability beats trust: the type simply has
  nothing unsafe to call.
- **Lives in the owning package.** Wrapping `.engine` is legitimate *inside* the package that
  owns the engine; it is exactly the coupling the surface must not have. The 13 engine-only
  services therefore need no change to their existing shape — their read services wrap
  `.engine` at home.
- **Keyword-only, tenant-scoped reads:** every method takes `*, tenant_id: str | None, ...`;
  `tenant_id=None` means *this local estate*, never all-tenants. The surface's existing
  two-way enforcement (400 if supplied in local mode, 400 if omitted in enterprise mode)
  applies to every new route; this sentence is FR text, not implementer discretion.
- **Registered name convention: `<domain>_read`** (precedent: `finding_read`). Registered
  read services join the `Runtime` dataclass and therefore **GC-003 registry coverage in both
  tenant modes automatically** — state this in the PR so the GC-003 expectation delta is
  deliberate, not discovered.
- **Satisfies `AQService`** (`start/stop/health`) like every other registered service, so
  `kernel.health()` and the `/health` endpoint extend without new contract.
- Registry keys and packages differ across the platform (`vuln_engine` → `src/aqelyn/vuln/`):
  reviews diff **by class identity, never name similarity** (the recorded GC-003 lesson).

**Rejected:** surface traversal of `.engine` (reintroduces the coupling ECR-0088's
`test_surface_imports_no_domain_engine_or_store` exists to prevent); a generic reflection
seam over all 30 services (unreviewable route surface, no per-capability contract).

Infrastructure services (`datalake_engine`, `event_bus`, `object_store`) get **no** read
service and no route in this pass.

## 3. Decision 2 — which capabilities widen first

**Adopted: the brief's four** — **ISPM posture, exposure, secrets/crypto, supply chain** —
on the stated grounds: clearest operator value, existing tenant-scoped reads (7–11 methods
each), all four already `assess`/`explain`-capable. With `finding_read`, inventory and vuln
already live, this takes the surface from 3 to 7 domain reads.

Routes (all `GET`/`HEAD`, all under the existing allowlist mechanism):
`/api/v1/ispm` · `/api/v1/exposure` · `/api/v1/secrets` · `/api/v1/supplychain`, each with
collection and detail forms as the domain read supports.

## 4. Decision 3 — every widened route carries its derivation

Wherever the underlying service exposes `explain`, the route's payload includes the
explanation alongside the score/posture — not behind a second round-trip, not optional.
Grounds: 11 of the services have `explain`; *Explain Before You Recommend* is the product
principle; a score without derivation on the operator surface would be the platform
contradicting itself. Where a domain read cannot yet explain, the payload says so explicitly
(an honest absent field, not an omitted one) — the unknown-factors discipline applied to
derivations.

## 5. Decision 4 — one data path: the report publishes through the read services

**Adopted: brief option (b).** `analyze_collection` keeps its handed-in-directory input and
the CLI contract is unchanged (`python -m aqelyn <dir>` → static HTML, "Local, operator-only
findings report (P-001)"), but internally the report constructs an in-memory runtime
(`create_inmemory_runtime()`) and publishes/reads through the same registered read services
the surface uses. One data path, two renderers.

**Rejected:** (a) recording the split as deliberate — divergence compounds into two products;
(c) serving the report from the surface — inherits `html.py:16`'s inlining of all 10,173
findings into a live server.

**Acceptance for (b):** report output over the real corpus (10,173 findings, 50,394 disclosed
unknown factors) is semantically identical before and after — same findings, same counts,
same disclosed unknowns — verified by golden comparison at the analysis layer (not
byte-identical HTML, which would pin incidentals). The report gains no socket, no server, no
new dependency; it remains one-shot and offline.

## 6. Functional requirements

- **FR-001** Each widened capability is exposed only via its `<domain>_read` service per the
  §2 contract; the surface imports models and `Runtime` only (the ECR-0088 import guard
  extends to the new routes unchanged).
- **FR-002** Tenant identity: every new route enforces the existing two-way tenant rule; FR
  text carries it explicitly per the brief.
- **FR-003** Pagination: every collection route pages by **keyset** on a stated composite key
  (ECR-0062 precedent; never offset), under the EA-0002 D8 work-budget discipline, with the
  10,173-finding corpus as the scale fixture.
- **FR-004** `degraded` is honest truncation and it **propagates**: any read that can return
  `degraded` (ECR-0034/0061 contracts) surfaces it in the payload and the UI renders it
  visibly. Papering over `degraded` is a review-blocking defect; three consumers are already
  guarded against ignoring it and the surface joins them.
- **FR-005** Reads only, loopback only, no new dependency, no events, nothing persisted —
  all ECR-0088 properties carry unchanged: `READ_METHODS = frozenset(("GET","HEAD"))`, fixed
  route allowlist, `LOOPBACK_HOST` with no bind seam, stdlib `asyncio`, GC-002 closed, no
  GC-004 census join.
- **FR-006** Client assets remain generated Python strings: `APP_JS` stays a raw literal;
  the served-asset quote guard and the `[hidden]` CSS rule survive (PR #290's lesson: a
  non-raw literal killed the UI while every gate stayed green).
- **FR-007** Rule 33 applied to routes: tests prove each route *uses* its read service and
  renders its payload (including `explain` and `degraded`), not merely that fields hold
  values.

## 7. Carried constraints (do not weaken)

ECR-0034 `degraded` · ECR-0061 exhaust-or-refuse · ECR-0062 keyset · rule 33 · GC-002
namespace closure · GC-003 registry coverage in both tenant modes (now including the new
read services) · GC-004 census (moot while FR-005 holds) · EA-0004 integrity ≠ authenticity ·
the network guard's scoped boundary (outbound: nowhere; inbound: `surface/` only, loopback)
· auth deferral remains coupled to loopback + read-only: if either relaxes, authentication is
a prerequisite, not a follow-up.

## 8. Reserved and out of scope

Nothing new is reserved to the owner; existing reservations (non-loopback bind, EA-0054,
EA-0052-FR-004) are untouched. Out of scope for this pass: writes, auth, frameworks,
non-loopback, events from the surface, read services for the remaining domains (they follow
this ECR's contract when scheduled — the seam decision is made once, here), and any
report-renderer change beyond the §5 data-path unification.

## 9. Ball

**Next: Codex implements** — the four read services in their owning packages, the four route
families with `explain` and `degraded` in payloads, keyset pagination, the §5 report
unification with golden comparison, GC-003 expectation delta stated in the PR.
**Then: Claude Code** reviews against §2's contract (by class identity, not name similarity)
and merges; re-check ECR number at merge. **Owner:** nothing queued.

## 10. Implementation outcome

Codex implemented the four owner-provided read services, registered the deliberate four-service
GC-003 delta in both tenant modes, widened the fixed surface routes, and moved P-001 analysis onto
the registered vulnerability publish and finding-read path. Mutation controls prove owner/tenant
cursor binding, explanation transport, degraded-state transport, and Runtime registration.
