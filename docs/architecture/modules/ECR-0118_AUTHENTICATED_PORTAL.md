# ECR-0118 — The authenticated customer portal: session, consent, then a tenant-scoped write

**Status:** Accepted — implemented and merged by the reviewer at the owner's direction.
**Raised and implemented by:** Claude Code, while Codex was unavailable (out until Saturday).
**Date:** 2026-08-07
**Number:** verified free at `4d9ff89` (main tip after ECR-0117, PR #320).

> ⚠️ Nineteenth consecutive ECR by one actor. §5 lists what independent review should attack.
> Fourth ECR of the customer-account arc (0115–0119); it wires 0115–0117 into gated routes.

## 1. Finding of record

The scan capability, the identity layer (0115/0116) and the consent/audit layer (0117) all exist,
but nothing connects them to a customer over the network. The deployed platform's customer face is
still an untested stdlib script in the deploy snapshot, and the operator surface **cannot** be that
face: it is read-only and refuses request bodies by design (ECR-0088), and that must not be
silently reversed. The customer needs a **separate, repo-resident, tested** write boundary.

## 2. Decision

A new `src/aqelyn/portal/` package — the authenticated customer portal — with an async
`PortalApplication.handle(method, target, headers, body)` (driven directly in tests, like the
surface app) exposing exactly the routes the flow needs:

- `POST /api/v1/register` — redeem an invite (0115), create the account, start a session, set the
  cookie.
- `POST /api/v1/login` / `POST /api/v1/logout` — authenticate / end a session.
- `POST /api/v1/consent` — record consent (0117); session required.
- `POST /api/v1/scans` — the gated upload (below).
- `GET /api/v1/findings` — the caller's findings, tenant-scoped.

The session cookie is `HttpOnly; Secure; SameSite=Strict; Path=/`. The boundary never leaks a
traceback: an unexpected error becomes a 500 with a generic message.

### The upload gate, in order

1. **session required** → 401 without a valid session;
2. **active consent required** (UX-005) → 403 without it;
3. **size bounded** → 413 if the body exceeds 1 MiB (checked before parsing);
4. **hostile input validated, never repaired** → the body is JSON-parsed and run through
   `validate_posture_shape`; a malformed document is refused **422** with a located reason;
5. **ingested into the caller's tenant only** — `ingest_posture_document` stamps the session's
   `tenant_id` onto every object, evidence record and finding it creates;
6. **audited** — a `scan_ingested` event with the upload's sha-256 digest, in the caller's tenant.

### The one property everything rests on

`tenant_id` comes from `session.tenant_id` — resolved from the authenticated account — and from
**nowhere else**. A caller cannot name a tenant in a body, a query, or a cookie. The uploaded
document is treated purely as observations; even if it carried a tenant field it would be ignored.

## 3. Isolation, as the load-bearing test

`test_two_tenants_never_see_each_others_findings`: tenant A and tenant B each register, consent and
upload (B twice); A's `GET /api/v1/findings` returns exactly A's one finding and B's returns exactly
B's two, each stamped with its own tenant. Because the object store resolves natural keys per tenant
and the finding store filters by `tenant_id`, two customers scanning the same hostname get separate
assets and separate findings.

## 4. Acceptance — 6 mutations, all red

Harness `~/AQELYN_ECR0118_PREP/matrix.sh`, cache purged. Each removed gate turns a witness red:
session gate removed (401→ingest), consent gate removed (403→ingest), size bound neutered
(413→422), findings read not tenant-scoped (isolation test), ingested finding not stamped with the
session tenant (isolation test), and hostile-input validation bypassed (422→201). 13 portal tests
in all. ruff + `mypy --strict` clean across 623 files; full suite on live Postgres. Carried matrix
rises to **117**.

GC-004 cascade (working as intended): once the portal actually *reads* `identity.email`,
`consent.text_version` and `consent.actor_account_id` (as call arguments), they move from exempt to
**consumed** and are removed from `EXEMPT_FIELDS`; only `identity.redeemed_by` and
`consent.revoked_at` remain genuinely owner-internal. The guard was not weakened — the fields simply
gained the external reader the arc always intended.

## 5. What review should attack

1. **No rate limit here.** The brief puts `limit_req` on `/login` and `/scans` at nginx; this app
   does not rate-limit itself. A brute-force or upload-flood defence lives at the edge, and the
   deploy must actually configure it — named, not enforced in code.
2. **The `PortalApplication` has no wired HTTP server in this ECR.** Tests drive `handle()`
   directly (as the surface tests do). A server that reads bodies and enforces the size bound at the
   socket (before buffering a huge body) is a follow-up; today the bound is checked after the body
   is read into memory.
3. **Objects and evidence are tenant-stamped, but cross-tenant object convergence was only reasoned
   about, not adversarially fuzzed.** 0119 is the adversarial isolation audit and route census; this
   ECR's isolation test is the happy-path proof, not the exhaustive one.
4. **Registration auto-logs-in.** Convenient, but it means a leaked invite token yields an active
   session immediately. TTL + single-use bound it (0115), and the invite is the only gate.

## 6. Scope

New `src/aqelyn/portal/{__init__,app,ingest}.py`; new `tests/portal/` (conftest + tests +
`__init__.py`); `EXEMPT_FIELDS` and its mirror updated as fields became consumed. No change to the
surface, identity, consent, or collector — this is the wiring layer. 0119 adds the adversarial
isolation audit and the structural route-census guard over this app.
