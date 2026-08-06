# ECR-0119 — Per-tenant isolation, audited adversarially and enforced by a route census

**Status:** Accepted — implemented and merged by the reviewer at the owner's direction.
**Raised and implemented by:** Claude Code, while Codex was unavailable (out until Saturday).
**Date:** 2026-08-07
**Number:** verified free at `7852264` (main tip after ECR-0118, PR #321).

> ⚠️ Twentieth consecutive ECR by one actor. §5 lists what independent review should attack.
> Final ECR of the customer-account arc (0115–0119).

## 1. Finding of record

The brief names per-tenant isolation "the highest-risk correctness property in the whole flow," and
it asks for two specific things this ECR delivers: **refusals are 404 on object-addressed routes**
(no existence oracle), and a **structural guard** so a future object-addressed route cannot ship
without an isolation test. ECR-0118 proved isolation on the happy path (two tenants' collections are
disjoint). This ECR proves it adversarially and makes it structurally un-regressable.

## 2. Decision

### An object-addressed route with no existence oracle

`GET /api/v1/findings/{finding_id}` is added. It resolves the session (401 without one), fetches the
finding by id, and returns it **only** if `finding.tenant_id == session.tenant_id`. Otherwise it
returns **404** — the *same* 404 whether the finding belongs to another tenant, does not exist, or
has a malformed id. A malformed id (which the store would reject with a validation error) is caught
and answered as 404 too, so the *shape* of an id is not an oracle either. An attacker who holds
another tenant's real finding id learns nothing they could not have guessed.

### A structural route census

`OBJECT_ADDRESSED_ROUTES` in `portal/app.py` declares every route that addresses an object by id.
The census test walks it and asserts every entry has a registered cross-tenant probe
(`test_every_object_addressed_route_has_a_cross_tenant_probe`), and a second test runs each probe
and asserts a cross-tenant request gets 404 (`test_route_census_every_object_route_refuses_cross_
tenant`). Adding a new object-addressed route without also registering its probe **fails the
census** — isolation coverage cannot silently fall behind the route table.

## 3. The adversarial audit

`test_no_existence_oracle` is the sharpest: tenant A makes three requests — B's real finding id, a
well-formed id that does not exist, and a malformed id — and asserts all three responses are
**byte-identical** (status and body). Also: A cannot read B's finding by id (404); the owner can read
their own (200); the detail route requires a session (401); and a **forged tenant smuggled into the
upload body** (`document["tenant_id"] = B`, and on the observation too) is ignored — the finding
still lands in A's tenant, because the tenant comes from the session and the document is only ever
read as observations.

## 4. Acceptance — 3 mutations, all red

Harness `~/AQELYN_ECR0119_PREP/matrix.sh`, cache purged:

1. finding-detail tenant check removed → the cross-tenant read succeeds and the byte-identical
   oracle breaks (`test_a_cannot_read_bs_finding_by_id`, `test_no_existence_oracle`, and the route
   census all go red);
2. finding-detail session gate removed → `test_finding_detail_requires_a_session` red;
3. a second route added to `OBJECT_ADDRESSED_ROUTES` without a probe → **the census itself goes
   red**, proving the structural guard actually fires when the route table outgrows its isolation
   tests.

7 new tests. ruff + `mypy --strict` clean across 624 files; full suite **2146 passed, 5 skipped** on
live Postgres. Carried matrix rises to **120**.

## 5. What review should attack

1. **The census covers *object-addressed* routes, not every isolation surface.** Collection routes
   (`GET /api/v1/findings`) are scoped too, and tested, but they are not in
   `OBJECT_ADDRESSED_ROUTES` — the census's remit is specifically the by-id routes where an
   existence oracle is the risk. A reviewer should confirm no by-id route bypasses `_object_id`
   dispatch (e.g. a route matched by exact string that still takes an id).
2. **The no-oracle proof is byte-equality of the response**, which also depends on `_error` not
   embedding the id or a distinguishing detail. It does not today; a future change to `_error` that
   echoed the request could reintroduce an oracle without the census noticing (the census checks
   status, `test_no_existence_oracle` checks bytes — keep both).
3. **Isolation rests on the store filters proven in 0116/0117 and the tenant-from-session rule in
   0118.** This ECR audits the portal's use of them; it does not re-audit the stores themselves.
4. **Timing is not addressed.** The 404 paths do different amounts of work (a cross-tenant hit
   fetches a real row; a missing id does not), so a timing side-channel is conceivable. Out of scope
   for a stdlib in-process app behind nginx, but named.

## 6. Scope

`GET /api/v1/findings/{id}` and `OBJECT_ADDRESSED_ROUTES` added to `src/aqelyn/portal/app.py`; new
`tests/portal/test_isolation_census.py`. No change to the stores, the ingest, or any other route —
this hardens and proves the isolation the arc built. **The customer-account arc (0115–0119) is
complete.**
