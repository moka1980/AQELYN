# ECR-0120 — Sessions in Postgres: lifting the single-worker constraint

**Status:** Accepted — implemented and merged by the reviewer at the owner's direction.
**Raised and implemented by:** Claude Code, while Codex was unavailable (out until Saturday).
**Date:** 2026-08-07
**Number:** verified free at `ae38f61` (main tip after the customer-account arc, PR #322).

> ⚠️ Twenty-first consecutive ECR by one actor. §5 lists what independent review should attack.
> Post-arc completion work. claude.ai (spec author) flagged this as load-bearing, not optional.

## 1. Finding of record

ECR-0116 kept sessions in process memory in every backend. That is not merely "dropped on
restart": a session minted on worker A is invisible to worker B, so the deployment **cannot run
more than one worker** without silently breaking login. That is a hard constraint on the deploy,
and leaving it implicit would make a shared session store a *precondition of scaling discovered at
scale* rather than a named piece of work. This ECR lifts it.

## 2. Decision

A `PostgresSessionStore` (asyncpg) behind the existing `SessionStore` protocol, selected by
`build_identity_stores` for the Postgres backend. The in-memory store stays for tests and local
runs (intentionally per-process). New `aq_session` table (token PK, account_id, tenant_id,
expires_at), created by the shared identity DDL and sharing the identity pool.

The contract is unchanged, and — critically — so is the isolation rule: `start` binds
`tenant_id = account.tenant_id`, never anything the client sends. `resolve` refuses (and deletes)
an expired row; `end` deletes. There are no new persisted field names — `token`, `account_id`,
`tenant_id`, `expires_at` were already the `Session` fields the GC-004 census classified, so no
exemption changes were needed.

## 3. The property under test

The whole identity contract test suite now runs its Postgres parametrization against
`PostgresSessionStore` (it previously used the in-memory store even under the Postgres param), so
tenant-binding, expiry and logout are proven on Postgres. The new, load-bearing test is
`test_sessions_survive_a_new_store_instance`: a session started on one store instance is resolved
by a **different** instance on the same database — i.e. another worker. It is skipped on the
in-memory backend, which is per-process by design.

## 4. Acceptance — 3 mutations, all red

Harness `~/AQELYN_ECR0120_PREP/matrix.sh`, cache purged, Postgres live. Session tenant not bound to
the account (fails tenant-carry, two-tenants, and cross-instance tests); expired session still
resolves; `end()` does not actually delete (logout test). Each turns the Postgres parametrization
red.

ruff + `mypy --strict` clean across 624 files; full suite on live Postgres. Carried matrix rises to
**123**.

## 5. What review should attack

1. **No reaping of expired rows except on access.** An expired session row is deleted when someone
   tries to resolve it, but rows never resolved again accumulate. A periodic sweep (or a partial
   index + a cron `DELETE WHERE expires_at < now()`) is the clean fix; today the table can grow with
   abandoned sessions. Named, not built.
2. **Session tokens are stored in the clear.** They are random 32-byte url-safe tokens (not
   guessable), but anyone with read access to `aq_session` holds live sessions. The finding/evidence
   stores make the same trust assumption about the database; worth stating that DB read access is
   session-compromise.
3. **The in-memory and Postgres session stores now diverge in durability** but must not diverge in
   contract — the shared parametrized suite is what keeps them honest; a behaviour added to one must
   be added to the test, not just the other store.

## 6. Scope

`aq_session` added to `identity/ddl.py`; `PostgresSessionStore` added to `identity/postgres.py`;
`build_identity_stores` wires it for the Postgres backend; the identity test harness's Postgres
param uses it, plus one cross-instance durability test. No change to accounts, invites, consent, the
portal, or any other domain. This does **not** touch the deployment — it makes the multi-worker
deploy *possible*; standing it up is the owner-gated deploy step (the forthcoming deploy-gate ECR).
