# ECR-0116 — Identity moves to Postgres, and the same contract is proven on both backends

**Status:** Accepted — implemented and merged by the reviewer at the owner's direction.
**Raised and implemented by:** Claude Code, while Codex was unavailable (out until Saturday).
**Date:** 2026-08-07
**Number:** verified free at `24512dd` (main tip after ECR-0115, PR #318).

> ⚠️ Seventeenth consecutive ECR by one actor. §5 lists what independent review should attack.
> Second ECR of the customer-account arc (0115–0119).

## 1. Finding of record

ECR-0115 shipped identity as a **file-backed, synchronous** bootstrap — deliberately, to pin down
the model (`Account`, `Invite`, `PasswordHash`) and the one isolation rule (a session's tenant comes
from its account, never from client input) under test. A file-backed store does not survive as
production identity: it does not share across workers, and it is not the durable, tenant-indexed
storage the rest of the platform runs on. The arc's plan was always "file in 0115 → Postgres in 0116
with no API change."

## 2. Decision

Identity now uses the **standard backend pair every other domain in this codebase uses**: an
in-memory store for local runs and tests, an asyncpg store for durable production, behind async
protocols.

- **`identity/store.py`** — now the async contracts: `AccountStore`, `InviteStore`, `SessionStore`
  protocols, plus `Session`, `IdentityError`, `InviteError`. Method names and semantics are exactly
  those of ECR-0115.
- **`identity/memory.py`** — `InMemory{Account,Invite,Session}Store`, async, lock-guarded, holding
  the same guards as the file bootstrap (dup-email, active-only auth, single-use/expiring invites,
  tenant-bound sessions).
- **`identity/postgres.py`** + **`identity/ddl.py`** — `Postgres{Account,Invite}Store` sharing one
  pool. `aq_account` has a `lower(email)` **unique index** (the one-account-per-email rule now holds
  even under a race the Python check would miss) and a `(tenant_id, id)` index; `aq_invite` a
  `(tenant_id, token)` index. `redeem` is a single `FOR UPDATE` transaction — the invite is locked,
  the account inserted, the invite stamped `redeemed_by` — so a token is spent exactly once under
  concurrent redemption. Sessions stay in-memory in both backends (ephemeral by design).
- **`identity/factory.py`** — `build_identity_stores(backend=…, database_url=…)` selects the pair,
  mirroring the platform's `backend` switch.

### The one honest deviation from the spec's letter

The brief said "no API change." The store's **method names, arguments and semantics are unchanged**,
and the isolation rule is unchanged. What changed is **sync → async**. This was forced, not chosen:
asyncpg is the only Postgres driver in the project (no psycopg), and the authenticated ingest app
this arc builds in ECR-0118 is itself async and must call identity in-process. A synchronous identity
API backed by asyncpg is not expressible without an event-loop hack that would break the moment it is
called from the async app. Async is the architecturally correct shape and matches every other store.

## 3. "No API change", made testable

The test body in `tests/identity/test_identity.py` is written **once** and run against **both**
backends via a parametrized fixture (`inmemory`, `postgres`; Postgres skipped without
`AQELYN_DATABASE_URL`). That the identical assertions pass on either backend is the concrete meaning
of "the contract did not change." A single movable clock is injected into all three stores so expiry
is deterministic without sleeping. The load-bearing test remains
`test_two_tenants_sessions_never_cross`.

## 4. Acceptance — 12 mutations, all red

Harness `~/AQELYN_ECR0116_PREP/matrix.sh`, cache purged per mutation, run with Postgres live so both
parametrizations execute. Memory backend: password-always-passes, session-tenant-not-bound,
invite-reusable, expired-invite-accepted, disabled-can-auth, duplicate-email-allowed,
expired-session-resolves. Postgres backend: password-always-passes, invite-reusable,
expired-invite-accepted, disabled-can-auth, and duplicate-email-translation-removed (the raw
`UniqueViolationError` escapes instead of `IdentityError`). Each turns exactly the expected
backend's parametrization red.

ruff + `mypy --strict` clean across 607 files; full suite on live Postgres. Carried matrix rises to
**103**.

GC-004: once the Postgres INSERTs exist, `email` and `redeemed_by` become visible as persisted
identity fields with no external reader. They are added to `EXEMPT_FIELDS` with honest reasons — the
login address is an internal lookup key reached through `authenticate`/`get_by_email`, and
`redeemed_by` is single-use bookkeeping read only inside the invite store. The census guard was
**not** weakened.

## 5. What review should attack

1. **Sessions are still process-memory**, now more visibly a gap: the Postgres backend is durable for
   accounts and invites but a restart or a second worker still drops sessions. A shared session store
   is the honest next step (named, not built).
2. **`redeem` duplicates the account-insert SQL** rather than delegating to `AccountStore.create`, so
   the whole redemption is one transaction. The duplication is small (`_insert_account`) but it is
   duplication, and a future column added to accounts must be added in two places.
3. **The Postgres dup-email witness is index-enforced**, so its mutation targets the *translation*
   (`IdentityError` vs raw `UniqueViolationError`), not the index itself — the DDL uses
   `CREATE ... IF NOT EXISTS` against a persisted table, so a mutation to the index would not take
   effect within a run. The index's correctness rides on the behaviour test passing on the Postgres
   param, not on a mutation.
4. **sync → async is a real API change** for any hypothetical synchronous caller. There is none today
   (the deployed portal is a separate, not-yet-repo-resident script that this arc will replace), but
   it is worth a reviewer confirming no code depends on the old synchronous surface.

## 6. Scope

Rewrote `identity/store.py` (now protocols); new `identity/{memory,postgres,ddl,factory}.py`; updated
`identity/__init__.py`. Rewrote `tests/identity/test_identity.py` (async, parametrized) with a new
`tests/identity/conftest.py` and `tests/identity/__init__.py` (the latter a missed ECR-0115 file that
the status guard surfaced). Two `EXEMPT_FIELDS` entries and their pinned mirror. No change to
`models.py`, `passwords.py`, or any other domain — this is entirely identity's storage layer.
